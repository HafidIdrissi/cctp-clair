"""Exercise the distributed n8n relay on a disposable Actions runner."""
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'tools'))
import slm_v6_piste_recovery as relay
from configurer_piste import ARTICLE


def check_article(directory):
    client_id = os.environ.pop('PISTE_SANDBOX_CLIENT_ID')
    client_secret = os.environ.pop('PISTE_SANDBOX_CLIENT_SECRET')
    if not (client_id.strip() and client_secret.strip()):
        raise SystemExit('Les deux secrets de sandbox sont requis.')
    local_key = secrets.token_urlsafe(32)
    header = dict(name='X-Clair-Relay', value=local_key)
    oauth = dict(grantType='clientCredentials', accessTokenUrl='https://sandbox-oauth.piste.gouv.fr/api/oauth/token',
                 scope='openid', authentication='body', clientId=client_id, clientSecret=client_secret)
    credentials = [
        dict(id='CctpTestRelayKey', name='Relais du test', type='httpHeaderAuth', data=header),
        dict(id='CctpTestOAuthKey', name='PISTE sandbox du test', type='oAuth2Api', data=oauth),
    ]
    workflow = json.loads((PROJECT / 'n8n/Relais PISTE sandbox.json').read_text(encoding='utf8'))
    workflow['id'] = 'CctpTestPisteMac'
    nodes = {node['name']: node for node in workflow['nodes']}
    for name, cred in zip(('Rechercher un critère manquant', 'PISTE · recherche ou article'), credentials):
        nodes[name]['credentials'] = {cred['type']: {'id': cred['id'], 'name': cred['name']}}
    env = dict(os.environ, N8N_USER_FOLDER=str(directory), N8N_LISTEN_ADDRESS='127.0.0.1',
               N8N_DIAGNOSTICS_ENABLED='false', N8N_VERSION_NOTIFICATIONS_ENABLED='false')
    path = directory / 'credentials.json'
    path.write_text(json.dumps(credentials), encoding='utf8')
    try:
        subprocess.run(['n8n', 'import:credentials', f'--input={path}'], env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        path.unlink(missing_ok=True)
    path = directory / 'workflow.json'
    path.write_text(json.dumps(workflow), encoding='utf8')
    subprocess.run(['n8n', 'import:workflow', f'--input={path}'], env=env, check=True)
    subprocess.run(['n8n', 'publish:workflow', '--id='+workflow['id']], env=env, check=True)
    relay.ROOT = directory
    config = directory / 'webapp/.local/config.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(dict(header_name=header['name'], header_value=local_key)), encoding='utf8')
    server = subprocess.Popen(['n8n', 'start'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(90):
            if server.poll() is not None:
                raise SystemExit('Le serveur n8n a quitté avant le test.')
            try:
                with urlopen('http://127.0.0.1:5678/healthz/readiness', timeout=2) as response:
                    if response.status == 200:
                        break
            except URLError:
                pass
            time.sleep(1)
        else:
            raise SystemExit('n8n ne signale pas être prêt.')
        answer = relay.transport(dict(operation='article', id=ARTICLE))['response']
        if (answer.get('article') or {}).get('id') != ARTICLE:
            code = (answer.get('error') or {}).get('statusCode') or 'indisponible'
            raise SystemExit(f'Article non reçu. Statut API : {code}. Vérifiez la souscription sandbox, les clés et le quota.')
        print(f'Article reçu via n8n sur Mac : {ARTICLE}.')
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == '__main__':
    os.umask(0o077)
    with tempfile.TemporaryDirectory() as temp:
        check_article(Path(temp))
