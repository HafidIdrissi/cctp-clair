"""Application Windows locale. Le moteur et les rapports sont exécutés sur le PC."""
import base64
import hashlib
import json
import re
import sys
import tarfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import randbelow
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
import slm_core_service as core
import clair_model_choice as models
from dila_local_store import DilaStore, DEFAULT_DB_PATH
from clair_annotations import render
from slm_source_display import source_display

PORT = 8789
RUNTIME = ROOT / 'local'
DEMO = ROOT / 'demo' / 'Exemple.pdf'


def initialize():
    RUNTIME.mkdir(exist_ok=True)
    if not DEFAULT_DB_PATH.exists():
        archive = RUNTIME / 'extrait-legi.tar.gz'
        with tarfile.open(archive,'w:gz') as target:
            for xml in sorted((ROOT/'demo/legi').glob('*.xml')):
                target.add(xml, arcname=xml.name)
        DilaStore().import_archive(archive, snapshot_date='2025-07-13',
            coverage_scope='Extrait pédagogique de trois articles LEGI',
            source_url='https://echanges.dila.gouv.fr/OPENDATA/LEGI/Freemium_legi_global_20250713-140000.tar.gz')
    core.configure_clair(RUNTIME)
    models.configure(core, RUNTIME/'interface/jobs')
    core.RELEASE={'id':'cctp-clair-portable','sha256':hashlib.sha256((ROOT/'tools/slm_core_engine.py').read_bytes()).hexdigest()}
    core.JOBS.mkdir(parents=True,exist_ok=True)
    for saved in core.JOBS.glob('*/state.json'):
        state=json.loads(saved.read_text(encoding='utf8'))
        core.STATES[state['id']]=state
        if state['status'] in ('queued','running'):
            core.update(state['id'],status='error',error='Traitement interrompu. Relancez le document.')


class App(BaseHTTPRequestHandler):
    def reply(self, status, body, mime='application/json', download=None):
        raw=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        if download:self.send_header('Content-Disposition',f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(raw)

    def local(self):
        hosts={f'127.0.0.1:{PORT}',f'localhost:{PORT}'}
        return self.headers.get('Host') in hosts and self.headers.get('Origin') in (None,*('http://'+h for h in hosts)) and self.headers.get('Sec-Fetch-Site')!='cross-site'

    def do_GET(self):
        if not self.local():return self.reply(403,{'error':'Accès local uniquement.'})
        path=urlsplit(self.path).path
        assets={'/':('interface/index.html','text/html; charset=utf-8'),'/app.js':('interface/app.js','text/javascript; charset=utf-8'),'/style.css':('interface/style.css','text/css'),'/exemple.pdf':('demo/Exemple.pdf','application/pdf')}
        if path in assets:
            file,mime=assets[path]
            return self.reply(200,(ROOT/file).read_bytes(),mime)
        if path=='/health':return self.reply(200,{'service':'cctp-clair-portable'})
        if path=='/models':
            try:return self.reply(200,models.local_models())
            except OSError:return self.reply(503,{'error':'Ouvrez Ollama puis relancez CCTP Clair.'})
        if path=='/jobs':
            with core.LOCK:
                return self.reply(200,[{k:s.get(k) for k in ('id','status','stage','error','created_at','filename','progress')} for s in reversed(list(core.STATES.values()))])
        match=re.fullmatch(r'/jobs/([a-f0-9]{32})/(report|pdf|html|inspection)',path)
        if not match or match[1] not in core.STATES:return self.reply(404,{})
        if core.STATES[match[1]]['status']!='done':return self.reply(409,{'error':'Rapport en préparation.'})
        report=json.loads((core.JOBS/match[1]/'report.json').read_text(encoding='utf8'))
        if match[2]=='pdf':return self.reply(200,base64.b64decode(report['pdf_base64']),'application/pdf','rapport.pdf')
        if match[2]=='inspection':return self.reply(200,report['preuves_json'],download='inspection.json')
        rows=[]
        for line in report['preuves_json']['analyse']['lignes']:
            fact=line.get('fait') or {}
            rows.append(dict(id=fact.get('id'),page=fact.get('page'),quote=fact.get('citation_visible'),status=line.get('statut'),source_display=source_display(line),explanation=line.get('explication')))
        html=render(report['rapport_html'],{'findings':rows})
        return self.reply(200,html,'text/html; charset=utf-8','rapport-annote.html' if match[2]=='html' else None)

    def do_POST(self):
        if not self.local() or self.headers.get('Content-Type','').split(';')[0]!='application/json':
            return self.reply(403,{'error':'Requête locale JSON requise.'})
        if self.path!='/jobs':return self.reply(404,{})
        try:
            length=int(self.headers.get('Content-Length',0))
            if not 0<length<36_000_000:raise ValueError('Fichier trop volumineux (25 Mo maximum).')
            self.connection.settimeout(40)
            data=json.loads(self.rfile.read(length))
            if data.get('demo'): filename,encoded,city,date=DEMO.name,base64.b64encode(DEMO.read_bytes()).decode(),'Projet fictif','2024-07-01'
            else: filename,encoded,city,date=data['filename'],data['file_base64'],data['city'],data['date']
            if Path(filename).suffix.lower() not in ('.pdf','.jpg','.jpeg','.png'):raise ValueError('Choisissez un PDF ou une image.')
            state=core.submit(dict(filename=filename,file_base64=encoded,execution_id=str(10**14+randbelow(9*10**14)),
                metadata=dict(city=city,reference=date,mode='local',vision='vision',format='cards',comparison_model=data.get('model') or models.DEFAULT)))
            core.update(state['id'],filename=filename)
            return self.reply(202,{'id':state['id'],'url':f'http://127.0.0.1:{PORT}/?job='+state['id']})
        except (ValueError,TypeError,KeyError,OSError) as exc:return self.reply(400,{'error':str(exc)[:350]})


if __name__=='__main__':
    initialize()
    print(f'CCTP Clair est prêt sur http://127.0.0.1:{PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),App).serve_forever()
