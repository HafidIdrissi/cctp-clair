"""Exercise native OCR, the public demo and the portable report downloads."""
import io
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pymupdf
import reportlab
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path.cwd() / 'tools'))
import v4_8_document_service as documents


def check_scans():
    image = Image.new('RGB', (800, 500), 'white')
    font = ImageFont.truetype(str(Path(reportlab.__file__).parent / 'fonts/Vera.ttf'), 38)
    ImageDraw.Draw(image).text((60, 100), 'Largeur libre 1,10 m', font=font, fill='black')
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    png = buffer.getvalue()
    with pymupdf.open() as doc:
        page = doc.new_page(width=800, height=500)
        page.insert_image(page.rect, stream=png)
        pdf = doc.tobytes()
    with tempfile.TemporaryDirectory() as directory:
        documents.OUT = Path(directory)
        (documents.OUT / 'tmp').mkdir()
        for name, data, scale in [('scan.png', png, 1), ('scan.pdf', pdf, 3)]:
            reading = documents.prepare(data, name, mode='ocr_seul')['pages_visuelles'][0]['ocr']
            assert 'Apple Vision' in reading['engine'], reading['engine']
            assert 'largeur' in reading['text'].lower(), reading['text']
            word = next(w for w in reading['words'] if 'largeur' in w['text'].lower())
            assert 45 < word['x']/scale < 90 and 80 < word['y']/scale < 150, word
            assert word['width'] > 0 and word['height'] > 0, word


def fetch(path, data=None):
    req = Request('http://127.0.0.1:8789' + path, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=60) as result:
        return result.read()


def check_demo():
    name = 'CCTP_Rennes_liaison_cyclable_B_avec_defauts_4_pages.pdf'
    assert fetch('/exemple.pdf') == (Path('demo/contrats') / name).read_bytes()
    job = json.loads(fetch('/jobs', b'{"demo":true}'))['id']
    deadline = time.monotonic() + 3 * 3600
    while time.monotonic() < deadline:
        state = next(row for row in json.loads(fetch('/jobs')) if row['id'] == job)
        if state['status'] == 'done':
            break
        assert state['status'] != 'error', state
        time.sleep(5)
    else:
        raise TimeoutError(state)
    prefix = '/jobs/' + job
    assert state['filename'] == name, state
    assert 'Taux de conformité des critères tranchés' in fetch(prefix + '/report').decode()
    assert fetch(prefix + '/pdf').startswith(b'%PDF-')
    report = fetch(prefix + '/document-html').decode()
    assert 'data:image/jpeg;' in report and 'https://www.legifrance.gouv.fr/' in report
    boxes = re.findall(r'<div class="(spot[^"]*)"', report)
    assert any('ok' in box.split() for box in boxes) and any('ok' not in box.split() for box in boxes), boxes
    print('Démo validée : deux verdicts, rapport PDF et CCTP annoté téléchargeable.', flush=True)


if __name__ == '__main__':
    check_scans()
    print('OCR natif PNG et PDF scanné validé.', flush=True)
    check_demo()
