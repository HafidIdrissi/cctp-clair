"""Small versioned official-source cache. This is NOT all French mobility law.

Curated controls, manually checked against the official texts on 2026-09-28.
No secret, contract text, arbitrary URL, or model-produced rule is sent out.
"""
import hashlib
import json
import sqlite3
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/local_sources/vision_v4_9'
DB = OUT / 'lois_officielles.sqlite'
CATALOG = {
    'access': {'titre':'Arrêté du 15 janvier 2007 - article 1', 'debut':'2024-03-24',
        'url':'https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000049320039',
        'heading':'Article 1', 'tokens':['2 %','1,40','1,20','2 centimètres','4 centimètres']},
    'scope': {'titre':'Décret 2006-1657 - article 1', 'debut':'2006-12-23',
        'url':'https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000006258010',
        'heading':'Article 1', 'tokens':['agglomération','réfection']},
    'parking': {'titre':'Code de la voirie routière - L118-5-1', 'debut':'2019-12-27',
        'url':'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000039678026',
        'heading':'Article L118-5-1', 'tokens':['cinq mètres','amont','réfection','2026']},
    'cycling': {'titre':'Code de l’environnement - L228-2', 'debut':'2019-12-27',
        'url':'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000039784686',
        'heading':'Article L228-2', 'tokens':['voies urbaines','itinéraires cyclables']},
    'derogation': {'titre':'Arrêté du 15 janvier 2007 - article 2', 'debut':'2007-02-03',
        'url':'https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000006259923',
        'heading':'Article 2', 'tokens':['préfet','commission','dérogation']},
}

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.skip+=1
        if tag in ('h1','h2','h3','p','div','li','br'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.skip-=1
        if tag in ('h1','h2','h3','p','div','li'): self.parts.append('\n')
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)

def plain(html):
    parser=TextParser(); parser.feed(html)
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())

def article_text(html, heading):
    text=plain(html)
    match=re.search(r'(?:^|\n)'+re.escape(heading)+r'\nVersion en vigueur[^\n]*\n(.*?)\nVoir les versions',text,re.S)
    if not match or len(match[1])<100:
        raise ValueError('Contenu officiel non identifiable : aucun remplacement par un résumé généré.')
    return match[1].strip()

def refresh():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for key, meta in CATALOG.items():
        req = urllib.request.Request(meta['url'],headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=25) as response:
            if urllib.parse.urlparse(response.url).hostname!='www.legifrance.gouv.fr':
                raise ValueError('Redirection hors source officielle.')
            raw = response.read(2_000_000)
        html = raw.decode('utf-8')
        text = article_text(html,meta['heading'])
        if not all(token.lower() in text.lower() for token in meta['tokens']):
            raise ValueError('Texte inattendu : contrôle manuel requis pour '+key)
        # Check the displayed version start independently of our reviewed rule.
        start = datetime.strptime(meta['debut'],'%Y-%m-%d').strftime('%d/%m/%Y')
        parent_text = plain(html)
        if start not in parent_text:
            raise ValueError('Début de version non confirmé pour '+key)
        record = {**meta, 'id':key, 'texte':text,'verified_through':date.today().isoformat(),
            'retrieved_at':datetime.now(timezone.utc).isoformat(),
            'sha256':hashlib.sha256(raw).hexdigest(),'canal':'site_officiel_legifrance',
            'controle':'texte_et_debut_version_verifies_catalogue_limite'}
        (OUT / ('source_'+key+'.html')).write_bytes(raw)
        rows.append(record)
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS articles (id TEXT PRIMARY KEY, record TEXT NOT NULL)')
        db.executemany('INSERT OR REPLACE INTO articles VALUES (?,?)',[(r['id'],json.dumps(r,ensure_ascii=False)) for r in rows])
    return {'sources':len(rows),'db':str(DB),'canal':'site officiel, pas API PISTE','exhaustive':False}

def sources_for(reference):
    parsed = date.fromisoformat(reference)
    if parsed.isoformat()!=reference: raise ValueError('Date invalide.')
    if not DB.exists(): return {}
    with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro',uri=True) as db:
        records=[json.loads(r[0]) for r in db.execute('SELECT record FROM articles')]
    return {r['id']:r for r in records if r['debut'] <= reference <= r['verified_through']}

def install_reviewed():
    """Offline excerpts checked on official pages; not a PISTE download."""
    reviewed=json.loads((Path(__file__).with_name('v4_9_sources_reviewed.json')).read_text(encoding='utf-8'))
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for key,meta in CATALOG.items():
        record={**meta,'id':key,'texte':reviewed[key], 'verified_through':reviewed['verification_date'],
            'retrieved_at':reviewed['verification_date'],'canal':reviewed['canal'],'nature':reviewed['nature'],
            'sha256':hashlib.sha256(reviewed[key].encode()).hexdigest(),
            'controle':'extraits_et_debut_version_verifies_sur_pages_officielles'}
        rows.append(record)
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS articles (id TEXT PRIMARY KEY, record TEXT NOT NULL)')
        db.executemany('INSERT OR REPLACE INTO articles VALUES (?,?)',[(r['id'],json.dumps(r,ensure_ascii=False)) for r in rows])
    return {'sources':len(rows),'canal':reviewed['canal'],'exhaustive':False}

if __name__=='__main__':
    import sys
    print(json.dumps(install_reviewed() if '--install-reviewed' in sys.argv else refresh(),ensure_ascii=True))
