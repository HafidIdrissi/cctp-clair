"""Recette de l'archive publiée sur un Mac isolé, dans un navigateur réel."""
import json
import os
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pymupdf
from playwright.sync_api import sync_playwright

root = Path.cwd()
case = os.environ["PARCOURS"]
origin = 'http://127.0.0.1:8789'
temp = Path(os.environ['RUNNER_TEMP'])
contracts = root / 'demo/contrats'


def first(pattern):
    return next(contracts.glob(pattern))


def split_pdf(source, start, end):
    dest = temp / f'{source.stem}-pages-{start}-{end}.pdf'
    with pymupdf.open(source) as pdf, pymupdf.open() as excerpt:
        excerpt.insert_pdf(pdf, from_page=start-1, to_page=end-1)
        excerpt.save(dest)
    return dest


def upload(page, path, city):
    page.locator('#file').set_input_files(str(path))
    page.locator('#city').fill(city)
    page.locator('#date').fill('2024-07-01')
    with page.expect_response(lambda r: r.url == origin+'/jobs' and r.request.method == 'POST', timeout=90000) as posted:
        page.locator('#form button').click()
    assert posted.value.status == 202, posted.value.text()
    return posted.value.json()['id']


def verify(page):
    page.goto(origin)
    page.get_by_text('Me guider', exact=True).click()
    for step in range(1, 4):
        assert f'Étape {step}' in page.locator('#step').inner_text()
        page.locator('#next').click()
    assert page.locator('#coach').is_hidden()
    if case == 'rennes-b':
        with page.expect_response(lambda r: r.url == origin+'/jobs' and r.request.method=='POST') as posted:
            page.locator('#demo').click()
        assert posted.value.status == 202, posted.value.text()
        job = posted.value.json()['id']
    elif case == 'n8n':
        jobs = page.request.get(origin+'/jobs').json()
        assert len(jobs) == 1 and 'Rennes' in jobs[0]['filename'], jobs
        job = jobs[0]['id']
    elif case == 'rennes-a':
        job = upload(page, first('*Rennes*A_version*'), 'Rennes')
    elif case == 'nantes':
        job = upload(page, first('*Nantes*'), 'Nantes')
    elif case.startswith('tain'):
        start, end = (1,15) if case=='tain-1' else (16,27)
        job = upload(page, split_pdf(first('*Tain*'), start,end), 'Tain-l’Hermitage')
    elif case == 'modele':
        data=json.dumps({'model':'qwen3:4b','stream':False}).encode()
        with urlopen(Request('http://127.0.0.1:11434/api/pull', data=data),timeout=1200) as reply:
            assert json.load(reply)['status']=='success'
        page.reload()
        page.locator('#form summary').click()
        page.locator('#model').select_option('qwen3:4b',timeout=30000)
        job = upload(page, split_pdf(first('*Rennes*B_avec*'),1,1), 'Rennes')
    else:
        raise ValueError(case)
    start = time.monotonic()
    last = None
    while True:
        state = next(s for s in page.request.get(origin+'/jobs').json() if s['id']==job)
        key=(state['stage'],(state.get('progress') or {}).get('done'))
        if key != last:
            print(case, round((time.monotonic()-start)/60,1), 'min', state['stage'],state.get('progress'),flush=True)
            last=key
        if state['status']=='done': break
        if state['status']=='error': raise RuntimeError(state)
        time.sleep(15)
    page.reload()
    with page.expect_popup() as pop:
        page.get_by_text('Lire le rapport',exact=True).click()
    text=pop.value.locator('body').inner_text()
    assert 'Taux de conformité' in text
    print('Synthèse du contrat de test :',text[:1500],flush=True)
    with page.expect_popup() as source:
        page.get_by_text('Inspecter le CCTP original',exact=True).click()
    doc=source.value
    assert doc.locator('.page img').count()>0
    if case in ('rennes-b','n8n'):
        for selector,value in [('.spot:not(.ok)','1,10'),('.spot.ok','1,00')]:
            target=doc.locator(selector).filter(has=doc.locator('.detail')).first
            matches=doc.locator(selector+'[aria-label*="'+value+'"]')
            if matches.count(): target=matches.first
            target.hover(timeout=12000)
            assert target.locator('.detail').is_visible()
            assert 'legifrance.gouv.fr/' in target.locator('a').first.get_attribute('href')
            print('Annotation au survol',target.get_attribute('aria-label'),flush=True)
            assert value in (target.get_attribute('aria-label')+' '+target.inner_text()), value
    for label, suffix in [('Télécharger le CCTP inspecté','html'),('Télécharger le PDF','pdf'),('Preuves JSON','json')]:
        with page.expect_download() as transfer:
            page.get_by_text(label,exact=True).click()
        dest=temp/('rapport.'+suffix)
        transfer.value.save_as(str(dest))
        if suffix=='pdf': assert dest.read_bytes().startswith(b'%PDF-')
        if suffix=='html':
            offline=page.context.new_page()
            offline.goto(dest.as_uri())
            assert offline.locator('.page img').first.evaluate('img=>img.complete && img.naturalWidth>0')
        if suffix=='json' and case=='modele':
            req=list(root.glob('local/**/'+job+'/request.json'))
            assert req and json.loads(req[0].read_text())['metadata']['comparison_model']=='qwen3:4b'
    print('Parcours terminé',case,flush=True)


if __name__=='__main__':
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome')
        try: verify(browser.new_page(accept_downloads=True))
        finally: browser.close()
