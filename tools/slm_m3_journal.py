"""Per-execution local journal; never exports credentials or image bytes."""
import json
import re
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

ROOT=Path(__file__).resolve().parents[1]/'webapp/.local/m3_journals'
CURRENT=ContextVar('m3_journal',default=None)
LOCK=threading.RLock()
SENSITIVE=re.compile(r'authorization|cookie|credential|secret|token|api.?key|csrf|header.?value',re.I)

def clean(value):
    if isinstance(value,dict):
        return {k:('[Masqué]' if SENSITIVE.search(k) else '[Binaire omis]' if k in ('images','binary') or 'base64' in k.lower() else clean(v)) for k,v in value.items() if k not in ('headers','headerParameters')}
    if isinstance(value,list):return [clean(v) for v in value]
    if isinstance(value,str):return re.sub(r'(?i)Bearer\s+[A-Za-z0-9._~+/=-]+','Bearer [Masqué]',value)
    return value

class Journal:
    def __init__(self,execution,root=ROOT):
        if not re.fullmatch(r'[1-9][0-9]{0,14}',str(execution)):raise ValueError('Exécution du journal invalide')
        self.path=Path(root)/str(execution)/'events.jsonl'
        self.path.parent.mkdir(parents=True,exist_ok=True)

    def emit(self,stage,status,**details):
        event=clean(dict(at=datetime.now(timezone.utc).isoformat(),stage=stage,status=status,**details))
        with LOCK:
            with self.path.open('a',encoding='utf-8') as f:f.write(json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n')
        return event

    def snapshot(self):
        with LOCK:
            events=[json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines() if line.strip()] if self.path.exists() else []
        return dict(version=1,events=events,scope='Événements réellement enregistrés ; le journal ne garantit pas une extraction exhaustive.')

def emit(stage,status,**details):
    journal=CURRENT.get()
    if journal:return journal.emit(stage,status,**details)

@contextmanager
def bind(journal):
    token=CURRENT.set(journal)
    try:yield journal
    finally:CURRENT.reset(token)

@contextmanager
def stage(name,**details):
    tick=time.monotonic();emit(name,'running',**details)
    try:
        yield
    except Exception as exc:
        emit(name,'error',duration_ms=round((time.monotonic()-tick)*1000),error=type(exc).__name__,message=str(exc)[:400],**details)
        raise
    else:emit(name,'done',duration_ms=round((time.monotonic()-tick)*1000),**details)
