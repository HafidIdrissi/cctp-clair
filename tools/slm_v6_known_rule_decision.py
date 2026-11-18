"""Decide a reviewed image criterion from verified facts and legal-scope reads.

The model does not get the final say on arithmetic or on an already verified
written absence. Real legal gaps, scope disagreement and unreviewed rules fail
closed. Raw model outputs are retained by the caller.
"""
import copy
import re
import unicodedata


def words(text):
    plain=''.join(c for c in unicodedata.normalize('NFKD',str(text).lower()) if not unicodedata.combining(c))
    return set(re.findall(r'[a-z]+|\d+',plain))


def verified_gate(binding):
    gate=(binding or {}).get('gate_version') or {}
    return bool(binding and binding.get('eligible') is True
        and binding.get('methode')=='critere_programme_retrouve_dans_sa_version_officielle_revue'
        and gate.get('eligible') is True and gate.get('checks') and all(v is True for v in gate['checks'].values())
        and gate.get('version_attendue')==binding.get('source_id'))


def explained_gap(text, fact, binding):
    """Only categories already established, or already proved reading facts.

    A named legal condition (courant, matérialisé, préfet, normes, etc.) is never
    in these vocabularies. It remains a real unresolved requirement.
    """
    tokens=words(text)
    generic=set('condition conditions d de l application exception exceptions non etabli etablie etablis etablies confirme confirmee confirmes confirmees manquant manquante manquants manquantes'.split())
    if tokens and tokens<=generic and tokens & {'application','exception','exceptions'}:
        return 'catégorie générale déjà confirmée dans les deux lectures'
    if binding.get('nature')!='presence' or fact.get('etat')!='projet':return None
    common=set(('a au aux d de des du l la le les un une en et ou ni ne n ont pas non sont est etre ete '
        'pour sur avant apres entre dans que ce cette ces il ils leur leurs toute toutes tout tous '
        'preuve preuves condition conditions justification justifications '
        'necessaire necessaires manquant manquante manquantes manquants manque manques '
        'fourni fournie fournies fournis etabli etablie etablis etablies etablir confirmer '
        'confirme confirmee confirmes confirmees documente documentee documentes documentees '
        'verification verifier informations information precision precisions '
        'suffisant suffisante suffisantes suffisants inconnue inconnu '
        'realisation travaux demande demandee demandes demandees '
        'projet projets projete projetee projetes projetees etat etats existence absence presence '
        'implantation implante implantee prevu prevus prevue prevues m metre metres').split())
    specific=set('bande bandes eveil vigilance'.split()) if fact.get('type_fait')=='bande_eveil' else set('amenagement amenagements cyclable cyclables itineraire itineraires piste pistes reseau continuite'.split())
    allowed_numbers=words(fact.get('citation_visible')) & set(re.findall(r'\d+',fact.get('citation_visible') or ''))
    if not tokens<=common|specific|allowed_numbers:return None
    if 'realisation' in tokens and tokens & {'preuve','preuves'}:
        return 'preuve de réalisation hors du contrôle de prescriptions au stade projet'
    if tokens & specific and tokens & {'existence','absence','implantation','presence'}:
        return 'état projeté et absence écrite déjà vérifiés sur la même image et citation OCR'
    return None


def decide(fact, readings, binding, arithmetic, first, second):
    from slm_v6_visual_evidence import verified
    if not verified_gate(binding) or not verified(fact,readings):return None
    if binding.get('type_fait')!=fact.get('type_fait'):return None
    original=(first,second)
    scope=('meme_objet','applicable','exceptions_resolues','sans_contradiction')
    if any(any(r.get(k) is not True for k in scope) for r in original):return None
    if any(r.get('resultat') not in ('respecte','ecart') for r in original):return None
    gaps=[x for r in original for x in r.get('manques',[])]
    if any(r.get('complet') is not True and not r.get('manques') for r in original):return None
    explanations=[explained_gap(x,fact,binding) for x in gaps]
    if any(x is None for x in explanations):return None
    quote=fact.get('citation_visible') or ''
    if binding.get('nature')=='dimension':
        if not isinstance(arithmetic,dict) or type(arithmetic.get('resultat')) is not bool:return None
        value=arithmetic['resultat'];reason=arithmetic['calcul']
        if re.search(r'confirmer|vérifier|verifier',reason,re.I):
            from v4_9_document_service import RULES
            number=f"{fact['valeur']:g}".replace('.',',')
            reason=f"Valeur écrite : {number} {fact['unite']}. Règle revue : {RULES[fact['type_fait']][2]} Résultat du calcul : "+('critère respecté.' if value else 'écart au critère.')
        basis='calcul indépendant du modèle sur le critère officiel revu'
    elif binding.get('nature')=='presence':
        if fact.get('type_fait') not in ('bande_eveil','absence_amenagement_cyclable'):return None
        if any(r['resultat']!='ecart' for r in original):return None
        # Require the actual written negative, not merely an absent drawing.
        ordered=''.join(c for c in unicodedata.normalize('NFKD',quote.lower()) if not unicodedata.combining(c))
        if re.search(r'(?:pas|non).{0,12}(?:absence|absent|aucun)',ordered):return None
        if not re.search(r'aucun|absence|non prevu|ni piste',ordered):return None
        value=False
        reason='Le dossier écrit explicitement cette absence dans l’état projeté : '+quote
        basis='absence écrite et rattachée à l’ouvrage par deux relectures image et l’OCR'
    else:return None
    outcome='respecte' if value else 'ecart'
    resolved=copy.deepcopy(list(original))
    for result in resolved:
        result.update(resultat=outcome,complet=True,critere_fidele=True,manques=[],raison=reason)
    proof=dict(methode='regle_revue_faits_verifies_et_application_double',base_decision=basis,
        source_id=binding['source_id'],article=binding['article'],calcul=arithmetic if binding['nature']=='dimension' else None,
        verdicts_proposes_par_modeles=[r['resultat'] for r in original],verdict_retenu=outcome,
        manques_initiaux=gaps,resolutions=[dict(manque=x,preuve=y) for x,y in zip(gaps,explanations)],
        fidelite_critere='Passage copié dans la version officielle revue ; aucun nouveau critère juridique généré.',
        controles_du_modele_conserves=list(scope),
        portee='Contrôle de ce critère sur les pièces fournies ; ni conformité globale ni constat d’ouvrage réalisé.')
    return dict(readings=resolved,proof=proof)
