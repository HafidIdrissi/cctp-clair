"""Experimental, evidence-bound semantic review. V5 never imports this reviewer.

Separate quotations need to exist in their own documents; they do not need to
have the same wording. A second pass tests the proposed interpretation. Neither
pass constitutes a legal certification or evidence of global completeness.
"""
import hashlib
import json
import math
import re
import time
import unicodedata
import urllib.request
import urllib.error

from slm_v5_article_review import MODEL, source_valid
from slm_v5_policy import invalid_fact
from slm_v6_structure import structural_context_reason
from slm_v6_duplicates import consolidate as consolidate_native_duplicates
from slm_v6_visual_evidence import verified as visual_verified, evidence_view, prepare as prepare_visual

CATEGORIES = ('obligation_contractuelle', 'prescription_technique', 'recommandation', 'contexte', 'indetermine')
OUTCOMES = ('respecte', 'ecart', 'indetermine', 'information')
PROPOSAL_STAGES = ('comparaison_semantique', 'reformulation_comparaison')
CLASSIFICATION_STAGES = ('classification_documentaire', 'arbitrage_documentaire')
MAX_CONTEXT = 42000
LABELS = {
    'lecture_valide': 'Citation native exacte ou annotation image vérifiée avec ses preuves OCR',
    'statut_prescriptif': 'Statut prescriptif du passage dans l’opération',
    'source_officielle_datee': 'Identité et version datée du texte officiel contrôlées',
    'citations_exactes': 'Citations du dossier et de l’article retrouvées séparément',
    'preuves_conditions': 'Preuves des conditions d’application et exceptions retrouvées',
    'portee_explicite': 'Critère précis, objet et limites explicités',
    'contre_lecture': 'Deuxième lecture concordante, avec vérification des preuves',
}
from slm_v6_prompts import CLASSIFY, PROPOSE, AUDIT, RESOLVE, REVISE, REFERENCE_INSTRUCTIONS


def canonical(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(text or ''))).strip()


def exact(quote, text):
    return isinstance(quote, str) and len(canonical(quote)) >= 12 and canonical(quote) in canonical(text)


def complete_law_quote(quote, text):
    if not exact(quote,text): return False
    q=canonical(quote); t=canonical(text); start=t.find(q); end=start+len(q)
    return ((start==0 or t[:start].rstrip()[-1:] in '.;:!?)')
            and (end==len(t) or q[-1:] in '.;!?' or t[end:end+1] in '.;!?'))


def page_quote(evidence, pages, key='citation'):
    return (isinstance(evidence, dict) and type(evidence.get('page')) is int
            and 1 <= evidence['page'] <= len(pages) and exact(evidence.get(key), pages[evidence['page']-1]))


def schema(stage):
    string = {'type': 'string'}
    evidence = dict(type='object', properties=dict(page={'type': 'integer'}, citation=string), required=['page', 'citation'], additionalProperties=False)
    if stage in CLASSIFICATION_STAGES:
        props = dict(id=string, raison={'type':'string','maxLength':400}, prescriptif={'type':'boolean'},
            mixte={'type':'boolean'}, categorie={'type':'string','enum':list(CATEGORIES)})
    elif stage in PROPOSAL_STAGES:
        condition = dict(type='object', properties=dict(article_citation=string, page={'type': 'integer'}, citation_cctp=string), required=['article_citation', 'page', 'citation_cctp'], additionalProperties=False)
        props = dict(id=string, categorie={'type':'string','enum':list(CATEGORIES)},
            outcome={'type':'string','enum':list(OUTCOMES)}, source_id=string, critere=string,
            obligation=string, citation_cctp=string, page={'type':'integer'}, application=evidence,
            conditions={'type':'array','items':condition}, raison=string,
            manques={'type':'array','items':string})
    else:
        props = dict(id=string, categorie={'type':'string','enum':list(CATEGORIES)},
            outcome={'type':'string','enum':list(OUTCOMES)}, source_id=string,
            meme_objet={'type':'boolean'}, applicable={'type':'boolean'}, complet={'type':'boolean'},
            exceptions_resolues={'type':'boolean'}, sans_contradiction={'type':'boolean'},
            critere_fidele={'type':'boolean'}, citation_dossier=evidence, citation_article=string,
            raison=string, manques={'type':'array','items':string})
    return dict(type='object',properties=props,required=list(props),additionalProperties=False)


def response_valid(value, spec):
    """Validate model output, including injected callers; JSON mode is no guarantee."""
    kind=spec.get('type')
    if kind=='object':
        return (isinstance(value,dict) and set(value)==set(spec['required'])
            and all(response_valid(v,spec['properties'][k]) for k,v in value.items()))
    if kind=='array': return isinstance(value,list) and len(value)<=32 and all(response_valid(v,spec['items']) for v in value)
    if kind=='string': return isinstance(value,str) and len(value)<=min(6000,spec.get('maxLength',6000)) and ('enum' not in spec or value in spec['enum'])
    if kind=='integer': return type(value) is int
    if kind=='boolean': return type(value) is bool
    return False


def reference_schema(stage, index=None, point_id=None):
    string={'type':'string'}
    if stage in CLASSIFICATION_STAGES:
        result=schema(stage)
        if point_id is not None: result['properties']['id']={'type':'string','enum':[point_id]}
        return result
    if stage in PROPOSAL_STAGES:
        condition=dict(type='object',properties=dict(article_id=string,dossier_id=string),required=['article_id','dossier_id'],additionalProperties=False)
        props=dict(id=string,categorie={'type':'string','enum':list(CATEGORIES)},outcome={'type':'string','enum':list(OUTCOMES)},
            source_id=string,critere=string,obligation_id=string,application_id=string,
            conditions={'type':'array','items':condition},raison=string,manques={'type':'array','items':string})
    else:
        props=dict(id=string,categorie={'type':'string','enum':list(CATEGORIES)},outcome={'type':'string','enum':list(OUTCOMES)},source_id=string,
            **{k:{'type':'boolean'} for k in ('meme_objet','applicable','complet','exceptions_resolues','sans_contradiction','critere_fidele')},
            citation_article_id=string,raison=string,manques={'type':'array','items':string})
    if index is not None:
        article_ids=['']+[k for k,v in index.items() if v.get('kind')=='article']
        dossier_ids=['']+[k for k,v in index.items() if v.get('kind')=='dossier']
        props['source_id']={'type':'string','enum':['']+sorted({v['source_id'] for v in index.values() if v.get('kind')=='article'})}
        props['id']={'type':'string','enum':[point_id]}
        props['obligation_id' if stage in PROPOSAL_STAGES else 'citation_article_id']={'type':'string','enum':article_ids}
        if stage in PROPOSAL_STAGES:
            props['application_id']={'type':'string','enum':dossier_ids}
            props['conditions']['items']['properties']['article_id']={'type':'string','enum':article_ids}
            props['conditions']['items']['properties']['dossier_id']={'type':'string','enum':dossier_ids}
    # Produce documentary evidence and a short justification before selecting
    # the classification/verdict. Early enum choices biased small local models.
    order=(('id','source_id','obligation_id','application_id','conditions','critere','raison','manques','categorie','outcome')
        if stage in PROPOSAL_STAGES else
        ('id','source_id','citation_article_id','meme_objet','applicable','complet','exceptions_resolues',
         'sans_contradiction','critere_fidele','raison','manques','categorie','outcome'))
    props={key:props[key] for key in order}
    return dict(type='object',properties=props,required=list(props),additionalProperties=False)


def priority_passages(quote, index):
    """Generic lexical retrieval within whole articles, no per-topic legal rule."""
    stop=set('avec dans pour entre cette comme plus moins sont etre doit doivent avoir une des les aux sur par pas elle elles leur leurs tous toute toutes est peut afin lorsque sans soit selon sous dont cas ces cet etait sera seront ainsi'.split())
    def words(text):
        plain=''.join(c for c in unicodedata.normalize('NFKD',text.lower()) if not unicodedata.combining(c))
        return {w.rstrip('s') for w in re.findall(r'[a-z]{4,}',plain) if w not in stop}
    passages={k:words(v['citation']) for k,v in index.items() if v.get('kind')=='article'}
    query=words(quote); scores=[]
    for key,tokens in passages.items():
        score=sum(math.log(1+len(passages)/(1+sum(word in other for other in passages.values()))) for word in query & tokens)
        if score: scores.append((score,key))
    return [key for _,key in sorted(scores,key=lambda p:(-p[0],p[1]))[:4]]


def reference_payload(payload):
    """Lossless paragraph references; model cannot manufacture quoted evidence."""
    indexed={k:v for k,v in payload.items() if k!='classification_documentaire'}; index={}
    point=payload['point']
    index['CIBLE']=dict(page=point['page'],citation=point['citation'],kind='dossier')
    indexed['point']=dict(point,citation_id='CIBLE')
    articles=[]
    for ai,article in enumerate(payload['articles']):
        passages=[]
        for pi,paragraph in enumerate(re.split(r'\n+',article['texte'])):
            if not paragraph.strip():continue
            key=f'A{ai+1}P{pi+1}'; index[key]=dict(citation=paragraph.strip(),source_id=article['id'],kind='article')
            passages.append(dict(id=key,texte=paragraph.strip()))
        articles.append({**{k:v for k,v in article.items() if k!='texte'},'passages':passages})
    indexed['articles']=articles
    contexts=[]
    for page in payload['passages_contexte']:
        passages=[]
        for pi,paragraph in enumerate(re.split(r'\n\s*\n',page['texte'])):
            if not paragraph.strip():continue
            key=f'D{page["page"]}P{pi+1}'; index[key]=dict(citation=paragraph.strip(),page=page['page'],kind='dossier')
            passages.append(dict(id=key,texte=paragraph.strip()))
        contexts.append(dict(page=page['page'],passages=passages))
    indexed['passages_contexte']=contexts
    candidates=priority_passages(point['citation'],index)
    target=indexed.pop('point')
    indexed=dict(passages_prioritaires=[dict(id=k,source_id=index[k]['source_id'],texte=index[k]['citation']) for k in candidates],**indexed,point=target)
    # Internal proposal contains exact long quotations. Avoid asking model to
    # recopy them; they're already available in the indexed primary passages.
    if 'proposition' in indexed:
        p=indexed['proposition']
        # A fresh conclusion must not just copy the first verdict or its story.
        indexed['proposition']={k:v for k,v in p.items() if k in ('id','source_id')}
        indexed['proposition']['citation_cctp_id']='CIBLE'
        indexed['proposition']['obligation_id']=next((k for k,v in index.items() if v.get('source_id')==p.get('source_id') and v['citation']==p.get('obligation')),'')
        application=p.get('application') or {}
        indexed['proposition']['application_id']=next((k for k,v in index.items() if v.get('kind')=='dossier' and v.get('page')==application.get('page') and v.get('citation')==application.get('citation')),'')
        indexed['proposition']['conditions']=[dict(
            article_id=next((k for k,v in index.items() if v.get('source_id')==p.get('source_id') and v['citation']==c.get('article_citation')),''),
            dossier_id=next((k for k,v in index.items() if v.get('kind')=='dossier' and v.get('page')==c.get('page') and v.get('citation')==c.get('citation_cctp')),'')) for c in p.get('conditions',[])]
    return indexed,index


def hydrate(output, index, stage):
    if stage in CLASSIFICATION_STAGES: return dict(output)
    result=dict(output); target=index['CIBLE']
    def resolve(identifier,kind,source_id=None):
        value=index.get(identifier,{})
        if value.get('kind')!=kind or source_id is not None and value.get('source_id')!=source_id:
            return {}
        return value
    if stage in PROPOSAL_STAGES:
        law=resolve(result.pop('obligation_id'),'article',result['source_id'])
        application=resolve(result.pop('application_id'),'dossier')
        result.update(obligation=law.get('citation',''),citation_cctp=target['citation'],page=target['page'],
            application=dict(page=application.get('page',0),citation=application.get('citation','')))
        conditions=[]
        for condition in result['conditions']:
            article=resolve(condition['article_id'],'article',result['source_id'])
            dossier=resolve(condition['dossier_id'],'dossier')
            conditions.append(dict(article_citation=article.get('citation',''),page=dossier.get('page',0),citation_cctp=dossier.get('citation','')))
        result['conditions']=conditions
    else:
        law=resolve(result.pop('citation_article_id'),'article',result['source_id'])
        result.update(citation_article=law.get('citation',''),citation_dossier=dict(page=target['page'],citation=target['citation']))
    return result


def call_local(stage, system, payload, trace):
    """No global wall-time cutoff: each interrupted operation gets its own retry."""
    indexed,index=reference_payload(payload)
    # Classification has no legal task or article-reference instructions.
    # Keep the target last so neighbouring prescriptions are not the subject.
    if stage in CLASSIFICATION_STAGES:
        indexed={k:indexed[k] for k in ('passages_contexte','point')}
    encoded = json.dumps(indexed, ensure_ascii=False)
    instructions='' if stage in CLASSIFICATION_STAGES else REFERENCE_INSTRUCTIONS
    # Reserve output/schema/system space too, not only the document characters.
    output_schema=reference_schema(stage,index,payload['point']['id'])
    estimated=(len((encoded+system+instructions+json.dumps(output_schema)).encode('utf-8'))+1)//2+1200
    context=8192 if estimated<=7500 else 16384 if estimated<=15000 else 32768
    body = dict(model=MODEL, stream=False, format=output_schema, messages=[
        dict(role='system',content=system+'\n\n'+instructions), dict(role='user',content=encoded)],
        options=dict(temperature=0,num_ctx=context,num_predict=300 if stage in CLASSIFICATION_STAGES else 900))
    for attempt, timeout in enumerate((180, 300), 1):
        entry = dict(stage=stage,request=body,started_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),attempt=attempt)
        if attempt == 2: entry['retry_reason']='Délai dépassé : reprise du même contrôle avec les mêmes preuves.'
        trace.append(entry); start=time.monotonic()
        try:
            request=urllib.request.Request('http://127.0.0.1:11434/api/chat',json.dumps(body).encode(),{'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result=json.loads(response.read(3_000_000))
            entry['response']=result
            output=json.loads(result['message']['content'])
            if not response_valid(output,output_schema): raise ValueError('Réponse hors schéma')
            output=hydrate(output,index,stage)
            if not response_valid(output,schema(stage)): raise ValueError('Preuves structurées invalides')
            entry['resolved_evidence']=output
            entry['status']='ok'
            if attempt==2: trace[-2]['recovered_by_retry']=True
            return output
        except Exception as exc:
            timed_out=isinstance(exc,TimeoutError) or isinstance(exc,urllib.error.URLError) and isinstance(exc.reason,TimeoutError)
            entry.update(status='error',error='TimeoutError' if timed_out else type(exc).__name__)
            if attempt==2: trace[-2]['recovered_by_retry']=False
            if not timed_out: return {}
        finally:
            entry['duration_ms']=round((time.monotonic()-start)*1000)
    return {}


def evidence_payload(row, readings, pool, reference):
    pages=readings.get('text') or []
    page=row['fait'].get('page')
    if type(page) is not int or not 1<=page<=len(pages): raise ValueError('Page native indisponible.')
    # Whole pages, no silently truncated law or quote. Include cover/scope and
    # adjacent pages; list omitted pages explicitly in both model exchanges.
    relevant=set([1,2,page-1,page,page+1]) & set(range(1,len(pages)+1))
    contexts=[dict(page=i,texte=pages[i-1]) for i in sorted(relevant)]
    articles=[dict(id=s['id'],titre=s.get('nom_code'),numero=s.get('numero'),texte=s['texte'],
        date_debut=s.get('date_debut'),date_fin_exclusive=s.get('date_fin_exclusive')) for s in pool.values()]
    payload=dict(date_reference=reference,point=dict(id=row['fait']['id'],page=page,
        citation=row['fait'].get('citation_visible','')),articles=articles,passages_contexte=contexts,
        couverture_visuelle=readings.get('couverture_visuelle',{}),
        limites=dict(pages_non_transmises=[i for i in range(1,len(pages)+1) if i not in relevant],
        images_non_transmises=True,conformite_globale=False))
    if len(json.dumps(payload,ensure_ascii=False))>MAX_CONTEXT:
        # Drop only adjacent pages first, preserving the target and scope.
        payload['passages_contexte']=[p for p in contexts if p['page'] in (1,2,page)]
        sent={p['page'] for p in payload['passages_contexte']}
        payload['limites']['pages_non_transmises']=[i for i in range(1,len(pages)+1) if i not in sent]
    if len(json.dumps(payload,ensure_ascii=False))>MAX_CONTEXT:
        raise ValueError('Articles et contexte trop volumineux : isoler le critère avant comparaison.')
    return payload


def validate(proposal, audit, row, readings, pool, reference):
    fact=row['fait']
    image_ok=visual_verified(fact,readings)
    if image_ok:readings=evidence_view(fact,readings)
    pages=readings.get('text') or []
    proposal=proposal if isinstance(proposal,dict) else {}; audit=audit if isinstance(audit,dict) else {}
    outcome=proposal.get('outcome'); sid=proposal.get('source_id')
    source=pool.get(sid,{}) if isinstance(sid,str) else {}
    decisive=outcome in ('respecte','ecart')
    conditions=proposal.get('conditions')
    exact_clause=page_quote(proposal,pages,'citation_cctp') and proposal.get('page')==fact.get('page') and exact(proposal.get('citation_cctp'),fact.get('citation_visible',''))
    if decisive:
        exact_clause=exact_clause and canonical(proposal.get('citation_cctp'))==canonical(fact.get('citation_visible'))
    # Information is a reading/classification outcome, never a compliance one.
    citations=bool(exact_clause and (not decisive or complete_law_quote(proposal.get('obligation'),source.get('texte',''))))
    condition_evidence=(isinstance(conditions,list) and all(isinstance(c,dict) and
        exact(c.get('article_citation'),source.get('texte','')) and page_quote(c,pages,'citation_cctp') for c in conditions))
    application=page_quote(proposal.get('application'),pages)
    same_category=(audit.get('categorie')==proposal.get('categorie') or decisive and
        {audit.get('categorie'),proposal.get('categorie')} <= {'obligation_contractuelle','prescription_technique'})
    matching=(audit.get('id')==fact['id'] and proposal.get('id')==fact['id'] and
        audit.get('outcome')==outcome and same_category and
        proposal.get('categorie') in CATEGORIES and outcome in OUTCOMES and page_quote(audit.get('citation_dossier'),pages)
        and audit['citation_dossier']['page']==fact.get('page') and exact(audit['citation_dossier'].get('citation'),fact.get('citation_visible','')))
    if decisive:
        matching=matching and audit.get('source_id')==source.get('id') and complete_law_quote(audit.get('citation_article'),source.get('texte','')) and canonical(audit.get('citation_article'))==canonical(proposal.get('obligation')) and all(audit.get(k) is True for k in
            ('meme_objet','applicable','complet','exceptions_resolues','sans_contradiction','critere_fidele'))
    else:
        matching=matching and audit.get('critere_fidele') is True
    checks=dict(lecture_valide=(not invalid_fact(fact) and (fact.get('origine')=='texte_natif' or image_ok) and exact_clause),
        statut_prescriptif=(not decisive or proposal.get('categorie') in ('obligation_contractuelle','prescription_technique')
            and fact.get('etat')!='existant' and not fact.get('hors_operation')),
        source_officielle_datee=(source_valid(source,reference) if decisive else True),
        citations_exactes=citations,preuves_conditions=(application and condition_evidence if decisive else True),
        portee_explicite=(bool(canonical(proposal.get('critere'))) and proposal.get('manques')==[] and audit.get('manques')==[] if decisive else True),
        contre_lecture=bool(matching and response_valid(proposal,schema('comparaison_semantique')) and response_valid(audit,schema('contre_lecture_semantique'))))
    # Reading validity and prescriptive scope are distinct; both remain required.
    if outcome=='information' and proposal.get('categorie') not in ('contexte','recommandation','prescription_technique'):
        checks['portee_explicite']=False
    if outcome=='information':
        checks['portee_explicite']=bool(checks['portee_explicite'] and proposal.get('manques')==[] and audit.get('manques')==[])
        checks['contre_lecture']=bool(checks['contre_lecture'] and audit.get('sans_contradiction') is True)
    verified=all(v is True for v in checks.values())
    final=outcome if verified else 'indetermine'
    missing=[LABELS[k]+' : non établi.' for k,v in checks.items() if v is not True]
    missing+= [str(x) for x in proposal.get('manques',[]) if isinstance(x,str)] if isinstance(proposal.get('manques'),list) else []
    missing+= [str(x) for x in audit.get('manques',[]) if isinstance(x,str)] if isinstance(audit.get('manques'),list) else []
    if final=='indetermine' and not missing: missing=[str(proposal.get('raison') or 'Comparaison non déterminée par les preuves disponibles.')]
    return dict(eligible=verified and decisive,outcome=final,checks=checks,labels=LABELS,
        missing=list(dict.fromkeys(missing)),proposal=proposal,audit=audit,
        classification_verifiee=verified,source_sha256=hashlib.sha256(source.get('texte','').encode()).hexdigest(),
        calculation='Comparaison du sens des prescriptions, avec citations distinctes et contre-lecture.',
        method='comparaison_semantique_v6',review_state='completed',
        perimetre='Critère documentaire cité ; aucune conformité globale du contrat ou de l’ouvrage.')


def fail(row, message, state='interrupted'):
    row['verification_article']=dict(eligible=False,outcome='erreur_technique',checks={},labels=LABELS,
        missing=[message],method='comparaison_semantique_v6',review_state=state)
    row.update(statut='a_verifier',comparaison=None,explication=message,action='Reprendre ce contrôle ; aucun verdict juridique produit.')
    row['verification_article']['resolution']=dict(kind='erreur_technique',detail=message,requested_inputs=[])


def resolution(result, pool):
    """A failed interpretation is not automatically a missing user document."""
    outcome=result.get('outcome'); checks=result.get('checks',{})
    kind=('conclusion' if outcome in ('respecte','ecart') else
        'information_documentaire' if outcome=='information' else
        'erreur_technique' if outcome=='erreur_technique' else
        'lecture_invalide' if checks.get('lecture_valide') is False else
        'source_insuffisante' if not pool or checks.get('source_officielle_datee') is False else
        'comparaison_non_concluante')
    return dict(kind=kind,detail=' ; '.join(result.get('missing',[])),requested_inputs=[])


def disputed_information(result, role):
    return (result.get('outcome')=='information' and
        result.get('proposal',{}).get('categorie') in ('contexte','recommandation') and
        (role.get('prescriptif') or role.get('mixte')))


def flag_documentary_disagreement(result):
    result['checks']['classement_documentaire']=False
    result['labels']={**result['labels'],'classement_documentaire':'Désaccord documentaire sur une prescription résolu'}
    result.update(eligible=False,outcome='indetermine',classification_verifiee=False)
    result['missing']=list(dict.fromkeys(result['missing']+['Le classement comme contexte ou recommandation ne résout pas la prescription détectée.']))


def review_point(row, readings, pool, reference, info, caller=call_local):
    fact=row['fait']; reason=structural_context_reason(fact.get('citation_visible'))
    if (reason and fact.get('origine')=='texte_natif' and not invalid_fact(fact)
        and page_quote(fact,readings.get('text') or [],'citation_visible')):
        row['classification_semantique']=dict(categorie='contexte',raison=reason,citation=fact['citation_visible'],page=fact['page'],verifiee=True,methode='structure_documentaire')
        row['verification_article']=dict(eligible=False,outcome='information',checks=dict(lecture_valide=True,structure_sommaire=True),
            labels=dict(lecture_valide=LABELS['lecture_valide'],structure_sommaire='Structure de sommaire : titre, pointillés et renvoi de page'),
            missing=[],method='comparaison_semantique_v6',review_state='completed',classification_verifiee=True,
            basis='structure_documentaire',proposal={},audit={},perimetre='Classement structurel seulement ; aucune conformité juridique.')
        row['verification_article']['resolution']=dict(kind='information_documentaire',detail=reason,requested_inputs=[])
        row.update(statut='technique',comparaison=None,regle=None,mode_verification='classification_structurelle',explication=reason,
            action='Consulter la page indiquée par cette entrée pour examiner les prescriptions réelles.')
        return
    try: payload=evidence_payload(row,readings,pool,reference)
    except ValueError as exc:
        fail(row,str(exc),'not_started');return
    before=len(info['exchanges'])
    role=caller('classification_documentaire',CLASSIFY,dict(payload,articles=[]),info['exchanges'])
    if (not response_valid(role,schema('classification_documentaire')) or role.get('id')!=fact['id']
        or len(info['exchanges'])>before and info['exchanges'][-1].get('status')=='error'):
        timeout=bool(info['exchanges'] and info['exchanges'][-1].get('error')=='TimeoutError')
        fail(row,'Délai dépassé malgré la reprise : classement documentaire non terminé.' if timeout else 'Classement documentaire indisponible ou JSON inexploitable.'); return
    row['lecture_role']=dict(role,citation=fact.get('citation_visible',''),page=fact.get('page'))
    payload['classification_documentaire']=role
    before=len(info['exchanges'])
    proposal=caller('comparaison_semantique',PROPOSE,payload,info['exchanges'])
    if not response_valid(proposal,schema('comparaison_semantique')) or (len(info['exchanges'])>before and info['exchanges'][-1].get('status')=='error'):
        timeout=bool(info['exchanges'] and info['exchanges'][-1].get('error')=='TimeoutError')
        fail(row,'Délai dépassé malgré la reprise : comparaison non terminée.' if timeout else 'Réponse de comparaison indisponible ou JSON inexploitable.');return
    # Never audit hallucinated quotations as though they were documentary facts.
    p=proposal if isinstance(proposal,dict) else {}
    exact_clause=(page_quote(p,readings['text'],'citation_cctp') and p.get('page')==row['fait'].get('page')
        and exact(p.get('citation_cctp'),row['fait'].get('citation_visible','')))
    legal=p.get('outcome') in ('respecte','ecart')
    if not exact_clause or (legal and not complete_law_quote(p.get('obligation'),pool.get(p.get('source_id'),{}).get('texte',''))):
        row['verification_article']=validate(p,{},row,readings,pool,reference)
    else:
        before=len(info['exchanges'])
        audited=caller('contre_lecture_semantique',AUDIT,dict(payload,proposition=p),info['exchanges'])
        if not response_valid(audited,schema('contre_lecture_semantique')) or (len(info['exchanges'])>before and info['exchanges'][-1].get('status')=='error'):
            timeout=bool(info['exchanges'] and info['exchanges'][-1].get('error')=='TimeoutError')
            fail(row,'Délai dépassé malgré la reprise : contre-lecture non terminée.' if timeout else 'Contre-lecture indisponible ou JSON inexploitable.');return
        row['verification_article']=validate(p,audited,row,readings,pool,reference)
        initial=row['verification_article']
        classification_dispute=disputed_information(initial,role)
        arbitration=None
        if classification_dispute:
            # A fresh document-only reading can correct the first classifier,
            # including an imperative quoted in an explicitly rejected example.
            before=len(info['exchanges'])
            arbitration=caller('arbitrage_documentaire',CLASSIFY,
                {k:v for k,v in dict(payload,articles=[]).items() if k!='classification_documentaire'},info['exchanges'])
            arbitration_valid=(response_valid(arbitration,schema('arbitrage_documentaire')) and arbitration.get('id')==fact['id']
                and not (len(info['exchanges'])>before and info['exchanges'][-1].get('status')=='error'))
            if arbitration_valid:
                payload['classification_documentaire']=arbitration
            if (not arbitration_valid or arbitration.get('prescriptif') or arbitration.get('mixte')
                or arbitration.get('categorie')!=p.get('categorie')):
                flag_documentary_disagreement(initial)
            else:
                classification_dispute=False
            initial['arbitrage_documentaire']=arbitration
        basic=('lecture_valide','statut_prescriptif','source_officielle_datee','citations_exactes','preuves_conditions')
        if (initial['outcome']=='indetermine' and p.get('outcome') in ('information','respecte','ecart')
            and all(initial['checks'].get(k) is True for k in basic)
            and (p.get('manques') or audited.get('manques') or classification_dispute)):
            # Resolve an alleged obstacle by another complete reading. Keep the
            # same validation gates and both attempts; never clear a flag by code.
            blockers=list(dict.fromkeys(p.get('manques',[])+audited.get('manques',[])))
            if classification_dispute:
                blockers.append('Un impératif détecté dans le passage reste à distinguer du contexte ou de la recommandation ; ne neutralise pas cette prescription.')
            retry_payload=dict(payload,proposition=p,blocages_signales=blockers)
            revised=p
            failed=False
            if p.get('manques') or classification_dispute:
                before=len(info['exchanges'])
                revised=caller('reformulation_comparaison',REVISE,retry_payload,info['exchanges'])
                failed=(not response_valid(revised,schema('reformulation_comparaison')) or revised.get('id')!=fact['id']
                    or len(info['exchanges'])>before and info['exchanges'][-1].get('status')=='error')
                if not failed:
                    revised_checks=validate(revised,{},row,readings,pool,reference)['checks']
                    failed=not all(revised_checks.get(k) is True for k in basic)
            recovered={}
            if not failed:
                before=len(info['exchanges'])
                recovered=caller('resolution_blocages',RESOLVE,dict(retry_payload,proposition=revised),info['exchanges'])
                failed=(not response_valid(recovered,schema('resolution_blocages')) or len(info['exchanges'])>before and info['exchanges'][-1].get('status')=='error')
            if failed:
                initial['resolution_attempt']=dict(status='error',detail='La reprise critique du blocage n’a pas abouti ; conclusion initiale non établie conservée.')
                initial['tentatives']=[dict(proposal=p,audit=audited),dict(proposal=revised,audit=recovered)]
            else:
                retried=validate(revised,recovered,row,readings,pool,reference)
                retried['audit_initial']=audited
                retried['proposal_initial']=p
                retried['tentatives']=[dict(proposal=p,audit=audited),dict(proposal=revised,audit=recovered)]
                if arbitration is not None:
                    retried['arbitrage_documentaire']=arbitration
                    if not arbitration_valid or disputed_information(retried,arbitration):
                        flag_documentary_disagreement(retried)
                retried['resolution_attempt']=dict(status='completed',changed=initial['outcome']!=retried['outcome'])
                row['verification_article']=retried
                p=revised
    result=row['verification_article']; outcome=result['outcome']
    result['resolution']=resolution(result,pool)
    result['classement_preliminaire']=role
    row['classification_semantique']=dict(categorie=p.get('categorie','indetermine'),raison=p.get('raison',''),
        citation=p.get('citation_cctp',''),page=p.get('page'),verifiee=result['classification_verifiee'])
    if outcome in ('respecte','ecart'):
        source=pool[p['source_id']]
        row.update(statut='critere_auto_respecte' if outcome=='respecte' else 'ecart_confirme_sur_critere',
            mode_verification='article_verifie',comparaison=outcome=='respecte',regle=p['obligation'],article=source.get('numero'),
            source=dict(source,titre=source.get('nom_code'),url=source.get('source_url') or source.get('url')),
            explication=p['raison'],action=('Aucune correction établie sur le critère cité.' if outcome=='respecte' else 'Corriger la prescription en contradiction avec le critère cité.')+' Voir les deux lectures et leurs preuves dans l’inspection.')
    elif outcome=='information':
        row.update(statut='technique',comparaison=None,regle=None,mode_verification='classification_semantique',
            explication=p['raison'],action='Information classée ; aucun verdict de conformité juridique sur ce passage.')
    else:
        row.update(statut='a_verifier',comparaison=None,explication=' ; '.join(result['missing']),
            action='Élément à établir : '+' ; '.join(result['missing']))


def completion_evidence(analysis, readings, info):
    """Bind all supplementary evidence to each point's checkpoint input."""
    from slm_v6_references import references_for_document
    from slm_v6_consistency import detect_inconsistencies
    from slm_v6_document_profile import profile
    enriched=dict(readings)
    enriched['document_profile']=profile(readings)
    info['document_profile']=enriched['document_profile']
    try:
        enriched['technical_references']=references_for_document(readings,analysis['date_reference'])
        own_id=(enriched['document_profile'].get('reference_identity') or {}).get('id')
        enriched['technical_references']=[r for r in enriched['technical_references'] if r['id']!=own_id]
        info['technical_references']=[{k:v for k,v in ref.items() if k not in ('pages','general_context')}
                                      for ref in enriched['technical_references']]
    except (ValueError,OSError,KeyError) as exc:
        enriched['technical_references']=[]
        info['reference_error']=str(exc)
    enriched['documentary_consistency']=detect_inconsistencies(readings)
    info['documentary_consistency']=enriched['documentary_consistency']
    return enriched


def apply_documentary_consistency(row, readings):
    """A proven contradictory clause cannot be displayed as an unqualified green."""
    findings=[item for item in readings.get('documentary_consistency',[])
              if row['fait']['id'] in item.get('fait_ids',[])]
    if not findings:return
    # More than one incompatible finding is kept for examination, never collapsed.
    row['coherence_documentaire']=findings
    finding=next((x for x in findings if x.get('confirmed') is True
                  and x.get('checks') and all(v is True for v in x['checks'].values())),None)
    if not finding:return
    row['verification_coherence']=finding
    if row.get('comparaison') is False:
        return  # The established gap remains visible, with the inconsistency alongside it.
    row.update(statut='incoherence_documentaire_confirmee',comparaison=None,
        mode_verification='coherence_documentaire',explication=finding['explication'],
        action='Harmoniser les valeurs du même ouvrage ou préciser leur priorité. Aucune valeur n’a été choisie arbitrairement.',
        regle=None,article=None)


def review(analysis, readings, plan, caller=None, progress=None, restore_point=None, save_point=None, point_reviewer=None):
    caller=caller or call_local
    info=dict(version=3,method='comparaison_semantique_v6',exchanges=[],evaluated=0,confirmed=0,
        deviations=0,information=0,skipped=0,errors=[],retries=0)
    if point_reviewer is not None:
        info.update(version=4,pipeline='critere_cible')
    analysis['verification_articles']=info
    if not analysis.get('controle_juridique'): return
    if point_reviewer is not None:
        info['deduplication']=consolidate_native_duplicates(analysis,readings)
        readings=completion_evidence(analysis,readings,info)
        prepare_visual(analysis,readings,info)
        readings['retrieval_policy']=dict(criterion_search=True,piste_allowed=plan.get('piste_autorise') is True)
        info.update(technical_respect=0,technical_deviations=0,documentary_conflicts=0)
    selected={**plan.get('sources_cache',{}),**plan.get('sources_piste',{}),**plan.get('sources_locales',{})}
    points={p['fait_id']:p for p in plan.get('points',[])}
    rows=analysis['lignes']
    candidates=[r for r in rows if r['statut'] not in ('hors_perimetre','lecture_rejetee')
        and not invalid_fact(r['fait']) and (
            not r.get('regle') and r['fait'].get('origine')=='texte_natif'
            or point_reviewer is not None and visual_verified(r['fait'],readings))]
    info['skipped']=len(rows)-len(candidates)
    if restore_point or save_point:
        info['checkpoint_counts']=dict(reused=0,recomputed=0)
    for index,row in enumerate(candidates,1):
        point=points.get(row['fait']['id'],{})
        sources=[selected[t] for t in point.get('topics',[]) if t in selected]+point.get('articles_complementaires',[])
        pool={s['id']:s for s in sources if source_valid(s,analysis['date_reference'])}
        if progress: progress(dict(done=index-1,total=len(candidates),fact_id=row['fait']['id'],stage='comparaison_semantique'))
        point_input=dict(row=json.loads(json.dumps(row)),readings=readings,pool=pool,reference=analysis['date_reference']) if restore_point or save_point else None
        restored=restore_point(point_input) if restore_point else None
        if restored is not None:
            row.clear(); row.update(restored['row'])
            row['verification_article']['checkpoint_reuse']=restored['provenance']
            info['exchanges'].extend(restored['exchanges'])
            info['checkpoint_counts']['reused']+=1
        else:
            start=len(info['exchanges'])
            if point_reviewer is None:
                review_point(row,readings,pool,analysis['date_reference'],info,caller)
            else:
                point_reviewer(row,readings,pool,analysis['date_reference'],info)
                apply_documentary_consistency(row,readings)
            if save_point:
                save_point(point_input,row,info['exchanges'][start:])
            if restore_point or save_point:
                info['checkpoint_counts']['recomputed']+=1
        info['evaluated']+=1
        outcome=row['verification_article']['outcome']
        info['confirmed']+=outcome=='respecte'; info['deviations']+=outcome=='ecart'; info['information']+=outcome=='information'
        if point_reviewer is not None:
            info['technical_respect']+=row.get('statut')=='critere_technique_respecte'
            info['technical_deviations']+=row.get('statut')=='ecart_technique_confirme'
            info['documentary_conflicts']+=row.get('statut')=='incoherence_documentaire_confirmee'
        if progress: progress(dict(done=index,total=len(candidates),fact_id=row['fait']['id'],outcome=outcome,stage='comparaison_semantique'))
    info.pop('_piste_cache',None)  # Responses already archived in the per-point traces.
    info['errors']=[e.get('error') for e in info['exchanges'] if e.get('status')=='error' and not e.get('recovered_by_retry')]
    info['retries']=sum(e.get('attempt',1)>1 for e in info['exchanges'])
    analysis['revision']='V6-SEMANTIQUE-TEST-2'
    analysis['limites'].append('Workflow expérimental : classement documentaire séparé, comparaison sémantique, citations contrôlées et lectures critiques du même modèle local. Les blocages allégués peuvent déclencher une reprise supplémentaire. Aucune certification juridique ; contexte limité explicitement dans chaque échange.')
    if point_reviewer is not None:
        analysis['revision']='V6-CRITERE-CIBLE'
        analysis['limites'][-1]='Workflow expérimental : rôle documentaire, sélection du critère précis, pertinence puis deux comparaisons sans partage du verdict, avec le même modèle local. Conversions arithmétiques des unités ; aucune règle juridique déduite des conversions. Les citations, conditions et versions sont contrôlées. Le contexte transmis et les limites de recherche sont conservés dans l’inspection. Aucune certification juridique ni garantie de couverture exhaustive.'
