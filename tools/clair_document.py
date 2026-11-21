"""Self-contained inspection of the submitted pages using recorded decisions."""
import base64
import io
import re
import unicodedata
from collections import defaultdict
from html import escape

import pymupdf as fitz
from PIL import Image, ImageOps
from slm_core_compact_report import criterion_reason
from slm_source_display import source_display
from slm_v6_presentation import row_presentation


def tokens(text):
    return re.findall(r"\w+|[^\w\s]", unicodedata.normalize('NFKC', text).casefold().replace('’', "'"))


def locate(quote, words):
    """Match a unique sequence, then union just its words on each source line."""
    wanted = tokens(quote)
    if not wanted:
        return []
    stream, owners = [], []
    for index, (text, _, _) in enumerate(words):
        parts = tokens(text)
        stream.extend(parts)
        owners.extend([index] * len(parts))
    matches = [i for i, token in enumerate(stream) if token == wanted[0] and stream[i:i+len(wanted)] == wanted]
    if len(matches) != 1:
        return []
    i = matches[0]
    lines = defaultdict(fitz.Rect)
    for index in range(owners[i], owners[i+len(wanted)-1]+1):
        _, rect, line = words[index]
        lines[line] |= rect
    return list(lines.values())


def ocr_words(page):
    ocr = page.get('ocr', {})
    words = iter(ocr.get('words', []))
    result = []
    # Windows OCR serializes words in the order of its lines. Verify the
    # boundaries before using their IDs, including punctuation-only tokens.
    for index, line in enumerate(ocr.get('lines', []), 1):
        expected = ''.join(line.split())
        seen = ''
        while len(seen) < len(expected):
            word = next(words, None)
            if not word:
                return []
            seen += ''.join(word['text'].split())
            x, y = word['x'], word['y']
            rect = fitz.Rect(x, y, x+word['width'], y+word['height'])
            result.append((word['text'], rect, f'L{index:03d}'))
        if seen != expected:
            return []
    return result if next(words, None) is None else []


def notes(proof):
    grouped = defaultdict(list)
    analysis = proof['analyse']
    for row in analysis['lignes']:
        display = row_presentation(row, analysis)
        if display.get('group') != 'conclusions' or display.get('conclusion_kind') != 'legal':
            continue
        outcome = display.get('automatic_outcome')
        if outcome not in ('ecart', 'respecte'):
            continue
        fact = row['fait']
        source = source_display(row)
        url = source.get('url') or ''
        link = (f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">Lire sur Légifrance</a>'
                if url.startswith('https://www.legifrance.gouv.fr/') else '')
        info = ''.join(f'<p>{escape(str(v))}</p>' for v in (
            criterion_reason(row, display) or row.get('explication'), source.get('title'),
            ' · '.join(source.get('metadata') or []), row.get('regle')) if v)
        grouped[fact.get('page')].append((fact, outcome, info+link))
    return grouped


STYLE = """
*{box-sizing:border-box}body{margin:auto;max-width:1080px;padding:16px;background:#eef2f5;color:#172d3e;font:16px/1.45 system-ui,sans-serif}
h1{font-size:1.6rem}h2{font-size:1rem;margin:1.2rem 0 .3rem}.page{position:relative;container-type:inline-size;background:white;box-shadow:0 1px 6px #4454}
.page img{width:100%;height:auto;display:block}.spot{position:absolute;z-index:1;border:2px solid #ac2135;background:#ef43572b;border-radius:3px;cursor:help}
.spot.ok{border-color:#137549;background:#22b36d2e}.spot:hover,.spot:focus-within{z-index:5;outline:1px solid currentColor}
.detail{display:none;position:absolute;top:100%;--w:min(85cqw,390px);width:var(--w);left:min(0px,calc(99cqw - var(--x) - var(--w)));background:white;color:#182d40;padding:.65rem .8rem;box-shadow:0 2px 10px #2237;border:1px solid #637688;border-radius:4px;font-size:.9rem}
.up .detail{top:auto;bottom:100%}.spot:hover .detail,.spot:focus-within .detail{display:block}.detail p,aside p{margin:.35rem 0}.detail a,aside a{color:#17588b}.unplaced{background:white;padding:.8rem}
@container (min-width:680px){.right .detail,.left .detail{width:min(40cqw,390px);top:0;bottom:auto}.right .detail{left:100%}.left .detail{left:auto;right:100%}.up.right .detail,.up.left .detail{bottom:0;top:auto}}
"""


def render_original(request, proof):
    raw = base64.b64decode(request['file_base64'], validate=True)
    grouped = notes(proof)
    visual = {p['page']: p for p in proof['lectures'].get('pages_visuelles', [])}
    filename = escape(request['filename'])
    out = ['<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
           f'<title>CCTP inspecté · {filename}</title><style>{STYLE}</style></head><body>',
           f'<h1>{filename}</h1><p>Rouge · non conforme &nbsp; / &nbsp; Vert · conforme. Survolez, touchez ou sélectionnez un encadré au clavier pour lire la décision et la loi.</p>']
    if not grouped:
        out.append('<p>Aucune décision juridique confirmée pour ce document.</p>')
    missing = []
    is_pdf = request['filename'].lower().endswith('.pdf')
    if is_pdf:
        doc = fitz.open(stream=raw, filetype='pdf')
    else:
        with Image.open(io.BytesIO(raw)) as original:
            picture = ImageOps.exif_transpose(original).convert('RGB')
        picture.thumbnail((2400, 2400))
        doc = None
    try:
        for n in range(1, (len(doc) if is_pdf else 1)+1):
            if is_pdf:
                page = doc[n-1]
                w, h = page.rect.width, page.rect.height
                zoom = 1700 / max(w, h)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom,zoom), colorspace=fitz.csRGB, alpha=False)
                img = pix.tobytes('jpeg', jpg_quality=88)
                native = [(v[4], fitz.Rect(v[:4])*page.rotation_matrix, (v[5],v[6])) for v in page.get_text('words')]
                ocr_scale = max(w,h)/2400
            else:
                w, h = picture.size
                buf = io.BytesIO()
                picture.save(buf, 'JPEG', quality=88)
                img, native, ocr_scale = buf.getvalue(), [], 1
            data = base64.b64encode(img).decode('ascii')
            out.append(f'<h2>Page {n}</h2><div class="page"><img alt="Page {n} du CCTP" src="data:image/jpeg;base64,{data}">')
            words = ocr_words(visual.get(n, {}))
            hotspots = defaultdict(list)
            for fact, outcome, info in grouped.pop(n, []):
                quote = fact.get('citation_visible') or ''
                if fact.get('origine') == 'texte_natif':
                    boxes = locate(quote,native)
                else:
                    obs = fact.get('preuve_visuelle_v6',{}).get('observations') or []
                    allowed = set.intersection(*(set(o.get('citation_ids', [])) for o in obs)) if obs else set()
                    selected = [v for v in words if v[2] in allowed] if allowed else words
                    boxes = [r*fitz.Matrix(ocr_scale,ocr_scale) for r in locate(quote,selected)]
                label = 'Conforme' if outcome == 'respecte' else 'Non conforme'
                note = f'<strong>{label} · {escape(str(fact.get("id","")))}</strong>{info}'
                if not boxes:
                    missing.append(f'<aside><b>Page {n} · {escape(quote)}</b><div>{note}</div></aside>')
                for box in boxes:
                    hotspots[tuple(box)].append((outcome,quote,note))
            for (x0,y0,x1,y1), entries in hotspots.items():
                x,y = 100*x0/w,100*y0/h
                ok = ' ok' if all(e[0]=='respecte' for e in entries) else ''
                position = ' up' if y>65 else ''
                if x1/w < .59:position += ' right'
                elif x0/w > .41:position += ' left'
                tip = '<hr>'.join(e[2] for e in entries)
                out.append(f'<div class="spot{ok}{position}" tabindex="0" aria-label="{escape(entries[0][1],quote=True)}" style="left:{x:.4f}%;top:{y:.4f}%;width:{100*(x1-x0)/w:.4f}%;height:{100*(y1-y0)/h:.4f}%;--x:{x:.4f}cqw"><div class="detail">{tip}</div></div>')
            out.append('</div>')
    finally:
        if doc is not None:doc.close()
    for n, entries in grouped.items():
        for fact, outcome, info in entries:
            missing.append(f'<aside>Page {escape(str(n))} · {escape(fact.get("citation_visible") or "")} · {"Conforme" if outcome=="respecte" else "Non conforme"}{info}</aside>')
    if missing:
        out.append('<section class="unplaced"><h2>Passages dont la position exacte reste à confirmer</h2>'+''.join(missing)+'</section>')
    return (''.join(out)+'</body></html>').encode('utf8')
