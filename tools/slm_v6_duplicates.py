"""Consolidate only exact native measurement clauses repeated by V6 extraction.

This is evidence identity, not semantic similarity. The sole removable text is
an explicit ``Repère XX :`` prefix. Original facts and their identifiers remain
in the retained fact and in the inspection's article-review audit.
"""
from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from slm_v5_policy import invalid_fact


def compact(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(text or ''))).strip()


PREFIX = re.compile(r'^Rep[èe]re\s+([A-Za-z][A-Za-z0-9_-]{0,30})\s*:\s*(.+)$', re.I)
MEASURE = re.compile(r'(?<![\w.,])\d+(?:[.,]\d+)?\s*(?:mm|cm|m|%)(?!\w)')
COMPOUND = re.compile(r'\b(?:et|ou|respectivement|ainsi)\b|[;!?/]', re.I)


def quantity(value, unit):
    if isinstance(value, bool) or unit not in ('m', 'cm', 'mm', '%'):
        return None
    try:
        number = Decimal(str(value).replace(',', '.'))
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    return ('percentage' if unit == '%' else 'length',
            number * {'m': Decimal(1), 'cm': Decimal('0.01'), 'mm': Decimal('0.001'), '%': Decimal(1)}[unit])


def scalar(body):
    """No partial, coordinated or multi-measure clause may disappear."""
    matches = list(MEASURE.finditer(body))
    if len(matches) != 1 or COMPOUND.search(body):
        return None
    match = matches[0]
    rest = body[:match.start()] + body[match.end():]
    if re.search(r'\d|\.(?=\s+\S)', rest):
        return None
    number, unit = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*(mm|cm|m|%)', match.group()).groups()
    return quantity(number, unit)


def kind_tokens(fact):
    kind = fact.get('type_extraction') or fact.get('type_fait') or ''
    return set(str(kind).split('_')) - {'autre'}


def duplicate_of(proposal, retained, pages):
    """Return an anchored identity proof, or None. Never infer a missing value."""
    if not proposal.get('extraction_modele_v6') or retained.get('extraction_modele_v6'):
        return None
    if any(f.get('origine') != 'texte_natif' or invalid_fact(f) for f in (proposal, retained)):
        return None
    page = proposal.get('page')
    if type(page) is not int or page != retained.get('page') or not 1 <= page <= len(pages):
        return None
    full = compact(retained.get('citation_visible'))
    match = PREFIX.fullmatch(full)
    if not match:
        return None
    marker, body = match.groups()
    quoted = compact(proposal.get('citation_visible'))
    proposal_match = PREFIX.fullmatch(quoted)
    if proposal_match:
        if proposal_match[1] != marker:
            return None
        quoted = proposal_match[2]
    if quoted != body:
        return None
    # The source prefix, not a model label, establishes the exact locator.
    locator = re.sub(r'^Rep[èe]re\s+', '', compact(proposal.get('repere')), flags=re.I)
    if locator != marker:
        return None
    native = compact(pages[page - 1])
    if full not in native or native.count(body) != 1:
        return None
    value = scalar(body)
    if value is None or any(quantity(f.get('valeur'), f.get('unite')) != value for f in (proposal, retained)):
        return None
    first, second = kind_tokens(proposal), kind_tokens(retained)
    if not first or not second or not (first <= second or second <= first):
        return None
    return dict(page=page, repere=marker, citation_complete=full, citation_commune=body,
                methode='citation_identique_hors_prefixe_repere',
                controles=['meme_page', 'occurrence_native_unique', 'repere_identique',
                           'clause_entiere', 'mesure_unique_identique', 'types_compatibles'])


def consolidate(analysis, readings):
    """Mutate V6 analysis rows only; native readings and legal verdicts stay intact."""
    rows = analysis.get('lignes', [])
    audit = dict(version=1, removed=0, events=[],
                 scope='Regroupement des extractions identiques ; aucun verdict ajouté ou modifié.')
    removed = set()
    for row in rows:
        fact = row.get('fait', {})
        if not fact.get('extraction_modele_v6'):
            continue
        matches = [(other, evidence) for other in rows if other is not row
                   if (evidence := duplicate_of(fact, other.get('fait', {}), readings.get('text', []))) is not None]
        if len(matches) != 1:
            continue
        retained, evidence = matches[0]
        event = dict(fact_id=fact.get('id'), retained_fact_id=retained['fait'].get('id'),
                     original_fact=copy.deepcopy(fact), original_status=row.get('statut'), evidence=evidence)
        retained['fait'].setdefault('doublons_extraction_v6', []).append(copy.deepcopy(event))
        retained.setdefault('doublons_extraction', []).append(copy.deepcopy(event))
        audit['events'].append(event)
        removed.add(id(row))
    if removed:
        analysis['lignes'] = [row for row in rows if id(row) not in removed]
    audit['removed'] = len(removed)
    return audit
