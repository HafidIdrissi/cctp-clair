"""Literal document provenance is information, never a compliance verdict."""
import re
from v4_8_document_service import norm
from v4_9_evidence import TOKEN
from slm_v6_semantic_review import page_quote
from slm_m3_journal import emit


def classify_documented_scope(row,readings,analysis):
    """A native scope clause linked to an already verified exclusion is context."""
    from slm_core_perimeter import verify
    from slm_v6_semantic_review import canonical
    fact=row['fait'];quote=fact.get('citation_visible','')
    if fact.get('origine')!='texte_natif' or fact.get('type_fait')!='clause_a_examiner' or TOKEN.search(quote) or not page_quote(fact,readings.get('text',[]),'citation_visible'):return False
    links=[]
    for other in analysis.get('lignes',[]):
        proof=other.get('verification_perimetre_core') or {};scope=proof.get('native_scope') or {}
        complete=scope.get('citation','');first=re.split(r'\n\s*\n',complete,maxsplit=1)[0]
        # Native inventory may stop at the complete first paragraph, whereas
        # the source passage also preserves a following annex index/footer.
        # No arbitrary excerpt or model-written summary is accepted.
        exact_segment=canonical(quote) in {canonical(complete),canonical(first)}
        if scope.get('page')==fact.get('page') and exact_segment and verify(other['fait'],readings,proof):
            links.append(dict(fact_id=other['fait']['id'],proof=proof,clause_segment=quote,
                segment_method='passage_integral' if canonical(quote)==canonical(complete) else 'paragraphe_initial_complet'))
    if not links:return False
    reason='Ce passage décrit le périmètre d’un ouvrage existant dont l’exclusion des travaux est établie par le texte et les deux lectures de sa ligne de plan. Il est conservé comme contexte, sans conformité juridique de l’existant.'
    row.update(statut='information_documentaire',comparaison=None,source=None,regle=None,article=None,
        mode_verification='classification_semantique',explication=reason,
        action='Consulter le contrôle du repère lié ; aucune conformité de l’existant n’est affirmée.',
        classification_semantique=dict(categorie='contexte',verifiee=True,raison=reason,citation=quote,page=fact['page'],methode='clause_exacte_du_perimetre_deja_documente'),
        verification_article=dict(method='comparaison_semantique_v6',outcome='information',eligible=True,classification_verifiee=True,
            checks=dict(citation_native_exacte=True,preuve_perimetre_rejouee=True,meme_passage_integral=True),missing=[],
            perimetres_lies_core=links,resolution=dict(kind='information_documentaire',detail=reason)))
    emit('contexte_perimetre_documente','done',fact_id=fact['id'],linked_fact_ids=[v['fact_id'] for v in links],model_call=False,legal_verdict=False)
    return True


def classify_metadata(row,readings):
    fact=row['fait'];quote=fact.get('citation_visible','')
    if classify_structure(row,readings):return True
    if (fact.get('origine')!='texte_natif' or fact.get('type_fait')!='clause_a_examiner'
        or not page_quote(fact,readings.get('text',[]),'citation_visible') or TOKEN.search(quote)):return False
    text=re.sub(r'\s+',' ',norm(quote))
    training=(re.search(r'support d.entrainement et de demonstration',text)
        and re.search(r'ne pas utiliser pour concevoir.{0,30}construire',text)
        and 'clauses ne constituent pas un modele juridique' in text)
    publication=('document produit pour une demonstration technique' in text
        and re.search(r'aucune partie n.est engagee',text)
        and 'fin de la piece cctp pedagogique' in text)
    if not (training or publication):return False
    reason='Ce passage décrit explicitement le statut et l’usage du support pédagogique, sans dimension technique à comparer. Il est conservé comme information ; aucune conformité juridique n’est affirmée.'
    row.update(statut='information_documentaire',comparaison=None,source=None,regle=None,article=None,
        mode_verification='classification_semantique',explication=reason,action='Lire les prescriptions et leurs résultats séparément de ces informations de provenance.',
        classification_semantique=dict(categorie='contexte',verifiee=True,raison=reason,citation=quote,page=fact['page'],methode='provenance_documentaire_litterale'),
        verification_article=dict(method='comparaison_semantique_v6',outcome='information',eligible=True,classification_verifiee=True,
            validation_mode='classification_litterale_du_statut_documentaire',checks=dict(citation_native_exacte=True,statut_pedagogique_explicite=True,aucune_mesure_technique=True),
            missing=[],resolution=dict(kind='information_documentaire',detail=reason)))
    emit('provenance_documentaire','done',fact_id=fact['id'],page=fact['page'],citation=quote,model_call=False,legal_verdict=False)
    return True


def classify_structure(row,readings):
    """Retain explicit numbered headings and repeated footers as information."""
    fact=row['fait'];quote=fact.get('citation_visible','')
    if fact.get('origine')!='texte_natif' or fact.get('type_fait')!='clause_a_examiner':return False
    page=fact.get('page')
    if type(page) is not int or not 1<=page<=len(readings.get('text',[])) or quote not in readings['text'][page-1]:return False
    text=re.sub(r'\s+',' ',quote).strip();plain=norm(text)
    match=re.fullmatch(r'(?:\d{1,3}\.\s+|(?:Article|Clause|Chapitre)\s+\d[\d.]*\s*[-:–]\s*)([^.!?;:]{2,90})',text,re.I)
    title=match.group(1) if match else ''
    from slm_core_obligations import ACTION
    # Numeric requirements, complete sentences and imperatives are not titles.
    heading=bool(title and not TOKEN.search(title) and not ACTION.search(norm(title)) and not re.search(
        r'\b(?:doit|doivent|devra|devront|est|sont|sera|seront|respecter|fournir|livrer|interdit|obligatoire|exige|impose|paiement sous)\b',norm(title)))
    if re.match(r'^(?:Article|Clause|Chapitre)\b',text,re.I):
        # A prefix "Article N" is not proof of a nominal heading. Keep
        # unknown verbal formulations for qualification rather than hide them.
        heading=heading and bool(re.match(r'^(?:objet|cheminement|documents?|travaux|description|materiaux|reception|plans?|profil|dispositions|conditions|annexes?|generalites)\b',norm(title)))
    document_title=plain in ('cahier des clauses techniques particulieres','cctp',
        'cctp fictif - essai logiciel uniquement')
    # Complete, labelled metadata only. A date inside a deadline/prescription
    # must not be mistaken for the document's reference date.
    metadata=bool(not ACTION.search(plain) and (
        re.fullmatch(r'date de reference\s*:\s*\d{4}-\d{2}-\d{2}\.?',plain)
        or re.fullmatch(r'commune\s*:\s*[a-z][a-z \'’-]{0,80}\.?',plain)))
    lot_header=bool(re.fullmatch(r'[A-ZÀ-ÖØ-Þ &/\-]+\|\s*LOT\s+\d+',text))
    footer=bool(re.search(r'\|\s*cctp\s*\|',plain) and re.search(r'\b\d+\s*/\s*\d+\s*$',plain)
        and sum(bool(re.search(r'\|\s*cctp\s*\|',norm(p))) for p in readings['text'])>=2)
    from slm_core_obligations import nominal_heading
    nominal=nominal_heading(quote)
    if not (heading or document_title or metadata or footer or lot_header or nominal):return False
    reason='Titre, métadonnée ou pied de page conservé comme contexte ; ce passage ne formule pas à lui seul une prescription contrôlable.'
    row.update(statut='information_documentaire',comparaison=None,source=None,regle=None,article=None,
        explication=reason,action='Consulter les prescriptions rattachées à ce titre.',mode_verification='classification_semantique',
        classification_semantique=dict(categorie='contexte',verifiee=True,raison=reason,citation=quote,page=page,methode='structure_documentaire_litterale_sans_modele'),
        verification_article=dict(method='comparaison_semantique_v6',classification_verifiee=True,validation_mode='structure_documentaire_litterale_sans_modele',outcome='information',eligible=True,checks=dict(citation_native_exacte=True,structure_documentaire=True),missing=[],
            resolution=dict(kind='information_documentaire',detail=reason)))
    emit('structure_documentaire','done',fact_id=fact['id'],citation=quote,model_call=False,legal_verdict=False)
    return True
