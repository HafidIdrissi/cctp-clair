"""Program exclusions before semantic source selection. Unknown is not applicable."""
import re
from v4_8_document_service import norm
from slm_v6_semantic_review import source_valid
from slm_m3_journal import emit

REGIMES={
 'navigation_maritime':(r'navires?|navigation maritime|securite des navires',r'navires?|navigation maritime|port maritime'),
 'lit_cours_eau':(r'lit detourne|nouveau lit|facies d.ecoulement|rubrique\s*3\.1\.2\.0',r'cours d.eau|lit (?:du|de la) (?:fleuve|riviere)|lit detourne|nouveau lit'),
 'formation_autisme':(r'autisme|troubles du spectre',r'autisme|troubles du spectre'),
 'competence_juridictionnelle':(r'code de justice administrative',r'tribunal|recours|juridiction|competence contentieuse'),
 'classement_touristique':(r'communes touristiques|stations classees de tourisme',r'commune touristique|station classee de tourisme'),
}

def examine(source,fact,readings,reference):
    checks=dict(version_datee=source_valid(source,reference))
    title=source.get('nom_code') or source.get('titre') or ''
    headings=' '.join(h.get('title','') for h in (source.get('codification') or {}).get('parents',[]))
    legal=norm(title+' '+headings+' '+source.get('texte',''))
    target=norm(fact.get('citation_visible',''))
    # Project context may establish a physical regime, never the action tested.
    project=norm(' '.join(readings.get('texte_natif_original',readings.get('text',[]))))
    exclusions=[]
    private=bool(re.search(r'\bdroit prive\b',project+' '+target))
    public_ccag=bool(re.search(r'cahier des clauses administratives generales des marches publics',legal))
    incorporates_ccag=bool(re.search(r'\bccag\b|cahier des clauses administratives generales',project+' '+target))
    if private and public_ccag and not incorporates_ccag:
        exclusions.append('ccag_marche_public_sans_incorporation_contrat_prive')
    for regime,(law_pattern,document_pattern) in REGIMES.items():
        if re.search(law_pattern,legal):
            text=target if regime=='competence_juridictionnelle' else project+' '+target
            if not re.search(document_pattern,text):exclusions.append(regime)
    reason='Version officielle datée invalide.' if not checks['version_datee'] else 'Régime spécifique non documenté dans le dossier : '+', '.join(exclusions) if exclusions else 'Aucune exclusion programmée détectée ; applicabilité encore à établir.'
    return dict(accepted_for_examination=checks['version_datee'] and not exclusions,checks=checks,excluded_regimes=exclusions,reason=reason,
        applicability_proved=False,source_id=source.get('id'))

def filter_pool(pool,fact,readings,reference,info):
    kept={}
    for key,source in pool.items():
        gate=examine(source,fact,readings,reference)
        info['exchanges'].append(dict(stage='filtre_source_programme',status='derived',model_call=False,fact_id=fact['id'],**gate))
        emit('filtre_source_programme','done',fact_id=fact['id'],**gate)
        if gate['accepted_for_examination']:kept[key]=source
    return kept
