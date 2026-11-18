"""Capture real DILA search arguments/results, never reconstruct old requests."""
import time
import re
import unicodedata
from datetime import datetime,timezone
from slm_m3_journal import emit


def search(store,query,reference,*,code=None,article=None,limit=5,fact_id=None,origin='mots_de_la_clause'):
    tokens=re.findall(r'[^\W_]+',unicodedata.normalize('NFKC',query),re.UNICODE)[:64]
    audit=dict(version=1,recorded=True,at=datetime.now(timezone.utc).isoformat(),fact_id=fact_id,
        origin=origin,request=dict(query=query,code=code,article=article,date_reference=reference,limit=limit),
        method='reference_ciblee' if article and code else 'recherche_lexicale',
        matching='AND' if tokens else None,fts_terms=tokens,
        ranking='BM25' if tokens else 'identifiant',
        temporal_filter='date_debut <= date_reference < date_fin ; fin absente admise',
        uncertain_versions_excluded=True,empty_text_excluded=True,
        results=[],selection_established=False)
    tick=time.monotonic()
    try:
        rows=store.search(query,reference,code=code,article=article,limit=limit)
        audit.update(status='done',returned_count=len(rows),limit_reached=len(rows)>=limit,
            results=[{k:r.get(k) for k in ('id','numero','nom_code','date_debut','date_fin_exclusive',
                'version_ambiguous','temporal_uncertain')} for r in rows])
        return rows,audit
    except Exception as exc:
        audit.update(status='error',error=type(exc).__name__)
        raise
    finally:
        audit['duration_ms']=round((time.monotonic()-tick)*1000)
        emit('recherche_dila_locale',audit['status'],fact_id=fact_id,search_audit=audit)
