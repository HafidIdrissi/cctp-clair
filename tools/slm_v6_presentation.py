"""V6-only presentation of recorded results; never produces a legal verdict."""
METHOD = 'comparaison_semantique_v6'
CHECKS = ('lecture_valide','source_officielle_datee','citations_exactes','preuves_conditions','portee_explicite','contre_lecture')
GROUPS = (
    ('conclusions','Conclusions automatiques'),
    ('information','Informations documentaires'),
    ('unresolved','Contrôles non conclus'),
    ('interrupted','Contrôles interrompus ou non démarrés'),
    ('user_confirmations','Confirmations de l’utilisateur'),
    ('reading','Passages relevés — lecture seule'),
)
REASONS = {
    'source_insuffisante':'Source juridique insuffisante',
    'comparaison_non_concluante':'Comparaison non concluante',
    'lecture_invalide':'Lecture non établie',
}


def is_v6(analysis, workflow_id=None):
    return (workflow_id == 'SlmSemanticTestV6' or
        str(analysis.get('workflow_version','')).startswith('V6') or
        str(analysis.get('revision','')).startswith('V6') or
        (analysis.get('verification_articles') or {}).get('method') == METHOD)


def documentary_information(row):
    """A recorded role classification used no legal source for its outcome."""
    check = row.get('verification_article') or {}
    return (row.get('mode_verification') == 'classification_semantique'
            and check.get('method') == METHOD and check.get('outcome') == 'information'
            and check.get('classification_verifiee') is True)


def excluded_information(row):
    if not documentary_information(row):
        return False
    stages = (row.get('verification_article') or {}).get('etapes_ciblees') or {}
    arbitration = stages.get('arbitrage_documentaire') or {}
    checks = arbitration.get('checks') or {}
    return all(checks.get(key) is True for key in
               ('exemple_explicitement_ecarte', 'preuves_natives', 'classement_etaye'))


def row_presentation(row, analysis):
    semantic = row.get('verification_article') or {}
    resolution = semantic.get('resolution') or {}
    status = row.get('statut_automatique',row.get('statut')) if row.get('revue_utilisateur') else row.get('statut')
    missing = '; '.join(str(x) for x in semantic.get('missing',[]) if x)
    detail = str(resolution.get('detail') or missing or row.get('explication') or 'Motif détaillé non enregistré pour ce point.')
    action = str(row.get('action') or '')
    group, label, colour, bg = 'unresolved','Contrôle non conclu','#854d0e','#fffbeb'
    outcome = semantic.get('outcome')
    required = all((semantic.get('checks') or {}).get(k) is True for k in CHECKS) and all(v is True for v in (semantic.get('checks') or {}).values())
    positive = status == 'critere_auto_respecte' and row.get('comparaison') is True
    negative = status == 'ecart_confirme_sur_critere' and row.get('comparaison') is False
    confirmed = (semantic.get('method') == METHOD and semantic.get('eligible') is True and required
        and row.get('mode_verification') == 'article_verifie'
        and ((positive and outcome == 'respecte') or (negative and outcome == 'ecart')))
    # Retain previously recorded programmed checks, without turning an unverified status into a conclusion.
    programmed = semantic.get('method') != METHOD and ((positive and (row.get('verification_automatique') or {}).get('eligible') is True) or
        (negative and row.get('mode_verification') == 'automatique' and
         (row.get('verification_ecart_automatique') or {}).get('eligible') is True))
    technical = row.get('verification_technique') or {}
    technical_checks = technical.get('checks') or {}
    technical_positive = status == 'critere_technique_respecte' and row.get('comparaison') is True and technical.get('outcome') == 'respecte'
    technical_negative = status == 'ecart_technique_confirme' and row.get('comparaison') is False and technical.get('outcome') == 'ecart'
    technical_confirmed = (technical.get('eligible') is True and bool(technical_checks)
        and all(v is True for v in technical_checks.values())
        and row.get('mode_verification') == 'reference_technique_verifiee'
        and (technical_positive or technical_negative))
    consistency = row.get('verification_coherence') or {}
    consistency_checks = consistency.get('checks') or {}
    consistency_confirmed = (status == 'incoherence_documentaire_confirmee'
        and row.get('mode_verification') == 'coherence_documentaire'
        and consistency.get('confirmed') is True and bool(consistency_checks)
        and all(v is True for v in consistency_checks.values())
        and len(consistency.get('preuves') or []) >= 2)
    conclusion_kind = None
    perimeter = row.get('verification_perimetre_core') or {}
    excluded = (row.get('mode_verification') == 'perimetre_documente' and status == 'hors_perimetre'
        and perimeter.get('method') == 'core_perimetre_texte_et_deux_lectures_image'
        and perimeter.get('eligible') is True and bool(perimeter.get('checks'))
        and all(v is True for v in perimeter['checks'].values()))
    if analysis.get('controle_juridique') is False:
        group,label,colour,bg = 'reading','Passage relevé — lecture seule','#1d4ed8','#eff6ff'
        detail = 'Texte relevé dans le document. Aucun contrôle juridique exécuté.'
        action = ''
    elif row.get('revue_utilisateur'):
        group,label,colour,bg = 'user_confirmations','Respect déclaré par l’utilisateur','#475569','#f1f5f9'
    elif excluded:
        group,label,colour,bg = 'information','Hors opération — exclusion documentée','#475569','#f1f5f9'
        detail = str(row.get('explication') or '')
        action = str(row.get('action') or '')
    elif consistency_confirmed:
        group,label,colour,bg = 'conclusions','Incohérence du dossier confirmée','#991b1b','#fff1f2'
        detail = str(consistency.get('explication') or row.get('explication') or '')
        conclusion_kind = 'coherence'
    elif technical_confirmed:
        group = 'conclusions'
        label,colour,bg = ('Critère technique atteint','#166534','#ecfdf3') if technical_positive else ('Écart au référentiel technique','#991b1b','#fff1f2')
        detail = str(row.get('explication') or technical.get('perimetre') or '')
        conclusion_kind = 'technical'
    elif confirmed or programmed:
        group = 'conclusions'
        label,colour,bg = ('Critère respecté — contrôle automatique','#166534','#ecfdf3') if positive else ('Écart confirmé — contrôle automatique','#991b1b','#fff1f2')
        conclusion_kind = 'legal'
    elif status in ('critere_technique_respecte','ecart_technique_confirme','incoherence_documentaire_confirmee'):
        label = 'Contrôle non conclu'
        detail = 'Les preuves enregistrées ne permettent pas de confirmer ce résultat technique ou documentaire.'
    elif semantic.get('method') == METHOD and outcome == 'erreur_technique':
        group,label = 'interrupted',('Contrôle non démarré' if semantic.get('review_state') == 'not_started' else 'Contrôle interrompu')
    elif (status == 'information_documentaire' and semantic.get('method') == 'core_intention_documentaire'
          and outcome == 'information' and semantic.get('review_state') == 'completed'
          and (semantic.get('checks') or {}).get('citation_native_exacte') is True
          and (row.get('core_control_intent') or {}).get('retained_as_context') is True
          and (row.get('core_control_intent') or {}).get('legal_question_established') is False):
        group,label,colour,bg = 'information','Information de contexte','#475569','#f1f5f9'
        action = ''
    elif semantic.get('method') == METHOD and outcome == 'information' and semantic.get('classification_verifiee') is True:
        group,colour,bg = 'information','#1d4ed8','#eff6ff'
        label = {'contexte':'Information de contexte','recommandation':'Recommandation technique',
            'prescription_technique':'Prescription technique — portée juridique non établie'}.get((row.get('classification_semantique') or {}).get('categorie'),'Information documentaire')
        if excluded_information(row):
            label = 'Information documentaire — exemple écarté'
        if (row.get('mode_verification')=='rattachement_controle'
            and resolution.get('kind')=='controle_deja_effectue' and row.get('core_control_link')):
            label='Prescription reliée au contrôle '+str(row['core_control_link']['target_id'])
    else:
        label = REASONS.get(resolution.get('kind'),'Source juridique insuffisante' if status=='non_verifiable' else 'Contrôle non conclu')
        if resolution.get('kind')=='source_insuffisante' and (row.get('fait') or {}).get('type_fait')=='largeur_cyclable':
            label='Critère de largeur non disponible'
        if not semantic:
            detail = str(row.get('explication') or 'Aucune comparaison juridique concluante enregistrée pour ce point.')
        # A failed proof gate is not a request for the user to supply an unspecified document.
        action = 'Aucune conclusion juridique enregistrée. Motif : ' + detail
    return dict(group=group,label=label,detail=detail,action=action,color=colour,background=bg,
        resolution_kind=({'technical':'conclusion_technique','coherence':'incoherence_documentaire'}.get(conclusion_kind) or resolution.get('kind')),
        requested_inputs=[] if group == 'conclusions' else resolution.get('requested_inputs') or [],
        automatic_conclusion=group == 'conclusions', conclusion_kind=conclusion_kind,
        automatic_outcome=('respecte' if (technical_positive if conclusion_kind == 'technical' else positive)
            and conclusion_kind != 'coherence' else 'ecart') if group == 'conclusions' else None)


def presentation(analysis, workflow_id=None):
    if not is_v6(analysis,workflow_id):
        return None
    rows = analysis.get('lignes') or []
    displays = [row_presentation(row,analysis) for row in rows]
    groups = []
    for key,label in GROUPS:
        ids = [str(row.get('fait',{}).get('id','')) for row,display in zip(rows,displays) if display['group'] == key]
        if ids:
            groups.append(dict(id=key,label=label,ids=ids,count=len(ids)))
    counts = {key:sum(x['group'] == key for x in displays) for key,_ in GROUPS}
    counts.update(total=len(rows),respect=sum(x['group']=='conclusions' and x['automatic_outcome']=='respecte' for x in displays),
        deviations=sum(x['group']=='conclusions' and x['automatic_outcome']=='ecart' for x in displays))
    counts.update({kind:sum(x['group']=='conclusions' and x['conclusion_kind']==kind for x in displays)
                   for kind in ('legal','technical','coherence')})
    return dict(mode='reading' if analysis.get('controle_juridique') is False else 'legal',groups=groups,counts=counts)


def prepared_rows(analysis):
    summary = presentation(analysis)
    if summary is None:
        return analysis['lignes'],None
    rows = []
    for row in analysis['lignes']:
        display=row_presentation(row,analysis)
        if row.get('revue_utilisateur'):
            original={**row,'statut':row.get('statut_automatique',row.get('statut'))}
            original.pop('revue_utilisateur',None)
            display['automatic_label']=row_presentation(original,analysis)['label']
        rows.append({**row,'_presentation':display,'explication':display['detail'],'action':display['action']})
    order = {key:index for index,(key,_) in enumerate(GROUPS)}
    rows.sort(key=lambda row:order[row['_presentation']['group']])
    return rows,summary
