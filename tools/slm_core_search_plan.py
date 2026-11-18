"""Keep a distinctive literal anchor when a small model drops the key term.

Corpus word frequencies rank discovery queries only. They never establish a
legal rule, an exception, applicability or compliance. No embedding model.
"""
import math,re
from slm_v6_retrieval_plan import plan as model_plan
from slm_v6_source_recovery import normalized,terms,STOP
from slm_core_context import ContextDilaReader
from slm_m3_journal import emit

GENERIC=STOP | set('interdit interdits interdite interdites exige exigee exigees exigeant respecter respectent comprend comprennent prevoit prevoyant applicable applicables present presente fixe fixee fixes fixees mention indique indiquee aucun aucune toute tout'.split())


def frequencies(words, reader=None):
    reader=reader or ContextDilaReader()
    with reader._connect() as db:
        total=db.execute('SELECT count(*) FROM articles').fetchone()[0]
        values={word:db.execute('SELECT count(*) FROM articles_fts WHERE articles_fts MATCH ?',('"'+word+'"',)).fetchone()[0] for word in words}
    return max(total,1),values


def anchors(fact,locations=(),frequency_lookup=frequencies):
    quote=fact.get('citation_visible','');allowed=set(terms(quote,locations))-GENERIC
    words=[]
    for match in re.finditer(r'[^\W\d_]+',quote,re.UNICODE):
        word=normalized(match.group())
        # Conservative data minimisation: capitalised names and acronyms are
        # left to the existing model plan, not sent by this literal fallback.
        if word in allowed and match.group()==match.group().lower():
            words.append((word,match.start(),match.end()))
    trace=dict(method='ancre_litterale_classee_par_frequence',candidates=[],
        scope='Requête de découverte, pas une règle ni une preuve de pertinence.',exhaustive=False)
    if len(words)<2:return trace
    try:total,counts=frequency_lookup(list(dict.fromkeys(w[0] for w in words)))
    except Exception as exc:
        trace['error']=type(exc).__name__;return trace
    for left,right in zip(words,words[1:]):
        if left[0]==right[0]:continue
        query=left[0]+' '+right[0]
        if query in [p['query'] for p in trace['candidates']]:continue
        rarity=sum(math.log((total+1)/(counts[word]+1)) for word in (left[0],right[0]))
        # A rare filler beyond a negation must not displace a tighter phrase.
        # This ranks discovery only; negations stay intact in the control proof.
        gap_words=len(re.findall(r'[^\W\d_]+',quote[left[2]:right[1]],re.UNICODE))
        score=rarity/(1+gap_words)
        trace['candidates'].append(dict(query=query,terms=[left[0],right[0]],
            anchor=quote[left[1]:right[2]],start=left[1],end=right[2],
            document_frequencies={word:counts[word] for word in (left[0],right[0])},score=round(score,6),
            gap_words=gap_words,rarity_score=round(rarity,6),
            purpose='ancre_litterale_discriminante',applicability_established=False))
    trace['candidates'].sort(key=lambda p:(-p['score'],p['start']))
    trace['corpus_articles']=total
    return trace


def plan(fact,caller,info,locations=(),*,context=None):
    qualified=info.get('core_obligations',{}).get(fact.get('id'))
    if qualified:
        from slm_core_obligations import query_plan
        trace=query_plan(fact,qualified,caller,info,locations)
        info['exchanges'].append(dict(stage='plan_recherche_general_core',status='derived',fact_id=fact.get('id'),model_call=False,resolved_evidence=trace))
        emit('plan_recherche_general_core','done',fact_id=fact.get('id'),queries=[q['query'] for q in trace['accepted']],model_call=False)
        return trace
    proposed=model_plan(fact,caller,info,locations,context=context)
    lexical=anchors(fact,locations)
    selected=lexical['candidates'][:1]
    for candidate in proposed['accepted']:
        if len(selected)>=2:break
        if candidate['query'] not in [q['query'] for q in selected]:selected.append(candidate)
    if not selected:selected=proposed['accepted']
    trace=dict(method='plan_modele_et_ancre_litterale_core',accepted=selected,
        model_plan=proposed,literal_anchor=lexical,
        limitation='Au plus deux recherches, dont une ancre littérale distinctive lorsqu’elle existe. La pertinence des résultats reste à vérifier ; aucun article ni seuil n’est inventé.')
    info['exchanges'].append(dict(stage='plan_recherche_general_core',status='derived',fact_id=fact.get('id'),model_call=False,
        resolved_evidence=trace))
    emit('plan_recherche_general_core','done',fact_id=fact.get('id'),queries=[q['query'] for q in selected],model_call=False)
    return trace
