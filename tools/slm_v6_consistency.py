"""Source-grounded inconsistencies between native project measurements.

This module makes no legal comparison, selects no prevailing document and
changes no facts. A firm documentary finding requires explicit same-object
scope and a literal statement that no priority between the indications exists.
"""
from __future__ import annotations

import itertools
import re
import unicodedata
from collections import defaultdict

from slm_v5_facts import enrich_native


VERSION = 'V6-COHERENCE-NATIVE-1'


def compact(text):
    return re.sub(r'\s+', ' ', ''.join(c for c in unicodedata.normalize('NFD', str(text or ''))
        if not unicodedata.combining(c)).lower().replace('’', "'")).strip()


def paragraphs(page):
    return [part.strip() for part in re.split(r'\n[ \t]*\n', page) if part.strip()]


def measurement_name(kind, quote):
    text = compact(quote)
    if kind.startswith('largeur_'):
        qualifiers = re.findall(r'\blargeur\s+(roulable|libre|totale|utile)\b', text)
        if len(set(qualifiers)) > 1:
            return None
        return 'largeur_' + (qualifiers[0] if qualifiers else 'non_qualifiee')
    return {'devers_pieton': 'devers', 'ressaut': 'hauteur_ressaut',
            'fente_grille': 'diametre_ouverture' if 'diametre' in text else 'largeur_ouverture',
            'distance_stationnement_amont': 'distance_amont'}.get(kind)


def native_observations(readings):
    pages, facts = readings.get('text', []), readings.get('faits', [])
    if not isinstance(pages, list) or any(not isinstance(p, str) for p in pages):
        raise ValueError('Pages natives attendues sous forme de textes.')
    if not isinstance(facts, list) or len(facts) > 400:
        raise ValueError('Inventaire de faits hors limite.')
    seen, observations = set(), []
    for fact in facts:
        if (not isinstance(fact, dict) or fact.get('origine') != 'texte_natif'
                or fact.get('rejet_humain') is True or fact.get('ambiguite')
                or fact.get('lecture_statut') == 'valeurs_contradictoires'):
            continue
        page = fact.get('page')
        quote = fact.get('citation_visible')
        if type(page) is not int or not 1 <= page <= len(pages) or not isinstance(quote, str):
            continue
        canonical = compact(quote)
        if not canonical or compact(pages[page-1]).count(canonical) != 1 or (page, canonical) in seen:
            continue
        # Repère comes from the quotation, never from the model's Clause field.
        markers = re.findall(r'\brep[eè]re\s+([A-Za-z0-9][A-Za-z0-9_.-]{0,39})\s*:', quote, re.I)
        if len(markers) != 1:
            continue
        candidates = enrich_native({'text': [quote], 'faits': []})['faits']
        if len(candidates) != 1:
            continue
        native = candidates[0]
        if native.get('ambiguite') or native.get('valeur') is None:
            continue
        property_name = measurement_name(native['type_fait'], quote)
        if not property_name:
            continue
        blocks = paragraphs(pages[page-1])
        position = next((i for i, block in enumerate(blocks) if canonical in compact(block)), None)
        context = blocks[position:position+2] if position is not None else [quote]
        value = native['valeur_m'] if native['valeur_m'] is not None else native['valeur']
        unit = 'm' if native['valeur_m'] is not None else native['unite']
        observations.append(dict(fact_id=fact.get('id'), page=page, citation=quote,
            repere_objet=markers[0], type_fait=native['type_fait'], mesure=property_name,
            etat=native['etat'], valeur=value, unite=unit,
            valeur_native=native['valeur'], unite_native=native['unite'], contexte=context))
        seen.add((page, canonical))
    return observations


def detect_inconsistencies(readings):
    """Return evidence-rich findings; input facts and conclusions stay intact."""
    observations = native_observations(readings)
    grouped = defaultdict(list)
    for item in observations:
        key = (compact(item['repere_objet']), item['type_fait'], item['mesure'], item['etat'], item['unite'])
        grouped[key].append(item)
    all_blocks = [(page, block) for page, text in enumerate(readings.get('text', []), 1)
                  for block in paragraphs(text)]
    results = []
    no_priority = re.compile(r'\b(?:aucune\s+regle\s+de\s+priorite\b[^.]{0,130}'
                             r'(?:n\x27est\s+definie|n\x27a\s+ete\s+definie)|'
                             r'absence\s+de\s+regle\s+de\s+priorite\b)')
    priority_words = re.compile(r'\b(?:priorite|preval\w*|prime|fait\s+foi|remplace|annule)\b')
    differentiated = re.compile(r'\b(?:variante|option|hypothese|exemple|indicatif|phase|etape|'
                                r'reference\s+technique|document\s+de\s+reference|'
                                r'avant\s+travaux|apres\s+travaux)\b|'
                                r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b|'
                                r'\b(?:en|pour|version|annee)\s+(?:19|20)\d{2}\b')
    for key, items in grouped.items():
        if len(items) < 2 or not any(abs(a['valeur']-b['valeur']) > 1e-8
                                    for a, b in itertools.combinations(items, 2)):
            continue
        marker, kind, measure, state, unit = key
        marker_pattern = re.compile(r'(?<![\w.-])' + re.escape(marker) + r'(?![\w-]|\.[A-Za-z0-9])')
        scope, priority, competing = [], [], []
        related_pages = {item['page'] for item in items}
        for page, block in all_blocks:
            plain = compact(block)
            if page in related_pages and marker_pattern.search(plain):
                if (re.search(r'\bmeme\s+(?:ouvrage|objet|amenagement|element)\b', plain)
                        and not re.search(r'\b(?:pas|non|distinct\w*|different\w*)\b', plain)):
                    scope.append(dict(page=page, citation=block))
                if no_priority.search(plain):
                    priority.append(dict(page=page, citation=block))
            # An explicit conflicting priority anywhere in the dossier prevents
            # a firm finding. This conservative gate never chooses a winner.
            if priority_words.search(no_priority.sub('', plain)):
                competing.append(dict(page=page, citation=block))
        contexts = [compact(block) for item in items for block in item['contexte']]
        checks = dict(citations_natives_uniques=True, repere_objet_identique=True,
            meme_mesure_et_unite=True, valeurs_distinctes=True,
            etat_projet_commun=state == 'projet', meme_perimetre_explicite=bool(scope),
            absence_priorite_documentee=bool(priority), aucune_priorite_concurrente=not competing,
            aucun_contexte_de_variante_date_ou_reference=not any(differentiated.search(c) for c in contexts))
        confirmed = all(checks.values())
        results.append(dict(version=VERSION, nature='incoherence_documentaire',
            confirmed=confirmed, statut='incoherence_documentaire_confirmee' if confirmed else 'difference_a_contextualiser',
            fait_ids=[item['fact_id'] for item in items], repere_objet=items[0]['repere_objet'],
            type_fait=kind, mesure=measure, etat=state,
            preuves=[{k:v for k,v in item.items() if k != 'contexte'} for item in items],
            preuves_meme_perimetre=scope, preuves_absence_priorite=priority,
            mentions_priorite_concurrentes=competing, checks=checks,
            missing=[name for name, value in checks.items() if value is not True],
            explication=('Le même ouvrage projeté porte des valeurs différentes pour la même mesure ; '
                         'le dossier précise le périmètre commun et l’absence de priorité entre les indications.'
                         if confirmed else 'Des valeurs différentes portent le même repère ; leur périmètre ou leur priorité restent à établir.'),
            valeur_retenue=None, conformite_juridique_etablie=False))
    return results
