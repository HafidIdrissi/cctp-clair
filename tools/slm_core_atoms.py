"""Domain-independent native inventory and lossless sentence-level control units.

An atom is an examination unit, not proof that it contains only one obligation.
The parent is always retained and transmitted as context. No legal decision,
ignored scope condition or claim of exhaustive legal coverage is made here.
"""
import copy
import hashlib
import re
from slm_m3_journal import emit

VERSION = 'core-native-units-2'


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def spans(text, boundary):
    start = 0
    for match in boundary.finditer(text):
        end = match.start()
        left, right = start, end
        while left < right and text[left].isspace(): left += 1
        while right > left and text[right-1].isspace(): right -= 1
        if left < right: yield left, right
        start = match.end()
    end = len(text)
    while start < end and text[start].isspace(): start += 1
    while end > start and text[end-1].isspace(): end -= 1
    if start < end: yield start, end


BLOCK = re.compile(r'\n[ \t]*\n|(?<=\n)(?=(?:Article|Clause|Chapitre)\s+\d)', re.I)
SENTENCE = re.compile(r'(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ0-9«])')
ABBREVIATION = re.compile(r'(?:\b(?:M|Mme|Mlle|Me|Dr|Pr|art|Art|cf|Cf|etc|p)|\b[A-Z])\.$')
HEADING = re.compile(r'^\s*(?:Article|Clause)\s+\d[\d.\-]*\s*[-:–]\s*[^\n]{1,130}\n', re.I)


def native_fact(ident, page, quote):
    return dict(id=ident, type_fait='clause_a_examiner', element='Passage natif à examiner',
        page=page, repere='Passage du contrat', citation_visible=quote,
        information=None, valeur_inscrite=None, valeur=None, valeur_m=None, unite=None,
        etat='non_precise', origine='texte_natif', lecture_statut='citation_native_exacte',
        validation_humaine=False, association_valeur_element_verifiee=False,
        ambiguite=None, hors_operation=None)


def inventory(readings):
    """Keep every nonblank native block, including clauses with unfamiliar verbs."""
    result = copy.deepcopy(readings)
    old = [f for f in result.get('faits', []) if f.get('origine') == 'texte_natif' and f.get('type_fait') == 'clause_a_examiner']
    kept = [f for f in result.get('faits', []) if f not in old]
    used = {f.get('id') for f in kept}; added = []; pages = []
    for page, raw in enumerate(result.get('text', []), 1):
        text = str(raw or '')
        units = []
        for left, right in spans(text, BLOCK):
            index = len(added)+1; ident = 'G%04d' % index
            while ident in used:
                index += 1; ident = 'G%04d' % index
            used.add(ident)
            fact = native_fact(ident, page, text[left:right])
            fact['core_native_span'] = dict(start=left, end=right, page_sha256=sha(text))
            added.append(fact); units.append(dict(id=ident, start=left, end=right, sha256=sha(fact['citation_visible'])))
        # Only whitespace separators may remain outside the inventoried spans.
        cursor = 0; covered = True
        for unit in units:
            covered = covered and not text[cursor:unit['start']].strip()
            cursor = unit['end']
        covered = covered and not text[cursor:].strip()
        pages.append(dict(page=page, sha256=sha(text), blocks=units,
            all_nonblank_native_characters_inventoried=covered,
            native_characters=len(text), blank_native_page=not text.strip()))
    result['faits'] = kept+added
    result['core_native_inventory'] = dict(version=VERSION, pages=pages,
        previous_generic_facts=old, native_blocks=len(added),
        native_character_coverage=all(p['all_nonblank_native_characters_inventoried'] for p in pages),
        legal_coverage_exhaustive=False,
        limitation='Couverture des caractères natifs uniquement. Ni détection de toutes les obligations implicites, ni lecture de toutes les images, ni conformité juridique globale.')
    result['inventaire_clauses'] = dict(methode=VERSION, clauses_ajoutees=len(added),
        clauses_candidates_non_retenues=0, exhaustive=False,
        native_character_coverage=result['core_native_inventory']['native_character_coverage'])
    emit('inventaire_natif_general', 'done', blocks=len(added), pages=len(pages),
        native_character_coverage=result['core_native_inventory']['native_character_coverage'], legal_coverage_exhaustive=False, model_call=False)
    return result


def sentence_spans(text):
    """Retain decimal points, initials, common abbreviations and semicolons."""
    boundaries = []
    for match in SENTENCE.finditer(text):
        # A numbered heading is a single structural unit, not a fact "1.".
        if re.fullmatch(r'\s*\d{1,3}\.',text[:match.start()]): continue
        prefix = text[max(0, match.start()-30):match.start()]
        if ABBREVIATION.search(prefix): continue
        boundaries.append((match.start(), match.end()))
    start = 0; result = []
    for end, following in boundaries+[(len(text), len(text))]:
        left, right = start, end
        while left < right and text[left].isspace(): left += 1
        while right > left and text[right-1].isspace(): right -= 1
        if left < right: result.append((left, right))
        start = following
    return result


def binding(fact, readings):
    """Replay a child-to-parent link against the original native page."""
    record = fact.get('core_atom') or {}
    page = fact.get('page'); text = record.get('parent_quote')
    if type(page) is not int or not 1 <= page <= len(readings.get('text', [])) or not isinstance(text, str): return None
    native = readings['text'][page-1]
    left, right = record.get('start'), record.get('end')
    if (type(left) is not int or type(right) is not int or not 0 <= left < right <= len(text)
        or sha(text) != record.get('parent_sha256') or sha(native) != record.get('page_sha256')
        or text not in native or text[left:right] != fact.get('citation_visible')): return None
    return dict(parent_quote=text, before=text[:left], after=text[right:], title=record.get('heading', ''),
        parent_id=record['parent_id'], page=page,
        limitation='Unité de lecture avec contexte parent intégral ; plusieurs exigences peuvent encore coexister dans une phrase.')


def expand(analysis, readings):
    """Replace multi-sentence generic rows with exact units; archive every parent."""
    if analysis.get('core_atomization'): return
    rows = []; parents = []; issues = []
    used = {r['fait']['id'] for r in analysis['lignes']}
    for row in analysis['lignes']:
        fact = row['fait']; quote = fact.get('citation_visible', ''); page = fact.get('page')
        if fact.get('origine') != 'texte_natif' or fact.get('type_fait') != 'clause_a_examiner':
            rows.append(row); continue
        if type(page) is not int or not 1 <= page <= len(readings.get('text', [])) or quote not in readings['text'][page-1]:
            rows.append(row); issues.append(dict(id=fact['id'], reason='citation_parent_non_exacte')); continue
        heading = HEADING.match(quote)
        if heading:
            from slm_core_obligations import ACTION
            from v4_8_document_service import norm
            from v4_9_evidence import TOKEN
            line=heading[0].split('-',1)[-1]
            if ACTION.search(norm(line)) or TOKEN.search(line) or re.search(r'[.!?;]',line):heading=None
        offset = heading.end() if heading else 0
        ranges = [(left+offset, right+offset) for left, right in sentence_spans(quote[offset:])]
        if len(ranges) < 2:
            rows.append(row); continue
        ids = []
        for index, (left, right) in enumerate(ranges, 1):
            ident = fact['id']+'_S%02d' % index
            if ident in used: raise ValueError('Identifiant de contrôle déjà utilisé : '+ident)
            used.add(ident); ids.append(ident)
            child = native_fact(ident, page, quote[left:right])
            child['element'] = (quote[:offset].strip() if heading else fact.get('element')) or 'Passage natif à examiner'
            child['core_parent_id'] = fact['id']
            child['core_atom'] = dict(parent_id=fact['id'], parent_quote=quote, parent_sha256=sha(quote),
                page_sha256=sha(readings['text'][page-1]), start=left, end=right,
                heading=quote[:offset].strip(), method=VERSION)
            assert binding(child, readings)
            rows.append(dict(fait=child, statut='a_verifier', comparaison=None, source=None,
                regle=None, article=None, explication='Unité native préparée ; contrôle non exécuté.',
                action='Exécuter le contrôle de cette unité avec son contexte parent.',
                mode_verification='a_executer', articles_complementaires=[]))
        cursor = offset
        for left, right in ranges:
            if quote[cursor:left].strip(): raise ValueError('Passage natif perdu lors de la décomposition.')
            cursor = right
        if quote[cursor:].strip(): raise ValueError('Fin de passage perdue lors de la décomposition.')
        parents.append(dict(fact=copy.deepcopy(fact), initial_status=row['statut'], children=ids,
            heading=quote[:offset], nonblank_body_characters_preserved=True,
            scope='Le parent est conservé comme contexte, pas compté une seconde fois comme contrôle.'))
        emit('decomposition_clause', 'done', fact_id=fact['id'], child_ids=ids,
            parent_sha256=sha(quote), full_context_retained=True, model_call=False)
    analysis['lignes'] = rows
    analysis['core_atomization'] = dict(version=VERSION, parents=parents, issues=issues,
        examination_units=len(rows), legal_coverage_exhaustive=False,
        limitation='Découpage de phrases sans supprimer le contexte parent. Ce découpage ne prouve ni une obligation unique par phrase ni une couverture juridique exhaustive.')


def parent_summary(analysis):
    """Summarise coverage of child results, never turn an unknown child into green."""
    from slm_v6_presentation import row_presentation
    rows = {r['fait']['id']:r for r in analysis['lignes']}
    for parent in (analysis.get('core_atomization') or {}).get('parents', []):
        groups = [row_presentation(rows[i], analysis)['group'] for i in parent['children']]
        parent['child_result_groups'] = {k:groups.count(k) for k in sorted(set(groups))}
        parent['all_children_processed'] = all(
            bool(rows[i].get('verification_article') or rows[i].get('verification_automatique'))
            and row_presentation(rows[i],analysis)['group'] not in ('interrupted','reading')
            for i in parent['children'])
        parent['all_children_resolved'] = all(k in ('conclusions', 'information') for k in groups)
        parent['legal_compliance_certified'] = False
