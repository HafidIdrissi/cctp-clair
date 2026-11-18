"""Read named project references; retrieving one never establishes a legal verdict.

The catalogue identifies files and editions, not numerical rules. Every returned
paragraph is extracted from a hash-checked PDF. Adoption is grounded in a literal
project passage and does not establish regional funding or general legal scope.
"""
import hashlib
import json
import math
import re
import unicodedata
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'RAG_RER_V/references/catalogue.json'
VERSION = 'references-documentaires-2'


def canonical(text):
    text = unicodedata.normalize('NFKD',str(text)).casefold()
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+',' ',text.replace('’',"'").replace('–','-').replace('‑','-')).strip()


def paragraphs(text):
    """Exact substrings, retaining text order, punctuation and source line breaks."""
    return [part.strip() for part in re.split(r'\n\s*\n',text) if part.strip()]


def _contains(text,alias):
    return re.search(r'(?<![\w])'+re.escape(canonical(alias))+r'(?![\w])',canonical(text)) is not None


def _sentences(text):
    # Do not let a nearby sentence adopt a different reference or turn a mention
    # in an appendix/index into a project requirement.
    return [s.strip() for s in re.split(r'(?<=[.!?;])\s+(?=[A-ZÀ-Ÿ0-9])',text) if s.strip()]


def _adoption(sentence):
    text=canonical(sentence)
    if re.search(r'\b(?:si|sous reserve|a condition|sous condition)\b',text):
        return None
    if re.search(r"\b(?:exemple|illustration|historique|anciennement|autre projet|recommandation|eventuel|envisage|pourrait|pourra|souhaite|facultatif)\b",text):
        return None
    if re.search(r"\b(?:absent|absence|non applicable|non retenu|non contractuel|informatif|informative|n'est pas|ne sera pas|n'a pas|ne s'applique pas|ne constitue pas|sans appliquer|sans retenir|sans valeur)\b",text):
        return None
    if re.search(r"\b(?:est|sont|sera|seront)\s+(?:(?:expressement|explicitement|contractuellement)\s+)?(?:retenu|retenue|adopte|adoptee|exige|exigee)s?\s+(?:comme|en tant qu')\s*(?:objectif technique|niveau de service|reference technique)",text):
        return 'objectif_technique'
    if re.search(r"\b(?:objectif technique|niveau de service)\b.{0,180}\b(?:est|sera)\s+(?:celui|defini|fixe|prescrit|retenu)\b",text):
        return 'objectif_technique'
    if re.search(r"\b(?:est|sera)\s+(?:(?:expressement|explicitement)\s+)?(?:contractuel|contractuelle|applicable|impose|imposee|incorpore|incorporee|annexe contractuelle)\b",text):
        return 'reference_contractuelle'
    if re.search(r"\b(?:doit|doivent|devra|devront)\s+(?:respecter|appliquer|satisfaire|etre conforme)\b",text) or re.search(r"\bs'applique\s+(?:au present|a ce|au projet|au marche|au lot|a l'ensemble)\b",text):
        return 'reference_contractuelle'
    return None


def restricted_scope(sentence):
    """A reference limited to one part is not automatically dossier-wide."""
    text=canonical(sentence)
    return bool(re.search(r'\b(?:uniquement|seulement|sauf|excepte|exclusion|limite|reserve)\b',text)
        or re.search(r'\b(?:lot|tranche|secteur|batiment|chapitre|article|section)\s+(?:n[°o]?\s*)?[a-z0-9]+\b',text))


def adoption_of_named_reference(sentence,aliases,editions):
    """Bind the adoption predicate to the named reference, not a nearby noun."""
    if restricted_scope(sentence):return None
    for clause in re.split(r'[,;]|\b(?:tandis que|alors que|mais|et)\b',canonical(sentence)):
        names=[re.search(r'(?<!\w)'+re.escape(canonical(a))+r'(?!\w)',clause) for a in aliases]
        dates=[re.search(r'(?<!\w)'+re.escape(canonical(e))+r'(?!\w)',clause) for e in editions]
        names=[m for m in names if m];dates=[m for m in dates if m]
        if not names or not dates:continue
        kind=_adoption(clause)
        if not kind:continue
        for name in names:
            for date in dates:
                begin=min(name.start(),date.start());end=max(name.end(),date.end())
                marked=clause[:begin]+'__ref__'+clause[end:]
                direct=re.search(r"__ref__\s+(?:(?:est|sont|sera|seront)\s+(?:(?:expressement|explicitement|contractuellement)\s+)?(?:retenu\w*\s+comme|adopte\w*\s+comme|exige\w*\s+comme|contractuel\w*\b|applicable\b|impose\w*\b|incorpore\w*\b|annexe contractuelle\b)|s'applique\b)",marked)
                required=re.search(r'\b(?:doit|doivent|devra|devront)\s+(?:respecter|appliquer|satisfaire|etre conforme a)\s+(?:(?:le|la|les|au|aux)\s+)?__ref__',marked)
                level=re.search(r'\b(?:objectif technique|niveau de service)\b[^,;]*\b(?:est|sera)\s+(?:celui|defini|fixe|prescrit|retenu)\s+(?:du|de|dans|par)\s+(?:(?:le|la)\s+)?__ref__',marked)
                if direct or required or level:return kind
    return None


def detect_application(readings,entry,reference_date=None):
    """Return evidence for an explicitly named edition, never a geographical guess."""
    aliases=entry.get('aliases') or [entry['title']]
    editions=entry.get('edition_aliases') or [entry['source_date']]
    page_texts=readings.get('text') or []
    if not isinstance(page_texts,list):
        return None
    matches=[]; conflicts=[]; mention_only=[]
    for page,text in enumerate(page_texts,1):
        for sentence in _sentences(str(text)):
            if not any(_contains(sentence,alias) for alias in aliases):
                continue
            if restricted_scope(sentence):
                conflicts.append(dict(page=page,citation=sentence,motif='portee_limitee_non_rattachee_au_point'))
                continue
            if re.search(r"\b(?:non applicable|non retenu|non contractuel|n'est pas|ne s'applique pas|ne sera pas|informatif|informative|historique)\b",canonical(sentence)):
                conflicts.append(dict(page=page,citation=sentence))
                continue
            if not any(_contains(sentence,edition) for edition in editions):
                mention_only.append(dict(page=page,citation=sentence,motif='edition_non_identifiee'))
                continue
            kind=adoption_of_named_reference(sentence,aliases,editions)
            if kind:
                matches.append(dict(page=page,citation=sentence,basis=kind))
    if not matches or conflicts:
        return None
    if reference_date and re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(reference_date)):
        if str(reference_date)[:7]<entry['source_date'][:7]:
            return None
    return dict(basis='reference_contractuelle' if any(x['basis']=='reference_contractuelle' for x in matches) else 'objectif_technique',
        evidence=matches,reference_date=reference_date,geography_inferred=False,
        legal_obligation_established=False,funding_established=False,
        limitation='Lien explicite avec le dossier pour comparaison technique. Aucun financement, obligation légale générale ou conformité globale déduit de ce lien.')


def _boxed_indexes(parts,ranges):
    result=set()
    for annotation in ranges:
        starts=[i for i,p in enumerate(parts) if _contains(p,annotation['start'])]
        ends=[i for i,p in enumerate(parts) if _contains(p,annotation['end_paragraph'])]
        if len(starts)!=1 or len(ends)!=1 or starts[0]>ends[0]:
            raise ValueError('Annotation visuelle non retrouvée de façon unique dans la page source.')
        result.update(range(starts[0],ends[0]+1))
    return result


def read_reference(entry,catalogue_path=CATALOGUE):
    """Hash-check before parsing, with catalogue-relative files confined locally."""
    catalogue_path=Path(catalogue_path).resolve()
    path=(catalogue_path.parent/entry['file']).resolve()
    if not path.is_relative_to(catalogue_path.parent):
        raise ValueError('Fichier de référence hors du répertoire du catalogue.')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
        raise ValueError('Empreinte du PDF de référence différente du catalogue.')
    # Parse the exact bytes whose identity was checked, not a reopened path.
    reader=PdfReader(BytesIO(raw))
    if len(reader.pages)!=entry['page_count']:
        raise ValueError('Nombre de pages du PDF de référence différent du catalogue.')
    pages=[]
    visual=entry.get('visual_annotations') or {}
    for number,page in enumerate(reader.pages,1):
        text=page.extract_text() or ''
        parts=paragraphs(text)
        annotations=visual.get(str(number),[])
        boxed=_boxed_indexes(parts,annotations)
        entries=[dict(id=f"{entry['id']}-P{number:03d}-{i+1:03d}",page=number,texte=part,
            boxed=True if i in boxed else None,
            visual_status='encadrement_observe' if i in boxed else 'non_qualifie',
            visual_review='Inspection visuelle de cette édition PDF ; ne constitue pas une validation juridique.' if i in boxed else None)
            for i,part in enumerate(parts)]
        pages.append(dict(page=number,texte=text,paragraphs=entries))
    general=[dict(page=p['page'],texte=p['texte']) for p in pages if p['page'] in entry.get('general_context_pages',[])]
    comparison_context=[]
    selections=entry.get('comparison_context_paragraphs')
    if selections:
        for selection in selections:
            found=[paragraph for p in pages if p['page']==selection['page']
                   for paragraph in p['paragraphs'] if _contains(paragraph['texte'],selection['anchor'])]
            if len(found)!=1:
                raise ValueError('Contexte de comparaison non retrouvé de manière unique dans le PDF.')
            if found[0] not in comparison_context:comparison_context.append(found[0])
    else:
        comparison_context=[paragraph for p in pages if p['page'] in entry.get('general_context_pages',[])
                            for paragraph in p['paragraphs']]
    included={p['id'] for p in comparison_context}
    omitted=[p['id'] for page in pages if page['page'] in entry.get('general_context_pages',[])
             for p in page['paragraphs'] if p['id'] not in included]
    catalogue_identity=None
    if catalogue_path.is_file():
        catalogue_raw=catalogue_path.read_bytes()
        registered=[x for x in json.loads(catalogue_raw).get('references',[]) if x.get('id')==entry['id']]
        if len(registered)==1 and registered[0]==entry:
            catalogue_identity=dict(path=str(catalogue_path),sha256=hashlib.sha256(catalogue_raw).hexdigest(),reference_id=entry['id'])
    return dict(id=entry['id'],title=entry['title'],source_date=entry['source_date'],sha256=entry['sha256'],
        catalogue_identity=catalogue_identity,
        path=str(path),source_type='reference_technique',provenance=entry['provenance'],
        source_url=entry.get('source_url'),page_count=len(pages),pages=pages,general_context=general,
        comparison_context=comparison_context,comparison_context_omitted=omitted,
        legal_source=False,values_programmed=False,
        limitations=['Texte extrait de la copie PDF identifiée. Les sauts de ligne et artefacts de lecture sont conservés.',
                    'Le rôle des paragraphes sans annotation visuelle reste non qualifié.',
                    'Une prescription de ce document technique n’est pas assimilée à une loi nationale.'])


def verify_reference(reference,readings):
    """Reconstruct evidence from the registered PDF and current dossier.

    A previous extraction is not trusted as proof. This checks catalogue/PDF
    identities, native page text, visual annotations and the adoption passage.
    The caller must obtain references from the server-side catalogue loader.
    """
    identity=reference.get('catalogue_identity') or {}
    if not identity.get('path') or identity.get('reference_id')!=reference.get('id'):
        raise ValueError('Identité du catalogue de référence absente ou incohérente.')
    catalogue_path=Path(identity['path']).resolve()
    raw=catalogue_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=identity.get('sha256'):
        raise ValueError('Le catalogue de référence a changé depuis sa lecture.')
    entries=[e for e in json.loads(raw).get('references',[]) if e.get('id')==reference['id']]
    if len(entries)!=1:
        raise ValueError('Référence non identifiée de manière unique dans le catalogue.')
    fresh=read_reference(entries[0],catalogue_path)
    for key in ('id','title','source_date','sha256','path','source_type','provenance','source_url',
                'page_count','pages','general_context','comparison_context','comparison_context_omitted',
                'catalogue_identity','legal_source'):
        if reference.get(key)!=fresh.get(key):
            raise ValueError('La référence fournie diffère du PDF ou du catalogue : '+key+'.')
    previous=reference.get('application') or {}
    application=detect_application(readings,entries[0],previous.get('reference_date'))
    if not application or application!=previous:
        raise ValueError('Adoption de cette édition non retrouvée exactement dans le dossier actuel.')
    fresh['application']=application
    return fresh


def references_for_document(readings,reference_date=None,catalogue_path=CATALOGUE):
    catalogue_path=Path(catalogue_path)
    catalogue=json.loads(catalogue_path.read_text(encoding='utf-8'))
    references=[]
    for entry in catalogue.get('references',[]):
        application=detect_application(readings,entry,reference_date)
        if application:
            reference=read_reference(entry,catalogue_path)
            reference['application']=application
            references.append(reference)
    return references


def candidate_passages(reference,quote,limit=8):
    """Lexical candidates only; complete paragraph and page remain available."""
    stop={'dans','pour','avec','cette','entre','doit','etre','sont','sera','projetee','projete','repere','plus','moins','hors','comme'}
    tokens={w for w in re.findall(r'[a-z]{3,}',canonical(quote)) if w not in stop}
    all_paragraphs=[p for page in reference['pages'] for p in page['paragraphs']]
    def has_word(text,word):
        return bool(re.search(r'\b'+re.escape(word.rstrip('s') if len(word)>4 else word)+r's?\b',text))
    weights={word:1+math.log((len(all_paragraphs)+1)/(1+sum(has_word(canonical(p['texte']),word) for p in all_paragraphs))) for word in tokens}
    candidates=[]
    for page in reference['pages']:
        for paragraph in page['paragraphs']:
            text=canonical(paragraph['texte'])
            score=sum(weights[word] for word in tokens if has_word(text,word))
            if score and paragraph.get('boxed') is True:
                score+=2
            if score:
                candidates.append({**paragraph,'score':score,'source_id':reference['id'],'source_title':reference['title'],
                    'source_page':page['page'],'context':page['texte'],
                    'context_ids':[p['id'] for p in page['paragraphs']],
                    'general_context':reference['general_context']})
    candidates.sort(key=lambda p:(-p['score'],p['page'],p['id']))
    return candidates[:max(0,min(int(limit),50))]
