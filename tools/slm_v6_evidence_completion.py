"""Complete split native equipment/measurement evidence, never its conclusion.

Only two adjacent sentences in one native paragraph, an explicit anaphor,
one equipment and one exact scalar measurement can be reunited. All original
facts, exact character offsets and any consolidation remain reviewable.
"""
from __future__ import annotations

import copy
import re
from decimal import Decimal, InvalidOperation

from slm_v6_object_guard import objects, characteristics, plain
from slm_v6_technical import MEASURE, scalar_target

VERSION = 'completion_native_adjacente-1'
MAX_PARAGRAPH_CHARS = 2400
MAX_COMPLETED_CHARS = 1600
EXCLUDED = re.compile(
    r"\b(?:exemple|illustration|facultati\w*|option\w*|variante\w*|hypothese\w*|"
    r"pourrait|pourraient|serait|seraient|si|sauf|exception\w*|eventuel\w*|"
    r"ecarte\w*|non retenu\w*|pas retenu\w*|hors projet|hors travaux|"
    r"a condition|sous reserve|a confirmer|ne|aucun\w*)\b|\bn['’]"
)
SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ])')
PARAGRAPH_BOUNDARY = re.compile(r'\n\s*\n')


def compact(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def spans(text, boundary, offset=0):
    start = 0
    for match in list(boundary.finditer(text)) + [None]:
        end = match.start() if match else len(text)
        left, right = start, end
        while left < right and text[left].isspace(): left += 1
        while right > left and text[right-1].isspace(): right -= 1
        if left < right: yield offset+left, offset+right
        if match: start = match.end()


def native_occurrences(quote, page):
    words = re.findall(r'\S+', quote)
    if not words: return []
    return list(re.finditer(r'\s+'.join(re.escape(word) for word in words), page))


def protected(fact):
    return any(fact.get(k) for k in ('validation_humaine', 'rejet_humain', 'relecteur',
                                    'ambiguite', 'correction_humaine', 'validation_juriste'))


def explicit_anaphor(sentence, antecedent_object):
    text = plain(sentence)
    dimensions = r'(?:largeur|hauteur|longueur|profondeur|epaisseur|diametre|rayon|devers|pente|entraxe)'
    if re.match(r'^(?:sa|son|ses)\s+(?:bande\s+roulable\b|'+dimensions+r'\b)', text):
        return True
    if re.match(r'^(?:elle|il|celle-ci|celui-ci|cet ouvrage|cet equipement)\b', text):
        return True
    if re.match(r'^(?:cette|ce|cet)\s+', text):
        mentioned = objects(sentence)['keys']
        return len(mentioned) == 1 and mentioned[0] == antecedent_object
    return False


def metadata_agrees(fact, scalar):
    """A pre-existing conflicting quantity is not silently repaired."""
    try:
        if fact.get('valeur_m') is not None:
            if scalar['unit'] != 'm' or Decimal(str(fact['valeur_m'])) != Decimal(scalar['value']):
                return False
        if fact.get('valeur') is not None:
            unit = fact.get('unite')
            factors = {'m': Decimal(1), 'cm': Decimal('.01'), 'mm': Decimal('.001'), '%': Decimal(1)}
            if unit not in factors or isinstance(fact['valeur'], bool): return False
            if (unit == '%') != (scalar['unit'] == '%'): return False
            if Decimal(str(fact['valeur']).replace(',', '.'))*factors[unit] != Decimal(scalar['value']):
                return False
    except (InvalidOperation, TypeError, ValueError):
        return False
    return True


def complete_fact(fact, readings):
    """Return a new fact with evidence, or None; never mutate caller data."""
    pages = readings.get('text') or []
    page_number = fact.get('page')
    if (fact.get('origine') != 'texte_natif' or protected(fact)
            or type(page_number) is not int or not 1 <= page_number <= len(pages)):
        return None
    page = pages[page_number-1]
    if not isinstance(page, str): return None
    quote = fact.get('citation_visible')
    if not isinstance(quote, str) or len(compact(quote)) < 20: return None
    found = native_occurrences(quote, page)
    if len(found) != 1: return None
    match = found[0]
    paragraph = next(((a,b) for a,b in spans(page,PARAGRAPH_BOUNDARY)
                      if a <= match.start() and match.end() <= b), None)
    if not paragraph: return None
    left, right = paragraph
    native_paragraph = page[left:right]
    if len(native_paragraph)>MAX_PARAGRAPH_CHARS or EXCLUDED.search(plain(native_paragraph)):
        return None
    paragraph_objects = objects(native_paragraph)
    if len(paragraph_objects['keys']) != 1 or len(list(MEASURE.finditer(native_paragraph))) != 1:
        return None
    parts = list(spans(native_paragraph,SENTENCE_BOUNDARY,left))
    position = next((i for i,(a,b) in enumerate(parts) if a==match.start() and b==match.end()),None)
    if position is None: return None  # A quote fragment cannot annex another sentence.
    original_objects = objects(quote)['keys']
    original_measures = list(MEASURE.finditer(quote))
    if not original_measures and len(original_objects)==1 and position+1<len(parts):
        first, second = parts[position], parts[position+1]
        direction = 'phrase_suivante'
    elif len(original_measures)==1 and not original_objects and position>0:
        first, second = parts[position-1], parts[position]
        direction = 'phrase_precedente'
    else:
        return None
    first_text, second_text = page[first[0]:first[1]], page[second[0]:second[1]]
    initial_objects = objects(first_text)['keys']
    if len(initial_objects)!=1 or list(MEASURE.finditer(first_text)):
        return None
    if not explicit_anaphor(second_text,initial_objects[0]): return None
    joined = page[first[0]:second[1]]
    if len(joined)>MAX_COMPLETED_CHARS: return None
    combined_objects = objects(joined)
    if combined_objects['keys'] != initial_objects or combined_objects['keys'] != paragraph_objects['keys']:
        return None
    axes = characteristics(second_text)['noms']
    if len(axes)!=1: return None
    scalar = scalar_target(joined)
    if not scalar or not metadata_agrees(fact,scalar): return None
    # Only literal extraction fields can change; no automatic legal rule appears here.
    from slm_v5_facts import literal_candidate
    candidate = literal_candidate(joined)
    if candidate and (candidate.get('ambiguite') or candidate.get('valeur') is None):
        return None
    result = copy.deepcopy(fact)
    if candidate:
        for key in ('type_fait','element','valeur','valeur_m','unite','valeur_inscrite','etat'):
            if key in candidate: result[key] = copy.deepcopy(candidate[key])
    else:
        # Unknown V5 measurement categories can retain precise evidence without
        # being mapped to any legal rule or pretending to be a known fact type.
        value = Decimal(scalar['value'])
        result.update(type_fait='autre',element=initial_objects[0]+' / '+axes[0],
                      valeur=float(value),valeur_m=float(value) if scalar['unit']=='m' else None,
                      unite=scalar['unit'],valeur_inscrite=scalar['literal'])
    result.update(citation_visible=joined,preuve_citation_native=joined,
                  lecture_statut='citation_native_exacte',association_valeur_element_verifiee=False)
    evidence = dict(version=VERSION,method='deux_phrases_natives_adjacentes_anaphore_univoque',
        original_fact=copy.deepcopy(fact),page=page_number,
        original=dict(debut=match.start(),fin=match.end(),citation=page[match.start():match.end()]),
        paragraphe=dict(debut=left,fin=right,citation=native_paragraph),
        complete=dict(debut=first[0],fin=second[1],citation=joined),sens=direction,
        antecedent=dict(debut=first[0],fin=first[1],citation=first_text),
        mesure=dict(debut=second[0],fin=second[1],citation=second_text,scalaire=scalar),
        objet=combined_objects,caracteristique=axes[0],
        checks=dict(citation_originale_unique=True,meme_paragraphe=True,phrases_adjacentes=True,
                    anaphore_explicite=True,objet_unique=True,mesure_unique=True,
                    caracteristique_unique=True,metadonnees_compatibles=True,human_preserved=True),
        scope='Complétion de lecture native seulement ; aucun verdict ni seuil de conformité.')
    result['preuve_native_completee_v6'] = evidence
    return result


def verify_completed_fact(fact, readings):
    """Rebuild completion from source evidence; a flag/offset alone is insufficient."""
    evidence = fact.get('preuve_native_completee_v6') or {}
    original = evidence.get('original_fact')
    if not isinstance(original,dict) or evidence.get('version') != VERSION: return False
    rebuilt = complete_fact(original,readings)
    if not rebuilt or rebuilt['preuve_native_completee_v6'] != evidence: return False
    fields = ('id','page','origine','citation_visible','preuve_citation_native','type_fait',
              'element','valeur','valeur_m','unite','valeur_inscrite')
    return all(fact.get(key)==rebuilt.get(key) for key in fields)


def complete_readings(readings):
    """Return a deep copy; strict no-op when nothing can be safely completed."""
    result = copy.deepcopy(readings)
    facts = result.get('faits')
    if not isinstance(facts,list): return result
    events = []
    completed = set()
    for index,fact in enumerate(facts):
        if not isinstance(fact,dict) or fact.get('preuve_native_completee_v6'): continue
        candidate = complete_fact(fact,result)
        if not candidate: continue
        facts[index] = candidate
        completed.add(index)
        events.append(dict(fact_id=fact.get('id'),evidence=copy.deepcopy(candidate['preuve_native_completee_v6'])))
    if not completed: return result
    # Merge only fresh completions of the very same native span, not merely
    # similar text or two clauses with the same number/equipment name.
    groups = {}
    merges = []
    removed = set()
    for index in sorted(completed):
        fact=facts[index];ev=fact['preuve_native_completee_v6']
        key=(fact['page'],ev['complete']['debut'],ev['complete']['fin'],fact['citation_visible'],
             fact['type_fait'],str(fact.get('valeur')),fact.get('unite'))
        if key not in groups:
            groups[key]=index; continue
        retained=facts[groups[key]]
        if retained.get('id')==fact.get('id'): continue
        event=dict(fact_id=fact.get('id'),retained_fact_id=retained.get('id'),
                   original_fact=copy.deepcopy(ev['original_fact']),
                   evidence=copy.deepcopy(ev),method='meme_segment_natif_complete')
        retained.setdefault('doublons_extraction_v6',[]).append(copy.deepcopy(event))
        merges.append(event);removed.add(index)
    result['faits']=[fact for index,fact in enumerate(facts) if index not in removed]
    result['evidence_completion_v6']=dict(version=VERSION,completed=len(events),removed=len(removed),
        events=events,consolidations=merges,
        scope='Lecture et regroupement de preuves natives identiques uniquement ; aucun verdict de conformité.')
    return result
