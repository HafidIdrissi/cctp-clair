"""Criterion-level PISTE discovery after local relevance fails.

Credentials stay in n8n. Only short search keywords, a date and article IDs
leave the computer. Every request/response, rejection and budget is traced.
Sources are candidates, never compliance evidence without the usual checks.
"""
import copy
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import urllib.request

from slm_v5_article_review import source_valid

ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:5678/webhook/slm-piste-recovery-v6'
LOCK=threading.Lock()
LAST_CALL=0.0
MAX_CALLS=400


def transport(payload):
    global LAST_CALL
    config=json.loads((ROOT/'webapp/.local/config.json').read_text(encoding='utf-8'))
    with LOCK:
        time.sleep(max(0,1.1-(time.monotonic()-LAST_CALL)))
        LAST_CALL=time.monotonic()
        request=urllib.request.Request(URL,data=json.dumps(payload).encode(),headers={
            'Content-Type':'application/json',config['header_name']:config['header_value']})
        with urllib.request.urlopen(request,timeout=100) as response:
            raw=response.read(4_000_001)
        if len(raw)>4_000_000:raise ValueError('Réponse PISTE trop volumineuse')
        value=json.loads(raw)
        if isinstance(value,list) and len(value)==1:value=value[0]
        if not isinstance(value,dict) or value.get('request')!=payload or 'response' not in value:
            raise ValueError('Réponse du relais PISTE non liée à la requête')
        return value


def candidates(response,fond):
    result=[]
    for hit in response.get('results',[]) or []:
        titles=hit.get('titles') or []
        title=next((t.get('title') for t in titles if t.get('title')),None)
        for section in hit.get('sections',[]) or []:
            for item in section.get('extracts',[]) or []:
                if re.fullmatch(r'LEGIARTI\d{12}',str(item.get('id',''))):
                    result.append(dict(id=item['id'],numero=item.get('num') or item.get('title'),titre=title,fond=fond,
                                       extrait=' '.join(item.get('values') or [])[:1500]))
    return result


def epoch_date(value):
    if type(value) not in (int,float):raise ValueError('Date PISTE absente')
    return datetime.fromtimestamp(value/1000,tz=timezone.utc).date().isoformat()


def normalize(response,candidate,reference):
    a=response.get('article') or {}
    if a.get('id')!=candidate['id']:raise ValueError('Identifiant article différent')
    if re.sub(r'\s+','',str(a.get('num','')))!=re.sub(r'\s+','',str(candidate.get('numero',''))):
        raise ValueError('Numéro article différent')
    start=epoch_date(a.get('dateDebut'));end=epoch_date(a.get('dateFin'))
    if not start<=reference<end:raise ValueError('Version hors date demandée')
    if not candidate.get('titre'):raise ValueError('Titre officiel absent')
    text=a.get('texte')
    source=dict(id=a['id'],numero=a['num'],nom_code=candidate['titre'],texte=text,
        date_debut=start,date_fin_exclusive=end,date_reference=reference,
        provenance='piste_sandbox',environnement='sandbox',
        source_url=f"https://www.legifrance.gouv.fr/{'codes' if candidate['fond']=='CODE_DATE' else 'loda'}/article_lc/{a['id']}/{reference}",
        freshness_confirmed=True,verified_through=date.today().isoformat(),corpus_complete=False,
        text_sha256=hashlib.sha256(str(text).encode()).hexdigest())
    if not source_valid(source,reference):raise ValueError('Source officielle datée invalide')
    # Preserve returned provenance without changing legacy comparison inputs.
    # Only Core forwards these parent headings to its scope verification.
    from slm_core_context import from_piste
    context=from_piste(a,reference)
    if context:
        source['codification']=context
        source['codification_context_raw']=copy.deepcopy(a['context'])
    return source


def request_traced(payload,info,trace,call=None):
    tick=time.monotonic()
    call=call or transport
    cache=info.setdefault('_piste_cache',{})
    usage=info.setdefault('piste_usage',dict(calls=0,cache_hits=0,errors=0,execution_ids=[]))
    key=json.dumps(payload,sort_keys=True)
    entry=dict(request=payload,started_at=datetime.now(timezone.utc).isoformat())
    trace.setdefault('calls',[]).append(entry)
    try:
        if key in cache:
            value=copy.deepcopy(cache[key]);entry['cache_hit']=True;usage['cache_hits']+=1
        else:
            if usage['calls']>=MAX_CALLS:
                entry['status']='budget_exceeded';return None
            usage['calls']+=1
            value=call(payload)
            if value.get('request')!=payload or not isinstance(value.get('response'),dict):raise ValueError('Réponse non liée à la requête')
            if value['response'].get('error'):
                entry['api_error']=value['response']['error'];raise ValueError('Erreur API PISTE')
            cache[key]=copy.deepcopy(value)
        entry.update(status='completed',execution_id=value.get('execution_id'),response=value['response'])
        if value.get('execution_id') not in usage['execution_ids']:usage['execution_ids'].append(value.get('execution_id'))
        return value['response']
    except Exception as exc:
        usage['errors']+=1;entry.update(status='error',error=type(exc).__name__)
        return None
    finally:
        entry['finished_at']=datetime.now(timezone.utc).isoformat()
        if info.get('pipeline')=='core':
            from slm_m3_journal import emit
            emit('piste_documentaire','done' if entry.get('status')=='completed' else 'error',
                fact_id=info.get('_m3_fact_id'),request=payload,execution_id=entry.get('execution_id'),
                cache_hit=entry.get('cache_hit',False),duration_ms=round((time.monotonic()-tick)*1000),
                result_status=entry.get('status'),error=entry.get('error'),actual_call=not entry.get('cache_hit',False) and entry.get('status')!='budget_exceeded')


def recover(queries,reference,info,*,allowed=False,call=None,existing_ids=()):
    date.fromisoformat(reference)
    trace=dict(method='piste_apres_pertinence_locale_insuffisante',allowed=allowed,calls=[],
               accepted_ids=[],exclusions=[],limits=dict(max_queries=2,fonds=['CODE_DATE','LODA_DATE'],
               max_articles=6,max_calls_per_analysis=MAX_CALLS,exhaustive=False),status='not_allowed')
    if not allowed:return dict(sources={},trace=trace)
    call=call or transport
    sources={};known=set(existing_ids); found={}
    def request(payload):
        return request_traced(payload,info,trace,call)
    for query in list(dict.fromkeys(queries))[:2]:
        if not isinstance(query,str) or not 3<=len(query)<=100 or not re.fullmatch(r'[^\W\d_]+(?:[ ’\'-][^\W\d_]+){0,11}',query):
            trace['exclusions'].append(dict(query=query,reason='mots_cles_invalides'));continue
        for fond in ('CODE_DATE','LODA_DATE'):
            response=request(dict(operation='search',query=query,date=reference,fond=fond))
            if response is None:continue
            for item in candidates(response,fond):
                if item['id'] not in known:found.setdefault(item['id'],item)
    trace['candidates']=list(found.values())
    for candidate in list(found.values())[:6]:
        response=request(dict(operation='article',id=candidate['id']))
        if response is None:continue
        try:
            source=normalize(response,candidate,reference)
            sources[source['id']]=source
        except (ValueError,TypeError,OverflowError,OSError) as exc:
            trace['exclusions'].append(dict(id=candidate['id'],reason=str(exc)))
    trace['accepted_ids']=list(sources)
    trace['status']='candidates_found' if sources else 'no_candidate'
    if any(c['status'] in ('error','budget_exceeded') for c in trace['calls']):trace['search_incomplete']=True
    return dict(sources=sources,trace=trace)
