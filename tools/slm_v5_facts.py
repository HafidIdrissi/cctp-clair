"""Add bounded, literally anchored native facts to the existing SLM readings.

This extractor interprets neither laws nor drawings. It keeps measurements from
the native page text, preserves the SLM's existing facts, and exposes ambiguous
measurements rather than selecting a convenient number. No network or model
call is made here. Existing legal/evidence gates remain responsible for verdicts.
"""
from __future__ import annotations

import copy
import re
import unicodedata


MAX_NATIVE_FACTS = 160
MAX_CLAUSES = 2000
MAX_CLAUSE_CHARS = 3500
MAX_PAGE_CHARS = 200_000

LABELS = {
    "largeur_pieton": "Largeur du cheminement piéton",
    "largeur_cyclable": "Largeur de l'aménagement cyclable",
    "largeur_espace_tampon": "Largeur de l'espace tampon",
    "devers_pieton": "Dévers du cheminement piéton",
    "ressaut": "Hauteur du ressaut",
    "fente_grille": "Ouverture de la grille",
    "distance_stationnement_amont": "Stationnement en amont du passage piéton",
    "bande_eveil": "Bande d'éveil de vigilance",
    "absence_amenagement_cyclable": "Absence écrite d'aménagement cyclable",
}

# Signs are retained: a negative distance is never silently changed to positive.
MEASURE = re.compile(
    r"(?<![\w.,])(?P<value>[+\-−]?\d{1,5}(?:[.,]\d{1,4})?)\s*"
    r"(?P<unit>mm|cm|m|%)(?![\w/²³])", re.I
)
PROJECT = re.compile(
    r"\b(?:projete(?:e|s|es)?|prevu(?:e|s|es)?|retenu(?:e|s|es)?|"
    r"sera|seront|aura|auront|realisera|realiseront|amenagera|amenageront|"
    r"presentera|presenteront|a\s+creer|a\s+realiser|a\s+amenager)\b"
)
DIRECTIVE = re.compile(r"\b(?:doit|devra|devront|doivent)\s+(?:avoir|presenter|etre|mesurer)\b")
EXISTING = re.compile(r"\b(?:existant(?:e|s|es)?|actuel(?:le|s|les)?|en\s+place)\b")
LEGAL = re.compile(r"\b(?:reglementation|reglementaire|arrete|decret|seuil\s+legal|norme|article\s+[lr]?\s*\d)\b")
CONDITIONAL = re.compile(r"\b(?:si|eventuel(?:le|s|les)?|hypothese|option(?:nelle)?|variante|a\s+confirmer)\b")
BOUNDED_VALUE = re.compile(
    r"(?:\b(?:minimum|minimale?s?|maximum|maximale?s?|au\s+moins|au\s+plus|"
    r"inferieure?s?|superieure?s?|entre|environ|approximativement|seuil)\b|[<>≤≥~])|"
    r"\d+(?:[.,]\d+)?\s*(?:a|ou|et|[+x×*\-–])\s*\d+(?:[.,]\d+)?\s*(?:mm|cm|m|%)\b"
)


def _norm(value: object) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(value or ""))
                   if not unicodedata.combining(c)).lower().replace("’", "'")


def _compact(value: object) -> str:
    return re.sub(r"\s+", " ", _norm(value)).strip()


def _clauses(text: str):
    """Yield exact spans. Wrapped lines stay together; table rows stay separate.

    Blank lines, sentence endings and explicit bullets are boundaries. A
    semicolon is retained because it often carries a threshold's condition.
    Long passages are rejected by the caller, never truncated into a quotation.
    """
    boundaries = re.compile(
        r"\n\s*\n|(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ])|\n(?=\s*[-•]\s)|"
        r"\n(?=\s*(?:Secteur|Lot|Repère)\s+[A-Z0-9][^\n]{0,70}[:|])"
    )
    start = 0
    for boundary in boundaries.finditer(text):
        left, right = start, boundary.start()
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right-1].isspace():
            right -= 1
        if left < right:
            yield left, right, text[left:right]
        start = boundary.end()
    right = len(text)
    while start < right and text[start].isspace():
        start += 1
    while right > start and text[right-1].isspace():
        right -= 1
    if start < right:
        yield start, right, text[start:right]


def _state(text: str):
    projected = list(PROJECT.finditer(text)) + list(DIRECTIVE.finditer(text))
    # A negated mention is not a planned state. Do not infer its opposite either.
    negated = [m for m in projected if re.search(
        r"\b(?:non|pas|aucun|aucune|sans|ne)\b[^.;:]{0,28}$", text[max(0, m.start()-35):m.start()]
    ) or re.match(r"\s+pas\b", text[m.end():])]
    current = bool(EXISTING.search(text))
    if negated or CONDITIONAL.search(text):
        return "non_precise", "État conditionnel ou négatif dans la citation."
    if projected and current:
        return "non_precise", "Projet et existant sont mentionnés dans le même passage."
    if projected:
        return "projet", None
    if current:
        return "existant", None
    return "non_precise", None


def _measured_object_text(text: str) -> str:
    """Remove explicitly excluded neighbouring objects from identity detection.

    Only the noun phrase is removed, never quantities, bounds or conditions.
    This is a derived matching view; all native evidence stays unchanged.
    """
    return re.sub(
        r"\bhors\s+(?:(?:du|des|de\s+la|de\s+l'|le|la|les|l')\s*)?"
        r"(?:(?:espace|zone|bande)\s+tampon|bordures?)\b", " ", text)


def _explicit_buffer_measure(text: str) -> bool:
    """Recognize the local owner in 'un espace tampon de 60 cm de largeur'."""
    return bool(re.search(
        r"\b(?:espace|zone|bande)\s+tampon\s+"
        r"(?:(?:projete|prevu|retenu|libre|utile|constant)(?:e|s|es)?\s+){0,3}"
        r"(?:de\s+)?[+\-−]?\d{1,5}(?:[.,]\d{1,4})?\s*(?:mm|cm|m)\s+"
        r"de\s+largeur\b", text))


def _without_spatial_between(text: str) -> str:
    """Ignore only the word 'entre' when it relates two named spatial objects.

    Object identifiers may contain digits; numeric measures still block the
    exception. Bounds and other words are retained for the ordinary checks.
    """
    object_name = r"(?:piste|stationnement|trottoir|chaussee|cheminement|bordure)"
    relation = re.compile(r"\bentre\s+([^,;:.]{1,120}?)\bet\s+([^,;:.]{1,120})")
    def replace(match):
        left, right = match[1], match[2]
        if (re.search(r"\b" + object_name + r"\b", left)
                and re.search(r"\b" + object_name + r"\b", right)
                and not MEASURE.search(match.group())
                and not re.search(r"\b(?:minimum|maximum|moins|plus|inferieur|superieur)\b", match.group())):
            return re.sub(r"^entre\b", "     ", match.group())
        return match.group()
    return relation.sub(replace, text)


def _kinds(text: str):
    text = _measured_object_text(text)
    pedestrian = bool(re.search(r"\btrottoir|\bcheminement(?:\s+pieton)?|\bpietonn?", text))
    cycling = bool(re.search(r"\bcyclable|\bpiste\b|\bvelo\b", text))
    buffer = "largeur" in text and bool(re.search(r"\b(?:espace|zone|bande)\s+tampon\b", text))
    # Adjacent objects do not inherit a buffer's dimension. Only a clearly
    # named subject suppresses their width candidates; mixed clauses stay
    # ambiguous and retain the ordinary multiple-quantity gates.
    subject = re.sub(r"^(?:repere|secteur|lot)\s+[^:]{1,60}:\s*", "", text)
    buffer_subject = buffer and bool(re.match(
        r"^(?:(?:le|la|un|une|l')\s*)?(?:(?:espace|zone|bande)\s+tampon\b|"
        r"largeur(?:\s+libre)?\s+(?:de\s+l'|de\s+la\s+|du\s+)(?:espace|zone|bande)\s+tampon\b)", subject))
    buffer_subject = buffer_subject or (buffer and _explicit_buffer_measure(text))
    if buffer_subject and re.search(
            r"\btampon\b(?:(?!\bentre\b).){0,80}\b(?:et|avec|ainsi\s+que)\s+"
            r"(?:(?:le|la|un|une)\s+)?(?:piste|trottoir|cheminement|chaussee)\b", subject):
        buffer_subject = False
    kinds = []
    if buffer:
        kinds.append("largeur_espace_tampon")
    if "largeur" in text and pedestrian and not buffer_subject:
        kinds.append("largeur_pieton")
    if "largeur" in text and cycling and not buffer_subject:
        kinds.append("largeur_cyclable")
    if "devers" in text and pedestrian:
        kinds.append("devers_pieton")
    if "ressaut" in text:
        kinds.append("ressaut")
    if re.search(r"\bfente|\bouverture|\btrou", text) and re.search(r"\bgrille|dans le sol", text):
        kinds.append("fente_grille")
    if "stationnement" in text and "amont" in text and re.search(r"passage.{0,30}pieton", text):
        kinds.append("distance_stationnement_amont")
    # Absence must be written for the equipment; silence is not an absence.
    if re.search(r"\b(?:aucune?\s+bande.{0,20}eveil|absence\s+de\s+bande.{0,20}eveil|"
                 r"bande.{0,20}eveil[^.;]{0,45}(?:absente|non\s+prevue|aucune\s+prevue))", text):
        kinds.append("bande_eveil")
    if re.search(r"\b(?:aucun\s+(?:amenagement|itineraire)\s+cyclable|"
                 r"absence\s+d['e ]+(?:amenagement|itineraire)\s+cyclable)", text):
        kinds.append("absence_amenagement_cyclable")
    return kinds


def _same_source(existing: dict, fact: dict) -> bool:
    if existing.get("page") != fact["page"]:
        return False
    old = _compact(existing.get("preuve_citation_native") or existing.get("citation_visible"))
    new = _compact(fact["citation_visible"])
    if not old or not new:
        return False
    overlap = old in new or new in old
    if not overlap:
        return False
    # Never re-create a rejected/ambiguous observation through another type.
    if existing.get("rejet_humain") or existing.get("ambiguite") or existing.get("lecture_statut") == "valeurs_contradictoires":
        return True
    if (old == new and existing.get('type_fait') == 'largeur_cyclable'
            and fact['type_fait'] == 'largeur_espace_tampon'):
        # The policy boundary rechecks the native object and any exact unit
        # conversion under the original ID. Do not create a duplicate finding.
        return True
    return existing.get("type_fait") == fact["type_fait"]


def _association(kind: str, quote: str, measure) -> bool:
    """A lone number elsewhere in the clause does not measure this object."""
    before = _compact(quote[:measure.start()])
    after = _compact(quote[measure.end():])
    anchors = {
        "largeur_pieton": r"\blargeur\b", "largeur_cyclable": r"\blargeur\b",
        "largeur_espace_tampon": r"\blargeur\b",
        "devers_pieton": r"\bdevers\b", "ressaut": r"\b(?:ressaut|hauteur)\b",
        "fente_grille": r"\b(?:fente|ouverture|trou|diametre|largeur)\b",
        "distance_stationnement_amont": r"\b(?:distance|stationnement)\b",
    }
    found = list(re.finditer(anchors[kind], before))
    bridge = before[found[-1].end():] if found else None
    if bridge is None or len(bridge) > 120:
        # Also allow "1,60 m de largeur libre" / "1,5 % de dévers".
        return bool(re.match(r"^(?:de\s+)?" + anchors[kind], after))
    if re.search(r"\b(?:pas|ne|inconnu|determiner|preciser|verifier|profondeur|longueur|epaisseur|surface|volume)\b", bridge):
        return False
    if kind == "largeur_pieton" and re.search(r"chaussee|cyclable|piste|tampon|separateur|emprise|stationnement|bordure", bridge):
        return False
    if kind == "largeur_cyclable" and re.search(r"chaussee|trottoir|tampon|separateur|emprise|stationnement|bordure", bridge):
        return False
    if kind == "largeur_espace_tampon" and re.match(
            r"^\s*(?:libre\s+|roulable\s+)?(?:de\s+la\s+|du\s+|des\s+)"
            r"(?:piste|chaussee|trottoir|cheminement|stationnement|bordure)\b", bridge):
        return False
    return True


def _candidate(kind, kinds, quote, page, start, end, number_id):
    text = _compact(quote)
    state, uncertainty = _state(text)
    measurements = list(MEASURE.finditer(quote))
    qualitative = kind in ("bande_eveil", "absence_amenagement_cyclable")
    problems = []
    if uncertainty:
        problems.append(uncertainty)
    if len(kinds) > 1:
        problems.append("Plusieurs objets ou critères dans la citation : attribution à vérifier.")
    if not qualitative:
        # Repeated identical tokens are allowed; two distinct values are not.
        quantities = {(float(m["value"].replace("−", "-").replace(",", ".")), m["unit"].lower())
                      for m in measurements}
        if len(quantities) != 1:
            problems.append("Plusieurs mesures dans la citation : aucune valeur unique retenue.")
        if len(quantities) == 1 and not all(_association(kind, quote, m) for m in measurements):
            problems.append("La mesure n'est pas rattachée sans ambiguïté à ce critère dans la citation.")
        bound_text = text
        if kind == 'largeur_espace_tampon':
            # "Entre la piste et le stationnement" locates the buffer; it
            # does not turn its one literal width into a numeric interval.
            bound_text = _without_spatial_between(text)
        if BOUNDED_VALUE.search(bound_text):
            problems.append("Borne, intervalle ou approximation : aucune mesure ponctuelle retenue.")
        if kind == "largeur_pieton" and not re.search(r"largeur\s+libre|libre\s+de\s+mobilier|libre\s+de\s+tout.{0,15}obstacle", text):
            problems.append("La largeur libre du cheminement n'est pas explicitement identifiée.")
        if kind == "devers_pieton" and re.search(r"rampe|pente\s+longitudinale", text):
            problems.append("Pente longitudinale ou rampe mentionnée : attribution du dévers à vérifier.")
        if kind == "fente_grille" and "entraxe" in text:
            problems.append("L'entraxe est mentionné : vérifier la largeur de l'ouverture.")
        value, unit = next(iter(quantities)) if len(quantities) == 1 else (None, None)
        if value is not None and (value < 0 or (kind == "devers_pieton") != (unit == "%")):
            problems.append("Valeur négative ou unité incompatible avec ce critère.")
    else:
        value, unit = None, None
        if re.search(r"\b(?:sauf|hormis|exception|ne|pas)\b", text):
            problems.append("Négation ou exception dans l'énoncé d'absence : relire la clause.")
    if problems:
        value, unit = None, None
    quantity = next((m.group() for m in measurements), None) if value is not None else None
    repere = re.search(r"\b(?:secteur|lot|rep[eè]re)\s+[A-Za-z0-9][A-Za-z0-9_.-]{0,39}", quote, re.I)
    # The condition and exclusion are copied from this same clause only.
    no_obstacles = bool(re.search(r"(?:aucun|absence\s+de|sans).{0,30}mur.{0,25}obstacle.{0,45}(?:deux\s+cotes|part\s+et\s+d'autre)", text))
    outside_match = re.search(r"\bhors.{0,12}operation\b", text)
    outside = bool(outside_match and not re.search(r"\b(?:non|pas|ne)\b[^.;:]{0,30}$", text[max(0, outside_match.start()-40):outside_match.start()]))
    return {
        "id": number_id, "type_fait": kind, "element": LABELS[kind],
        "page": page, "repere": repere.group() if repere else None,
        "citation_visible": quote, "preuve_citation_native": quote,
        "origine": "texte_natif", "lecture_statut": "attribution_a_verifier" if problems else "citation_native_exacte",
        "valeur_inscrite": quantity, "valeur": value, "unite": unit,
        "valeur_m": value * {"m": 1, "cm": .01, "mm": .001}[unit] if value is not None and unit in ("m", "cm", "mm") else None,
        "information": quote if qualitative else None,
        "etat": state, "hors_operation": True if outside else None,
        "sans_obstacle_deux_cotes": True if no_obstacles and not problems else None,
        "ambiguite": " ".join(problems) or None,
        "validation_humaine": False, "association_valeur_element_verifiee": False,
        "extraction_native_v5": {"methode": "reperage_deterministe_natif", "page": page,
            "debut": start, "fin": end, "citation_exacte": True,
            "etat_ancre_dans_citation": state != "non_precise",
            "types_candidats": list(kinds),
            "mesures_visibles": [m.group() for m in measurements]},
    }


def literal_candidate(quote: str, kind: str | None = None) -> dict | None:
    """Parse a bounded complete native span without splitting its sentences.

    Callers must independently verify why sentences belong to the same object
    and that the entire span is uniquely present on the native page. This
    function grants neither that binding nor any legal/technical verdict.
    Ambiguity is returned in the ordinary candidate fields, never cleared.
    """
    if not isinstance(quote, str) or not quote.strip() or len(quote) > MAX_CLAUSE_CHARS:
        return None
    kinds = _kinds(_compact(quote))
    if len(kinds) != 1 or (kind is not None and kinds[0] != kind):
        return None
    if kinds[0] not in ('bande_eveil', 'absence_amenagement_cyclable') and not MEASURE.search(quote):
        return None
    return _candidate(kinds[0], kinds, quote, 1, 0, len(quote), 'NATIVE')


def enrich_native(readings: dict) -> dict:
    """Return a copy with additional source-backed facts and explicit coverage.

    Existing facts, IDs, ambiguities, reviewer decisions and visual propositions
    are preserved. Repeated calls do not add duplicates. ``text`` must contain
    native page strings; OCR is deliberately never used by this function.
    """
    if not isinstance(readings, dict):
        raise ValueError("Lectures natives attendues sous forme d'objet.")
    pages = readings.get("text", [])
    existing = readings.get("faits", [])
    if not isinstance(pages, list) or any(not isinstance(p, str) for p in pages):
        raise ValueError("Le texte natif doit être une liste de pages textuelles.")
    if not isinstance(existing, list) or any(not isinstance(f, dict) for f in existing):
        raise ValueError("Les faits doivent être une liste d'objets.")
    result = copy.deepcopy(readings)
    result.setdefault("faits", [])
    coverage = {
        "methode": "reperage_deterministe_natif", "revision": "V5",
        "limites": {"faits_ajoutes_max": MAX_NATIVE_FACTS, "clauses_max": MAX_CLAUSES,
                    "caracteres_clause_max": MAX_CLAUSE_CHARS, "caracteres_page_max": MAX_PAGE_CHARS},
        "pages_total": len(pages), "pages_lues": [], "pages_sans_texte": [],
        "pages_non_lues": [], "pages_partielles": [], "clauses_lues": 0, "clauses_trop_longues": 0,
        "references_reglementaires_seules": 0, "doublons_ecartes": 0,
        "faits_ajoutes": 0, "faits_ambigus": 0, "limite_atteinte": False,
        "exhaustive": False,
        "note": "Repérage de critères nommés dans le texte natif. Aucun verdict ni conformité globale déduit par cet extracteur.",
    }
    ids = {str(f.get("id")) for f in existing}
    serial = 1
    budget_exhausted = False
    for page, text in enumerate(pages, 1):
        if not text.strip():
            coverage["pages_sans_texte"].append(page)
            continue
        if len(text) > MAX_PAGE_CHARS or budget_exhausted:
            coverage["pages_non_lues"].append(page)
            coverage["limite_atteinte"] = True
            continue
        coverage["pages_lues"].append(page)
        for start, end, quote in _clauses(text):
            if coverage["clauses_lues"] >= MAX_CLAUSES or coverage["faits_ajoutes"] >= MAX_NATIVE_FACTS:
                coverage["limite_atteinte"] = True
                budget_exhausted = True
                if page not in coverage["pages_partielles"]:
                    coverage["pages_partielles"].append(page)
                break
            coverage["clauses_lues"] += 1
            if len(quote) > MAX_CLAUSE_CHARS:
                coverage["clauses_trop_longues"] += 1
                coverage["limite_atteinte"] = True
                if page not in coverage["pages_partielles"]:
                    coverage["pages_partielles"].append(page)
                continue
            normalized = _compact(quote)
            kinds = _kinds(normalized)
            if LEGAL.search(normalized) and not PROJECT.search(normalized):
                if kinds:
                    coverage["references_reglementaires_seules"] += 1
                continue
            for kind in kinds:
                if kind not in ("bande_eveil", "absence_amenagement_cyclable") and not MEASURE.search(quote):
                    continue
                while "V5N%03d" % serial in ids:
                    serial += 1
                candidate = _candidate(kind, kinds, quote, page, start, end, "V5N%03d" % serial)
                if any(_same_source(f, candidate) for f in result["faits"]):
                    coverage["doublons_ecartes"] += 1
                    continue
                if coverage["faits_ajoutes"] >= MAX_NATIVE_FACTS:
                    coverage["limite_atteinte"] = True
                    budget_exhausted = True
                    if page not in coverage["pages_partielles"]:
                        coverage["pages_partielles"].append(page)
                    break
                result["faits"].append(candidate)
                ids.add(candidate["id"])
                serial += 1
                coverage["faits_ajoutes"] += 1
                coverage["faits_ambigus"] += bool(candidate["ambiguite"])
    result["extraction_native_v5"] = coverage
    return result
