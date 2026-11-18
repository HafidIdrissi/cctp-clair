"""Concise restitution of recorded decisions. No inference or page-count clipping.

Complete evidence remains in preuves_json, journals and interface inspection.
All examination IDs remain in the summary, including uncertain results.
"""
import re
from collections import Counter, OrderedDict
from slm_v6_presentation import row_presentation

LAYOUT_VERSION = 'SYNTHESE-7-DECISIONS'
ACTIONS = {
    'source_insuffisante': 'Rechercher le critère applicable à la clause dans une source datée.',
    'obligation_a_preciser': 'Identifier qui doit agir, sur quel ouvrage et sous quelles conditions.',
    'pertinence_a_etablir': 'Vérifier si le champ de la référence candidate couvre cet ouvrage.',
    'comparaison_non_concluante': 'Vérifier le lien entre la prescription, la preuve et le critère retenu.',
    'critere_contractuel_a_definir': 'Identifier les pièces exigées et vérifier leur remise à l’échéance prévue.',
    'lecture_invalide': 'Reprendre la lecture de la page et vérifier la citation sur le document.',
    'interruption': 'Examiner le journal technique et reprendre le contrôle interrompu.',
}


def short(value, size=230):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if len(text) <= size:
        return text
    prefix = text[:size - 1]
    return prefix.rsplit(' ', 1)[0] + '…' if ' ' in prefix else prefix + '…'


def reference_title(key):
    title = ' '.join(key[2].split())
    article = key[3] if re.match(r'(art\.|article|page)\s', key[3], re.I) else 'article ' + key[3]
    return title + (' · ' + article if key[3] and not title.casefold().endswith(article.casefold()) else '')


def criterion_reason(row, display):
    """Explain a recorded verdict; examples below only apply to the bound text version."""
    fallback = short(display.get('detail'), 500)
    if display.get('group') != 'conclusions' or display.get('conclusion_kind') != 'legal':
        return fallback
    fact = row.get('fait') or {}
    binding = ((row.get('verification_article') or {}).get('etapes_ciblees') or {}).get('critere_programme_retrouve') or {}
    kind = fact.get('type_fait')
    if not (binding.get('eligible') is True and binding.get('type_fait') == kind and
            binding.get('source_id') == (row.get('source') or {}).get('id') == 'LEGIARTI000049320039'):
        return fallback
    rule = ' '.join(str(row.get('regle') or '').lower().split())
    positive = display['automatic_outcome'] == 'respecte'
    if kind == 'bande_eveil' and not positive and 'est implantée' in rule and 'traversées matérialisées' in rule and 'aucune' in str(fact.get('citation_visible') or '').lower():
        return 'Le CCTP ne prévoit aucune bande d’éveil de vigilance à cette traversée matérialisée. Le texte impose une bande pour signaler la traversée aux personnes aveugles ou malvoyantes.'
    value, unit = fact.get('valeur'), fact.get('unite')
    for m in re.finditer(r'(?<![\w.,])([0-9]+(?:[.,][0-9]+)?)\s*(mm|cm|m|%)(?!\w)', str(fact.get('citation_visible') or '')):
        if unit != m[2] or value != float(m[1].replace(',', '.')): continue
        v = m[1].replace('.', ',') + ' ' + unit
        metres = value * {'mm':.001, 'cm':.01, 'm':1}.get(unit, 0)
        if kind == 'largeur_pieton' and unit != '%' and '1,40 mètre' in rule and '1,20 mètre' in rule and not positive and metres < 1.20:
            return f'La largeur prévue est de {v}. Le minimum est de 1,40 m ; même le minimum réduit de 1,20 m, admis en l’absence de mur ou d’obstacle de part et d’autre, n’est pas atteint.'
        if kind == 'devers_pieton' and unit == '%' and 'dévers est inférieur ou égal à 2 %' in rule and positive == (value <= 2):
            return f'Le dévers prévu est de {v}. En cheminement courant, le maximum autorisé est de 2 %.'
        if kind == 'fente_grille' and unit != '%' and 'inférieurs à 2 centimètres' in rule and positive == (metres < .02):
            return f'Les fentes de la grille mesurent {v}. Leur largeur doit être strictement inférieure à 2 cm.'
        if kind == 'pente_longitudinale' and unit == '%' and 'inférieure à 5 %' in rule and positive and value < 5:
            return f'La pente longitudinale prévue est de {v}, en dessous du seuil ordinaire de 5 % fixé par le texte. Ce contrôle porte sur la pente seule.'
        if kind == 'ressaut' and unit != '%' and '2 centimètres' in rule and '4 centimètres' in rule and not positive and metres > .04:
            return f'Le ressaut prévu mesure {v}. Le maximum est de 2 cm, ou de 4 cm avec le chanfrein prévu par le texte. Les deux limites sont dépassées.'
    return fallback


def summary(readings, analysis):
    """Build a presentation only; never rewrite statuses or evidence."""
    items = []
    sources = OrderedDict()
    for row in analysis.get('lignes', []):
        fact = row.get('fait') or {}
        display = row_presentation(row, analysis)
        review = row.get('revue_utilisateur') or {}
        if review:
            original = dict(row, statut=row.get('statut_automatique'))
            original.pop('revue_utilisateur', None)
            initial = row_presentation(original, analysis)
            if initial['group'] == 'conclusions':
                display = initial  # Preserve a proven finding beside the separate declaration.
        source = row.get('source') or {}
        stages = (row.get('verification_article') or {}).get('etapes_ciblees') or {}
        binding = stages.get('critere_programme_retrouve') or {}
        selected_id = (stages.get('selection') or {}).get('passage_id')
        selected = next((p for p in stages.get('candidats') or [] if selected_id and p.get('id') == selected_id), {})
        compared = bool(selected and stages.get('comparaisons'))
        if selected and (not source or (compared and source.get('id') != selected.get('source_id'))):
            source = dict(id=selected.get('source_id'), titre=selected.get('titre'), numero=selected.get('numero'))
        ref = ''
        # Sources for pending controls are candidates, not validated applicability.
        if source:
            key = (str(source.get('id') or source.get('url') or source.get('source_url') or ''),
                   str(source.get('date_debut') or source.get('debut') or ''),
                   str(source.get('nom_code') or source.get('titre') or 'Source enregistrée'),
                   str(source.get('numero') or row.get('article') or ''))
            if key not in sources:
                sources[key] = 'S' + str(len(sources) + 1)
            ref = sources[key]
        law = reference_title(key) if ref else ''
        if ref and binding.get('source_id') == source.get('id') and binding.get('article'):
            article = str(binding['article'])
            coarse = re.search(r'\s+[-·]\s+article\s+(\d+)\s*$', law, re.I)
            if coarse and re.match(r'art\.\s*'+coarse[1]+r'(?=\s*,|$)', article, re.I):
                law = law[:coarse.start()] + ', ' + article
            else:
                law += ' (' + article + ')'
        elif ref and compared and selected.get('intitule_section'):
            law += ' · ' + short(str(selected['intitule_section']).split(':', 1)[0], 85)
        if ref and key[1]:
            law += ' · version du ' + key[1]
        kind = display.get('resolution_kind') or 'motif_non_precise'
        if display['group'] == 'unresolved' and kind in ('conclusion', 'conclusion_technique'):
            # A stale internal resolution cannot overrule a failed final gate.
            kind = 'comparaison_non_concluante'
        items.append(dict(id=str(fact.get('id') or '?'), page=str(fact.get('page') or '?'),
            subject=short(fact.get('citation_visible') or fact.get('information') or fact.get('element'), 190),
            detail=short(display['detail'], 330), label=(display['detail'] if
                display['group'] == 'information' and (row.get('core_control_intent') or {}).get('plans_verifies')
                else display['label']), group=display['group'],
            follow_up=short(row.get('suivi_redactionnel') or display['detail'], 280),
            why=criterion_reason(row, display), review=review,
            law=law, compared=compared, conclusion_kind=display.get('conclusion_kind'),
            rule=row.get('regle') or (selected.get('texte') if compared else ''),
            outcome=display.get('automatic_outcome'), reason=kind, source=ref))
    counts = Counter(x['group'] for x in items)
    counts['respect'] = sum(x['group'] == 'conclusions' and x['outcome'] == 'respecte' for x in items)
    counts['ecarts'] = sum(x['group'] == 'conclusions' and x['outcome'] == 'ecart' for x in items)
    return dict(items=items, sources=sources, counts=counts)


def dossier_verdict(data, analysis):
    items, c = data['items'], data['counts']
    deviations = [x for x in items if x['group'] == 'conclusions' and x['outcome'] == 'ecart']
    legal = [x for x in deviations if x['conclusion_kind'] == 'legal']
    if analysis.get('controle_juridique') is False:
        return 'Lecture seule — conformité non évaluée', 'Aucun contrôle juridique demandé.', None
    if deviations:
        first = (legal or deviations)[0]
        scope = 'réglementaires contrôlés' if legal else 'techniques contrôlés' if first['conclusion_kind']=='technical' else 'de cohérence du dossier'
        return 'CCTP non conforme sur les critères ' + scope, f"Page {first['page']} ({first['id']}) : {first['why']}", first
    if c['unresolved'] or c['interrupted'] or c['user_confirmations'] or not c['respect']:
        return 'Conformité du CCTP à établir', ('Des vérifications restent à terminer ; aucun écart confirmé ne permet de déclarer le dossier non conforme.' if c['unresolved'] or c['interrupted'] else 'Les éléments disponibles ne permettent pas de rendre un verdict automatique sur le dossier.'), None
    return 'CCTP conforme sur les seuls critères contrôlés', 'Tous les critères contrôlés sont respectés. Le détail ci-dessous indique pour chacun la prescription et la règle appliquée.', None


def sections(readings, analysis):
    data = summary(readings, analysis)
    items, counts = data['items'], data['counts']
    blocks = []
    def prose(text): blocks.append(('text', text))
    def heading(text, tone='neutral'): blocks.append(('heading', (text, tone)))
    def table(headers, rows, widths, tone='neutral'):
        if rows: blocks.append(('table', (headers, rows, widths, tone)))
    verdict, why, first = dossier_verdict(data, analysis)
    tone = ('fail' if first else 'info' if analysis.get('controle_juridique') is False
            else 'pass' if verdict.startswith('CCTP conforme') else 'wait')
    blocks.append(('verdict', (verdict, why, first['law'] if first else '', tone)))
    if analysis.get('controle_juridique') is False:
        prose('Lecture seule : aucun contrôle juridique exécuté.')
    else:
        blocks.append(('metrics', [(counts['ecarts'], 'Non conformes', 'fail'),
            (counts['respect'], 'Conformes', 'pass'),
            (counts['information'], 'Repères du dossier', 'neutral')]))
    totals = [f"{len(items)} points recensés"]
    if counts['user_confirmations']: totals.append(f"{counts['user_confirmations']} déclaration(s) utilisateur distincte(s)")
    if counts['reading']: totals.append(f"{counts['reading']} passage(s) en lecture seule")
    blocks.append(('note', ' · '.join(totals)+'. Chaque décision porte sur le critère cité.'))
    if counts['unresolved'] or counts['interrupted']:
        blocks.append(('note', 'Les passages sans décision sont conservés en annexe et ne sont pas comptés comme conformes.'))
    ordered = sorted((x for x in items if x['group']=='conclusions'), key=lambda x:x['outcome']!='ecart')
    if len(ordered)>1:
        heading('Les décisions en un coup d’œil')
        blocks.append(('overview', ordered))
    for outcome, title, tone in [('ecart', 'Critères non conformes', 'fail'), ('respecte', 'Critères conformes', 'pass')]:
        selected = [x for x in ordered if x['outcome']==outcome]
        if selected:
            heading(title, tone)
            for x in selected:
                blocks.append(('finding', x))
    info = [x for x in items if x['group'] == 'information']
    if info:
        heading('Informations documentaires — aucun verdict de conformité')
        table(['Point / page', 'Extrait conservé', 'Nature'],
              [[x['id'] + ' / p. ' + x['page'], x['subject'], x['label']] for x in info], [0.17, 0.61, 0.22])
    other = [x for x in items if x['group'] in ('reading', 'user_confirmations')]
    if other:
        heading('Lecture et déclarations de l’utilisateur')
        table(['Point / page', 'Extrait', 'Nature'],
              [[x['id'] + ' / p. ' + x['page'], x['subject'], x['label']] for x in other], [0.17, 0.56, 0.27])
    for x in items:
        if x['review']:
            r = x['review']
            heading('Déclaration de relecture · ' + x['id'])
            prose('Respect déclaré par ' + str(r.get('reviewer') or 'l’utilisateur') + ' · ' + str(r.get('at') or 'date non renseignée'))
            if r.get('note'): prose(str(r['note']))
    if data['sources']:
        heading('Références juridiques et techniques', 'info')
        table(['Réf.', 'Texte et article', 'Version / identifiant'],
              [[ref, reference_title(key),
                (key[1] or 'Date non renseignée') + ' · ' + short(key[0], 100)]
               for key, ref in data['sources'].items()], [0.08, 0.64, 0.28], 'info')
    heading('Limites et accès au détail')
    version = analysis.get('workflow_version') or analysis.get('revision')
    if version: blocks.append(('note', 'Version du moteur enregistrée : ' + str(version)))
    if analysis.get('note_de_relecture'): prose(analysis['note_de_relecture'])
    prose('Les passages cités sont des extraits synthétiques. Les preuves, prompts et réponses sont accessibles dans l’inspection, par identifiant.')
    prose('La couverture du document et des annotations visuelles n’est pas présumée exhaustive. '
          'Une valeur reconnue sur un plan doit encore être rattachée au bon ouvrage et à ses conditions. '
          'Consulter l’inspection pour les preuves et blocages de chaque point, sans nouvelle analyse.')
    # Deduplicate limitations instead of reproducing per-control boilerplate.
    for limit in dict.fromkeys(str(x) for x in analysis.get('limites', [])):
        prose(short(re.sub(r'\bnon conclu(?:s|e|es)?\b', 'à vérifier', limit, flags=re.I), 420))
    pending = [x for x in items if x['group'] in ('unresolved', 'interrupted')]
    if pending:
        blocks.append(('annex_start', 'Annexe · Passages sans décision'))
        prose('Le registre distingue les textes effectivement comparés et les sources candidates. Chaque ligne précise le travail à terminer avant de statuer.')
        for reason in dict.fromkeys('interruption' if x['group'] == 'interrupted' else x['reason'] for x in pending):
            affected = [x for x in pending if ('interruption' if x['group'] == 'interrupted' else x['reason']) == reason]
            blocks.append(('subheading', ACTIONS.get(reason, 'Examiner le motif enregistré et compléter la vérification.')))
            table(['Point / page', 'Passage du CCTP', 'Texte et article', 'Suite proposée'],
                  [[x['id'] + ' / p. ' + x['page'], x['subject'],
                    (('Texte comparé : ' if x['compared'] else 'Source candidate : ') + x['law'])
                    if x['law'] else 'Aucune référence retenue enregistrée.',
                    ('Contrôle interrompu. ' if x['group'] == 'interrupted' else '') +
                    re.sub(r'\bnon conclu(?:s|e|es)?\b', 'à vérifier', x['follow_up'], flags=re.I)]
                   for x in affected], [0.14, 0.28, 0.29, 0.29])
        blocks.append(('annex_end', None))
    return blocks


def html_report(readings, analysis, format_report=None):
    from slm_core_report_style import render_html
    return render_html(readings, analysis, sections(readings, analysis))


def pdf_report(readings, analysis, format_report=None):
    from slm_core_report_style import render_pdf
    return render_pdf(readings, analysis, sections(readings, analysis))
