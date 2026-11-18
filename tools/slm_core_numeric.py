"""Core-only slope operator bound to the reviewed official access version."""
import re,math,hashlib
from v4_8_document_service import norm
from v4_9_evidence import tokens
from slm_v5_report import reviewed_sources
from slm_v6_semantic_review import source_valid

def reviewed_arithmetic(fact,source,section,reference):
    from slm_v6_numeric_evidence import programmed_arithmetic,reviewed_criterion
    result=programmed_arithmetic(fact,source,section,reference)
    if result:return result
    if fact.get('type_fait')!='ressaut':return slope_arithmetic(fact,source,section,reference)
    binding=reviewed_criterion(fact,source,section,reference)
    if not binding:return None
    quote=fact.get('citation_visible','');plain=norm(quote);v=fact.get('valeur');unit=fact.get('unite');metres=fact.get('valeur_m')
    if type(v) not in (int,float) or not math.isfinite(v) or (v,unit) not in tokens(quote) or unit not in ('m','cm','mm'):return None
    if type(metres) not in (int,float) or not math.isfinite(metres) or abs(metres-v*{'m':1,'cm':.01,'mm':.001}[unit])>1e-8 or metres<0:return None
    if re.search(r'(?:sans|non|aucun|pas de).{0,25}(?:arrondi|chanfrein)',plain):return None
    shape=bool(re.search(r'\barrondis?\b|\bchanfreins?\b',plain))
    ratio=bool(re.search(r'chanfrein.{0,25}(?:un pour trois|1\s*(?:pour|/|:)\s*3)',plain))
    if not shape or metres>.02 and not (metres<=.04 and ratio):return None
    return dict(resultat=True,calcul=f'Ressaut écrit : {v:g} {unit}. '+('Hauteur au plus 2 cm et forme arrondie ou chanfreinée explicitement citée.' if metres<=.02 else 'Hauteur au plus 4 cm et chanfrein un pour trois explicitement cité.'),
        source_id=source['id'],article=binding['article'],sha256_source=hashlib.sha256(source['texte'].encode()).hexdigest(),
        methode='calcul_core_et_forme_du_ressaut_citee',forme_citee=True,ratio_un_pour_trois=ratio,
        limites='Hauteur et forme prescrites seulement ; attribution, champ des travaux et source datée requis.')

def slope_binding(fact,source,section,reference):
    if fact.get('type_fait')!='pente_longitudinale':return None
    _,gates,_=reviewed_sources(dict(date_reference=reference,sources_locales={'access':source}))
    original=gates.get('access',{});checks={k:v for k,v in original.get('checks',{}).items() if k!='source_dila'}
    if not checks or not all(checks.values()) or not source_valid(source,reference):return None
    if not re.match(r'^\s*1\s*[°º]\s+Pentes\b',section):return None
    # Keep the complete numbered section including tolerance branches.
    if not all(re.search(p,norm(section)) for p in (r'inferieure a 5\s*%',r'8\s*%',r'12\s*%',r'impossibilite technique')):return None
    return dict(eligible=True,type_fait='pente_longitudinale',article='art. 1, 1°',source_id=source['id'],
        gate_version=original,obligation=section,nature='dimension',methode='section_pentes_version_officielle_revue')

def slope_arithmetic(fact,source,section,reference):
    binding=slope_binding(fact,source,section,reference)
    if not binding:return None
    quote=fact.get('citation_visible','');v=fact.get('valeur')
    if type(v) not in (int,float) or not math.isfinite(v) or v<0 or fact.get('unite')!='%' or (v,'%') not in tokens(quote):return None
    if not re.search(r'pente longitudinale',norm(quote)):return None
    # The intermediate tolerance cases require additional documented conditions.
    if v>=5 and v<=12:return None
    result=v<5
    return dict(resultat=result,calcul=f'Pente longitudinale écrite : {v:g} %. '+('Inférieure au seuil ordinaire de 5 %.' if result else 'Supérieure au maximum de 12 % de toutes les branches citées.'),
        operateur='<' if result else '>',seuil_cite=5 if result else 12,source_id=source['id'],
        sha256_source=hashlib.sha256(source['texte'].encode()).hexdigest(),
        limites='Seul critère de pente longitudinale ; paliers, garde-corps et autres obligations contrôlés séparément. Champ et attribution requis.')
