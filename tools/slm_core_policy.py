"""Core adds the explicit scope source needed by its reviewed controls."""
from slm_m3_policy import coverage as inherited_coverage
from slm_v5_policy import TOPICS,LOCAL_INSTRUMENTS,checked_article
from slm_m3_search_audit import search as traced_search
from dila_local_store import DilaStore,DEFAULT_DB_PATH
from slm_m3_journal import emit
from slm_core_context import ContextDilaReader
from slm_core_atoms import inventory as generic_inventory

SCOPED={'largeur_pieton','devers_pieton','pente_longitudinale','ressaut','fente_grille','bande_eveil',
        'distance_stationnement_amont','absence_amenagement_cyclable','derogation_par_visa'}


def mark_reviewed_sources(selected,reference):
    from slm_v5_report import reviewed_sources
    from slm_v6_semantic_review import source_valid
    for topic,source in selected.items():
        _,gates,_=reviewed_sources(dict(date_reference=reference,sources_locales={topic:source}))
        checks=gates.get(topic,{}).get('checks',{})
        if checks and all(v for k,v in checks.items() if k!='source_dila') and source_valid(source,reference):source['core_catalogue_exact']=True
        else:source.pop('core_catalogue_exact',None)


def coverage(body,store=None,cache=None,today=None,*,catalogue_call=None):
    store=store or ContextDilaReader()
    result=inherited_coverage(body,store=store,cache=cache,today=today,inventory_fn=generic_inventory)
    plan=result['couverture_locale'];readings=result['lectures_images']
    targets=[f for f in readings.get('faits',[]) if f.get('type_fait') in SCOPED]
    if not body.get('controle_juridique',True):return result
    selected={**plan.get('sources_cache',{}),**plan.get('sources_piste',{}),**plan.get('sources_locales',{})}
    mark_reviewed_sources(selected,plan['date_reference'])
    if not targets:return result
    if 'scope' not in selected and plan['base_recente'] and plan['date_couverte']:
        spec=TOPICS['scope'];reference=plan['date_reference']
        rows,audit=traced_search(store or DilaStore(DEFAULT_DB_PATH),'',reference,
            code=LOCAL_INSTRUMENTS.get('scope',spec.get('code')),article=spec.get('article'),
            limit=20,fact_id=targets[0]['id'],origin='champ_des_controles_core')
        valid={r['id']:r for r in rows if checked_article(r,'scope',reference)
            and not r.get('version_ambiguous') and not r.get('temporal_uncertain')}
        if len(valid)==1:
            selected['scope']=next(iter(valid.values()));plan['sources_locales']['scope']=selected['scope']
            plan['decisions']['scope']=dict(canal='dila_local',motif='version_datee_retrouvee_localement',recherche_dila=audit)
        emit('source_champ_core','done',candidate_ids=list(valid),resolved='scope' in selected,search_audit=audit)
    # The inherited plan only schedules missing sources. This async Core
    # worker has no n8n loop executing that schedule: resolve exact reviewed
    # references once here instead of rediscovering them for every measure.
    if plan.get('piste_autorise'):
        from v4_9_laws import CATALOG
        from slm_v6_piste_recovery import request_traced,normalize
        info={'pipeline':'core'};trace={'calls':[]};accepted=[]
        needed={t for p in plan['points'] for t in p.get('topics_manquants',[]) if t in CATALOG}
        if any(f.get('type_fait')=='pente_longitudinale' for f in targets):needed.add('access')
        needed.add('scope')
        for topic in sorted(needed):
            if topic in selected:continue
            item=CATALOG[topic];ident=item['url'].rsplit('/',1)[-1]
            response=request_traced(dict(operation='article',id=ident),info,trace,catalogue_call)
            if response is None:continue
            try:
                article=response.get('article') or {}
                source=normalize(response,dict(id=ident,numero=article.get('num'),titre=item['titre'],
                    fond='CODE_DATE' if '/codes/' in item['url'] else 'LODA_DATE'),plan['date_reference'])
                # Exact known ID, period and all reviewed passages must pass.
                from slm_v5_report import reviewed_sources
                _,gates,_=reviewed_sources(dict(date_reference=plan['date_reference'],sources_locales={topic:source}))
                checks=gates.get(topic,{}).get('checks',{})
                if not checks or not all(v for k,v in checks.items() if k!='source_dila'):continue
                source['core_catalogue_exact']=True
                selected[topic]=source;plan.setdefault('sources_piste',{})[topic]=source;accepted.append(topic)
                plan['decisions'][topic]=dict(canal='piste',motif='reference_exacte_revue_retrouvee',source_id=ident)
            except (ValueError,TypeError,KeyError) as exc:
                trace.setdefault('exclusions',[]).append(dict(topic=topic,error=str(exc)))
        plan['catalogue_recovery']=dict(trace=trace,usage=info.get('piste_usage',{}),accepted=accepted)
        plan['recherche_piste_executee']=bool(info.get('piste_usage',{}).get('calls'))
    # The same reviewed reference must remain reusable regardless of its
    # channel. This flag describes source/version checks, never applicability.
    mark_reviewed_sources(selected,plan['date_reference'])
    by_id={p['fait_id']:p for p in plan['points']}
    for fact in targets:
        point=by_id.get(fact['id'])
        if point is not None and 'scope' in selected and 'scope' not in point['topics']:
            point['topics'].append('scope')
            audit=plan['decisions'].get('scope',{}).get('recherche_dila')
            if audit:point['dila_searches'].append(audit)
    for point in plan['points']:
        point['topics_manquants']=[t for t in point.get('topics_manquants',[]) if t not in selected]
    return result
