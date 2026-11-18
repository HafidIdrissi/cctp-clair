"""DILA first; PISTE only for recorded documentary gaps. No network here."""
import copy
import math
import re
from datetime import date
from pathlib import Path

from dila_local_store import DilaStore, DEFAULT_DB_PATH
from v4_9_fallback import (TOPICS, FACT_TOPICS, inventory, topics_for,
    discovery_for, real_date, checked_article as legacy_checked_article,
    cached_sources, resolve as old_resolve)
from v4_8_document_service import norm
from v4_9_evidence import tokens as measure_tokens

CACHE_DB = Path(__file__).resolve().parents[1]/'RAG_RER_V/dila/.local/piste_cache.sqlite'
MAX_AGE_DAYS = 7
LOCAL_INSTRUMENTS = {
    'access': 'JORFTEXT000000646680',
    'derogation': 'JORFTEXT000000646680',
    'scope': 'JORFTEXT000000789317',
}


def compact(value):
    return re.sub(r'\s+', ' ', norm(str(value or ''))).strip()


def verified_document_locator(marker, page_text, quote):
    """Distinguish a literal section heading from an object's physical marker.

    A model may place ``Clause : 1.3 Cheminement piéton`` in ``repere`` while
    the quoted object is labelled ``Repère PI-01``. They are compatible only
    when that exact heading is the last numbered heading before this unique
    quotation on the same native page. A title somewhere else is insufficient.
    """
    locator = re.fullmatch(r'(?:clause|article|section)\s*:\s*'
                           r'(\d+(?:\.\d+)*\.?\s+\S.*)', compact(marker))
    native, citation = compact(page_text), compact(quote)
    if not locator or not citation or native.count(citation) != 1:
        return None
    quote_start = native.index(citation)
    previous = None
    for heading in re.finditer(r'(?m)^[ \t]*\d+(?:\.\d+)*\.?[ \t]+\S[^\r\n]*', page_text):
        heading_start = len(compact(page_text[:heading.start()]))
        if heading_start >= quote_start:
            break
        previous = heading.group().strip()
    return previous if previous and compact(previous) == locator[1] else None


def checked_article(article, topic, reference):
    """Check the instrument separately from the article's reviewed version.

    A decree cited in an order's title is not that order. DILA carries the
    instrument identifiers; PISTE candidates lacking them need an exact title
    prefix. Discovery keeps its existing documentary-only validation.
    """
    if not legacy_checked_article(article, topic, reference):
        return False
    if topic not in ('access', 'derogation', 'scope'):
        return True
    expected_nature = 'decret' if topic == 'scope' else 'arrete'
    nature = compact(article.get('nature'))
    if nature and nature != expected_nature:
        return False
    for key in ('date_signature', 'signature'):
        if article.get(key) and article[key] != TOPICS[topic]['signature']:
            return False
    title = compact(article.get('nom_code'))
    if topic == 'scope':
        return bool(re.match(r'^decret\s+(?:n[\u00b0\u00bao]?\s*)?2006\s*[-\u2013\u2014]\s*1657\s+du\s+21\s+decembre\s+2006\b', title))
    if not re.match(r'^arrete\s+du\s+15\s+janvier\s+2007\b', title):
        return False
    identities = {article[key] for key in ('text_id', 'cid')
        if isinstance(article.get(key), str) and article[key]}
    for alias in article.get('text_aliases') or []:
        if not isinstance(alias, dict) or not isinstance(alias.get('id'), str):
            continue
        try:
            start = real_date(alias['debut']) if alias.get('debut') else '0001-01-01'
            end = real_date(alias['fin']) if alias.get('fin') else '2999-01-01'
        except (ValueError, TypeError):
            continue
        if start <= reference < end:
            identities.add(alias['id'])
    expected_ids = {'JORFTEXT000000646680', 'LEGITEXT000006055384'}
    if identities or article.get('provenance') == 'dila_open_data':
        return bool(identities & expected_ids)
    return True


def restore_literal_buffer_width(fact):
    """Correct a model's buffer-as-cycletrack label from one literal clause.

    No threshold or verdict is inferred. The incoming measurement must already
    be exactly equivalent to the native one, including its metric conversion.
    Prior ambiguities and reviewer decisions cannot be repaired through here.
    """
    from slm_v5_facts import enrich_native, LABELS
    if (fact.get('type_fait') not in ('largeur_cyclable', 'largeur_espace_tampon')
            or invalid_fact(fact) or fact.get('validation_humaine') is True):
        return
    candidates = enrich_native({'text': [fact['citation_visible']], 'faits': []})['faits']
    if len(candidates) != 1:
        return
    candidate = candidates[0]
    if candidate['type_fait'] != 'largeur_espace_tampon' or candidate.get('ambiguite'):
        return
    number, unit, metric = fact.get('valeur'), fact.get('unite'), fact.get('valeur_m')
    if type(number) not in (int, float) or not math.isfinite(number) or unit not in ('m', 'cm', 'mm'):
        return
    equivalent = number * {'m': 1, 'cm': .01, 'mm': .001}[unit]
    if (candidate.get('valeur_m') is None or abs(equivalent-candidate['valeur_m']) > 1e-8
            or (metric is not None and (type(metric) not in (int, float)
                or not math.isfinite(metric) or abs(metric-equivalent) > 1e-8))):
        return
    original = {key: fact.get(key) for key in ('type_fait', 'element', 'valeur', 'valeur_m', 'unite', 'valeur_inscrite')}
    literal = {key: candidate[key] for key in ('type_fait', 'valeur', 'valeur_m', 'unite', 'valeur_inscrite')}
    if fact['type_fait'] != candidate['type_fait'] or (number, unit) != (candidate['valeur'], candidate['unite']):
        fact['correction_extraction_native'] = dict(
            methode='objet_tampon_explicite_et_equivalence_metrique_exacte',
            entree=original, lecture_native=literal, page=fact.get('page'),
            citation=fact['citation_visible'], repere_objet=candidate.get('repere'))
        fact.update(literal, element=LABELS[candidate['type_fait']])


def grounded_readings(readings):
    from slm_v5_facts import enrich_native, literal_candidate
    result = copy.deepcopy(readings)
    pages = result.get('text', [])
    if not isinstance(pages, list) or len(pages) > 40:
        raise ValueError('Texte attendu par page, 40 pages maximum.')
    if not isinstance(result.get('faits', []), list) or len(result.get('faits', [])) > 400:
        raise ValueError('Inventaire de faits hors limite.')
    seen = set()
    for fact in result.get('faits', []):
        if not isinstance(fact, dict) or not fact.get('id') or fact['id'] in seen:
            raise ValueError('Chaque fait doit porter un identifiant unique.')
        seen.add(fact['id'])
        if fact.get('origine') == 'texte_natif':
            page = fact.get('page')
            quote = compact(fact.get('citation_visible'))
            if type(page) is not int or not 1 <= page <= len(pages) or not quote or quote not in compact(pages[page-1]):
                fact.update(ambiguite='Citation native introuvable à la page indiquée.',
                            lecture_statut='citation_non_retrouvee', validation_humaine=False)
                continue
            restore_literal_buffer_width(fact)
            if fact.get('type_fait') in ('largeur_pieton','largeur_cyclable','largeur_espace_tampon','devers_pieton','ressaut','fente_grille','distance_stationnement_amont') and (fact.get('valeur') is not None or fact.get('valeur_m') is not None):
                number = fact.get('valeur')
                metric = fact.get('valeur_m')
                finite = type(number) in (int,float) and math.isfinite(number)
                finite_metric = metric is None or (type(metric) in (int,float) and math.isfinite(metric))
                if not finite or not finite_metric or fact.get('unite') not in ('m','cm','mm','%'):
                    fact.update(ambiguite='Mesure numérique complète et finie obligatoire.',
                        lecture_statut='mesure_invalide',validation_humaine=False)
                    continue
                datum = (fact['valeur'],fact['unite'])
                if datum not in measure_tokens(fact['citation_visible']):
                    fact.update(ambiguite='La valeur attribuée ne figure pas dans cette citation native.',
                        lecture_statut='valeur_non_retrouvee',validation_humaine=False)
                elif fact['unite'] in ('m','cm','mm'):
                    expected = fact['valeur']*{'m':1,'cm':.01,'mm':.001}[fact['unite']]
                    if fact.get('valeur_m') is not None and abs(fact['valeur_m']-expected)>1e-8:
                        fact.update(ambiguite='Conversion de la mesure incohérente.',
                            lecture_statut='conversion_incoherente',validation_humaine=False)
                # Independently bind the measurement to the quoted object.
                # A token elsewhere in a mixed quotation is insufficient.
                verified = enrich_native({'text':[fact['citation_visible']], 'faits':[]}).get('faits',[])
                if fact.get('preuve_native_completee_v6'):
                    # Reconstruct the native object/measurement link rather
                    # than trusting a completion flag or a supplied identity.
                    # Ordinary multi-sentence facts keep the stricter path.
                    from slm_v6_evidence_completion import verify_completed_fact
                    if verify_completed_fact(fact, result):
                        completed = literal_candidate(fact['citation_visible'], fact.get('type_fait'))
                        verified = [completed] if completed else []
                    else:
                        verified = []
                candidates = [candidate for candidate in verified
                    if candidate.get('type_fait') == fact.get('type_fait')]
                # Two independently measured clauses cannot be assigned using
                # the value alone: it may belong to another sector. Native V5
                # facts already retain a single clause and therefore keep the
                # ordinary, unambiguous path through this check.
                candidate = candidates[0] if len(candidates) == 1 else None
                marker = compact(fact.get('repere'))
                candidate_marker = compact((candidate or {}).get('repere'))
                strip_marker = lambda value: re.sub(r'^(?:secteur|lot|repere)\s+', '', value)
                document_locator = verified_document_locator(marker, pages[page-1],
                    fact['citation_visible']) if candidate else None
                if document_locator:
                    marker_matches = True
                elif marker and candidate_marker:
                    marker_matches = strip_marker(marker) == strip_marker(candidate_marker)
                elif marker and candidate:
                    # Free-text sector names must occur in the retained clause;
                    # a marker elsewhere in the larger quotation is not enough.
                    marker_matches = bool(re.search(r'(?<!\w)' + re.escape(marker) + r'(?!\w)',
                        compact(candidate.get('citation_visible'))))
                else:
                    marker_matches = True
                if not candidate or (candidate.get('valeur'),candidate.get('unite')) != datum or candidate.get('ambiguite') or not marker_matches:
                    fact.update(ambiguite='L’objet et la mesure ne sont pas reliés sans ambiguïté dans la citation.',
                        lecture_statut='association_non_etablie',validation_humaine=False)
                else:
                    # Keep literal state recovery observable. Only an absent
                    # state can be completed; existing states/reviewer flags
                    # and all prior ambiguities remain authoritative.
                    fact['ancrage_mesure_native'] = dict(
                        methode='citation_native_unique_et_mesure_rattachee',
                        page=page, citation=fact['citation_visible'],
                        titre_section=document_locator,
                        repere_documentaire=fact.get('repere'),
                        repere_objet=candidate.get('repere'),
                        etat_dans_citation=candidate.get('etat'))
                    if (fact.get('etat') in (None, 'non_precise')
                            and candidate.get('etat') in ('projet', 'existant')
                            and not invalid_fact(fact)):
                        fact['etat'] = candidate['etat']
    return result


def invalid_fact(fact):
    return (fact.get('rejet_humain') is True or bool(fact.get('ambiguite'))
        or fact.get('lecture_statut') == 'valeurs_contradictoires'
        or (fact.get('origine') == 'ministral_vision' and fact.get('corroboration_ocr') is not True))


def supported(fact):
    if fact.get('type_fait') in FACT_TOPICS:
        return True
    words = compact(' '.join(str(fact.get(k) or '') for k in ('element','citation_visible','information')))
    return bool(re.search(r'accessibil|pieton|trottoir|ressaut|devers|eveil|grille|stationnement|cyclab|velo|zone\s*30|zone de rencontre|signalisation|derogation', words))


def coverage(body, store=None, cache=None, today=None):
    from slm_v5_facts import enrich_native
    reference = real_date(body['date_reference'])
    readings = grounded_readings(inventory(enrich_native(body['lectures'])))
    enabled = body.get('controle_juridique', True) is True
    piste_allowed = body.get('piste_autorise', True) is True and enabled
    if enabled:
        store = store or DilaStore(DEFAULT_DB_PATH)
        state = store.status()
    else:
        state = dict(article_count=0,coverage_scope='lecture_seule_base_non_interrogee',
            verified_through=None,continuity_verified=False,ready=False)
    now = today or date.today()
    snapshot = state.get('verified_through')
    try:
        stamp = date.fromisoformat(snapshot)
        fresh = state.get('continuity_verified') is True and 0 <= (now-stamp).days <= MAX_AGE_DAYS
        temporal = reference <= snapshot
    except (ValueError, TypeError):
        fresh, temporal = False, False
    cached = (cached_sources(reference, CACHE_DB) if cache is None else cache) if enabled else {}
    local, selected_cache, decisions, needed, points = {}, {}, {}, {}, []
    queries_local = {}
    for fact in readings.get('faits', []):
        bad = invalid_fact(fact)
        in_scope = supported(fact)
        topics = topics_for(fact) if in_scope else []
        point = dict(fait_id=fact['id'], page=fact.get('page'), topics=topics,
            discovery_topics=[], topics_manquants=[], conformite_etablie=False,
            statut='preuve_a_verifier' if bad else 'lecture_seule' if not enabled else
                'hors_perimetre_automatise' if not in_scope else 'sources_documentaires_disponibles')
        if enabled and not bad and in_scope:
            for topic in topics:
                if topic not in decisions:
                    spec = TOPICS[topic]
                    rows = []
                    reason = None
                    if not state.get('article_count'):
                        reason = 'base_dila_vide'
                    else:
                        local_code = LOCAL_INSTRUMENTS.get(topic, spec.get('code'))
                        query = '' if local_code and spec.get('article') else spec.get('expression') or spec.get('title_terms', '')
                        rows = store.search(query, reference, code=local_code, article=spec.get('article'), limit=20)
                        rows = [r for r in rows if checked_article(r, topic, reference)]
                        queries_local[topic] = [dict(r, statut='candidat_documentaire_date') for r in rows]
                        unique = {r['id']:r for r in rows}
                        if not fresh:
                            reason = 'base_dila_a_actualiser'
                        elif not temporal:
                            reason = 'date_posterieure_au_corpus'
                        elif not unique:
                            reason = 'reference_absente_du_perimetre_local'
                        elif any(r.get('version_ambiguous') or r.get('temporal_uncertain') for r in rows) or (spec.get('article') and len(unique) != 1):
                            reason = 'versions_locales_ambigues'
                        else:
                            local[topic] = next(iter(unique.values()))
                    if reason and topic in cached and TOPICS[topic].get('article') and checked_article(cached[topic], topic, reference) and not cached[topic].get('version_ambiguous') and not cached[topic].get('temporal_uncertain'):
                        selected_cache[topic] = cached[topic]
                        decisions[topic] = dict(canal='cache_piste', motif='version_exacte_en_cache_recent', lacune_dila=reason)
                    elif reason:
                        decisions[topic] = dict(canal='piste' if piste_allowed else 'aucun', motif=reason)
                    else:
                        decisions[topic] = dict(canal='dila_local', motif='version_datee_retrouvee_localement')
                if topic not in local and topic not in selected_cache:
                    point['topics_manquants'].append(topic)
                    if piste_allowed:
                        needed.setdefault(topic, []).append(fact['id'])
            point['statut'] = 'source_a_rechercher' if point['topics_manquants'] else 'sources_documentaires_disponibles'
            # Local complementary discovery costs zero PISTE requests.
            if fresh and temporal and state.get('article_count'):
                extras = {}
                for discovery in discovery_for(fact, topics):
                    spec = TOPICS[discovery]
                    if discovery not in queries_local:
                        queries_local[discovery] = store.search(spec['expression'], reference, limit=5)
                    for row in queries_local[discovery]:
                        if not checked_article(row,discovery,reference) or row.get('version_ambiguous') or row.get('temporal_uncertain'):
                            continue
                        extras[row['id']] = dict(row, titre=row['nom_code'], url=row['source_url'],
                            statut='candidat_documentaire_date', requetes=[discovery],
                            motif='Recherche lexicale DILA locale ; applicabilité à examiner.')
                point['articles_complementaires'] = list(extras.values())[:15]
        points.append(point)
    specs = [dict(TOPICS[t], id=t, fact_ids=sorted(set(ids)),
        motif_fallback=decisions[t]['motif']) for t,ids in needed.items()]
    plan = dict(mode='dila_local_prioritaire_v5', date_reference=reference,
        perimetre='CCTP de voirie, mobilité et accessibilité ; autres clauses signalées à examiner',
        base_dila=state, fraicheur_max_jours=MAX_AGE_DAYS, base_recente=fresh,
        date_couverte=temporal, piste_autorise=piste_allowed,
        points=points, requetes=specs, decisions=decisions,
        recherche_piste_necessaire=bool(specs), recherche_piste_executee=False,
        sources_locales=local, sources_cache=selected_cache, cache_hits=list(selected_cache),
        requetes_locales=len(queries_local), recherche_exhaustive=False,
        conformite_globale_etablie=False,
        limites_recherche=dict(pages_par_requete=5,resultats_par_page=20,consultations_max=60))
    return {**readings, 'lectures_images':readings, 'date_reference':reference,
        'format_rapport':body.get('format_rapport','cartes'), 'controle_juridique':enabled,
        'couverture_locale':plan, 'recherche_piste_necessaire':bool(specs)}


def resolve(body, db_path=CACHE_DB):
    prepared = body['preparation']
    plan = prepared['couverture_locale']
    if plan.get('mode') != 'dila_local_prioritaire_v5' or not plan.get('piste_autorise'):
        raise ValueError('Ce dossier ne permet pas une résolution PISTE.')
    reference = real_date(prepared['date_reference'])
    by_topic = {}
    allowed = {s['id'] for s in plan['requetes']}
    for row in body.get('resultats', []):
        article = row.get('article')
        if row.get('validation_status') != 'source_verifiee' or not isinstance(article,dict):
            continue
        for meta in article.get('query_topics', []):
            topic = meta.get('id')
            if topic in allowed and checked_article(article,topic,reference) and not article.get('version_ambiguous') and not article.get('temporal_uncertain'):
                by_topic.setdefault(topic,set()).add(article['id'])
    ambiguous = {k for k,v in by_topic.items() if TOPICS[k].get('article') and len(v)>1}
    safe = copy.deepcopy(body)
    safe['preparation']['couverture_locale']['sources_cache'] = {
        topic: article for topic, article in plan.get('sources_cache', {}).items()
        if checked_article(article, topic, reference)
        and not article.get('version_ambiguous') and not article.get('temporal_uncertain')}
    for row in safe.get('resultats', []):
        if isinstance(row.get('article'),dict):
            invalid = row['article'].get('version_ambiguous') or row['article'].get('temporal_uncertain')
            row['article']['query_topics'] = [] if invalid else [x for x in row['article'].get('query_topics',[])
                if x.get('id') in allowed and x.get('id') not in ambiguous
                and checked_article(row['article'], x.get('id'), reference)]
    result = old_resolve(safe,db_path=db_path)
    # Preserve local discovery instead of replacing it with an empty API list.
    old_points = {p['fait_id']:p for p in plan['points']}
    for point in result['couverture_locale']['points']:
        point['articles_complementaires'] = old_points[point['fait_id']].get('articles_complementaires',[]) + point.get('articles_complementaires',[])
    result['couverture_locale']['versions_piste_ambigues'] = sorted(ambiguous)
    result['couverture_locale']['erreurs'] += ['Plusieurs versions PISTE pour '+t+' : aucun choix automatique.' for t in sorted(ambiguous)]
    for source in result['couverture_locale'].get('sources_piste',{}).values():
        source['provenance'] = 'piste_sandbox'
    return result
