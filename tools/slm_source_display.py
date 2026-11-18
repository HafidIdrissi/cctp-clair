"""Readable source attribution derived only from recorded per-point evidence."""
import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

CATALOGUE = Path(__file__).resolve().parents[1] / 'RAG_RER_V/references/catalogue.json'
BASE = 'http://127.0.0.1:8770'


def official_url(value):
    value = str(value or '')
    url = urlsplit(value)
    return value if url.scheme == 'https' and url.netloc == 'www.legifrance.gouv.fr' else None


def reference_url(sha, page=None):
    if not re.fullmatch(r'[a-f0-9]{64}', str(sha or '')):
        return None
    return BASE + '/api/references/' + sha + '.pdf' + (
        '#page=' + str(page) if type(page) is int and page > 0 else '')


def reference_bytes(sha, catalogue_path=CATALOGUE):
    """Serve only a registered, confined PDF whose bytes match the requested hash."""
    if not re.fullmatch(r'[a-f0-9]{64}', str(sha)):
        raise ValueError('Identifiant de référence invalide.')
    catalogue_path = Path(catalogue_path).resolve()
    entries = [e for e in json.loads(catalogue_path.read_text(encoding='utf-8'))['references']
               if e.get('sha256') == sha]
    if len(entries) != 1:
        raise ValueError('Copie de référence non disponible dans le catalogue local.')
    path = (catalogue_path.parent / entries[0]['file']).resolve()
    if not path.is_relative_to(catalogue_path.parent) or path.suffix.lower() != '.pdf':
        raise ValueError('Chemin de référence non autorisé.')
    raw = path.read_bytes()
    if not raw.startswith(b'%PDF-') or hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('La copie locale ne correspond plus à la source enregistrée.')
    return raw


def legal_excerpt(row, source):
    text = str(source.get('texte') or '')
    proposed = str(((row.get('verification_article') or {}).get('proposal') or {}).get('obligation') or '')
    normalize = lambda s: re.sub(r'\s+', ' ', s).strip()
    if proposed and normalize(proposed) in normalize(text):
        return proposed
    number = re.search(r',\s*(\d+)\s*[°º]', str(row.get('article') or ''))
    if number:
        section = re.search(r'(?:^|\n)' + number[1] + r'\s*[°º].*?(?=\n\d+\s*[°º]|\Z)', text, re.S)
        if section:
            letter = re.search(r'[°º]\s*([a-z])\b', str(row.get('article') or ''))
            if letter:
                subsection = re.search(r'(?:^|\n)' + letter[1] + r'\).*?(?=\n[a-z]\)|\Z)', section[0], re.S)
                if subsection:
                    return subsection[0].strip()
            return section[0].strip()
    return text


def source_display(row):
    from slm_v6_presentation import documentary_information
    mode = row.get('mode_verification')
    source = row.get('source') or {}
    if mode == 'perimetre_documente':
        check=row.get('verification_perimetre_core') or {}
        evidence=check.get('native_scope') or {}
        return dict(kind='documentary',heading='Preuve du périmètre des travaux',title='Texte du CCTP et repère du plan',
            metadata=['Page du texte : '+str(evidence.get('page','non précisée'))],excerpt=evidence.get('citation',''),url=None,
            note='Exclusion des travaux de ce lot ; aucune conformité de l’ouvrage existant n’est affirmée.')
    if mode == 'coherence_documentaire' or documentary_information(row):
        return dict(kind='documentary', heading='Preuve documentaire', title='Passages du CCTP',
            metadata=[], excerpt='', url=None,
            note='Ce résultat est fondé sur les passages du dossier ; aucune loi utilisée pour ce constat.')
    if mode == 'reference_technique_verifiee':
        check = row.get('verification_technique') or {}
        ref = check.get('reference') or {}
        page = ref.get('page')
        return dict(kind='technical', heading='Source du contrôle technique',
            title=ref.get('titre') or source.get('titre') or 'Référentiel technique',
            metadata=['Référentiel technique', 'Édition : ' + str(ref.get('date') or 'non précisée'),
                      'Page : ' + str(page if page is not None else 'non précisée'), 'Origine : copie PDF locale'],
            excerpt=(check.get('critere') or {}).get('citation') or row.get('regle') or '',
            url=reference_url(ref.get('sha256'), page), link_label='Ouvrir le PDF utilisé à cette page',
            note='Comparaison avec le référentiel retenu par le projet. Ce résultat technique ne s’appuie pas sur un article de loi.')
    title = source.get('titre') or source.get('nom_code') or source.get('title')
    if not title:
        return dict(kind='missing', heading='Source du contrôle', title='Aucune source juridique retenue pour ce point',
                    metadata=[], excerpt='', url=None, note='Aucun critère juridique applicable établi dans les preuves de ce résultat. Les candidats recherchés restent consultables dans l’inspection.')
    article = str(row.get('article') or source.get('numero') or '')
    if article and not article.lower().startswith('art'):
        article = 'Article ' + article
    provider = source.get('canal') or source.get('provenance')
    if not isinstance(provider, str): provider = ''
    if provider == 'dila_open_data': provider = 'DILA open data — copie locale'
    metadata = [article, 'Version depuis le ' + str(source.get('debut') or source.get('date_debut') or 'date non précisée')]
    if provider: metadata.append('Origine : ' + provider)
    if source.get('id'): metadata.append('Identifiant : ' + str(source['id']))
    codification=source.get('codification') or {}
    if codification.get('verified') and codification.get('article_id')==source.get('id'):
        for heading in codification.get('parents',[])[-2:]:
            if heading.get('title'):metadata.append('Rubrique de l’article : '+heading['title'])
    decided = row.get('statut') in ('critere_auto_respecte', 'ecart_confirme_sur_critere')
    return dict(kind='legal', heading='Source juridique utilisée' if decided else 'Source juridique examinée',
        title=title, metadata=[s for s in metadata if s], excerpt=legal_excerpt(row, source),
        url=official_url(source.get('url') or source.get('source_url')), link_label='Ouvrir l’article sur Légifrance',
        note='Passage conservé pour ce contrôle, dans la version indiquée.')


def inspection_sources(inspection, proof):
    """Enrich the returned view, including old caches, without editing the archive."""
    result = copy.deepcopy(inspection)
    rows = {r['fait']['id']: r for r in (proof.get('analyse') or {}).get('lignes', [])}
    if (proof.get('analyse') or {}).get('core_atomization'):
        result['control_units']=copy.deepcopy(proof['analyse']['core_atomization'])
        result['native_inventory']=copy.deepcopy(proof.get('lectures',{}).get('core_native_inventory',{}))
    for association in result.get('associations', []):
        row = rows.get((association.get('fact') or {}).get('id'))
        if row is not None:
            display = source_display(row)
            association['source_display'] = display
            if display['kind'] == 'documentary':
                association['source'] = None
                association['article'] = None
                association['rule'] = ''
                association['source_heading'] = 'Preuve documentaire'
            elif display['kind'] == 'technical':
                association['source_heading'] = 'Référence technique'
    return result
