"""Explicit examination questions; inventory units are not all legal checks.

Only literal, narrow documentary/context cases bypass legal discovery.
Unknown prescriptions remain active. A contractual obligation is not a legal
verdict or evidence that the contractor has actually performed the work.
"""
import re
from v4_8_document_service import norm
from v4_9_evidence import TOKEN
from slm_v6_semantic_review import page_quote
from slm_m3_journal import emit
from slm_core_atoms import sentence_spans

CONTEXT=(
    r'^l.operation porte sur la realisation de .+sur un lineaire de \d+ metres\.$',
    r'^les travaux concernent une voie urbaine publique .+\.$',
    r'^le cheminement pieton et les details .+ sont integralement crees ou reconstruits dans le present lot\.$',
    r'^aucun de ces ouvrages n.est conserve en l.etat\.$',
    r'^aucune impossibilite technique ni derogation administrative n.est retenue pour cette operation\.$',
    r'^le projet prevoit la refection complete de la chaussee\.$',
    r'^le cheminement pieton est integralement cree ou reconstruit\.$',
)


def scope_continuation(quote, fact, readings):
    """Recognize a layout-split scope sentence, with its full native witness.

    No neighbouring prescription is consumed and the original units remain.
    """
    page=fact.get('page')
    if type(page) is not int or not 1<=page<=len(readings.get('text',[])):return None
    text=readings['text'][page-1]
    pattern=r'Les travaux concernent une voie urbaine publique située en agglomération,\s+ouverte à la circulation publique\.'
    for match in re.finditer(pattern,text,re.I):
        witness=match.group()
        # Each inventory unit must be one complete side of this comma break.
        sides=re.split(r',\s+',witness,maxsplit=1)
        choices=[witness,sides[0]+',',sides[1]]
        if ' '.join(quote.split()) in [' '.join(s.split()) for s in choices]:
            return dict(page=page,citation=witness,debut=match.start(),fin=match.end(),
                method='phrase_de_perimetre_native_continuee_apres_virgule')
    return None


def describe(row):
    fact=row['fait'];quote=fact.get('citation_visible','');kind=fact.get('type_fait','')
    technical=kind in ('largeur_pieton','devers_pieton','pente_longitudinale','ressaut','fente_grille',
        'bande_eveil','distance_stationnement_amont','absence_amenagement_cyclable')
    measured=bool(TOKEN.search(quote))
    regulatory=bool(re.search(r'\b(?:reglementaire|reglementation|loi|decret|arrete|code de|code du)\b',norm(quote)))
    category='controle_technique' if technical or measured else 'question_reglementaire' if regulatory else 'a_qualifier'
    question=('La caractéristique « '+(fact.get('element') or kind or 'du passage')+' » prescrite dans ce dossier respecte-t-elle le critère applicable, à la date et sous les conditions établies ?')
    intent=dict(category=category,question=question,
        justification='Proposition à qualifier : la présence d’une phrase ou d’une mesure ne prouve pas une obligation réglementaire.',
        evidence=dict(page=fact.get('page'),citation=quote,origin=fact.get('origine')),
        required_facts=['objet et caractéristique','état et périmètre de l’ouvrage','critère et version datée','conditions et exceptions'],
        evidence_state='a_verifier',legal_question_established=technical,
        evaluation_scope='prescriptions_du_dossier',execution_verified=False)
    row['core_control_intent']=intent
    return intent


def verify_plan_references(quote, readings):
    """Bind each cited drawing to its own caption on the stated page."""
    match = re.fullmatch(r'Les plans (P\d+) et (P\d+) des pages (\d+) et (\d+) '
                         r'définissent les ouvrages projetés\.', ' '.join(quote.split()), re.I)
    if not match:
        return []
    first, second, page_one, page_two = match.groups()
    if first.upper() == second.upper() or int(page_one) == int(page_two):
        return []
    evidence = []
    for ref, number in ((first, int(page_one)), (second, int(page_two))):
        pages = [p for p in readings.get('pages_visuelles', []) if p.get('page') == number]
        if len(pages) != 1 or not 1 <= number <= len(readings.get('text', [])):
            return []
        # Require both a native mention and a separate drawing caption.
        if not re.search(r'\b' + re.escape(ref) + r'\b', readings['text'][number - 1], re.I):
            return []
        captions = [line for line in pages[0].get('ocr', {}).get('lines', [])
                    if re.fullmatch(r'\s*PLAN\s+' + re.escape(ref) + r'\s*[-–:]\s*\S.+', line, re.I)]
        if len(captions) != 1:
            return []
        evidence.append(dict(page=number, repere=ref, legende=captions[0]))
    return evidence


def classify(row,readings):
    """Return True only for explicit metadata, context or document duties."""
    fact=row['fait'];quote=fact.get('citation_visible','');intent=row.get('core_control_intent') or describe(row)
    if fact.get('origine')!='texte_natif' or fact.get('type_fait')!='clause_a_examiner' or not page_quote(fact,readings.get('text',[]),'citation_visible'):return False
    text=norm(quote);category=None;reason=None
    continuation=scope_continuation(quote,fact,readings)
    plans = verify_plan_references(quote, readings)
    if plans:
        category = 'information_documentaire'
        reason = 'Renvois aux plans vérifiés : ' + ' et '.join(
            f"{p['repere']} page {p['page']}" for p in plans) + '.'
        intent['plans_verifies'] = plans
    elif re.fullmatch(r'le present cctp est etabli le \d{1,2}(?:er)? [a-z]+ \d{4}\.',text):
        category='information_documentaire';reason='Date de rédaction du CCTP conservée comme métadonnée ; aucune question de validité juridique n’est établie par cette seule date.'
    elif continuation or (len(sentence_spans(quote))==1 and not re.search(r';|\b(?:largeur|pente|devers|ressaut|fente|paiement|normes)\b',text)
          and any(re.fullmatch(pattern,text) for pattern in CONTEXT)):
        category='contexte_analyse';reason='Condition ou périmètre explicite conservé pour les contrôles liés ; ce contexte ne constitue pas à lui seul un écart ni une conformité.'
    contractual=(re.fullmatch(r'(?:le titulaire|il) (?:soumet|remet|fournit) .+\.',text)
        and re.search(r'\b(?:plans?|phasage|dossier|fiches?|documents?)\b',text)
        and not re.search(r';|\b(?:et adapte|sauf|si|lorsque|sans|aucun|aucune|dispense|derogation|code|loi|decret|arrete|norme|normes)\b',text))
    if category:
        if continuation:row['core_scope_continuation']=continuation
        intent.update(category=category,question='Quel contexte ou renseignement ce passage apporte-t-il aux contrôles du dossier ?',
            justification=reason,required_facts=[],evidence_state='citation_native_exacte',legal_question_established=False,
            evaluation_scope='contexte_documentaire',retained_as_context=True)
        row.update(statut='information_documentaire',comparaison=None,regle=None,article=None,source=None,explication=reason,
            verification_article=dict(outcome='information',eligible=False,method='core_intention_documentaire',
                checks=dict(citation_native_exacte=True),missing=[],review_state='completed',
                resolution=dict(kind='information_documentaire',detail=reason)))
        emit('intention_controle','done',fact_id=fact['id'],**intent)
        return True
    if contractual:
        reason='Obligation de remise documentaire identifiée. Aucun critère réglementaire distinct n’est établi ; la prescription ne prouve pas sa réalisation effective. Obligation conservée comme contrôle contractuel, sans verdict de conformité.'
        intent.update(category='obligation_contractuelle',question='Quelles pièces ce passage impose-t-il de remettre, par qui et à quelle échéance ?',
            justification=reason,required_facts=['pièces exigées','acteur','échéance ou condition de remise'],
            evidence_state='citation_native_exacte',legal_question_established=False,evaluation_scope='prescription_contractuelle')
        row.update(statut='a_verifier',comparaison=None,source=None,article=None,regle=None,explication=reason,
            verification_article=dict(outcome='indetermine',eligible=False,method='core_obligation_contractuelle',
                checks=dict(citation_native_exacte=True),missing=['Critère d’évaluation contractuel à définir ; aucune non-conformité réglementaire déduite.'],
                review_state='not_started',resolution=dict(kind='critere_contractuel_a_definir',detail=reason)))
        emit('intention_controle','done',fact_id=fact['id'],**intent)
        return True
    return False


def qualify_question(row,qualification):
    intent=row.get('core_control_intent') or describe(row);p=qualification.get('proposal',{})
    if qualification.get('search_ready'):
        intent.update(question='Quel critère applicable contrôle « '+p.get('objet','')+' — '+p.get('action','')+' »'+
            (' pour « '+p['caracteristique']+' »' if p.get('caracteristique') else '')+' ?',
            justification='Objet et action cités dans le CCTP ; l’existence et l’applicabilité de la règle restent à établir.',
            legal_question_established=False,evidence_state='qualification_citee')
    else:
        intent.update(evidence_state='preuve_manquante_ou_insuffisante',
            justification='Qualification de la prescription non établie ; aucun contrôle supprimé ni conformité déduite.')
    emit('question_controle','done',fact_id=row['fait']['id'],**intent)


def finalize(row):
    intent=row.get('core_control_intent') or describe(row);check=row.get('verification_article') or {}
    if check.get('outcome')=='information' and intent['category'] not in ('contexte_analyse','obligation_contractuelle'):
        intent.update(category='information_documentaire',evaluation_scope='contexte_documentaire',legal_question_established=False)
    source=row.get('source') or {}
    if check.get('outcome') in ('respecte','ecart'):
        intent.update(legal_question_established=bool(source.get('id')),
            evaluation_scope='critere_reglementaire_prescrit' if source.get('id') else 'critere_technique_documentaire')
    if check.get('checks',{}).get('lecture_valide') is False:
        intent['evidence_state']='preuve_manquante_ou_insuffisante'
    # This engine examines a specification, never certifies completed works.
    intent['execution_verified']=False
    return intent
