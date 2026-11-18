"""Literal equipment/characteristic gate, independent of model assertions.

Compatibility is only permission to continue the two semantic audits. It is
never a compliance verdict. This module neither reads nor stores thresholds.
Source citations and any preceding context must be grounded by the caller.
"""
from __future__ import annotations

import re
import unicodedata


def text(value):
    return value if isinstance(value, str) else ''


def plain(value):
    value = unicodedata.normalize('NFKD', text(value)).lower().replace('’', "'")
    return re.sub(r'\s+', ' ', ''.join(c for c in value if not unicodedata.combining(c))).strip()


# Explicit equipment names, not topic words or model-proposed fact categories.
OBJECTS = (
    ('espace_tampon', r'\b(?:espaces?|zones?|bandes?)\s+(?:tampons?|de\s+separation)\b'),
    ('voie_verte', r'\bvoies?\s+vertes?\b'),
    ('piste', r'\bpistes?(?:\s+cyclables?)?\b'),
    ('bande_cyclable', r'\bbandes?\s+cyclables?\b'),
    ('cheminement_pieton', r'\bcheminements?\s+pieton(?:s|ne|nes)?\b'),
    ('cheminement', r'\bcheminements?\b'),
    ('trottoir', r'\btrottoirs?\b'),
    ('passage_pieton', r'\bpassages?\s+pietons?\b'),
    ('ressaut', r'\bressauts?\b'),
    ('grille', r'\bgrilles?\b'),
    ('bande_eveil', r"\bbandes?\s+d'eveil(?:\s+de\s+vigilance)?\b"),
    ('stationnement', r'\bstationnements?(?:\s+automobiles?)?\b'),
    ('chaussee', r'\bchaussees?\b'),
    ('bordure', r'\bbordures?\b'),
    # Other domains retain their literal equipment name; no semantic synonyms.
    *((noun, rf'\b{noun}s?\b') for noun in (
        'porte', 'fenetre', 'canalisation', 'luminaire', 'mur', 'poteau',
        'conduit', 'gaine', 'cable', 'borne', 'escalier', 'rampe',
        'poutre', 'dalle', 'cloison', 'tuyau', 'regard', 'ventilateur')),
)
DIRECTIONS = {'unidirectionnelle': r'\buni[- ]?directionnel(?:le)?s?\b',
              'bidirectionnelle': r'\bbi[- ]?directionnel(?:le)?s?\b'}
CHARACTERISTICS = ('largeur', 'hauteur', 'longueur', 'profondeur', 'epaisseur',
                   'diametre', 'rayon', 'devers', 'pente', 'entraxe',
                   'puissance', 'eclairement', 'vitesse', 'distance')
WIDTH_QUALIFIERS = ('libre', 'utile', 'roulable', 'totale')
SPATIAL_QUANTITY = re.compile(r'\d+(?:[.,]\d+)?\s*(?:mm|cm|m|millimetres?|centimetres?|metres?)\b')
ANAPHORA = re.compile(r'\b(?:cet espace|cette zone|cette bande)\b')


def objects(value):
    normalized = plain(value)
    ignored = []
    # Literal exclusions identify what the measured width does NOT include.
    # Keep each excluded phrase in the evidence rather than hiding its presence.
    exclusion = re.compile(r'\bhors\s+(?:(?:les|des|du|de la|de l\')\s*)?'
                           r'(?:bordures?|espaces?\s+tampons?|zones?\s+de\s+separation)\b')
    ignored.extend(m.group() for m in exclusion.finditer(normalized))
    normalized = exclusion.sub(' ', normalized)
    # A buffer located BETWEEN two named neighbours does not give those
    # neighbours its dimension. Only this bounded, unit-free spatial clause
    # is removed; coordinated measured equipment remains ambiguous.
    if re.search(OBJECTS[0][1], normalized):
        locative = re.compile(r'\ble long des places de stationnement(?:\s+automobile)?\s*,')
        ignored.extend(m.group() for m in locative.finditer(normalized))
        normalized = locative.sub(' ', normalized)
        spatial = re.compile(
            r'\bentre\s+(?:le\s+bord\s+de\s+)?(?:la|le|les|une?|l\')\s*'
            r'(?:pistes?(?:\s+cyclables?)?(?:\s+[a-z]{1,5}-\d+)?|stationnement(?:\s+automobile)?|trottoirs?|chaussee|cheminements?)'
            r'\s+et\s+(?:la|le|les|une?|l\')\s*'
            r'(?:pistes?(?:\s+cyclables?)?|stationnement(?:\s+automobile)?|trottoirs?|chaussee|cheminements?)\b')
        ignored.extend(m.group() for m in spatial.finditer(normalized))
        normalized = spatial.sub(' ', normalized)
    spans = []
    for kind, pattern in OBJECTS:
        for match in re.finditer(pattern, normalized):
            if any(match.start() < end and match.end() > start for start, end, _, _ in spans):
                continue
            spans.append((match.start(), match.end(), kind, match.group()))
    directions = [kind for kind, pattern in DIRECTIONS.items() if re.search(pattern, normalized)]
    keys = set()
    for _, _, kind, _ in spans:
        if kind in ('piste', 'bande_cyclable'):
            keys.update(kind + ':' + direction for direction in (directions or ['direction_non_nommee']))
        else:
            keys.add(kind)
    # Unknown coordinated equipment must not disappear just because the small
    # vocabulary recognises its neighbour. Common measurement nouns are dealt
    # with separately by the axis check.
    for match in re.finditer(r"\b(?:et|ou|ainsi que)\s+(?:le\s+|la\s+|les\s+|un\s+|une\s+|des\s+|l')([a-z][a-z-]{2,})", normalized):
        start, end = match.span(1)
        noun = match.group(1).rstrip('s')
        if (noun not in CHARACTERISTICS
                and not any(start < right and end > left for left, right, _, _ in spans)):
            keys.add('objet_coordonne_non_resolu:' + noun)
    return dict(keys=sorted(keys), mentions=[dict(objet=k, extrait=s) for _, _, k, s in spans],
                relations_spatiales=ignored, directions=directions)


def buffer_antecedent(criterion, context):
    """Resolve the anaphor's own literal noun, never the CCTP's expected type.

    A piste/bordure/chaussée cannot be the antecedent of ``cet espace``. Another
    espace with an unknown or different qualification can, and blocks this
    bounded resolution. All occurrences of that noun must name the same buffer.
    """
    anaphor = ANAPHORA.search(plain(criterion))
    if not anaphor:
        return None
    noun = anaphor.group().split()[-1]
    native = plain(context)
    heads = list(re.finditer(rf'\b{noun}s?\b', native))
    if not heads:
        return None
    known = list(re.finditer(rf'\b{noun}s?\s+(?:tampons?|de\s+separation)\b', native))
    if len(heads) != len(known) or any(not any(m.start() == head.start() for m in known) for head in heads):
        return None
    if re.search(r'\b(?:non|pas)\s+(?:un\s+|une\s+)?'+noun+r'\b',native):
        return None
    return dict(keys=['espace_tampon'],
                mentions=[dict(objet='espace_tampon', extrait=m.group()) for m in known],
                relations_spatiales=[], directions=[],
                methode='antecedent_du_nom_litteral_'+noun)


def characteristics(value):
    normalized = plain(value)
    found = [name for name in CHARACTERISTICS if re.search(rf'\b{name}s?\b', normalized)]
    qualifiers = [q for q in WIDTH_QUALIFIERS
                  if re.search(rf'\blargeurs?\s+{q}s?\b', normalized)]
    return dict(noms=found, qualifications_largeur=qualifiers)


def compatibility(quote, criterion, source_context_before='', fact=None):
    """Reject literal mismatches/ambiguity before any numerical conclusion.

    ``fact`` is accepted for API symmetry but never provides missing identity.
    A source's unnamed spatial characteristic may continue to the audits only
    when an explicit quantity is tied to one identified equipment. That limited
    permission is separately exposed; it is not a full program verification.
    """
    if isinstance(criterion, dict):
        criterion = criterion.get('citation', '')
    quote, criterion, context = text(quote), text(criterion), text(source_context_before)
    target = objects(quote)
    source = objects(criterion)
    preceding = objects(context)
    target_characteristic = characteristics(quote)
    source_characteristic = characteristics(criterion)
    context_used = False
    antecedent = False
    # Resolve only the narrowly named buffer anaphora. A broad page containing
    # other equipment cannot supply an antecedent by selective word matching.
    if not source['keys'] and ANAPHORA.search(plain(criterion)):
        resolved = buffer_antecedent(criterion,context)
        if resolved:
            source = resolved
            context_used = antecedent = True
    characteristic_origin = 'critere'
    if not source_characteristic['noms'] and context:
        context_characteristic = characteristics(context)
        context_object_safe = (not preceding['keys'] or preceding['keys'] == source['keys'])
        if len(context_characteristic['noms']) == 1 and context_object_safe:
            source_characteristic = context_characteristic
            characteristic_origin = 'contexte_precedent'
            context_used = True
    unique_target = len(target['keys']) == 1
    unique_source = len(source['keys']) == 1
    same_object = unique_target and unique_source and target['keys'] == source['keys']
    target_axis = target_characteristic['noms']
    source_axis = source_characteristic['noms']
    ambiguous_axis = len(target_axis) > 1 or len(source_axis) > 1
    source_unnamed = not source_axis
    target_unnamed = not target_axis
    axis_conflict = bool(target_axis and source_axis and target_axis != source_axis)
    qualifiers_target = target_characteristic['qualifications_largeur']
    qualifiers_source = source_characteristic['qualifications_largeur']
    qualifier_conflict = bool(qualifiers_target and qualifiers_source and qualifiers_target != qualifiers_source)
    quantity_attached = bool(SPATIAL_QUANTITY.search(plain(criterion)) and unique_source
                             and (source['mentions'] and not antecedent or antecedent))
    # Even a preceding context that cannot be used must not hide a competing
    # axis when resolving a source with no named characteristic.
    context_axes = characteristics(context)['noms']
    unresolved_context = bool((source_unnamed and context and len(context_axes) > 1)
                              or (ANAPHORA.search(plain(criterion)) and not antecedent and not source['keys']))
    characteristic_ok = (not ambiguous_axis and not axis_conflict and not qualifier_conflict
                         and not unresolved_context and not target_unnamed
                         and (not source_unnamed or quantity_attached))
    checks = dict(cible_objet_unique=unique_target, source_objet_unique=unique_source,
                  meme_objet_litteral=bool(same_object),
                  axes_non_ambigus=not ambiguous_axis and not unresolved_context,
                  absence_conflit_caracteristique=not axis_conflict and not qualifier_conflict,
                  caracteristique_cible_nommee=not target_unnamed,
                  caracteristique_source_non_nommee=source_unnamed,
                  caracteristique_verifiee_programme=bool(characteristic_ok and not source_unnamed),
                  mesure_source_rattachee=quantity_attached,
                  caracteristique_compatible_pour_audits=bool(characteristic_ok),
                  antecedent_tampon_verifie=antecedent)
    compatible = bool(quote and criterion and same_object and characteristic_ok)
    if not unique_target or not unique_source:
        reason = "L'objet n'est pas identifié de façon unique dans chaque passage."
    elif not same_object:
        reason = "Les passages nomment des objets différents : " + ', '.join(target['keys']) + ' / ' + ', '.join(source['keys']) + '.'
    elif not characteristic_ok:
        reason = "Les caractéristiques sont différentes, ambiguës ou insuffisamment rattachées à l'objet."
    elif source_unnamed:
        reason = "Même objet littéral ; la dimension source n'est pas nommée. Les deux audits doivent encore vérifier la caractéristique."
    else:
        reason = "Objet et caractéristique littéralement compatibles ; applicabilité, rôle du seuil et deux audits restent requis."
    return dict(compatible=compatible, checks=checks, reason=reason,
                evidence=dict(cible=dict(citation=quote, objets=target, caracteristique=target_characteristic),
                              source=dict(citation=criterion, objets=source, caracteristique=source_characteristic),
                              contexte_precedent=dict(citation=context, utilise=context_used,
                                                      objets=preceding, origine_caracteristique=characteristic_origin)),
                perimetre='Prérequis documentaire uniquement. Aucun seuil, calcul ou verdict de conformité.')
