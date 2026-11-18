"""Automatic green for a narrowly evidenced criterion, with explicit gates.

No confidence score or human validation is invented. Positive documentary
checks concern the stated project value, not the actual completed works.
"""
import re
from v4_8_document_service import norm
from v4_9_evidence import tokens


def automatic_check(fact, readings, sources, comparison):
    kind=fact.get('type_fait')
    quote=str(fact.get('preuve_citation_native') or fact.get('citation_visible') or '')
    page=fact.get('page')
    text=readings.get('text',[])
    native=text[page-1] if isinstance(page,int) and 1<=page<=len(text) else ''
    compact=lambda s:re.sub(r'\s+',' ',norm(s)).strip()
    # A model's quotation is checked against the actual page, independently
    # from the existing OCR corroboration heuristics.
    literal=bool(compact(quote) and compact(quote) in compact(native))
    datum=(fact.get('valeur'),fact.get('unite'))
    annotation=norm(quote)
    patterns={'largeur_pieton':r'(?:cheminement\s+pieton|trottoir|largeur libre)',
              'devers_pieton':r'devers', 'fente_grille':r'fente|ouverture'}
    correct_object=bool(kind in patterns and re.search(patterns[kind],annotation))
    if kind=='largeur_pieton':
        correct_object=correct_object and bool(re.search(r'largeur libre|libre de mobilier|libre de tout.{0,15}obstacle',annotation))
        if re.search(r'cyclab|piste|grille|fente',annotation):correct_object=False
    if kind=='devers_pieton':
        correct_object=correct_object and bool(re.search(r'cheminement courant|cheminement pieton|trottoir',annotation)) and not bool(re.search(r'rampe|pente longitudinale',annotation))
    if kind=='fente_grille':
        correct_object=correct_object and bool(re.search(r'grille|dans le sol',annotation)) and bool(re.search(r'cheminement|pieton|trottoir|dans le sol',annotation))
        if 'entraxe' in annotation:correct_object=False
    # Conditions must be written in the same retained quotation.
    condition=True
    if kind=='largeur_pieton' and (fact.get('valeur_m') or 0)<1.40:
        condition=fact.get('sans_obstacle_deux_cotes') is True and bool(re.search(r'(?:aucun|absence de|sans).{0,30}mur.{0,25}obstacle.{0,45}(?:deux cotes|part et d.autre)',annotation))
    paragraphs=[norm(p) for t in text for p in re.split(r'\n\s*\n',str(t))]
    # Require written, native project context in one passage, not an OCR
    # guess or three isolated phrases pulled from different project sectors.
    context=next((p for p in paragraphs if
        re.search(r'refection|renovation|rehabilitation|reamenagement|realisation de voies nouvelles|(?:creation|cree|creer|amenagement).{0,35}(?:cheminement|trottoir|voie)',p) and
        re.search(r'en agglomeration|voirie urbaine|voie urbaine',p) and
        re.search(r'circulation publique|voirie publique|espace public|traversees pietonnes publiques',p) and
        not re.search(r'hors agglomeration|(?:pas|non).{0,12}(?:publique|agglomeration)|sans travaux',p)),None)
    # Conflicting scope and derogation references require closer examination.
    alltext=norm('\n'.join(str(t) for t in text))
    competing=bool(re.search(r'hors agglomeration|voirie privee|derogation|impossibilite technique',alltext))
    # Recover an explicit project state only from the exact retained native
    # quotation. Never turn an existing/ambiguous state into a project.
    project_quote=literal and bool(re.search(r'\bprojete(?:e|s|es)?\b',annotation)) and not bool(re.search(r'non\s+projete|pas\s+projete',annotation))
    project_state=fact.get('etat')=='projet' or (fact.get('etat') in (None,'non_precise') and project_quote)
    checks={
        'comparaison_positive':comparison is True,
        'critere_programme':kind in patterns,
        'sources_datees_disponibles':'access' in sources and 'scope' in sources,
        'citation_exacte_page_native':literal,
        'objet_et_mesure_explicites':correct_object and datum[0] is not None and datum in tokens(quote),
        'unite_et_conversion_coherentes':(kind=='devers_pieton' and fact.get('unite')=='%') or (kind!='devers_pieton' and fact.get('unite') in ('m','cm','mm') and isinstance(fact.get('valeur'),(int,float)) and abs((fact.get('valeur_m') or 0)-fact['valeur']*{'m':1,'cm':.01,'mm':.001}[fact['unite']])<1e-8),
        'etat_projet':project_state and fact.get('hors_operation') is not True and not bool(re.search(r'existant|hors.{0,12}operation',annotation)),
        'lecture_sans_ambiguite':not fact.get('ambiguite') and fact.get('lecture_statut')!='valeurs_contradictoires' and fact.get('rejet_humain') is not True,
        'conditions_du_seuil':bool(condition),
        'champ_application_documente':bool(context) and not competing,
    }
    evidence={
        'critere_programme':{'type_fait':kind,'methode':'contrôle programmé' },
        'sources_datees_disponibles':{key:{k:value for k,value in sources[key].items() if k in ('id','url','source_url','debut','date_debut','date_fin_exclusive','verified_through','canal')} for key in ('access','scope') if key in sources},
        'citation_exacte_page_native':{'page':page,'citation':quote,'retrouvee':literal},
        'etat_projet':{'etat':fact.get('etat'),'hors_operation':fact.get('hors_operation'),'projet_explicite_citation_native':bool(project_quote),'citation':quote if project_quote else None},
        'champ_application_documente':{'passage':context,'mention_concurrente_detectee':competing},
        'conditions_du_seuil':{'citation':quote,'sans_obstacle_deux_cotes':fact.get('sans_obstacle_deux_cotes')}
    }
    return {'eligible':all(checks.values()),'checks':checks,'evidence':evidence,'missing':[k for k,v in checks.items() if not v],
            'proof_page':page,'proof_quote':quote,'context_excerpt':context,
            'method':'Comparaison déterministe, citation native exacte et conditions explicites ; aucune validation humaine attribuée.'}
