"""Core orchestration: native rule-bound pending controls are not excluded."""
from slm_v6_semantic_review import (consolidate_native_duplicates,completion_evidence,prepare_visual,
    source_valid,invalid_fact,visual_verified,apply_documentary_consistency)
from slm_m3_journal import emit
import math
import time
import urllib.error
from slm_v6_visual_evidence import call as image_call
from slm_core_perimeter import establish as establish_perimeter


def traced_image_call(stage,page,questions,material,spec,info):
    tick=time.monotonic();start=len(info['exchanges'])
    questions=[{**q,'preuve_ocr_attendue':"citation_ids contient les lignes qui nomment l'objet ET la donnée écrite de sa même ligne/annotation, même si le tableau sépare ces textes en colonnes. Ne cite pas la donnée d'un autre objet."} for q in questions]
    ids=[q['id'] for q in questions]
    emit(stage,'running',page=page['page'],fact_ids=ids,image_sha256=material['image_sha256'],ocr_sha256=material['ocr_sha256'])
    try:
        try:
            value=image_call(stage,page,questions,material,spec,info)
        except urllib.error.URLError as exc:
            # The shared reader already retries timeouts. A connection reset
            # or refusal is different: retry it once, with the same evidence.
            # HTTP failures (e.g. invalid model/request) are not transient here.
            if isinstance(exc,urllib.error.HTTPError) or isinstance(exc.reason,TimeoutError):raise
            failed=list(range(start,len(info['exchanges'])))
            emit(stage,'retry',page=page['page'],fact_ids=ids,error=type(exc).__name__,
                reason=str(exc.reason)[:400],retry=1,same_image_sha256=material['image_sha256'])
            time.sleep(.5)
            value=image_call(stage,page,questions,material,spec,info)
            for index in failed:
                if info['exchanges'][index].get('status')=='error':
                    info['exchanges'][index].update(recovered_by_retry=True,
                        core_retry_reason='Connexion interrompue ; même image, mêmes questions et mêmes preuves OCR reprises une fois.')
    except Exception as exc:
        emit(stage,'error',page=page['page'],fact_ids=ids,error=type(exc).__name__,reason=str(exc)[:500],
            attempts=info['exchanges'][start:],duration_ms=round((time.monotonic()-tick)*1000))
        raise
    else:
        emit(stage,'done',page=page['page'],fact_ids=ids,duration_ms=round((time.monotonic()-tick)*1000),
            attempts=info['exchanges'][start:])
        return value


def normalize_scalar_numbers(analysis):
    # n8n transports JSON through JavaScript: 5.0 becomes 5. Bind integral
    # measurements as integers before creating new proofs, never patch an old
    # proof hash. Otherwise intact evidence fails its replay after delivery.
    for row in analysis.get('lignes',[]):
        fact=row['fait']
        for key in ('valeur','valeur_m'):
            value=fact.get(key)
            if type(value) is float and math.isfinite(value) and value.is_integer():
                fact[key]=int(value)


def review(analysis,readings,plan,*,caller,point_reviewer,progress=None):
    # Keep the renderer's existing protocol key. Per-row method/validation_mode
    # still distinguishes a program calculation from a model comparison.
    info=dict(version=4,method='comparaison_semantique_v6',coordinator='comparaison_structuree_core',exchanges=[],evaluated=0,confirmed=0,
        deviations=0,information=0,skipped=0,errors=[],retries=0,pipeline='core',
        technical_respect=0,technical_deviations=0,documentary_conflicts=0)
    analysis['verification_articles']=info
    if not analysis.get('controle_juridique'):return
    # The document/consistency view must see the same exact units as the
    # comparison, while the original generic parents remain in the inventory.
    readings={**readings,'faits':[r['fait'] for r in analysis['lignes']]}
    from slm_core_native_evidence import prefer_native
    prefer_native(analysis,readings)
    normalize_scalar_numbers(analysis)
    info['deduplication']=consolidate_native_duplicates(analysis,readings)
    readings=completion_evidence(analysis,readings,info)
    for row in analysis['lignes']:
        if row['fait'].get('hors_operation') is True:
            try:establish_perimeter(row,readings,info,traced_image_call)
            except Exception as exc:emit('perimetre_documente','error',fact_id=row['fait']['id'],error=type(exc).__name__)
    # Reuse only proof objects that pass their full hash/citation replay gate.
    reused=[r['fait']['id'] for r in analysis['lignes'] if visual_verified(r['fait'],readings)]
    partial={**analysis,'lignes':[r for r in analysis['lignes'] if r['fait']['id'] not in reused]}
    prepare_visual(partial,readings,info,caller=traced_image_call)
    info['lecture_images']['reused_verified_ids']=reused
    readings['retrieval_policy']=dict(criterion_search=True,piste_allowed=plan.get('piste_autorise') is True)
    selected={**plan.get('sources_cache',{}),**plan.get('sources_piste',{}),**plan.get('sources_locales',{})}
    reviewed_candidates={s['id']:s for s in selected.values() if s.get('core_catalogue_exact') is True and source_valid(s,analysis['date_reference'])}
    points={p['fait_id']:p for p in plan.get('points',[])}
    for row in analysis['lignes']:
        fact=row['fait']
        if fact.get('core_measurement_pending') and invalid_fact(fact):
            reason='Mesure extraite conservée, mais objet, unité ou valeurs contradictoires restent à établir. Aucun verdict déduit.'
            row.update(statut='a_verifier',comparaison=None,explication=reason,
                verification_article=dict(outcome='indetermine',eligible=False,checks=dict(lecture_valide=False),
                    method='core_mesure_conservee',missing=[reason],review_state='not_started',
                    resolution=dict(kind='lecture_invalide',detail=reason)))
    candidates=[r for r in analysis['lignes'] if r['statut'] not in ('hors_perimetre','lecture_rejetee')
        and not invalid_fact(r['fait']) and (r['fait'].get('origine')=='texte_natif'
            and r['statut'] not in ('critere_auto_respecte','ecart_confirme_sur_critere','ecart_confirme')
            or visual_verified(r['fait'],readings))]
    info['skipped']=len(analysis['lignes'])-len(candidates)
    if plan.get('catalogue_recovery',{}).get('usage'):
        import copy
        info['piste_usage']=copy.deepcopy(plan['catalogue_recovery']['usage'])
        info['catalogue_recovery']=plan['catalogue_recovery']
        info['_piste_cache']={__import__('json').dumps(e['request'],sort_keys=True):dict(request=e['request'],response=e['response'],execution_id=e.get('execution_id'))
            for e in plan['catalogue_recovery']['trace'].get('calls',[]) if e.get('status')=='completed' and 'response' in e}
    for index,row in enumerate(candidates,1):
        point=points.get(row['fait']['id'],points.get(row['fait'].get('core_parent_id'),{}))
        sources=[selected[t] for t in point.get('topics',[]) if t in selected]+point.get('articles_complementaires',[])
        if row['fait'].get('type_fait')=='pente_longitudinale' and selected.get('access'):sources.append(selected['access'])
        pool={s['id']:s for s in sources if source_valid(s,analysis['date_reference'])}
        reused=[];conflicts=[]
        for ident,source in reviewed_candidates.items():
            if ident in pool and ' '.join(pool[ident]['texte'].split())!=' '.join(source['texte'].split()):
                conflicts.append(ident);pool.pop(ident);continue
            pool[ident]=source;reused.append(ident)
        emit('references_revues_disponibles','done',fact_id=row['fait']['id'],source_ids=reused,conflicting_ids=conflicts,
            model_call=False,applicability_established=False,
            reason='Références du catalogue vérifiées pour cette date, réutilisées comme candidats ; champ et critère revérifiés pour ce fait.')
        scope=selected.get('scope')
        if scope and source_valid(scope,analysis['date_reference']):pool[scope['id']]=scope
        if progress:progress(dict(done=index-1,total=len(candidates),fact_id=row['fait']['id']))
        from slm_core_control_reuse import reuse
        if not reuse(row,analysis,readings,pool,analysis['date_reference'],info):
            point_reviewer(row,readings,pool,analysis['date_reference'],info)
        apply_documentary_consistency(row,readings)
        outcome=row['verification_article']['outcome'];info['evaluated']+=1
        info['confirmed']+=outcome=='respecte';info['deviations']+=outcome=='ecart';info['information']+=outcome=='information'
        info['technical_respect']+=row.get('statut')=='critere_technique_respecte'
        info['technical_deviations']+=row.get('statut')=='ecart_technique_confirme'
        info['documentary_conflicts']+=row.get('statut')=='incoherence_documentaire_confirmee'
        emit('controle_selectionne','done',fact_id=row['fait']['id'],outcome=outcome)
        if progress:progress(dict(done=index,total=len(candidates),fact_id=row['fait']['id'],outcome=outcome))
    info.pop('_piste_cache',None)
    info.pop('_core_rule_cache',None)
    info['errors']=[e.get('error') for e in info['exchanges'] if e.get('status')=='error' and not e.get('recovered_by_retry')]
    info['retries']=sum(e.get('attempt',1)>1 for e in info['exchanges'])
