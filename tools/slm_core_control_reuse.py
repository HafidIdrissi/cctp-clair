"""Link an exact scalar inventory unit to a replayed control of this analysis.

No copied verdict, fuzzy match, persisted result cache or independent vote.
Mixed prescriptions and qualitative requirements keep their own examination.
"""
import copy
import hashlib
import re
from v4_8_document_service import norm
from v4_9_evidence import tokens
from slm_m3_journal import emit
from slm_core_programmed import decide

KINDS={'largeur_pieton','ressaut','pente_longitudinale','devers_pieton','fente_grille'}


def single_scalar(quote):
    text=' '.join(norm(quote).split())
    if len(tokens(quote))!=1:return False
    if re.search(r';|\b(?:et|mais|sauf|si|lorsque|sans|chanfrein|arrondi|bords?|doit|doivent|devra|devront)\b',text):return False
    # Deliberately limited syntax: the entire sentence states one dimension.
    return bool(re.fullmatch(r'(?:le|la|les) [a-z ’\'-]+ (?:presente|presentent) une (?:largeur libre|hauteur|pente|largeur|inclinaison) de \d+(?:[.,]\d+)?\s*(?:m|cm|mm|%)\.',text))


def reuse(row,analysis,readings,pool,reference,info):
    fact=row['fait'];quote=fact.get('citation_visible','');page=fact.get('page')
    if (fact.get('type_fait')!='clause_a_examiner' or fact.get('origine')!='texte_natif'
        or not single_scalar(quote) or type(page) is not int
        or not 1<=page<=len(readings.get('text',[]))):return False
    native=readings['text'][page-1]
    if native.count(quote)!=1:return False
    matched=[]
    for other in analysis['lignes']:
        original=other['fait'];check=other.get('verification_article') or {}
        if (original.get('type_fait') not in KINDS or original.get('origine')!='texte_natif'
            or original.get('page')!=page or original.get('citation_visible')!=quote
            or check.get('method')!='core_regle_revue_et_preuves_structurees'
            or check.get('eligible') is not True or check.get('outcome') not in ('respecte','ecart')
            or not check.get('checks') or not all(v is True for v in check['checks'].values())):continue
        # Recalculate from current native evidence and current dated sources.
        # Never trust a status/hash copied from another execution.
        replay=copy.deepcopy(other)
        if not decide(replay,readings,pool,reference,info):continue
        current=replay.get('verification_article') or {}
        if (current.get('eligible') is not True or current.get('outcome')!=check['outcome']
            or current!=check
            or replay.get('comparaison') is not other.get('comparaison')
            or replay.get('regle')!=other.get('regle')
            or (replay.get('source') or {}).get('texte')!=(other.get('source') or {}).get('texte')
            or (replay.get('source') or {}).get('id')!=(other.get('source') or {}).get('id')):continue
        matched.append(other)
    if len(matched)!=1:return False
    target=matched[0];target_id=target['fait']['id']
    reason=f'Cette prescription numérique exacte est déjà examinée par {target_id}. Consulter sa source, ses conditions et son calcul ; aucun second verdict ni contrôle de la forme n’est ajouté.'
    link=dict(target_id=target_id,page=page,date_reference=reference,citation=quote,
        page_sha256=hashlib.sha256(native.encode()).hexdigest(),
        source_id=target['source']['id'],method='meme_prescription_scalaire_et_calcul_rejoue',
        independent_validation=False)
    row.update(statut='information_documentaire',comparaison=None,source=None,regle=None,article=None,
        mode_verification='rattachement_controle',explication=reason,action=f'Consulter {target_id}.',
        core_control_link=link,verification_article=dict(method='comparaison_semantique_v6',
            outcome='information',eligible=False,classification_verifiee=True,review_state='completed',
            checks=dict(citation_native_exacte=True,meme_page=True,prescription_scalaire_unique=True,calcul_rejoue=True),
            missing=[],resolution=dict(kind='controle_deja_effectue',detail=reason)))
    emit('rattachement_controle_existant','done',fact_id=fact['id'],**link,model_call=False)
    return True
