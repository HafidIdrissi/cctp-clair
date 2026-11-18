"""Exact qualitative legal sentence candidates, with their complete parent.

This is a retrieval boundary, not an applicability or compliance decision.
Numeric and explicitly conditional paragraphs keep their existing boundaries.
"""
import copy,hashlib,re
from slm_core_atoms import sentence_spans
from slm_v6_semantic_review import complete_law_quote,priority_passages


def expand(index):
    result={};trace=[]
    for key,item in index.items():
        text=item.get('citation','')
        conditional=re.match(r'^\s*(?:lorsque|quand|si\b|en cas)',text,re.I)
        numeric=re.search(r'\b\d+(?:[.,]\d+)?\s*(?:mm|cm|m|%|millimètres?|centimètres?|mètres?)\b',text,re.I)
        units=list(sentence_spans(text)) if item.get('kind')=='article' and not conditional and not numeric else []
        if not 2<=len(units)<=4 or any(not complete_law_quote(text[a:b],text) for a,b in units):
            result[key]=copy.deepcopy(item);continue
        ids=[]
        for i,(left,right) in enumerate(units,1):
            child=key+'S'+str(i);ids.append(child)
            result[child]=dict(copy.deepcopy(item),citation=text[left:right],core_legal_parent=dict(
                id=key,citation=text,sha256=hashlib.sha256(text.encode()).hexdigest(),start=left,end=right))
        trace.append(dict(parent_id=key,source_id=item['source_id'],citation=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),units=ids,
            scope='Phrases candidates ; contexte intégral obligatoire pour la pertinence, le champ et les exceptions.'))
    return result,trace


def route(index,parent_candidates,quote):
    """Rank parents first, so a short exact rule does not lose its source slot."""
    selected={key:index[key] for key in parent_candidates}
    children,trace=expand(selected);ordered=[]
    for parent in parent_candidates:
        group={k:v for k,v in children.items() if k==parent or v.get('core_legal_parent',{}).get('id')==parent}
        ranked=priority_passages(quote,group)
        ordered.extend(ranked+[k for k in group if k not in ranked])
    return {**index,**children},ordered,trace
