"""Bounded lexical DILA recovery from a clause, independent of topic catalogues.

An existing store/search function is injected. This module never initializes or
imports a corpus, calls a model/network, or treats discovery as applicability.
"""
from __future__ import annotations

import copy
from datetime import date
import re
import unicodedata

from slm_v5_article_review import source_valid


STOP = set('''avec dans pour entre cette comme plus moins sont etre doit doivent
avoir une des les aux sur par pas elle elles leur leurs tous toute toutes est peut
afin lorsque sans soit selon sous dont cas ces cet etait sera seront ainsi ont ses
deux autre autres aucune aucun vers hors non alors mais ou et du de la le un au ce
devra devront doivent aurait auraient pourrait pourraient serait seraient
projet projete projetee projetes projetees prevu prevus prevues prevue retenu retenue
prevoit prescrit prescription prescriptions reperes repere reference references
article articles clause clauses native natif examiner examen controle controler
necessaire disponible demande demandee dossier contrat cctp titulaire entreprise
millimetre millimetres centimetre centimetres metre metres pourcent cm mm km
saint sainte ville commune situe situee situees situes juillet janvier fevrier mars
avril mai juin aout septembre octobre novembre decembre'''.split())


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower()) if not unicodedata.combining(c))


def terms(value, locations=()):
    """Literal words only. Numbers, object IDs and explicit municipality names go out."""
    raw = str(value or '')
    raw = re.sub(r'\b(?:Rep[èe]re|R[ée]f(?:[ée]rence)?\.?)\s*[:#]?\s*[A-Za-z][A-Za-z0-9_-]*\s*:', ' ', raw, flags=re.I)
    raw = re.sub(r'(?<!\w)[A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*(?!\w)', ' ', raw)
    # Names explicitly attached to a location are never search criteria.
    names = [locations] if isinstance(locations,str) else list(locations)
    names += re.findall(r'(?:\b[àa]|commune de|ville de)\s+([A-ZÀ-Ÿ][\w’\'-]+(?:[ -][A-ZÀ-Ÿ][\w’\'-]+){0,3})', raw)
    excluded = {word for name in names for word in re.findall(r'[^\W\d_]+', normalized(name), re.UNICODE)}
    found = []
    for word in re.findall(r'[^\W\d_]+', normalized(raw), re.UNICODE):
        if len(word) >= 3 and word not in STOP and word not in excluded and word not in found:
            found.append(word)
    return found


def queries_for(fact, criterion=None, locations=()):
    """At most two short AND queries; criterion words must occur in the clause."""
    quote_words = terms(fact.get('citation_visible'), locations)
    requested = terms(criterion or fact.get('element'), locations)
    focus = [word for word in requested if word in quote_words][:2]
    objects = [word for word in quote_words if word not in focus][:2]
    if not objects:
        objects = quote_words[:2]
    precise = list(dict.fromkeys(focus + objects[:1]))[:3]
    broad = objects[:2]
    result = []
    for words, purpose in ((precise,'objet_et_caracteristique'),(broad,'objet_du_passage')):
        expression = ' '.join(words)
        if expression and expression not in [item['query'] for item in result]:
            result.append(dict(query=expression, terms=words, purpose=purpose))
    return result[:2]


def exclusions(source, reference, existing):
    if not isinstance(source,dict):
        return ['resultat_non_structure']
    reasons = []
    for flag in ('quarantined','temporal_uncertain','version_ambiguous'):
        if source.get(flag):reasons.append(flag)
    if source.get('provenance') != 'dila_open_data':reasons.append('provenance_non_dila')
    try:
        valid = source_valid(source,reference)
    except (TypeError,ValueError,AttributeError):
        valid = False
    if not valid:reasons.append('identite_texte_ou_version_officielle_invalide')
    if source.get('date_reference') not in (None,reference):reasons.append('date_reference_differente')
    if source.get('freshness_confirmed') is not True:reasons.append('fraicheur_non_confirmee')
    try:
        if date.fromisoformat(source.get('verified_through','')) < date.fromisoformat(reference):
            reasons.append('date_non_couverte_par_le_corpus')
    except (TypeError,ValueError):
        reasons.append('date_de_couverture_absente_ou_invalide')
    if source.get('id') in existing:reasons.append('article_deja_disponible')
    return reasons


def candidate_record(source):
    if not isinstance(source,dict):return {'type':type(source).__name__}
    return {key:copy.deepcopy(source.get(key)) for key in
            ('id','numero','nom_code','source_url','date_debut','date_fin_exclusive','date_reference',
             'provenance','quarantined','quarantine_reasons','temporal_uncertain','version_ambiguous',
             'freshness_confirmed','verified_through','text_sha256','corpus_complete')}


def recover_sources(fact, reference, *, store=None, search=None, criterion=None,
                    locations=(), existing_ids=(), query_plan=None):
    """Return ``sources`` and ``trace``. Search only; caller must compare each criterion."""
    parsed = date.fromisoformat(reference)
    if parsed.isoformat() != reference:
        raise ValueError('Date de référence attendue au format AAAA-MM-JJ.')
    if search is not None and store is not None:
        raise ValueError('Injecter un store ou une fonction search, pas les deux.')
    lookup = search if search is not None else getattr(store,'search',None)
    if not callable(lookup):
        raise ValueError('Un magasin DILA local existant ou sa fonction search est requis.')
    query_plan = queries_for(fact,criterion,locations) if query_plan is None else query_plan[:2]
    sources = {}
    trace = dict(version=1, fact_id=fact.get('id'), date_reference=reference,
                 method='recherche_dila_par_passage', queries=[], accepted_ids=[],
                 limits=dict(max_queries=2,max_articles_per_query=5,semantic_expansion=False,
                             exhaustive=False,piste_calls=0),
                 scope='Candidats officiels datés uniquement. La pertinence, les conditions et la comparaison restent à établir.',
                 lexical_limitation='DILA applique AND aux mots littéraux ; ni synonymes ni toutes les sources possibles ne sont couverts.')
    known = set(existing_ids)
    if any(q.get('purpose')=='reformulation_metier_a_verifier' for q in query_plan):
        trace['limits']['semantic_expansion']=True
        trace['lexical_limitation']='Recherche littérale des reformulations proposées ; aucun encodeur vectoriel ni garantie de couverture. La pertinence reste à vérifier.'
    for plan in query_plan:
        entry = dict(plan, reference_date=reference, requested_limit=5, candidates=[], exclusions=[],
                     status='started', received=0, limit_reached=False)
        trace['queries'].append(entry)
        try:
            results = lookup(plan['query'],reference,limit=5)
            if not isinstance(results,list):
                raise ValueError('La recherche locale doit renvoyer une liste.')
            entry.update(received=len(results),limit_reached=len(results)>=5)
            for source in results[:5]:
                candidate = candidate_record(source)
                reasons = exclusions(source,reference,known | set(sources))
                candidate['accepted'] = not reasons
                entry['candidates'].append(candidate)
                if reasons:
                    entry['exclusions'].append(dict(id=source.get('id') if isinstance(source,dict) else None,reasons=reasons))
                    continue
                recovered = copy.deepcopy(source)
                recovered['recovery_v6'] = dict(query=plan['query'],fact_id=fact.get('id'),date_reference=reference,
                                                status='candidat_a_comparer',applicability_established=False)
                sources[source['id']] = recovered
            entry['status']='completed'
        except Exception as exc:
            # A search error is a retrieval failure, never a missing legal duty.
            entry.update(status='error',error=type(exc).__name__)
    trace['accepted_ids']=list(sources)
    trace['status']='candidates_found' if sources else 'no_new_candidate'
    if not query_plan:trace['status']='no_search_terms'
    if any(item['status']=='error' for item in trace['queries']):trace['search_incomplete']=True
    return dict(sources=sources,trace=trace)
