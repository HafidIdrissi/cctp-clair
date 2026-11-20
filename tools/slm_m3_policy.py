"""DILA-first coverage for the V4.9-derived workflow, without topic fallback."""
import copy
from datetime import date

from dila_local_store import DilaStore, DEFAULT_DB_PATH
from slm_v5_policy import (grounded_readings,invalid_fact,MAX_AGE_DAYS,CACHE_DB,
    cached_sources,checked_article,LOCAL_INSTRUMENTS,real_date)
from slm_v5_facts import enrich_native
from v4_9_fallback import FACT_TOPICS,TOPICS,inventory
from slm_v6_source_recovery import queries_for,exclusions
from slm_m3_journal import emit,stage
from slm_m3_search_audit import search as traced_search

def coverage(body,store=None,cache=None,today=None,*,inventory_fn=None):
    reference=real_date(body['date_reference'])
    readings=grounded_readings((inventory_fn or inventory)(enrich_native(body['lectures'])))
    enabled=body.get('controle_juridique',True) is True
    allowed=enabled and body.get('piste_autorise',True) is True
    state=(store or DilaStore(DEFAULT_DB_PATH)).status() if enabled else dict(article_count=0,ready=False)
    if enabled:store=store or DilaStore(DEFAULT_DB_PATH)
    now=today or date.today()
    try:
        stamp=date.fromisoformat(state.get('verified_through',''))
        verified_snapshot=state.get('continuity_verified') is True and stamp<=now
        fresh=verified_snapshot and (now-stamp).days<=MAX_AGE_DAYS
        temporal=reference<=stamp.isoformat()
    except (ValueError,TypeError):fresh=temporal=verified_snapshot=False
    cached=((cached_sources(reference,CACHE_DB) if cache is None else cache) if enabled else {})
    local,selected_cache,decisions,needed,points,queries={},{},{},{},[],{}
    with stage('recherche_dila',date_reference=reference):
        for fact in readings.get('faits',[]):
            bad=invalid_fact(fact)
            # Only explicit known fact types use the reviewed article catalogue.
            # Generic clauses NEVER inherit cycling from a word or a default.
            topics=list(FACT_TOPICS.get(fact.get('type_fait'),[]))
            point=dict(fait_id=fact['id'],page=fact.get('page'),topics=topics,discovery_topics=[],
                topics_manquants=[],conformite_etablie=False,articles_complementaires=[],
                statut='preuve_a_verifier' if bad else 'lecture_seule' if not enabled else 'sources_documentaires_disponibles',dila_searches=[])
            if enabled and not bad:
                for topic in topics:
                    if topic not in decisions:
                        spec=TOPICS[topic];rows=[];audit=None
                        # A verified historical snapshot can supply a dated catalogue article
                        # even when it is too old to answer a question about today's law.
                        reason=('base_dila_vide' if not state.get('article_count') else 'base_dila_a_actualiser' if not verified_snapshot else 'date_posterieure_au_corpus' if not temporal else None)
                        if not reason:
                            code=LOCAL_INSTRUMENTS.get(topic,spec.get('code'))
                            rows,audit=traced_search(store,'' if code and spec.get('article') else spec.get('expression') or spec.get('title_terms',''),reference,code=code,article=spec.get('article'),limit=20,fact_id=fact['id'],origin='reference_du_catalogue')
                            rows=[r for r in rows if checked_article(r,topic,reference)]
                            accepted={r['id'] for r in rows}
                            for candidate in audit['results']:candidate['accepted_reference']=candidate['id'] in accepted
                            ids={r['id']:r for r in rows}
                            if not ids:reason='reference_absente_du_perimetre_local'
                            elif len(ids)!=1 or any(r.get('version_ambiguous') or r.get('temporal_uncertain') for r in rows):reason='versions_locales_ambigues'
                            else:local[topic]=next(iter(ids.values()))
                        if reason and topic in cached and checked_article(cached[topic],topic,reference) and not cached[topic].get('version_ambiguous') and not cached[topic].get('temporal_uncertain'):
                            selected_cache[topic]=cached[topic];decisions[topic]=dict(canal='cache_piste',motif='version_exacte_en_cache_recent',lacune_dila=reason)
                        else:decisions[topic]=dict(canal='piste' if reason and allowed else 'aucun' if reason else 'dila_local',motif=reason or 'version_datee_retrouvee_localement')
                        if audit:decisions[topic]['recherche_dila']=audit
                        emit('source_catalogue','done',fact_id=fact['id'],topic=topic,decision=decisions[topic],candidates=[{k:r.get(k) for k in ('id','numero','nom_code','date_debut','date_fin_exclusive')} for r in rows])
                    if decisions[topic].get('recherche_dila'):point['dila_searches'].append(decisions[topic]['recherche_dila'])
                    if topic not in local and topic not in selected_cache:
                        point['topics_manquants'].append(topic)
                        if allowed:needed.setdefault(topic,[]).append(fact['id'])
                # Unknown clauses get literal, bounded searches, never a generic cycling query.
                if not topics and fresh and temporal:
                    candidates={}
                    for q in queries_for(fact,locations=[readings.get('city',''),readings.get('region','')]):
                        query=q['query']
                        if query not in queries:queries[query]=traced_search(store,query,reference,limit=5,fact_id=fact['id'])
                        rows,audit=queries[query]
                        point['dila_searches'].append(audit)
                        for source in rows:
                            if not exclusions(source,reference,set()):candidates[source['id']]=source
                        emit('recherche_clause','done',fact_id=fact['id'],query=query,candidate_ids=[r.get('id') for r in rows],selection_established=False)
                    point['articles_complementaires']=list(candidates.values())[:10]
                if point['topics_manquants']:point['statut']='source_a_rechercher'
            points.append(point)
            emit('orientation','done',fact_id=fact['id'],page=fact.get('page'),type_fait=fact.get('type_fait'),topics=topics,
                method='type_explicite' if topics else 'recherche_litterale_sans_repli_thematique',status_detail=point['statut'])
    specs=[dict(TOPICS[t],id=t,fact_ids=sorted(set(ids)),motif_fallback=decisions[t]['motif']) for t,ids in needed.items()]
    plan=dict(mode='dila_local_prioritaire_v5',date_reference=reference,perimetre='Critères sourcés et clauses documentaires ; aucune couverture exhaustive garantie',
        base_dila=state,fraicheur_max_jours=MAX_AGE_DAYS,base_recente=fresh,date_couverte=temporal,instantane_verifie=verified_snapshot,piste_autorise=allowed,
        points=points,requetes=specs,decisions=decisions,recherche_piste_necessaire=bool(specs),recherche_piste_executee=False,
        sources_locales=local,sources_cache=selected_cache,cache_hits=list(selected_cache),requetes_locales=len(queries),
        recherche_exhaustive=False,conformite_globale_etablie=False,
        limites_recherche=dict(pages_par_requete=5,resultats_par_page=20,consultations_max=60),
        moteur_recherche='M3-DILA-sans-repli-cyclable')
    return {**readings,'lectures_images':readings,'date_reference':reference,
        'format_rapport':body.get('format_rapport','cartes'),'controle_juridique':enabled,
        'couverture_locale':plan,'recherche_piste_necessaire':bool(specs)}
