"""Date-bound codification context from the exact imported DILA XML bytes."""
import hashlib,json,re,sqlite3,zlib,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import date
from contextlib import closing,contextmanager
from slm_v6_focused_review import ExistingDilaReader

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'RAG_RER_V/dila/.local/source_contexts.sqlite'


def active(start,end,reference):
    if not all(isinstance(x,str) for x in (start,reference)) or end is not None and not isinstance(end,str):return False
    try:
        return bool(date.fromisoformat(start)<=date.fromisoformat(reference)
            and (not end or end.startswith('2999') or date.fromisoformat(reference)<date.fromisoformat(end)))
    except (ValueError,TypeError):return False


def from_xml(raw,source,reference):
    sha=hashlib.sha256(raw).hexdigest()
    if sha!=source.get('sha256') or len(raw)>16*1024*1024 or b'\x00' in raw or re.search(br'<!ENTITY|<!DOCTYPE[^>]*\[',raw,re.I):return None
    try:tree=ET.fromstring(raw)
    except ET.ParseError:return None
    if tree.findtext('META/META_COMMUN/ID')!=source['id']:return None
    parents=[];matched=False;complete=True
    for context in tree.findall('CONTEXTE/TEXTE'):
        if source.get('text_id') and context.get('cid')!=source['text_id']:continue
        titles=[t for t in context.findall('TITRE_TXT') if active(t.get('debut'),t.get('fin'),reference)]
        if not titles:continue
        matched=True
        for heading in context.findall('.//TITRE_TM'):
            if not heading.get('debut') or not heading.get('fin'):complete=False;continue
            if not active(heading.get('debut'),heading.get('fin'),reference):complete=False;continue
            item=dict(id=heading.get('id'),title=' '.join(''.join(heading.itertext()).split()),
                date_debut=heading.get('debut'),date_fin_exclusive=None if heading.get('fin','').startswith('2999') else heading.get('fin'))
            if item not in parents:parents.append(item)
    if not matched or not complete:return None
    return dict(verified=True,origin='dila_xml_local',article_id=source['id'],date_reference=reference,
        source_xml_sha256=sha,parents=parents,source_file=source.get('source_file'),
        limitation='Rubriques de codification datées, pas un verdict d’applicabilité au projet ni une preuve d’absence de renvois.')


def from_piste(article,reference):
    context=article.get('context') or {};parents=[]
    if not isinstance(context,dict) or not isinstance(context.get('titreTxt'),list) or not context['titreTxt']:return None
    if not isinstance(context.get('titresTM',[]),list):return None
    groups={}; discarded=[]
    for heading in context.get('titresTM',[]):
        if not isinstance(heading,dict):return None
        if not heading.get('debut') or not heading.get('fin'):return None
        try:
            if date.fromisoformat(heading['debut'])>=date.fromisoformat(heading['fin']):return None
        except (ValueError,TypeError):return None
        # PISTE may return historical versions of the same hierarchy slot.
        # Every slot needs exactly one active version, not every version active.
        slot=heading.get('xPath') or heading.get('cid') or heading.get('id')
        if not slot:return None
        groups.setdefault(slot,[]).append(heading)
    selected=[]
    for slot,versions in groups.items():
        current=[h for h in versions if active(h['debut'],h['fin'],reference)]
        if len(current)!=1:return None
        selected.extend(current)
        discarded.extend(dict(id=h.get('id'),debut=h['debut'],fin=h['fin'],slot=slot) for h in versions if h is not current[0])
    for heading in selected:
        parents.append(dict(id=heading.get('id'),title=heading.get('titre','').strip(),date_debut=heading['debut'],
            date_fin_exclusive=None if heading['fin'].startswith('2999') else heading['fin']))
    if not any(isinstance(h,dict) and active(h.get('debut'),h.get('fin'),reference) for h in context['titreTxt']):return None
    return dict(verified=True,origin='piste_article_context',article_id=article['id'],date_reference=reference,parents=parents,
        historical_versions_excluded=discarded,
        response_context_sha256=hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        limitation='Contexte renvoyé avec l’article ; application au dossier et renvois restent à vérifier.')


def initialize(path=CACHE):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS raw_contexts(article_id TEXT,xml_sha TEXT,raw_xml BLOB,PRIMARY KEY(article_id,xml_sha))')
        db.commit()


def store(raw,source,path=CACHE):
    if hashlib.sha256(raw).hexdigest()!=source.get('sha256'):raise ValueError('XML différent du document importé')
    initialize(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('INSERT OR REPLACE INTO raw_contexts VALUES(?,?,?)',(source['id'],source['sha256'],zlib.compress(raw)))
        db.commit()


def enrich(source,reference,path=CACHE):
    # Rebuild derived evidence. A stored verified=True flag is not a proof.
    source={k:v for k,v in source.items() if k!='codification'}
    if source.get('provenance')=='piste_sandbox' and source.get('codification_context_raw'):
        context=from_piste(dict(id=source['id'],context=source['codification_context_raw']),reference)
        return {**source,'codification':context} if context else source
    if not Path(path).exists() or not source.get('sha256'):return source
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT raw_xml FROM raw_contexts WHERE article_id=? AND xml_sha=?',(source['id'],source['sha256'])).fetchone()
    if not row:return source
    unpack=zlib.decompressobj()
    try:raw=unpack.decompress(row[0],16*1024*1024+1)
    except zlib.error:return source
    if len(raw)>16*1024*1024 or unpack.unconsumed_tail or not unpack.eof:return source
    context=from_xml(raw,source,reference)
    return {**source,'codification':context} if context else source


class ContextDilaReader(ExistingDilaReader):
    @contextmanager
    def _connect(self):
        db=sqlite3.connect(Path(self.db_path).resolve().as_uri()+'?mode=ro',uri=True,timeout=60)
        db.row_factory=sqlite3.Row
        try:yield db
        finally:db.close()

    def search(self,query,reference_date,code=None,article=None,limit=10):
        return [enrich(s,reference_date) for s in super().search(query,reference_date,code,article,limit)]
