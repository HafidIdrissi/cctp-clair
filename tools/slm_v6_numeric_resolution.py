"""Discharge only an irrelevant branch-choice gap after a proved numeric failure.

Both actual model verdicts must already be ecart and every independent legal
gate must be true. A version-bound calculation must fail in all numeric
alternatives. This never creates green or supplies missing scope evidence.
"""
import copy
import re
import unicodedata


def discharge(fact, arithmetic, first, second):
    kind=fact.get('type_fait')
    if kind not in ('largeur_pieton','ressaut') or not isinstance(arithmetic,dict):return None
    gate=arithmetic.get('gate_version') or {}
    if (arithmetic.get('methode')!='calcul_de_la_regle_existante_liee_a_sa_version_officielle'
        or arithmetic.get('resultat') is not False or arithmetic.get('toutes_alternatives_numeriques_en_ecart') is not True
        or gate.get('eligible') is not True or not gate.get('checks') or not all(v is True for v in gate['checks'].values())):return None
    required=('meme_objet','applicable','exceptions_resolues','sans_contradiction','critere_fidele')
    readings=(first,second)
    if any(r.get('resultat')!='ecart' or any(r.get(k) is not True for k in required) for r in readings):return None
    if any(r.get('complet') is not True and not r.get('manques') for r in readings):return None
    missing=[x for r in readings for x in r.get('manques',[])]
    if not missing:return None
    common=set(('a au aux d de des du l la le les un une en et ou ni ne pas non sont est etre ete '
        'pour sur avant afin que ce cette ces il ils leur leurs toute toutes tout tous deux 2 '
        'absence presence preuve preuves condition conditions justification justifications '
        'necessaire necessaires manquant manquante manquantes manquants manque manques '
        'fourni fournie fournies fournis etabli etablie etablis etablies etablir confirmer '
        'confirme confirmee confirmes confirmees documente documentee documentes documentees '
        'documenter verification verifier informations information precisions precision '
        'suffisant suffisante suffisantes suffisants reste restent restee restent inconnue inconnu').split())
    specific=set(('mur murs obstacle obstacles lateral laterale lateraux laterales cote cotes part autre '
        'chaque des deux').split()) if kind=='largeur_pieton' else set(('chanfrein chanfreins '
        'arrondi arrondis arrondie arrondies forme formes profil pente rapport ratio un trois 1 3').split())
    anchors={'mur','murs','obstacle','obstacles'} if kind=='largeur_pieton' else {'chanfrein','chanfreins','arrondi','arrondis','arrondie','arrondies'}
    for text in missing:
        if not isinstance(text,str):return None
        plain=''.join(c for c in unicodedata.normalize('NFKD',text.lower()) if not unicodedata.combining(c))
        words=set(re.findall(r'[a-z]+|\d+',plain))
        if not words & anchors or not words <= common | specific:return None
    resolved=copy.deepcopy(list(readings))
    for reading in resolved:reading.update(complet=True,manques=[])
    proof=dict(methode='condition_numerique_non_determinante_resolue_par_calcul',
        manques_initiaux=missing,calcul=arithmetic['calcul'],source_id=arithmetic.get('source_id'),article=arithmetic.get('article'),
        motif='La valeur échoue dans toutes les alternatives numériques de la règle revue. La condition qui choisit entre ces alternatives ne peut pas modifier cet écart.',
        champs_completes=['complet','manques'],
        controles_juridiques_conserves=list(required),verdicts_initiaux=[r['resultat'] for r in readings])
    return dict(readings=resolved,proof=proof)
