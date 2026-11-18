"""Arithmetic aid/veto for existing version-reviewed rules, never applicability."""
import copy
import hashlib
import math
import re


def reviewed_criterion(fact, source, section, reference):
    """Recognize an existing control in its reviewed official source/version.

    This establishes the criterion, never the project's legal scope or verdict.
    Exact complete rule sentences retain their conditional alternatives.
    """
    from v4_9_document_service import RULES
    from v4_8_document_service import norm
    from slm_v5_report import reviewed_sources
    from slm_v6_semantic_review import source_valid
    kind=fact.get('type_fait')
    if kind not in RULES:return None
    key,article,_,_=RULES[kind]
    _,gates,_=reviewed_sources(dict(date_reference=reference,sources_locales={key:source}))
    original=gates.get(key,{})
    checks={k:v for k,v in original.get('checks',{}).items() if k!='source_dila'}
    checks['source_officielle_datee']=source_valid(source,reference)
    if not original or not all(checks.values()):return None
    gate=dict(checks=checks,eligible=True,version_attendue=original['version_attendue'],
        sha256_texte=original['sha256_texte'],provenance=source.get('provenance'))
    expected=re.search(r'\b(\d+)\s*°',article)
    if expected and set(re.findall(r'(?m)^\s*(\d+)\s*[°º]',section))!={expected[1]}:return None
    patterns={
        'largeur_pieton':r'La largeur minimale du cheminement[^.]*\.\s*Cette largeur[^.]*\.',
        'devers_pieton':r'En cheminement courant,\s+le dévers est[^.]*\.',
        'ressaut':r'Les ressauts sur les cheminements[^.]*\.\s+La hauteur des ressauts[^.]*\.\s+Elle peut atteindre[^.]*\.',
        'fente_grille':r'Les trous ou fentes dans le sol[^.]*\.',
        'bande_eveil':r"Une bande d['’]éveil de vigilance[^.]*au droit des traversées matérialisées\.",
    }
    if kind in patterns:
        match=re.search(patterns[kind],section,re.I)
        if not match:return None
        obligation=match[0]
        before=section[:match.start()]
        previous=before.rstrip().splitlines()[-1] if before.rstrip() else ''
        if re.match(r'^\s*\d+\s*[°º]',previous):
            # Retain an unpunctuated section heading so the literal quote starts
            # at a complete legal boundary, without adding another criterion.
            obligation=section[before.rfind(previous):match.end()]
    else:
        obligation=section.strip()
        anchors={'distance_stationnement_amont':r'amont',
                 'absence_amenagement_cyclable':r'itineraire.{0,12}cyclabl',
                 'derogation_par_visa':r'prefet|commission'}
        if not re.search(anchors[kind],norm(obligation)):return None
    return dict(eligible=True,type_fait=kind,article=article,source_id=source['id'],gate_version=gate,
        obligation=obligation,nature='presence' if kind in ('absence_amenagement_cyclable','bande_eveil') else 'procedure' if kind=='derogation_par_visa' else 'dimension',
        methode='critere_programme_retrouve_dans_sa_version_officielle_revue',
        limites='Correspondance du critère seulement ; applicabilité et verdict restent à établir sur les preuves du CCTP.')


def programmed_arithmetic(fact, source, section, reference):
    from v4_9_document_service import compare
    from v4_9_evidence import tokens
    from v4_8_document_service import norm
    kind=fact.get('type_fait')
    if kind not in ('largeur_pieton','devers_pieton','ressaut','fente_grille','distance_stationnement_amont'):return None
    binding=reviewed_criterion(fact,source,section,reference)
    if not binding:return None
    quote=str(fact.get('citation_visible') or '')
    value=fact.get('valeur');unit=fact.get('unite')
    if type(value) not in (int,float) or not math.isfinite(value) or (value,unit) not in tokens(quote):return None
    if kind=='devers_pieton':
        if unit!='%':return None
    elif (unit not in ('m','cm','mm') or type(fact.get('valeur_m')) not in (int,float)
          or not math.isfinite(fact['valeur_m']) or abs(fact['valeur_m']-value*{'m':1,'cm':.01,'mm':.001}[unit])>1e-8):return None
    derived=copy.deepcopy(fact);condition=None
    if kind=='largeur_pieton':
        # A model flag alone cannot establish the conditional reduced width.
        condition=bool(re.search(r'(?:aucun|absence de|sans).{0,30}mur.{0,25}obstacle.{0,45}(?:deux cotes|part et d.autre)',norm(quote)))
        derived['sans_obstacle_deux_cotes']=True if condition else None
    result,why=compare(derived)
    if type(result) is not bool:return None
    decisive=result is False and kind in ('largeur_pieton','ressaut') and condition is not True
    return dict(resultat=result,calcul=f'Valeur écrite : {value:g} {unit}. '+why,
        methode='calcul_de_la_regle_existante_liee_a_sa_version_officielle',article=binding['article'],source_id=source['id'],
        sha256_source=hashlib.sha256(source['texte'].encode()).hexdigest(),gate_version=binding['gate_version'],
        condition_absence_obstacles_citee=condition,citation=quote,
        toutes_alternatives_numeriques_en_ecart=decisive,
        condition_numerique_non_determinante=('Le résultat est négatif dans toutes les alternatives de cette règle. La condition qui choisit entre ces alternatives ne peut pas rendre la valeur acceptable. Ne pas demander cette condition pour trancher le seul écart numérique.' if decisive else None),
        limites='Calcul du critère seulement. Le même objet, le champ d’application, les conditions et exceptions restent à vérifier dans les deux lectures.')
