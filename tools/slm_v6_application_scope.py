"""Resolve explicit application references before allowing a legal comparison.

Only references literally present in the selected article are queried. This is
not a complete legal dependency parser. Missing or ambiguous references cannot
be treated as established application conditions by a model's boolean answer.
"""
import re
import unicodedata
from slm_v5_article_review import source_valid
from slm_v6_piste_recovery import request_traced,candidates,normalize

REF=re.compile(r"(?:en application|au sens)\s+de\s+l[’']article\s+([LRD]\s*\.?\s*\d+(?:-\d+){1,4})",re.I)

def norm(value):
    value=unicodedata.normalize('NFKD',str(value or '')).lower().replace('’',"'")
    return ''.join(c for c in value if not unicodedata.combining(c) and c.isalnum())

def references(source,text):
    result=[]
    for match in REF.finditer(text):
        number=re.sub(r'[.\s]','',match[1]).upper()
        tail=text[match.end():match.end()+180]
        # A different named code must never silently resolve in the source code.
        other=re.match(r'\s+du\s+(code\s+[^,;.\n]+)',tail,re.I)
        code=other[1].strip().capitalize() if other else source.get('nom_code','')
        entry=dict(numero=number,code=code,citation=match[0])
        if entry not in result:result.append(entry)
    return result

def resolve(source,text,reference,pool,info,*,lookup,allowed=False,call=None):
    trace=dict(method='renvois_explicites_application',source_id=source['id'],references=[],calls=[],
               scope='Renvois explicites « en application de » et « au sens de » ; contrôle non exhaustif.',missing=[])
    sources={}
    for ref in references(source,text)[:4]:
        item=dict(ref,source_ids=[],status='missing');trace['references'].append(item)
        def matching(s):
            return (norm(s.get('numero'))==norm(ref['numero']) and norm(s.get('nom_code'))==norm(ref['code'])
                    and source_valid(s,reference))
        found={s['id']:s for s in pool.values() if matching(s)}
        if not found:
            try:
                for s in lookup('',reference,code=ref['code'],article=ref['numero'],limit=3):
                    if matching(s):found[s['id']]=s
                item['local_search']='completed'
            except Exception as exc:item['local_search']=type(exc).__name__
        if not found and allowed and ref['code'].startswith('Code '):
            response=request_traced(dict(operation='reference',code=ref['code'],numero=ref['numero'],date=reference),info,trace,call)
            accepted=[]
            for candidate in candidates(response or {},'CODE_DATE'):
                if norm(candidate.get('titre'))==norm(ref['code']) and norm(candidate.get('numero'))==norm(ref['numero']):
                    if candidate['id'] not in [c['id'] for c in accepted]:accepted.append(candidate)
            # Multiple current versions must be resolved, never choose one at random.
            if len(accepted)==1:
                response=request_traced(dict(operation='article',id=accepted[0]['id']),info,trace,call)
                try:
                    s=normalize(response or {},accepted[0],reference)
                    if matching(s):found[s['id']]=s
                except (ValueError,TypeError,OverflowError,OSError) as exc:item['online_error']=type(exc).__name__
            elif len(accepted)>1:item['status']='ambiguous'
        item['source_ids']=list(found)
        if len(found)==1:
            item['status']='resolved';sources.update(found)
        elif len(found)>1:item['status']='ambiguous'
        if item['status']!='resolved':trace['missing'].append(ref)
    if len(references(source,text))>4:trace['missing'].append(dict(reason='limite_renvois',numero='renvois supplémentaires'))
    trace['complete']=not trace['missing']
    return dict(sources=sources,trace=trace)
