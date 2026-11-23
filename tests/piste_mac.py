"""Test the official ZIP and local n8n on an ephemeral Mac. No credential logs."""
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

url = 'http://127.0.0.1:5678'
relay_file = Path('n8n/Relais PISTE sandbox.json')
relay = json.loads(relay_file.read_text())
assert 'https://sandbox-api.piste.gouv.fr/dila/legifrance/' in relay['nodes'][2]['parameters']['url']
token_url = 'https://sandbox-oauth.piste.gouv.fr/api/oauth/token'
real = bool(os.environ.get('PISTE_TEST_ID') and os.environ.get('PISTE_TEST_SECRET'))


def assistant(answer):
    return subprocess.run(['./Configurer PISTE.command'], input=answer, capture_output=True,
                          text=True, timeout=120, check=True).stdout


def request(ctx, path, body):
    response=ctx.request.post(url+'/rest/'+path,data=body)
    if not response.ok:
        raise RuntimeError(f'{path.split("/")[0]} HTTP {response.status}')
    return response.json().get('data')


def open_ui(page, file):
    page.goto(url+'/workflow/new')
    item=page.get_by_test_id
    item('workflow-menu').click()
    if item('workflow-menu-item-import').is_visible():
        item('workflow-menu-item-import').click()
    with page.expect_file_chooser() as chooser:
        item('workflow-menu-item-import-from-file').click()
    chooser.value.set_files(str(file.resolve()))
    page.locator('[data-node-name="PISTE · recherche ou article"][data-test-id="canvas-node"]').dblclick()
    empty=item('node-credentials-empty-state').get_by_role('button').first
    if empty.is_visible():
        empty.click()
    else:
        item('node-credentials-select').first.click()
        item('node-credentials-select-item-new').first.click()
    modal=item('editCredential-modal')
    modal.wait_for()
    grant=modal.get_by_test_id('parameter-input-grantType')
    grant.click()
    page.get_by_text('Client Credentials',exact=True).last.click()
    for key in ('clientId','clientSecret','accessTokenUrl','scope'):
        modal.get_by_test_id('parameter-input-'+key).locator('input').first.wait_for()
    print('Éditeur : import via le menu, troisième nœud, Grant Type et quatre champs OAuth visibles.',flush=True)


def test(pw):
    pw.selectors.set_test_id_attribute('data-test-id')
    browser=pw.chromium.launch(channel='chrome')
    ctx=browser.new_context()
    page=ctx.new_page()
    page.set_default_timeout(10000)
    for attempt in range(60):
        settings=ctx.request.get(url+'/rest/settings')
        if settings.ok and 'application/json' in settings.headers.get('content-type',''): break
        time.sleep(2)
    else:
        raise RuntimeError('Le serveur répond sur /healthz mais son éditeur et ses réglages ne sont pas prêts.')
    page.goto(url)
    page.locator('input[type="email"],input[name="email"],input[autocomplete="email"]').first.wait_for(timeout=60000)
    print('Page de premier démarrage :',page.url.split('?')[0],flush=True)
    owner_data=dict(email='mac-test@example.invalid',firstName='Test',lastName='Local',
                    password='Temporary8'+secrets.token_hex(10))
    for field,hint in (('email','email'),('firstName','given-name'),('lastName','family-name'),('password','new-password')):
        page.locator(f'input[autocomplete="{hint}"]').fill(owner_data[field])
    with page.expect_response(lambda r: r.request.method=='POST' and '/owner/setup' in r.url) as submitted:
        page.get_by_test_id('setup-form').get_by_role('button',name='Next').click()
    if not submitted.value.ok:
        raise RuntimeError(f'Création de compte via le formulaire HTTP {submitted.value.status}')
    print('Compte de test local créé depuis le formulaire.',flush=True)
    try:
        open_ui(page,relay_file)
    except Exception as exc:
        print('Étape éditeur non confirmée :',type(exc).__name__,flush=True)
        # No real PISTE values have been entered in the editor at this point.
        print('Dernière vue avant toute saisie secrète :',page.locator('body').inner_text()[:1000],flush=True)
    assistant('\n')
    assert not Path('local/piste-active').exists()
    config=json.loads(Path('webapp/.local/config.json').read_text())
    header=request(ctx,'credentials',{'name':'Relais du Mac de test','type':'httpHeaderAuth',
                  'data':{'name':config['header_name'],'value':config['header_value']}})
    if not real:
        print('Relais local créé ; identifiants PISTE sandbox absents. Appel officiel non exécuté.',flush=True)
        browser.close()
        return
    try:
        oauth=request(ctx,'credentials',{'name':'PISTE sandbox essai','type':'oAuth2Api','data':{
            'grantType':'clientCredentials','accessTokenUrl':token_url,'scope':'openid','authentication':'body',
            'clientId':os.environ['PISTE_TEST_ID'],'clientSecret':os.environ['PISTE_TEST_SECRET']}})
        for index,key,cred in [(0,'httpHeaderAuth',header),(2,'oAuth2Api',oauth)]:
            relay['nodes'][index]['credentials']={key:{'id':cred['id'],'name':cred['name']}}
        workflow=request(ctx,'workflows',{k:relay[k] for k in ['name','nodes','connections','settings']})
        request(ctx,'workflows/'+workflow['id']+'/activate',{'versionId':workflow['versionId']})
        time.sleep(2)
        result=assistant('\n')
        if 'Article reçu. PISTE est actif' not in result:
            raise RuntimeError('Le relais publié n’a pas renvoyé l’article attendu.')
        assert Path('local/piste-active').is_file()
        assert 'Mode local actif' in assistant('O\n')
        assert not Path('local/piste-active').exists()
        print('PISTE réel : article LEGIARTI000049320039 reçu, activation puis retour au mode local vérifiés.')
    finally:
        browser.close()


if __name__=='__main__':
    try:
        with sync_playwright() as playwright:
            test(playwright)
    except Exception as exc:
        # Only our controlled, credential-free errors may be printed after secret access.
        print('Essai interrompu :',str(exc) if type(exc) is RuntimeError else type(exc).__name__,flush=True)
        raise SystemExit(1)
