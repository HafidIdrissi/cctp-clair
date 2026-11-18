"""General numeric routing: no subject catalogue and no stored legal thresholds."""
import copy
import math
import re
import unicodedata

def words(text):
    t=''.join(c for c in unicodedata.normalize('NFKD',str(text).lower()) if not unicodedata.combining(c))
    ignored=set('dans pour avec sans doit doivent sera seront une des les du de la le et ou au aux sur en un ce cette plus moins largeur hauteur longueur diametre mesure valeur metre metres centimetres millimetres'.split())
    return {w.rstrip('s') for w in re.findall(r'[a-z]{3,}',t) if w not in ignored}

def rank_candidates(candidates,index,quote):
    from slm_v6_focused_review import scalar_arithmetic,physical_measures
    target=words(quote)
    articles=[k for k,v in index.items() if v.get('kind')=='article']
    universe=articles if len(physical_measures(quote))==1 else list(candidates)
    tokens={key:words(index[key]['citation']) for key in articles}
    def score(key):
        citation=index[key]['citation']
        scalar=scalar_arithmetic(quote,citation)
        overlap=target & words(citation)
        weighted=sum(math.log(1+len(articles)/(1+sum(word in other for other in tokens.values()))) for word in overlap)
        # This is a retrieval order only: relevance/application checks remain mandatory.
        return (bool(scalar) and bool(overlap),weighted)
    return sorted(universe,key=score,reverse=True)[:6]

def context_pieces(source,obligation,law):
    from slm_v6_focused_review import article_sections,canonical
    section=law['section_complete']
    starts=list(re.finditer(r'(?m)^\s*[a-z]\)\s+',section))
    pieces={'REGLE':obligation}
    intro=article_sections(source)[0].strip()
    if intro and canonical(intro)!=canonical(section):pieces['INTRO']=intro
    if not starts:
        for line in section.splitlines():
            if line.strip() and canonical(line)!=canonical(obligation):pieces['R'+str(len(pieces))]=line.strip()
        return pieces,dict(method='section_integrale_sans_sous_paragraphes',section_conservee=section)
    criterion=re.sub(r'^\s*\d+\s*[°º][^\n]*\n','',obligation).strip()
    selected=None;retained=[]
    for i,m in enumerate(starts):
        block=section[m.start():starts[i+1].start() if i+1<len(starts) else len(section)].strip()
        if canonical(criterion) in canonical(block):selected=block
        elif re.search(r'\b(?:sauf|toutefois|ensemble|tous les cas|dispositions communes|par dérogation)\b',block,re.I):retained.append(block)
    if selected is None:return {'REGLE':obligation,**{'R'+str(i):p for i,p in enumerate(section.splitlines(),1) if p.strip()}},dict(method='section_integrale_sous_paragraphe_non_resolu')
    if canonical(selected)!=canonical(obligation):pieces['SOUS_PARAGRAPHE']=selected
    for i,p in enumerate(retained,1):pieces['RESERVE'+str(i)]=p
    return pieces,dict(method='sous_paragraphe_complet_et_introduction',section_conservee=section,
        sous_paragraphe=selected,reserves_conservees=retained,
        limite='Autres sous-paragraphes conservés dans les preuves. Les renvois d’application restent vérifiés séparément.')

def numeric_decision(arithmetic,first,second):
    if not arithmetic or type(arithmetic.get('resultat')) is not bool:return None
    required=('meme_objet','applicable','complet','exceptions_resolues','sans_contradiction','critere_fidele')
    if any(any(r.get(k) is not True for k in required) or r.get('manques')!=[] for r in (first,second)):return None
    outcome='respecte' if arithmetic['resultat'] else 'ecart'
    a,b=copy.deepcopy(first),copy.deepcopy(second)
    for r in (a,b):
        r['resultat']=outcome
        r['raison']='Calcul indépendant : '+arithmetic['calcul']+' Le même objet, le champ et les conditions sont établis par les deux lectures.'
    return a,b,dict(method='calcul_generique_apres_verification_du_champ',calcul=arithmetic,
        propositions_initiales=[first,second],resultat_calcule=outcome,
        limite='Décision numérique seulement ; aucune condition ou réserve n’est supprimée.')
