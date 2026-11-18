"""Async, loopback-only, frozen-release worker. n8n owns ingress and delivery."""
import base64,copy,hashlib,json,re,threading,uuid,urllib.request,time
from pathlib import Path
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
from slm_m3_journal import Journal,bind,emit
from slm_core_policy import coverage
from slm_core_engine import review,MODEL,WORKFLOW,VERSION
from slm_v5_report import report
from slm_core_compact_report import pdf_report as summary_pdf, html_report as summary_html
from slm_v6_checkpoint import atomic_json
import v4_8_document_service as reader
from v4_9_document_service import vision
from slm_core_extraction import repair,attach_geometry

ROOT=Path(__file__).resolve().parents[1]
PORT=8774
SERVICE='slm-core-metier'
HEALTH_VERSION='CORE1'
JOBS=ROOT/'webapp/.local/core_jobs'
STATES={};LOCK=threading.RLock();POOL=ThreadPoolExecutor(max_workers=1)
RELEASE={}

def now():return datetime.now(timezone.utc).isoformat()
def identity():
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=10) as r:models=json.load(r)['models']
    matches=[m for m in models if m.get('name')==MODEL]
    if len(matches)!=1:raise ValueError('Ministral 3B local indisponible.')
    return dict(name=MODEL,digest=matches[0]['digest'])
def update(ident,**values):
    with LOCK:
        STATES[ident].update(values,updated_at=now());atomic_json(JOBS/ident/'state.json',STATES[ident])
def progress(ident,stage,done=0,total=0,**extra):
    prior=STATES[ident]
    if prior.get('stage')!=stage:
        if prior.get('phase_started') is not None:emit(prior['stage'],'done',duration_ms=round((time.monotonic()-prior['phase_started'])*1000))
        update(ident,phase_started=time.monotonic())
    update(ident,stage=stage,progress=dict(stage=stage,done=done,total=total,**extra))
    emit(stage,'running',done=done,total=total,**extra)

def execute(ident,payload):
    state=STATES[ident];execution=state['execution_id'];meta=payload['metadata']
    journal=Journal(execution,root=ROOT/'webapp/.local/core_journals')
    with bind(journal):
        try:
            update(ident,status='running',model=identity(),release=RELEASE)
            progress(ident,'reading')
            raw=base64.b64decode(payload['file_base64'],validate=True)
            readings=reader.prepare(raw,payload['filename'],meta.get('pages',''),'auto' if meta.get('vision')=='vision' else 'ocr_seul')
            readings.update(city=meta['city'])
            attach_geometry(readings)
            progress(ident,'vision')
            readings=vision(readings)
            readings=repair(readings)
            progress(ident,'inventory')
            prepared=coverage(dict(lectures=readings,date_reference=meta['reference'],
                controle_juridique=meta.get('mode')!='reading',piste_autorise=meta.get('mode') in ('auto','full'),
                format_rapport='tableau' if meta.get('format')=='table' else 'cartes'))
            readings=prepared['lectures_images'];plan=prepared['couverture_locale']
            # The focused engine can recover missing exact/local references and
            # consult the existing credentialed n8n relay per control.
            progress(ident,'legal')
            body=dict(lectures=readings,couverture_locale=plan,date_reference=meta['reference'],
                controle_juridique=meta.get('mode')!='reading',format_rapport=prepared['format_rapport'])
            def reviewer(analysis,view,policy):
                progress(ident,'comparison')
                def on_point(p):progress(ident,'comparison',p.get('done',0),p.get('total',0),fact_id=p.get('fact_id'))
                review(analysis,view,policy,execution_id=execution,release=RELEASE,progress=on_point)
                analysis['journal_etapes']=journal.snapshot()
                analysis['core_coverage']=dict(pages_total=len(readings.get('text',[])),
                    visual=readings.get('couverture_visuelle'),inventory=readings.get('inventaire_clauses'),
                    native_character_coverage=readings.get('core_native_inventory',{}).get('native_character_coverage'),
                    examination_units=len(analysis['lignes']),
                    parent_blocks_split=len(analysis.get('core_atomization',{}).get('parents',[])),exhaustive=False)
                progress(ident,'report')
            def before_render(view,analysis,kind):
                # Save complete evidence before either renderer can fail. No
                # report success is inferred from this intermediate snapshot.
                atomic_json(JOBS/ident/'pre_render.json',dict(
                    version=VERSION,revision=analysis.get('revision'),
                    analyse=analysis,lectures=view,provenance_sources=plan,
                    validation_juriste_realisee=False,format_rapport=kind,
                    rendering_pending=True,execution_id=execution,release=RELEASE))
            result=report(body,article_reviewer=reviewer,workflow_version=VERSION,before_render=before_render,
                          pdf_renderer=summary_pdf,html_renderer=summary_html)
            emit('report','done',duration_ms=round((time.monotonic()-STATES[ident]['phase_started'])*1000))
            emit('analyse','done',job_id=ident)
            result['preuves_json']['analyse']['journal_etapes']=journal.snapshot()
            result['preuves_json']['analyse']['report_origin']=dict(workflow_id=WORKFLOW,local_execution_id=execution)
            atomic_json(JOBS/ident/'report.json',result)
            update(ident,status='done',stage='done',finished_at=now(),summary=result['synthese'])
        except Exception as exc:
            emit('analyse','error',message=str(exc)[:500]);update(ident,status='error',error=f'{type(exc).__name__}: {str(exc)[:500]}',finished_at=now())

def submit(payload):
    if not isinstance(payload,dict):raise ValueError('Requête JSON attendue.')
    execution=str(payload.get('execution_id',''))
    if not re.fullmatch(r'[1-9][0-9]{0,14}',execution):raise ValueError('Exécution n8n requise.')
    meta=payload.get('metadata',{})
    if not isinstance(meta,dict) or not isinstance(meta.get('city'),str) or len(meta['city'])<2:raise ValueError('Commune requise.')
    from datetime import date
    date.fromisoformat(meta['reference'])
    if meta.get('mode') not in ('auto','local','full','reading') or meta.get('vision') not in ('vision','ocr'):raise ValueError('Mode invalide.')
    raw=base64.b64decode(payload.get('file_base64',''),validate=True)
    if not 0<len(raw)<=25*1024*1024:raise ValueError('Fichier vide ou supérieur à 25 Mo.')
    name=payload.get('filename')
    if not isinstance(name,str) or Path(name).name!=name:raise ValueError('Nom de fichier invalide.')
    identity() # fail before queueing, not after OCR
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    with LOCK:
        for s in STATES.values():
            if s['execution_id']==execution:
                if s['request_sha256']!=fingerprint:raise ValueError('Autre requête pour cette exécution.')
                return s
        if any(s['status'] in ('queued','running') for s in STATES.values()):raise ValueError('Une analyse Core est déjà en cours.')
        ident=uuid.uuid4().hex;(JOBS/ident).mkdir(parents=True)
        atomic_json(JOBS/ident/'request.json',payload)
        STATES[ident]=dict(id=ident,execution_id=execution,web_job_id=meta.get('web_job_id'),status='queued',stage='queued',
            created_at=now(),request_sha256=fingerprint,release=RELEASE)
        update(ident);POOL.submit(execute,ident,copy.deepcopy(payload));return STATES[ident]

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def allowed(self):return not self.headers.get('Origin') and self.headers.get('Host') in (f'127.0.0.1:{PORT}',f'localhost:{PORT}')
    def send(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if not self.allowed():return self.send(403,{'error':'Appels locaux uniquement.'})
        if self.path=='/health':
            try:model=identity();ready=True
            except Exception:model=None;ready=False
            return self.send(200,dict(service=SERVICE,version=HEALTH_VERSION,model=MODEL,ready=ready,release=RELEASE,
                active=sum(s['status'] in ('queued','running') for s in STATES.values())))
        match=re.fullmatch(r'/web-jobs/([a-f0-9]{32})',self.path)
        if match:
            found=[s for s in STATES.values() if s.get('web_job_id')==match[1]]
            return self.send(200,found[-1] if found else {})
        match=re.fullmatch(r'/jobs/([a-f0-9]{32})(/report)?',self.path)
        if not match or match[1] not in STATES:return self.send(404,{'error':'Analyse inconnue.'})
        state=STATES[match[1]]
        if match[2]:
            if state['status']!='done':return self.send(409,{'error':state.get('error','Analyse non terminée.')})
            return self.send(200,json.loads((JOBS/match[1]/'report.json').read_text(encoding='utf-8')))
        return self.send(200,state)
    def do_POST(self):
        if not self.allowed() or self.path!='/jobs':return self.send(403,{'error':'Appels locaux uniquement.'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<36_000_000:raise ValueError('Requête trop volumineuse.')
            self.connection.settimeout(30);self.send(202,submit(json.loads(self.rfile.read(length))))
        except Exception as exc:self.send(400,{'error':str(exc)[:500]})

def configure_clair(runtime):
    """Explicit profile for a distinct worker; default Core remains unchanged."""
    global ROOT,PORT,JOBS,SERVICE,HEALTH_VERSION,WORKFLOW
    ROOT=Path(runtime).resolve()
    PORT=8776;SERVICE='slm-cctp-clair';HEALTH_VERSION='CLAIR1';WORKFLOW='SlmCctpClairV1'
    JOBS=ROOT/'webapp/.local/core_jobs'
    reader.OUT=ROOT/'ocr'
    reader.MAX_PAGES=15
    (reader.OUT/'tmp').mkdir(parents=True,exist_ok=True)
    import slm_core_engine
    slm_core_engine.WORKFLOW=WORKFLOW


def main(release):
    global RELEASE
    RELEASE=release;JOBS.mkdir(parents=True,exist_ok=True)
    for p in JOBS.glob('*/state.json'):
        state=json.loads(p.read_text(encoding='utf-8'));STATES[state['id']]=state
        if state['status'] in ('queued','running'):update(state['id'],status='error',error='Service interrompu ; lancer une nouvelle analyse explicite.')
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
