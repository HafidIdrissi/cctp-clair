"""Bounded OCR corroboration, not measurement or human validation.

Only inspect written annotations. Retain model proposals and expose uncertainty
when the OCR cannot link a value to a nearby object. Never consult test truth.
"""
import re
from v4_8_document_service import norm

TOKEN = re.compile(r'(?<![\d.,])(\d{1,5}(?:[.,]\d{1,3})?)\s*(mm|cm|m|%)(?![a-z])', re.I)
ANCHORS = {
    'largeur_pieton': r'trottoir|cheminement\s+p[iie]*ton|largeur libre',
    'largeur_cyclable': r'piste|cyclable|bidirection',
    'devers_pieton': r'devers',
    'ressaut': r'ressaut',
    'fente_grille': r'fente|ouverture.{0,25}grille',
    'distance_stationnement_amont': r'distance.{0,20}amont',
    'bande_eveil': r'bande.{0,15}eveil',
    'absence_amenagement_cyclable': r'(?:aucun|absen|ni).{0,45}(?:amenagement cyclable|itineraire|piste)',
}

def tokens(text):
    return [(float(m[1].replace(',', '.')), m[2].lower()) for m in TOKEN.finditer(str(text))]

def lines(page):
    # Physical row order is supplemental evidence; it is not a verified table.
    return [x.strip() for x in str(page.get('ocr_disposition') or
        page.get('ocr', {}).get('text') or '').replace('|', ' ').splitlines() if x.strip()]

def corroborate(f, page):
    rows = lines(page); target = (f.get('valeur'), f.get('unite'))
    kind = f['type_fait']; pattern = ANCHORS.get(kind)
    compact=lambda text:re.sub(r'[^a-z0-9]','',norm(text))
    quote=compact(f.get('citation_visible') or '')
    source=compact(page.get('ocr',{}).get('text') or '')
    f['citation_litterale_ocr']=bool(quote and quote in source)
    f['preuve_citation_ocr']=f.get('citation_visible') if f['citation_litterale_ocr'] else None
    # An absence on sector B must not substantiate a model claim about A/C.
    # For qualitative omissions, require a literal source quotation, not merely
    # a matching equipment name somewhere else on the page.
    qualitative_ok=kind not in ('bande_eveil','absence_amenagement_cyclable') or bool(quote and quote in source)
    candidates = []
    for i, line in enumerate(rows):
        if not qualitative_ok:continue
        if target[0] is not None:
            if target not in tokens(line): continue
        elif not pattern or not re.search(pattern, norm(line)): continue
        # Do not traverse another measurement row to associate a number.
        start = i
        for j in range(i - 1, max(-1, i - 3), -1):
            if tokens(rows[j]) and target not in tokens(rows[j]): break
            start = j
        end = i + 1
        if end < len(rows) and not tokens(rows[end]): end += 1
        direct = bool(pattern and re.search(pattern,norm(line)))
        block = line if direct else ' '.join(rows[start:end])
        n = norm(block)
        if not pattern or not re.search(pattern, n): continue
        if kind == 'largeur_pieton' and re.search(r'piste|bidirection|fente|grille', n): continue
        # A different numeric datum in the same row leaves the association open.
        if target[0] is not None and any(t != target for t in tokens(line)): continue
        # Prefer a direct annotation rather than a longer neighborhood.
        specificity=0
        if kind=='devers_pieton' and not re.search(r'cheminement|trottoir|pieton',n):specificity=1
        candidates.append((0 if direct else 2, specificity, len(block), i, block))
    candidates.sort()
    f['corroboration_ocr'] = bool(candidates)
    f['preuve_ocr'] = candidates[0][4] if candidates else None
    f['controle_automatique'] = 'Annotation OCR rapprochée de la donnée ; attribution visuelle non validée.' if candidates else 'Objet et donnée non rapprochés dans les annotations OCR : aucun verdict automatique.'
    if not candidates: return ''
    i = candidates[0][3]
    # Conditions must belong to this annotation, not a different table row.
    nearby = [rows[i]]
    for line in rows[i + 1:i + 5]:
        if tokens(line): break
        nearby.append(line)
    return norm(' '.join(nearby))

def coverage(readings):
    selected = [p['page'] for p in readings.get('pages_visuelles', [])]
    visual = [p['page'] for p in readings.get('pages_visuelles', []) if p.get('vision') and p.get('statut') != 'vision_echouee_ocr_conserve']
    failed = [p['page'] for p in readings.get('pages_visuelles', []) if p.get('statut') == 'vision_echouee_ocr_conserve']
    ocr_only = [p for p in selected if p not in visual and p not in failed]
    return {'selected': selected, 'visual': visual, 'failed': failed, 'ocr_only': ocr_only,
        'not_selected': readings.get('couverture_visuelle', {}).get('pages_candidates_non_lues', [])}
