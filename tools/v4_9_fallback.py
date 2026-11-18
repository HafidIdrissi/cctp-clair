"""Local-first documentary coverage, with bounded n8n/PISTE fallback.

Only static legal topics/known references leave the machine. A fetched article
is a documentary candidate, never an automatic finding of legal compliance.
This module does not hold OAuth credentials or make external HTTP requests.
"""
import copy
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from v4_9_laws import DB, sources_for

TOPICS = {
    'access': dict(label='Accessibilité des cheminements piétons', fond='LODA_DATE', article='1', signature='2007-01-15', title_terms='accessibilité de la voirie', title_marker='2006-1658'),
    'scope': dict(label='Champ d’application de l’accessibilité de la voirie', fond='LODA_DATE', article='1', signature='2006-12-21', title_terms='accessibilité de la voirie', title_marker='2006-1657'),
    'cycling': dict(label='Aménagement cyclable des voies urbaines', fond='CODE_DATE', article='L228-2', code="Code de l'environnement"),
    'parking': dict(label='Stationnement en amont des passages piétons', fond='CODE_DATE', article='L118-5-1', code='Code de la voirie routière'),
    'derogation': dict(label='Procédure de dérogation à l’accessibilité', fond='LODA_DATE', article='2', signature='2007-01-15', title_terms='accessibilité de la voirie', title_marker='2006-1658'),
    'double_sens': dict(label='Double sens cyclable en voie limitée à 30 km/h', fond='CODE_DATE', article='R412-28-1', code='Code de la route'),
    'zones': dict(label='Définition des zones 30 et zones de rencontre', fond='CODE_DATE', article='R110-2', code='Code de la route'),
    'signalisation': dict(label='Signalisation des aménagements cyclables', fond='CODE_DATE', expression='signalisation cyclable'),
    'mobilite_autre': dict(label='Recherche complémentaire de mobilité cyclable', fond='CODE_DATE', expression='aménagement cyclable'),
}
FACT_TOPICS = {
    **{k: ['access', 'scope'] for k in ('largeur_pieton', 'devers_pieton', 'ressaut', 'fente_grille', 'bande_eveil')},
    'distance_stationnement_amont': ['parking'], 'absence_amenagement_cyclable': ['cycling'],
    'largeur_cyclable': ['cycling'], 'derogation_par_visa': ['derogation'],
}
ALLOWED_CODES = {"code de l'environnement", 'code de la route', 'code des transports', 'code de la voirie routiere'}
MAX_NATIVE_CLAUSES = 80

# Discovery is complementary to the configured checks. Public vocabulary only:
# the contract text and the commune never leave the machine for these searches.
DISCOVERY_TERMS = {
    'access': 'accessibilité voirie', 'scope': 'accessibilité voirie',
    'cycling': 'aménagement cyclable', 'parking': 'stationnement passage piéton',
    'derogation': 'dérogation accessibilité voirie',
    'double_sens': 'double sens cyclable', 'zones': 'zone rencontre',
    'signalisation': 'signalisation cyclable', 'mobilite_autre': 'aménagement cyclable',
}
FACT_TERMS = {
    'largeur_pieton': 'largeur cheminement', 'devers_pieton': 'dévers cheminement',
    'ressaut': 'ressaut', 'fente_grille': 'grille cheminement',
    'bande_eveil': 'éveil vigilance', 'largeur_cyclable': 'largeur piste cyclable',
}
for _term in sorted(set(DISCOVERY_TERMS.values()) | set(FACT_TERMS.values())):
    for _fond in ('CODE_DATE', 'LODA_DATE'):
        _key = 'discovery_' + hashlib.sha256((_fond + _term).encode()).hexdigest()[:12]
        TOPICS[_key] = dict(label='Recherche complémentaire : ' + _term,
            expression=_term, fond=_fond, discovery=True)


def discovery_for(fact, topics):
    terms = {DISCOVERY_TERMS[t] for t in topics if t in DISCOVERY_TERMS}
    if fact.get('type_fait') in FACT_TERMS:
        terms.add(FACT_TERMS[fact['type_fait']])
    passage = norm(' '.join(str(fact.get(k) or '') for k in ('element','information','citation_visible')))
    for trigger, expression in [('ressaut','ressaut'),('devers','dévers cheminement'),
            ('grille','grille cheminement'),('eveil','éveil vigilance')]:
        if trigger in passage:
            terms.add(expression)
    return [key for key, spec in TOPICS.items() if spec.get('discovery') and spec['expression'] in terms]


def norm(value):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', str(value or '')) if not unicodedata.combining(c)).lower().replace('’', "'")


def real_date(value):
    parsed = date.fromisoformat(str(value))
    if parsed.isoformat() != value:
        raise ValueError('Date de référence réelle obligatoire.')
    return value


def topics_for(fact):
    if fact.get('type_fait') in FACT_TOPICS:
        return FACT_TOPICS[fact['type_fait']]
    text = norm(' '.join(str(fact.get(k) or '') for k in ('element', 'information', 'citation_visible')))
    if re.search(r'zone\s*30|double.{0,5}sens.{0,15}cycl|30\s*km', text):
        return ['double_sens', 'zones']
    if 'zone de rencontre' in text:
        return ['zones']
    if 'signalisation' in text or 'signal' in text:
        return ['signalisation']
    if 'derogation' in text:
        return ['derogation']
    if re.search(r'accessibil|pieton|trottoir|ressaut|devers|eveil|grille', text):
        return ['access', 'scope']
    if 'stationnement' in text and 'passage' in text:
        return ['parking']
    if re.search(r'cyclab|velo|itineraire', text):
        return ['cycling']
    return ['mobilite_autre']


def inventory(readings):
    """Retain exact native normative passages, not model-generated legal rules.

    This is an explicit bounded inventory, not a claim of extracting all clauses.
    Uncorroborated visual propositions remain in the existing evidence channel.
    """
    result = copy.deepcopy(readings)
    existing = {(f.get('page'), norm(f.get('citation_visible'))) for f in result.get('faits', [])}
    retained = []
    excluded = 0
    for page, text in enumerate(result.get('text', []), 1):
        # Keep paragraph context; line wrapping is not a sentence boundary.
        for passage in re.split(r'\n\s*\n|\n(?=Article\s+\d)', str(text)):
            passage = passage.strip()
            if len(passage) < 40 or not re.search(r'\b(doit|doivent|devra|devront|interdit|interdite|autorise|obligatoire|prescrit|reglementaire|derogation)\b', norm(passage)):
                continue
            if (page, norm(passage)) in existing:
                continue
            if len(retained) >= MAX_NATIVE_CLAUSES:
                excluded += 1
                continue
            if len(passage) > 3500:
                # Do not turn a truncated clause into a supposedly complete quote.
                excluded += 1
                continue
            retained.append(dict(id='C%03d' % (len(retained)+1), type_fait='clause_a_examiner',
                element='Clause native à examiner', page=page, repere='Passage du CCTP',
                citation_visible=passage, information=None, valeur_inscrite=None, valeur=None,
                valeur_m=None, unite=None, etat='non_precise', origine='texte_natif',
                lecture_statut='citation_native_exacte', validation_humaine=False,
                association_valeur_element_verifiee=False, ambiguite=None, hors_operation=None))
    result['faits'] = result.get('faits', []) + retained
    result['inventaire_clauses'] = dict(methode='passages normatifs natifs, repérage heuristique',
        clauses_ajoutees=len(retained), clauses_candidates_non_retenues=excluded,
        limite=MAX_NATIVE_CLAUSES, exhaustive=False)
    return result


def checked_article(article, topic, reference):
    """Recheck identity, exact dates and official URLs at the report/cache boundary."""
    if not isinstance(article, dict) or topic not in TOPICS:
        return False
    spec = TOPICS[topic]
    if not re.fullmatch(r'LEGIARTI\d+', str(article.get('id', ''))):
        return False
    if article.get('date_reference') != reference or len(str(article.get('texte', '')).strip()) < 21:
        return False
    try:
        start = real_date(article.get('date_debut'))
        end = article.get('date_fin_exclusive') or '2999-01-01'
        real_date(end)
        if not start <= reference < end:
            return False
    except (ValueError, TypeError):
        return False
    url = urlsplit(str(article.get('source_url', '')))
    if url.scheme != 'https' or url.netloc != 'www.legifrance.gouv.fr' or article['id'] not in url.path:
        return False
    title = norm(article.get('nom_code'))
    if spec.get('code') and title != norm(spec['code']):
        return False
    if spec.get('article') and re.sub(r'[.\s]', '', str(article.get('numero', ''))).upper() != spec['article'].upper():
        return False
    if spec.get('discovery'):
        # Identity/date validation does not establish legal applicability.
        return bool(title)
    if spec['fond'] == 'LODA_DATE':
        if norm(spec['title_terms']) not in title or spec['title_marker'] not in title:
            return False
    elif title not in ALLOWED_CODES:
        return False
    return True


def cached_sources(reference, db_path=DB):
    if not Path(db_path).exists():
        return {}
    cutoff = (datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
    with closing(sqlite3.connect(f'file:{Path(db_path).as_posix()}?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='piste_candidates'").fetchone():
            return {}
        records = db.execute('SELECT topic, record FROM piste_candidates WHERE reference=? AND retrieved_at>=? ORDER BY retrieved_at DESC', (reference, cutoff)).fetchall()
    result = {}
    for topic, raw in records:
        article = json.loads(raw)
        if topic not in result and checked_article(article, topic, reference):
            result[topic] = article
    return result


def coverage(body, local_sources=None, cache=None):
    reference = real_date(body['date_reference'])
    readings = inventory(body['lectures'])
    enabled = body.get('controle_juridique', True) is True
    local = sources_for(reference) if local_sources is None else local_sources
    cached = cached_sources(reference) if cache is None else cache
    points = []
    needed = {}
    for fact in readings.get('faits', []):
        invalid = fact.get('rejet_humain') is True or bool(fact.get('ambiguite')) or fact.get('lecture_statut') == 'valeurs_contradictoires' or (fact.get('origine') == 'ministral_vision' and not fact.get('corroboration_ocr'))
        topics = topics_for(fact)
        # A broad keyword candidate is not enough to cover a new clause.
        # Only exact-reference topics may suppress a new PISTE search.
        missing = [t for t in topics if t not in local and
            (t not in cached or not TOPICS[t].get('article'))]
        status = 'preuve_a_verifier' if invalid else 'lecture_seule' if not enabled else 'source_a_rechercher' if missing else 'sources_documentaires_disponibles'
        exploration = discovery_for(fact, topics) if enabled and not invalid else []
        points.append(dict(fait_id=fact['id'], page=fact.get('page'), topics=topics,
            discovery_topics=exploration,
            topics_manquants=missing if enabled and not invalid else [], statut=status,
            conformite_etablie=False))
        if enabled and not invalid:
            for topic in missing:
                needed.setdefault(topic, []).append(fact['id'])
            for topic in exploration:
                needed.setdefault(topic, []).append(fact['id'])
    specs = [dict(TOPICS[t], id=t, fact_ids=ids) for t, ids in needed.items()]
    plan = dict(mode='catalogue_et_recherche_elargie', date_reference=reference,
        perimetre='Pistes cyclables, voirie et accessibilité ; codes et textes législatifs/réglementaires à la date de référence',
        limites_recherche=dict(pages_par_requete=5, resultats_par_page=20, consultations_max=60),
        points=points, requetes=specs, recherche_piste_necessaire=bool(specs),
        cache_hits=list(cached), sources_cache=cached, sources_locales=local,
        recherche_exhaustive=False, conformite_globale_etablie=False)
    return {**readings, 'lectures_images':readings, 'date_reference':reference,
        'format_rapport':body.get('format_rapport', 'cartes'), 'controle_juridique':enabled,
        'couverture_locale':plan, 'recherche_piste_necessaire':bool(specs)}


def resolve(body, db_path=DB):
    prepared = body['preparation']
    plan = copy.deepcopy(prepared['couverture_locale'])
    reference = real_date(prepared['date_reference'])
    allowed_topics = {s['id'] for s in plan['requetes']}
    accepted = dict(plan.get('sources_cache', {}))
    complementary = {}
    errors = []
    for row in body.get('resultats', []):
        article = row.get('article')
        if row.get('validation_status') != 'source_verifiee' or not isinstance(article, dict):
            errors.append('Aucune version d’article vérifiée dans une réponse PISTE.')
            continue
        for meta in article.get('query_topics', []):
            topic = meta.get('id')
            if topic in allowed_topics and checked_article(article, topic, reference):
                if TOPICS[topic].get('discovery'):
                    entry = complementary.setdefault(article['id'], dict(article, discovery_topics=[]))
                    if topic not in entry['discovery_topics']:
                        entry['discovery_topics'].append(topic)
                else:
                    accepted.setdefault(topic, article)
    fresh = {k:v for k,v in accepted.items() if k in allowed_topics}
    if fresh:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS piste_candidates (topic TEXT NOT NULL, reference TEXT NOT NULL, article_id TEXT NOT NULL, record TEXT NOT NULL, retrieved_at TEXT NOT NULL, PRIMARY KEY(topic,reference,article_id))')
            for topic, article in fresh.items():
                db.execute('INSERT OR REPLACE INTO piste_candidates VALUES (?,?,?,?,?)',
                    (topic, reference, article['id'], json.dumps(article, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
            db.commit()
    query_coverage = body.get('couverture_recherche') or next((r.get('coverage') for r in body.get('resultats', []) if r.get('coverage')), {})
    for point in plan['points']:
        relevant = []
        for article in complementary.values():
            shared = set(point.get('discovery_topics', [])) & set(article['discovery_topics'])
            if shared:
                relevant.append(dict(id=article['id'], numero=article['numero'], titre=article['nom_code'],
                    url=article['source_url'], date_debut=article['date_debut'],
                    date_fin_exclusive=article.get('date_fin_exclusive'),
                    date_reference=reference, texte=article['texte'],
                    requetes=sorted(shared), statut='candidat_documentaire_date',
                    motif='Trouvé par les recherches liées à ce fait ; identité et période de vigueur contrôlées. Applicabilité et comparaison non établies par cette recherche.'))
        point['articles_complementaires'] = relevant
    plan.update(sources_piste=accepted, erreurs=errors, couverture_recherche=query_coverage,
        candidats_complementaires=list(complementary.values()),
        recherche_piste_executee=True, articles_archives_localement=len(fresh))
    return dict(lectures=prepared['lectures_images'], date_reference=reference,
        format_rapport=prepared['format_rapport'], controle_juridique=prepared['controle_juridique'],
        couverture_locale=plan)


def enrich_analysis(analysis, plan):
    sources = {**plan.get('sources_locales', {}), **plan.get('sources_cache', {}), **plan.get('sources_piste', {})}
    points = {p['fait_id']:p for p in plan.get('points', [])}
    analysis['recherche_automatique'] = {k:v for k,v in plan.items() if k not in ('sources_locales', 'sources_cache', 'sources_piste')}
    for row in analysis['lignes']:
        point = points.get(row['fait']['id'])
        if not point or point['statut'] in ('preuve_a_verifier', 'lecture_seule'):
            continue
        found = next((sources[t] for t in point['topics'] if t in sources), None)
        if not row.get('source') and found:
            row.update(statut='a_verifier', comparaison=None, regle=None,
                source=dict(found, titre=found.get('nom_code', found.get('titre')), url=found.get('source_url', found.get('url')), debut=found.get('date_debut', found.get('debut'))),
                article=found.get('numero', found.get('heading', '')),
                explication='Source officielle datée retrouvée. Son applicabilité et les obligations de cette version restent à examiner ; aucun verdict automatique.',
                action='Lire l’article lié, vérifier son champ d’application et comparer la clause avec cette version. Une source trouvée ne certifie pas la clause.')
        missing = [t for t in point['topics_manquants'] if t not in sources]
        if missing:
            row.update(statut='non_verifiable', comparaison=None,
                explication='Contrôle juridique incomplet : aucune source datée vérifiée pour '+', '.join(TOPICS[t]['label'] for t in missing)+'.',
                action='Compléter la recherche officielle ou faire examiner ce point. Ni conformité ni non-conformité ne sont établies.')
    analysis['limites'].append('Recherche PISTE complémentaire par thèmes dans les codes et textes législatifs/réglementaires à la date choisie, même si une référence locale existe. Les articles complémentaires sont des candidats documentaires : leur applicabilité reste à examiner. Les limites et erreurs figurent dans la trace ; la couverture de tout le droit applicable n’est pas garantie.')
    return analysis
