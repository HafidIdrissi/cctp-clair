"""Assistant du relais local. Les identifiants OAuth restent dans n8n."""
import json
import secrets
from pathlib import Path
from urllib.error import HTTPError, URLError

from slm_v6_piste_recovery import transport

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'webapp/.local/config.json'
ENABLED = ROOT / 'local/piste-active'
ARTICLE = 'LEGIARTI000049320039'


def main():
    if ENABLED.exists():
        if input('PISTE est actif. Revenir au mode local uniquement (O/N) ? ').strip().upper() == 'O':
            ENABLED.unlink()
            print('Mode local actif pour les prochaines analyses.')
            return
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        config = dict(header_name='X-Clair-Relay', header_value=secrets.token_urlsafe(32))
        with CONFIG.open('x', encoding='utf-8') as out:
            json.dump(config, out)
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    print('Dans n8n, importez n8n/Relais PISTE sandbox.json.')
    print('Dans le premier nœud, créez un identifiant Header Auth avec ces deux champs :')
    print('Name  :', config['header_name'])
    print('Value :', config['header_value'])
    print('Gardez cette clé sur votre PC. Configurez OAuth2 dans le nœud PISTE selon le README.')
    input('Après publication du workflow, appuyez sur Entrée pour tester un article. ')
    try:
        result = transport(dict(operation='article', id=ARTICLE))
        if (result['response'].get('article') or {}).get('id') != ARTICLE:
            print('Article non reçu. Vérifiez les identifiants sandbox, les droits Légifrance et les quotas.')
            return
    except HTTPError as error:
        print(f'Relais HTTP {error.code}. Vérifiez la publication du workflow et les deux champs Header Auth.')
        return
    except (URLError, OSError, ValueError):
        print('Relais inaccessible ou réponse inattendue. Vérifiez n8n sur le port 5678 et réessayez.')
        return
    ENABLED.parent.mkdir(exist_ok=True)
    ENABLED.touch()
    print('Article reçu. PISTE est actif pour les prochaines analyses.')


if __name__ == '__main__':
    main()
