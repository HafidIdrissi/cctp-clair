"""Readable report presentation. It renders existing findings without re-evaluating them."""
import base64
import io
import re
from collections import Counter
from datetime import datetime
from html import escape
from urllib.parse import urlsplit
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak, CondPageBreak, Image as RLImage

LAYOUT_VERSION = 'Lecture-2026.10.18-retour-annexe-parent-r6'


def general_core(analysis):
    return bool(analysis.get('core_atomization'))


def urban_for_report(readings,analysis):
    urban=analysis.get('revue_mobilite_urbaine')
    if general_core(analysis):
        native='\n'.join(readings.get('text',[]))
        if not re.search(r'\b(?:voirie|voie[s]? urbaine[s]?|trottoir[s]?|cheminement[s]? pi[ée]ton[s]?|piste[s]? cyclable[s]?|am[ée]nagement[s]? cyclable[s]?|passage[s]? pi[ée]ton[s]?)\b',native,re.I):
            return None
    return urban


def document_value(fact):
    from v4_9_report import value
    if (fact.get('core_native_span') or fact.get('core_atom')) and not (fact.get('valeur_inscrite') or fact.get('information')):
        return 'Passage écrit du document'
    return value(fact)


def document_title(fact):
    from v4_9_report import title
    if fact.get('core_native_span') or fact.get('core_atom'):
        heading=(fact.get('core_atom') or {}).get('heading') or fact.get('citation_visible','').split('\n')[0].strip()
        if heading and len(heading)<=140:return heading
    return title(fact)


def report_limits(analysis):
    limits=list(analysis.get('limites',[]))
    if general_core(analysis) and limits and limits[0].startswith('Contrôles programmés de voirie'):
        limits[0]='Le catalogue de voirie est complété par la recherche et la comparaison de critères hors catalogue. La couverture de tout contrat nouveau n’est pas démontrée.'
    return limits


def native_coverage(readings):
    from v4_9_report import coverage_text
    text=coverage_text(readings)
    if readings.get('core_native_inventory'):
        pages=readings.get('text',[])
        text='Texte natif présent sur '+str(sum(bool(str(p).strip()) for p in pages))+' page(s) sur '+str(len(pages))+'. '+text
    return text


def context_lines(readings,analysis):
    from v4_9_report import context_text
    if general_core(analysis) and urban_for_report(readings,analysis) is None:
        return ['Le champ de chaque critère est examiné avec les passages cités du dossier et les rubriques juridiques ; les indices de voirie ne définissent pas le domaine de ce document.']
    return context_text(analysis)
INK = '#172b3a'
MUTED = '#475569'
NAVY = '#1d4ed8'
LINE = '#c4cdd6'
BLUE_SOFT = '#eff6ff'
LEGEND = [
    ('Écart confirmé', '#991b1b', 'Le contrôle a confirmé un écart sur le critère présenté.'),
    ('À vérifier', '#854d0e', 'Écart potentiel, source ou conditions à vérifier avant de conclure.'),
    ('Respect confirmé', '#166534', 'Respect du critère confirmé ; le libellé précise contrôle automatique ou déclaration utilisateur.'),
    ('Information', NAVY, 'Point technique à examiner, sans obligation légale démontrée.'),
    ('Hors contrôle', MUTED, 'Lecture rejetée ou périmètre déclaré à confirmer.')]


def report_identity(analysis):
    """Identify the recorded producer, independently of today's default workflow."""
    origin = analysis.get('report_origin') or {}
    workflow = origin.get('workflow_id') or ''
    version = str(analysis.get('workflow_version') or analysis.get('revision') or '')
    labels = {'SlmSemanticTestV6':'V6 · comparaison sémantique · test',
              'SlmM3DilaCompare':'V4.9 + DILA + comparaison · Ministral 3B',
              'SlmDilaWebV5':'V5 · DILA local', 'CctpWebInterface49':'V4.9 · revue documentaire'}
    if workflow in labels:
        label = labels[workflow]
    elif version.startswith('V6'):
        label = labels['SlmSemanticTestV6']
    elif version.startswith('V5'):
        label = labels['SlmDilaWebV5']
    elif version:
        label = version
    else:
        label = 'Version non enregistrée'
    identity = ['Workflow utilisé : ' + label + (' (' + workflow + ')' if workflow else '')]
    execution = origin.get('n8n_execution_id')
    valid_execution = type(execution) is int and execution > 0 or isinstance(execution,str) and re.fullmatch(r'[1-9][0-9]{0,14}',execution)
    previous=str(origin.get('continuation_of_execution',''))
    if not valid_execution and origin.get('local_journal') and re.fullmatch(r'[1-9][0-9]{0,14}',previous):
        identity.append('Reprise locale de l’exécution source '+previous+' ; aucune nouvelle exécution n8n.')
    else:identity.append('Exécution n8n : ' + (str(execution) if valid_execution else 'identifiant non enregistré'))
    if origin.get('job_id'):
        identity.append('Rapport local : ' + str(origin['job_id']))
    if origin.get('created_at'):
        identity.append('Analyse lancée : ' + str(origin['created_at']))
    return identity


def result_totals(rows):
    counts = Counter(row['statut'] for row in rows)
    confirmed = sum(counts[key] for key in ('validation_utilisateur', 'critere_atteint', 'critere_auto_respecte'))
    information = sum(counts[key] for key in ('technique', 'lecture_rejetee', 'hors_perimetre'))
    deviation = counts['ecart_confirme_sur_critere']
    return dict(total=len(rows), deviation=deviation, confirmed=confirmed, information=information,
                pending=len(rows)-confirmed-information-deviation)


def clean(text):
    return str('' if text is None else text).replace('\u2011', '-').replace('\u2013', '-').replace('\u2014', '-')


def short(text, size=800):
    text = clean(text)
    return text if len(text) <= size else text[:size].rsplit(' ', 1)[0] + '…'


def label(row):
    from v4_9_report import LABELS
    if row.get('_presentation'):
        display=row['_presentation']
        return display['label'],display['color'],display['background']
    semantic=row.get('verification_article') or {}
    if semantic.get('method')=='comparaison_semantique_v6' and not row.get('revue_utilisateur'):
        if semantic.get('outcome')=='erreur_technique':
            return ('Contrôle interrompu — à reprendre', '#854d0e', '#fffbeb')
        if semantic.get('outcome')=='information':
            category=(row.get('classification_semantique') or {}).get('categorie')
            return ({'contexte':'Contexte — sans verdict juridique','recommandation':'Recommandation technique',
                'prescription_technique':'Prescription technique — portée juridique non établie'}.get(category,'Information documentaire'),NAVY,BLUE_SOFT)
        if semantic.get('outcome')=='indetermine':
            return ('Contrôle non conclu', '#854d0e', '#fffbeb')
    return LABELS.get(row['statut'], LABELS['a_verifier'])


def status_help(row):
    """Explain the existing status without introducing a new legal conclusion."""
    if row.get('_presentation'):
        return row['_presentation']['detail']
    semantic=row.get('verification_article') or {}
    if semantic.get('method')=='comparaison_semantique_v6' and semantic.get('outcome')=='information':
        if semantic.get('basis')=='structure_documentaire':
            return 'Entrée de sommaire reconnue par sa structure et sa citation dans le document. Aucun appel de comparaison ou de contre-lecture du modèle pour ce classement. Aucun respect juridique n’est déduit de cette classification.'
        return 'Passage classé après comparaison et contre-lecture. '+str((row.get('classification_semantique') or {}).get('raison',''))+' Aucun respect juridique n’est déduit de cette classification.'
    if row.get('mode_verification')=='article_verifie' and row['statut']=='critere_auto_respecte':
        return 'Respect de ce critère documentaire confirmé à partir de l’article retrouvé : citations vérifiées, comparaison contrôlée et contre-lecture automatisée. Ce résultat ne certifie pas l’ensemble du contrat.'
    if row.get('verification_article') and row['statut']=='a_verifier':
        missing=row['verification_article'].get('missing') or []
        return 'Pourquoi ce point n’est pas confirmé : '+(' ; '.join(missing) if missing else 'comparaison à l’article non concluante.')
    if row['statut']=='ecart_confirme_sur_critere' and row.get('mode_verification')=='automatique':
        return 'Écart confirmé automatiquement sur ce critère : la donnée, les conditions et la version de la règle sont vérifiées. Ce résultat ne porte pas sur tout le contrat.'
    return {
        'ecart_potentiel': 'Le document semble contredire la règle examinée. Vérifiez le passage et les conditions de cette règle avant de demander une correction.',
        'ecart_confirme_sur_critere': 'La comparaison vérifiée relève un non-respect de ce critère précis. Cela ne constitue pas un avis sur l’ensemble du contrat.',
        'validation_utilisateur': 'Vous avez confirmé le respect de ce point. Votre déclaration est enregistrée ; le résultat automatique est conservé ci-dessous.',
        'critere_atteint': 'Ce critère précis a été vérifié et est respecté. Les autres obligations ne sont pas couvertes par cette confirmation.',
        'critere_auto_respecte': 'Le contrôle automatique a retrouvé la valeur dans le texte original, une règle datée et les conditions prévues pour ce critère. La valeur du projet respecte ce critère ; les autres obligations et l’ouvrage réalisé ne sont pas vérifiés.',
        'critere_a_confirmer': 'La valeur relevée entre dans le seuil étudié, mais ses conditions d’application ne sont pas encore confirmées.',
        'non_verifiable': 'Il manque une source juridique suffisante pour comparer ce point. On ne peut dire ni conforme ni non conforme.',
        'a_verifier': 'Les éléments disponibles ne permettent pas encore de dire si ce point respecte la règle.',
        'lecture_rejetee': 'La lecture a été rejetée. Elle ne permet pas de conclure sur ce point.',
        'technique': 'Il s’agit d’un point technique de conception, pas d’une obligation légale démontrée.',
        'hors_perimetre': 'Ce point est déclaré hors des travaux. Ce périmètre doit encore être vérifié.',
    }.get(row['statut'], 'Des éléments complémentaires sont nécessaires pour conclure.')


def reviewed_text(row):
    review = row.get('revue_utilisateur')
    if not review:
        return ''
    try:
        when = datetime.fromisoformat(review['at']).astimezone().strftime('%d/%m/%Y à %H:%M')
    except (ValueError, KeyError):
        when = review.get('at', '')
    return 'Confirmation de ' + review['reviewer'] + ', le ' + when + '.'


def automatic_label(row):
    from v4_9_report import LABELS
    return (row.get('_presentation') or {}).get('automatic_label') or LABELS.get(row.get('statut_automatique'),LABELS['a_verifier'])[0]


def source_info(row):
    from slm_source_display import source_display
    display = source_display(row)
    if display['kind'] == 'missing':
        return display['title'], None, ''
    if row.get('mode_verification') == 'perimetre_documente':
        return display['title'], None, ' · '.join(display['metadata']) + ' · ' + display['note']
    from slm_v6_presentation import documentary_information
    if documentary_information(row):
        return 'Classement fondé sur les passages du dossier.', None, 'Aucune source juridique utilisée pour ce classement documentaire.'
    if row.get('mode_verification') == 'coherence_documentaire':
        proof = row.get('verification_coherence') or {}
        pages = sorted({str(p.get('page')) for p in proof.get('preuves', []) if p.get('page') is not None})
        return 'Passages du dossier — pages ' + ', '.join(pages), None, 'Contrôle de cohérence documentaire ; aucune source juridique utilisée pour ce constat.'
    if row.get('mode_verification') == 'reference_technique_verifiee':
        from slm_source_display import reference_url
        ref = (row.get('verification_technique') or {}).get('reference') or {}
        title = str(ref.get('titre') or 'Référence technique du projet')
        version = 'Édition : ' + str(ref.get('date') or 'date non précisée')
        if ref.get('page') is not None: version += ' · page ' + str(ref['page'])
        return title, reference_url(ref.get('sha256'), ref.get('page')), version + ' · copie PDF locale utilisée'
    source = row.get('source') or {}
    url = source.get('url') or source.get('source_url') or ''
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'www.legifrance.gouv.fr':
        url = None
    title = source.get('titre') or source.get('nom_code') or 'Texte officiel'
    article = row.get('article') or source.get('numero') or ''
    if article and str(article).casefold() not in title.casefold():
        title += ' - ' + (str(article) if str(article).lower().startswith('art') else 'article ' + str(article))
    channel = source.get('canal') or {'dila_open_data':'DILA open data — copie locale','piste_sandbox':'PISTE · environnement sandbox'}.get(source.get('provenance'),'')
    return title, url, 'Version depuis le ' + str(source.get('debut') or source.get('date_debut') or 'date non précisée') + (' · Origine : ' + str(channel) if channel else '')


def source_heading(row):
    if row.get('mode_verification') == 'perimetre_documente':
        return 'Preuve du périmètre des travaux'
    from slm_source_display import source_display
    if source_display(row)['kind'] == 'missing':
        return 'Source du contrôle non établie'
    from slm_v6_presentation import documentary_information
    if documentary_information(row):
        return 'Preuve documentaire'
    return {'coherence_documentaire':'Passages du dossier',
            'reference_technique_verifiee':'Référence technique'}.get(row.get('mode_verification'), 'Règle et source juridique')


def source_evidence(row):
    """Readable documentary proofs, without presenting them as statutes."""
    if row.get('mode_verification') == 'coherence_documentaire':
        check = row.get('verification_coherence') or {}
        entries = check.get('preuves', []) + check.get('preuves_meme_perimetre', []) + check.get('preuves_absence_priorite', [])
        seen, lines = set(), []
        for entry in entries:
            key = (entry.get('page'), entry.get('citation'))
            if key in seen or not key[1]: continue
            seen.add(key)
            lines.append('Document p. ' + str(key[0]) + ' : « ' + str(key[1]) + ' »')
        return lines
    if row.get('mode_verification') == 'reference_technique_verifiee':
        check = row.get('verification_technique') or {}
        ref = check.get('reference') or {}
        lines = [str(check['perimetre'])] if check.get('perimetre') else []
        if ref.get('application') and isinstance(ref['application'],str): lines.append(ref['application'])
        elif isinstance(ref.get('application'), dict):
            application=ref['application']
            for evidence in application.get('evidence', []):
                if evidence.get('citation'):
                    lines.append('Référence retenue dans le dossier, p. '+str(evidence.get('page'))+' : « '+str(evidence['citation'])+' »')
            if application.get('limitation'):lines.append(str(application['limitation']))
        limits = check.get('limites') or []
        lines += [str(item) for item in limits] if isinstance(limits,list) else [str(limits)]
        return lines
    from slm_source_display import source_display
    display = source_display(row)
    if row.get('mode_verification') == 'perimetre_documente' and display['excerpt']:
        passage = ' '.join(re.split(r'\n\s*\n', display['excerpt'], maxsplit=1)[0].split())
        return ['Texte du périmètre, document p. ' + str((row.get('verification_perimetre_core') or {}).get('native_scope',{}).get('page')) + ' : « ' + passage + ' »']
    if display['kind'] == 'legal' and display['excerpt']:
        return ['Passage de l’article conservé : « ' + display['excerpt'] + ' »']
    return []


def report_rows(analysis, readings):
    """Presentation only: replay current reading evidence; retain old warnings as history."""
    from slm_v6_presentation import prepared_rows
    from slm_core_perimeter import verify as perimeter_verified
    from slm_v6_visual_evidence import verified, page_for, page_material
    rows, summary = prepared_rows(analysis)
    rendered = []
    for original in rows:
        row = dict(original)
        fact = row['fait']; proof = row.get('verification_perimetre_core') or {}
        if fact.get('core_atom'):
            from slm_core_atoms import binding
            bound=binding(fact,readings)
            if bound:row['_report_parent']=bound
        if row.get('mode_verification') == 'perimetre_documente' and perimeter_verified(fact, readings, proof):
            material = page_material(page_for(fact, readings))
            cited = set()
            for observation in proof['observations']:
                for key in ('citation_ids', 'repere_ids', 'etat_ids'):
                    cited.update(observation.get(key, []))
            quote = '\n'.join(text for key, text in material['lines'].items() if key in cited)
            row['_report_excerpt'] = ('Lecture du repère vérifiée pour établir le périmètre', quote)
            row['_report_reading_state'] = 'Le périmètre est maintenant vérifié par le texte, la ligne OCR et deux lectures image. Aucun verdict juridique sur l’existant.'
        elif fact.get('origine') == 'ministral_vision' and verified(fact, readings):
            row['_report_reading_state'] = 'Le rattachement de l’annotation à cet objet est maintenant vérifié. Le résultat du contrôle figure séparément.'
        rendered.append(row)
    return rendered, summary


def report_excerpt(row):
    from v4_9_report import excerpt
    return row.get('_report_excerpt') or excerpt(row['fait'])


def reading_notes(row):
    history = ' '.join(row['fait'].get('rectifications_automatiques') or [])
    current = row.get('_report_reading_state')
    if current and history:
        return 'Historique de la lecture initiale (avant la reprise) : ' + history + ' État actuel : ' + current
    return history


def semantic_activity_text(analysis):
    review = analysis.get('verification_articles') or {}
    text = ('Traitements du modèle : ' + str(review.get('evaluated', 0)) +
            ' points (classement, recherche du critère ou comparaison).')
    details = [(row.get('verification_article') or {}).get('etapes_ciblees') for row in analysis.get('lignes', [])]
    if any(isinstance(item, dict) for item in details):
        count = sum(bool((item or {}).get('comparaisons')) for item in details)
        technical_count = sum(bool((row.get('verification_technique') or {}).get('audits')) for row in analysis.get('lignes',[]))
        text += ' Comparaisons à un critère enregistrées : ' + str(count + technical_count) + ' (' + str(count) + ' juridiques, ' + str(technical_count) + ' techniques).'
    usage=review.get('piste_usage')
    if usage:
        prefix=' Recherche documentaire PISTE : ' if review.get('catalogue_recovery') else ' Complément PISTE après comparaison : '
        text+=prefix+str(usage.get('calls',0))+' appels au relais, '+str(usage.get('cache_hits',0))+' réponses réutilisées, '+str(usage.get('errors',0))+' erreurs.'
    return text + ' Traces et motifs disponibles dans l’inspection.'


def conclusion_kinds_text(counts):
    return ('Nature des conclusions : ' + str(counts.get('legal', 0)) + ' contrôles juridiques, '
            + str(counts.get('technical', 0)) + ' contrôles techniques, '
            + str(counts.get('coherence', 0)) + ' constats de cohérence documentaire.')


def styles():
    if 'CctpArial' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('CctpArial', 'C:/Windows/Fonts/arial.ttf'))
        pdfmetrics.registerFont(TTFont('CctpArialBold', 'C:/Windows/Fonts/arialbd.ttf'))
        pdfmetrics.registerFontFamily('CctpArial', normal='CctpArial', bold='CctpArialBold', italic='CctpArial', boldItalic='CctpArialBold')
    body = ParagraphStyle('Text', fontName='CctpArial', fontSize=12, leading=18,
                          textColor=colors.HexColor(INK), spaceAfter=8, splitLongWords=True)
    return {name: ParagraphStyle(name, parent=body, **args) for name, args in {
        'Text': {}, 'Meta': dict(fontSize=11, leading=16, textColor=colors.HexColor(MUTED)),
        'Title': dict(fontName='CctpArialBold', fontSize=26, leading=32, spaceAfter=14, keepWithNext=True),
        'Heading': dict(fontName='CctpArialBold', fontSize=17, leading=22, spaceBefore=12, spaceAfter=10, keepWithNext=True),
        'QuoteMeta': dict(fontSize=11, leading=16, textColor=colors.HexColor(MUTED), keepWithNext=True),
        'Point': dict(fontName='CctpArialBold', fontSize=15, leading=20, spaceAfter=10),
        'Label': dict(fontName='CctpArialBold', fontSize=11, leading=15, textColor=colors.HexColor(NAVY), spaceBefore=10, spaceAfter=5),
        'Cell': dict(fontSize=11, leading=16, spaceAfter=6),
        'Measure': dict(fontName='CctpArialBold', fontSize=19, leading=25, spaceAfter=8),
        'Stat': dict(fontName='CctpArialBold', fontSize=22, leading=27, spaceAfter=3),
    }.items()}


def pdf_report(readings, analysis, format_report):
    from v4_9_report import excerpt, LABELS, DEFINITIONS, coverage_text, fallback_text, context_text
    title,value=document_title,document_value
    from slm_v6_presentation import prepared_rows
    rows,presentation = report_rows(analysis, readings)
    reading_only = bool(presentation and presentation['mode']=='reading')
    groups = {group['id']:group for group in (presentation or {}).get('groups',[])}
    fmt_table = format_report == 'tableau'
    page_size = landscape(A4) if fmt_table else A4
    width = page_size[0] - 96
    s = styles()
    def p(text, style='Text'):
        return Paragraph(escape(clean(text)).replace('\n', '<br/>'), s[style])
    def link(text, url, style='Meta'):
        return Paragraph('<link href="' + escape(url, quote=True) + '" color="' + NAVY + '">' + escape(clean(text)) + '</link>', s[style])
    def box(content, colour=LINE, bg='#ffffff', padding=14, available_width=None):
        t = Table([[content]], colWidths=[available_width or width], splitInRow=1, hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor(bg)),
            ('LINEBEFORE',(0,0),(0,-1),4,colors.HexColor(colour)),
            ('BOX',(0,0),(-1,-1),.5,colors.HexColor(LINE)),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),padding),
            ('RIGHTPADDING',(0,0),(-1,-1),padding),('TOPPADDING',(0,0),(-1,-1),padding),
            ('BOTTOMPADDING',(0,0),(-1,-1),padding)]))
        return t
    def badge(row, small=False, summary=False):
        text,col,bg=label(row)
        if summary and not presentation:
            text={
                'ecart_confirme_sur_critere':'Écart confirmé sur ce critère',
                'ecart_potentiel':'Écart potentiel',
                'critere_auto_respecte':'Respect confirmé automatiquement',
                'validation_utilisateur':'Respect déclaré par l’utilisateur',
                'critere_atteint':'Respect confirmé sur ce critère',
                'critere_a_confirmer':'Conditions à confirmer',
                'a_verifier':'À vérifier', 'non_verifiable':'Source insuffisante',
                'technique':'Point technique', 'lecture_rejetee':'Lecture rejetée',
                'hors_perimetre':'Périmètre à confirmer',
            }.get(row['statut'],text)
        st=ParagraphStyle('Status',parent=s['Cell' if small else 'Text'],fontName='CctpArialBold',
            textColor=colors.white,backColor=colors.HexColor(col),borderPadding=6,spaceBefore=6,spaceAfter=12)
        return Paragraph(escape(clean(text)),st)
    totals = result_totals(rows)
    flow = [p('SLM JURIDIQUE / REVUE DOCUMENTAIRE', 'Label'), p('Rapport d’analyse du CCTP', 'Title'),
        p(readings.get('filename', 'Document'), 'Point'),
        p('Date juridique de référence : ' + analysis['date_reference'] + '   |   Format : ' + ('tableau' if fmt_table else 'cartes'), 'Meta'), Spacer(1,16)]
    flow += [p(line,'Meta') for line in report_identity(analysis)]
    flow.append(Spacer(1,12))
    if analysis.get('controle_juridique') is False:
        flow += [box([p('LECTURE SEULE — AUCUN CONTRÔLE JURIDIQUE EXÉCUTÉ','Label'),
            p('Les passages du document ont été relevés. Aucune comparaison juridique ni conclusion de conformité n’a été réalisée.'+('' if presentation else ' Les mentions « à vérifier » concernent les données et leur lecture.'))],NAVY,BLUE_SOFT),Spacer(1,12)]
    article_review=analysis.get('verification_articles')
    document_message=(article_review or {}).get('document_profile',{}).get('message')
    if document_message:
        flow += [box([p('Nature du document déposé','Label'),p(document_message)],NAVY,BLUE_SOFT),Spacer(1,12)]
    if article_review and presentation and not reading_only:
        flow.append(p(semantic_activity_text(analysis), 'Meta'))
    elif article_review and not reading_only:
        flow.append(p('Comparaison à partir des articles : '+str(article_review.get('evaluated',0))+
            ' propositions examinées, '+str(article_review.get('confirmed',0))+' critères confirmés. '+
            'Limite : '+str(article_review.get('max_points',0))+' points hors catalogue par analyse. '+
            str(article_review.get('skipped',0))+' points non soumis au modèle et '+str(article_review.get('without_proposal',0))+
            ' sans proposition exploitable. Motifs et traces disponibles dans l’inspection.', 'Meta'))
    metrics = [(totals['total'],'points examinés'),(totals['deviation'],'écarts confirmés'),(totals['pending'],'points à vérifier'),(totals['confirmed'],'respects confirmés')]
    if presentation:
        counts=presentation['counts']
        metrics = [(counts['reading'],'passages relevés')] if reading_only else [(counts[key],title) for key,title in
            [('conclusions','conclusions automatiques'),('information','informations documentaires'),('unresolved','contrôles non conclus'),('interrupted','contrôles interrompus')]]
    stats = Table([[[p(n,'Stat'),p(t,'Meta')] for n,t in metrics]], colWidths=[width/len(metrics)]*len(metrics))
    stats.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f0f4f7')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    for cell,tint,accent in [(0,BLUE_SOFT,NAVY),(1,'#fff1f2','#991b1b'),(2,'#fff7d6','#854d0e'),(3,'#ecfdf3','#166534')]:
        if cell>=len(metrics):continue
        if presentation:tint,accent=('#fff7d6','#854d0e') if cell in (2,3) else (BLUE_SOFT,NAVY)
        stats.setStyle(TableStyle([('BACKGROUND',(cell,0),(cell,0),colors.HexColor(tint)),('LINEABOVE',(cell,0),(cell,0),3,colors.HexColor(accent))]))
    if presentation:
        flow += [stats,Spacer(1,10),p('Tous les '+str(counts['total'])+' points sont conservés dans les groupes ci-dessous.','Meta')]
        if analysis.get('core_atomization',{}).get('parents'):
            flow.append(p('Les clauses composées sont examinées par unités, reliées à leurs passages parents complets. Le nombre d’unités ne se compare pas directement au nombre de paragraphes des anciennes analyses.','Meta'))
        if not reading_only:flow += [p(str(counts['respect'])+' critères respectés et '+str(counts['deviations'])+' écarts confirmés automatiquement. '+str(counts['user_confirmations'])+' confirmations utilisateur présentées séparément.','Meta'),p(conclusion_kinds_text(counts),'Meta'),p('Chaque contrôle non conclu ou interrompu présente son motif ; une information documentaire n’est pas une alerte juridique.')]
    else:
        flow += [stats,Spacer(1,10),p(str(totals['information'])+' autres points : information technique, lecture rejetée ou périmètre à confirmer.','Meta'),p('Par où commencer ?', 'Heading'),
            p('Examinez les écarts signalés, puis les points dont la source ou les conditions restent à préciser. Chaque point indique sa page, le passage relevé et le texte officiel disponible.')]
    for row in [r for r in rows if r['statut'] in ('ecart_confirme_sur_critere','ecart_potentiel')][:(1 if fmt_table else 3)]:
        f=row['fait'];flow.append(link(f['id']+' - '+title(f)+' (document p. '+str(f['page'])+')', '#point-'+f['id'], 'Text'))
    legend_rows = LEGEND if not presentation else [
        ('Écart confirmé','#991b1b','Écart établi par un contrôle automatique sur le critère cité.'),
        ('Critère respecté','#166534','Respect établi par un contrôle automatique sur le critère cité.'),
        ('Information',NAVY,'Contexte ou information documentaire ; aucun verdict juridique.'),
        ('Non conclu / interrompu','#854d0e','Motif et état du contrôle indiqués sur chaque point.'),
        ('Déclaration utilisateur',MUTED,'Confirmation personnelle séparée du résultat automatique.')]
    legend=Table([[Paragraph(escape(a),ParagraphStyle('Legend',parent=s['Cell'],fontName='CctpArialBold',textColor=colors.white)),p(b,'Meta')] for a,c,b in legend_rows],colWidths=[width*.31,width*.69])
    legend.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,-1),.5,colors.HexColor(LINE))]+[('BACKGROUND',(0,i),(0,i),colors.HexColor(c)) for i,(_,c,_) in enumerate(legend_rows)]))
    # Keep the landscape cover short; its detailed key is placed on the next page.
    if fmt_table:flow.append(PageBreak())
    if not reading_only:flow += [p('Comment lire les couleurs ?', 'Heading'),legend,
        p('Une case cochée enregistre une déclaration de l’utilisateur, datée. L’analyse automatique reste visible. Le rapport porte sur les points recensés ; il ne certifie pas l’ensemble du contrat.', 'Meta'),
        PageBreak()]
    flow.append(p('Tous les points en un coup d’œil','Title'))
    overview=[[p(t,'Label') for t in ['Repère / page','Point examiné','Résultat']]]
    overview_groups=[];last_group=None
    for row in rows:
        group=(row.get('_presentation') or {}).get('group')
        if group and group!=last_group:
            overview_groups.append(len(overview));overview.append([p(groups[group]['label']+' ('+str(groups[group]['count'])+')','Label'),'','']);last_group=group
        f=row['fait']
        overview.append([link(f['id']+' / p. '+str(f['page']),'#point-'+f['id'],'Cell'),p(title(f),'Cell'),badge(row,True,summary=True)])
    overview_table=Table(overview,colWidths=[width*.18,width*.4,width*.42],repeatRows=1,hAlign='LEFT')
    overview_table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor(BLUE_SOFT)),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor(LINE))]))
    overview_table.setStyle(TableStyle([('SPAN',(0,i),(-1,i)) for i in overview_groups]))
    flow += [overview_table,PageBreak(),Paragraph('<a name="faits"/>Comprendre chaque point',s['Title'])]
    long_quotes=[]
    parents_in_annex=set()
    def parent_link(row,style='Meta'):
        parent=row.get('_report_parent')
        if not parent:return []
        ident=parent['parent_id']
        if ident not in parents_in_annex:
            parents_in_annex.add(ident)
            long_quotes.append((dict(row['fait'],id=ident,_return_point_id=row['fait']['id']),'Passage parent intégral conservé',parent['parent_quote']))
        return [link('Lire le passage parent '+ident+' et ses conditions','#citation-'+ident,style)]
    visual_pages={page['page'] for page in readings.get('pages_visuelles',[])}
    def detail(row, compact=False):
        f=row['fait'];st='Cell' if compact else 'Text'
        items=[]
        review=row.get('revue_utilisateur')
        if review:
            items += [p(reviewed_text(row),st)]
            if review.get('note'):items.append(p('Observation : '+review['note'],st))
            items += [p('Analyse automatique conservée', 'Label'),p(automatic_label(row),st)]
        items += [p('2. Pourquoi ce résultat ?', 'Label'),p(row['explication'],st)]
        items.append(p('3. '+source_heading(row),'Label'))
        if row.get('regle') and source_heading(row) not in ('Passages du dossier','Preuve documentaire'):items.append(p(row['regle'],st))
        src,url,version=source_info(row)
        items += [link(src,url,st) if url else p(src,st)]
        if url:items.append(link('Ouvrir le PDF utilisé à la page citée' if source_heading(row)=='Référence technique' else 'Ouvrir l’article sur Légifrance',url,st))
        if version:items.append(p(version,'Meta'))
        items += [p(line,st) for line in source_evidence(row)]
        scope=analysis.get('sources',{}).get('scope')
        if source_heading(row) == 'Règle et source juridique' and ((row.get('source') or {}).get('id')=='access' or (row.get('source') or {}).get('cle_regle')=='access') and scope:
            scope_url=scope.get('url','')
            if urlsplit(scope_url).netloc=='www.legifrance.gouv.fr':items.append(link('Champ d’application - décret 2006-1657, article 1',scope_url,st))
        if not reading_only:items += [Spacer(1,8),box([p('4. Action proposée par l’analyse automatique' if review else '4. Que faire maintenant ?','Label'),p(row['action'],st)],NAVY,BLUE_SOFT,padding=10,available_width=width-28)]
        if f['type_fait'] in DEFINITIONS:items.append(p(DEFINITIONS[f['type_fait']],'Meta'))
        if reading_notes(row):items.append(p('Contrôles de lecture : '+reading_notes(row),'Meta'))
        return items
    if fmt_table and rows:
        data=[[p(x,'Label') for x in ('Point / document','Constat et preuve','Résultat et source','Suite à donner')]]
        for row in rows:
            f=row['fait'];ql,quote=report_excerpt(row);lab,col,bg=label(row)
            long_quotes.append((f,ql,quote))
            src,url,version=source_info(row)
            result=[badge(row,True),p(status_help(row),'Cell'),p(row['explication'],'Cell')]
            if row.get('revue_utilisateur'):result += [p(reviewed_text(row),'Cell'),p('Analyse initiale : '+automatic_label(row),'Cell'),p(row['revue_utilisateur'].get('note',''),'Cell')]
            result.append(p(source_heading(row),'Label'))
            if row.get('regle') and source_heading(row) not in ('Passages du dossier','Preuve documentaire'):result.append(p(row['regle'],'Cell'))
            result += [link(src,url,'Cell') if url else p(src,'Cell'),p(version,'Meta')]
            if url:result.append(link('Ouvrir la source utilisée',url,'Cell'))
            result += [p(line,'Cell') for line in source_evidence(row)]
            scope=analysis.get('sources',{}).get('scope')
            if source_heading(row) == 'Règle et source juridique' and ((row.get('source') or {}).get('id')=='access' or (row.get('source') or {}).get('cle_regle')=='access') and scope:result.append(link('Champ d’application',scope['url'],'Cell'))
            extras=[p(row['action'],'Cell')]+parent_link(row,'Cell')
            if f['type_fait'] in DEFINITIONS:extras.append(p(DEFINITIONS[f['type_fait']],'Cell'))
            if reading_notes(row):extras.append(p('Contrôles de lecture : '+reading_notes(row),'Cell'))
            data.append([[Paragraph('<a name="point-'+escape(f['id'],quote=True)+'"/>'+escape(f['id']),s['Label']),p('Document p. '+str(f['page']),'Cell'),p(f.get('repere') or 'Repère non précisé','Cell')],
                [p(title(f),'Label'),p(value(f),'Cell'),p(short(quote,260),'Cell'),link('Extrait intégral en annexe','#citation-'+f['id'],'Cell')],result,extras])
        table=Table(data,colWidths=[width*.12,width*.27,width*.35,width*.26],repeatRows=1,splitInRow=0,hAlign='LEFT')
        ts=[('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8eef3')),('LINEBELOW',(0,0),(-1,-1),.5,colors.HexColor('#d3dce4')),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]
        for i,row in enumerate(rows,1):
            ts.append(('LINEBEFORE',(0,i),(0,i),3,colors.HexColor(label(row)[1])))
            ts.append(('BACKGROUND',(3,i),(3,i),colors.HexColor(BLUE_SOFT)))
        table.setStyle(TableStyle(ts))
        table.wrap(width,10000)
        if max(table._rowHeights[1:]) + table._rowHeights[0] > page_size[1]-110:
            table.splitInRow=1
        flow.append(table)
    else:
        last_group=None
        for row in rows:
            group=(row.get('_presentation') or {}).get('group')
            if group and group!=last_group:
                flow.append(p(groups[group]['label']+' ('+str(groups[group]['count'])+')','Heading'));last_group=group
            f=row['fait'];lab,col,bg=label(row);ql,quote=report_excerpt(row)
            src,src_url,src_version=source_info(row)
            source_summary=[p('Source du résultat','Label'),link(src,src_url,'Meta') if src_url else p(src,'Meta'),p(src_version,'Meta')]
            contents=[Paragraph('<a name="point-'+escape(f['id'],quote=True)+'"/>'+escape(clean(f['id']+' - '+title(f))),s['Point']),
                p('Document p. '+str(f['page'])+'  |  '+(f.get('repere') or 'Repère non précisé')+'  |  '+str(f.get('etat','non précisé')).replace('_',' '),'Meta'),
                badge(row),p(status_help(row),'Meta'),*source_summary,p('1. Ce que dit le document','Label'),p(value(f),'Measure'),
                box([p(ql,'QuoteMeta'),p(' '.join(short(quote,450).split()))],LINE,'#f8fafc',padding=10,available_width=width-28)]
            contents+=parent_link(row)
            if len(clean(quote))>450:
                long_quotes.append((f,ql,quote));contents.append(link('Lire la citation intégrale en annexe','#citation-'+f['id']))
            if f['page'] in visual_pages:contents.append(link('Voir l’image source - document p. '+str(f['page']),'#preuve'+str(f['page'])))
            contents+=detail(row)
            card=box(contents,col)
            if card.wrap(width,10000)[1]<page_size[1]-145:
                flow.append(KeepTogether([card]))
            else:
                flow += [CondPageBreak(230),card]
            flow.append(Spacer(1,18))
    if not rows:flow.append(p('Aucun point exploitable dans ce périmètre. Aucun résultat de conformité ne peut être déduit.'))
    if long_quotes:
        flow += [PageBreak(),p('Annexe - citations intégrales','Title')]
        for quote_index,(f,ql,quote) in enumerate(long_quotes):
            return_id=f.get('_return_point_id',f['id'])
            quote_block=[Paragraph('<a name="citation-'+escape(f['id'],quote=True)+'"/>'+escape(f['id']+' - document p. '+str(f['page'])),s['Heading']),p(ql,'QuoteMeta'),p(' '.join(clean(quote).split())),link('Retour au point '+return_id,'#point-'+return_id)]
            quote_height=sum(item.wrap(width-12,10000)[1]+item.getSpaceBefore()+item.getSpaceAfter() for item in quote_block)
            # Reserve room for the annex title; long citations remain splittable.
            if quote_height <= page_size[1]-(190 if quote_index==0 else 130):
                flow.append(KeepTogether(quote_block))
            else:
                flow += quote_block
            flow.append(Spacer(1,12))
    urban=urban_for_report(readings,analysis)
    if urban and not reading_only:
        from slm_urban_review import STATUS_LABELS, presented_review, piece_detail
        urban=presented_review(urban,analysis)
        flow += [PageBreak(),p('Revue du dossier - mobilité urbaine','Title'),p(urban['conclusion'])]
        if urban.get('questions_ciblees'):
            flow.append(p('Informations à préciser pour poursuivre les contrôles','Heading'))
            flow += [p(q['question']+' - '+', '.join(q['faits_ids'])) for q in urban['questions_ciblees']]
        for theme in urban['themes']:
            flow.append(KeepTogether([p(theme['titre'],'Heading'),p(STATUS_LABELS[theme['statut']],'Meta'),
                     p(theme['question']),p(theme['couverture_actuelle'],'Meta'),
                     p('Critères automatiques enregistrés : '+str(theme['criteres_automatiques'])+
                       ' | Écarts signalés : '+str(theme['ecarts_signales']),'Meta')]))
        pieces_block=[p('Pièces à rapprocher du CCTP, selon le projet','Heading')]
        for piece in urban['pieces']:
            pieces_block += [p(piece['titre']+' : '+('mention repérée' if piece['mentionnee'] else 'mention non repérée')+
                       ' ; '+piece_detail(piece),'Meta')]
        pieces_height=sum(item.wrap(width-12,10000)[1]+item.getSpaceBefore()+item.getSpaceAfter() for item in pieces_block)
        if pieces_height <= page_size[1]-130:
            flow.append(KeepTogether(pieces_block))
        else:
            flow += pieces_block
    flow += [PageBreak(),p('Lecture et sources utilisées','Title'),p('Pages traitées','Heading'),p(native_coverage(readings)),p('Recherche des textes','Heading'),p(fallback_text(analysis) or 'Sources disponibles dans le catalogue local à la date de référence.')]
    inv=readings.get('inventaire_clauses')
    if inv:flow.append(p((str(inv['clauses_ajoutees'])+' passages natifs inventoriés. Cette couverture des caractères ne prouve pas une couverture juridique exhaustive.') if general_core(analysis) else (str(inv['clauses_ajoutees'])+' passages normatifs ajoutés ; '+str(inv['clauses_candidates_non_retenues'])+' passages non retenus. Repérage ciblé, non exhaustif.'),'Meta'))
    flow += [p('Contexte repéré','Heading')]+[p(x,'Meta') for x in context_lines(readings,analysis)]
    flow += [p('Périmètre de la revue','Heading')]+[p(x,'Meta') for x in report_limits(analysis)]
    if analysis.get('revue_native'):flow += [p(analysis['revue_native']['resume']),p(analysis['revue_native']['avertissement'],'Meta')]
    if readings.get('validation',{}).get('note'):flow += [p('Note de relecture','Heading'),p(readings['validation']['note'])]
    for page in readings.get('pages_visuelles',[]):
        flow += [PageBreak(),Paragraph('<a name="preuve'+str(page['page'])+'"/>Image source - document p. '+str(page['page']),s['Heading']),
            p('Repères : '+', '.join(f['id'] for f in readings.get('faits',[]) if f['page']==page['page']),'Meta'),
            p('Agrandissement central. Le document original reste la référence pour la page entière.','Meta')]
        image=io.BytesIO(base64.b64decode(page.get('detail_base64') or page['apercu_base64']))
        im=Image.open(image);iw,ih=im.size;image.seek(0);scale=min(width/iw,(page_size[1]-220)/ih)
        flow += [RLImage(image,width=iw*scale,height=ih*scale),Spacer(1,8),link('Retour aux points examinés','#faits')]
    def footer(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#d3dce4'));canvas.line(48,38,page_size[0]-48,38)
        canvas.setFont('CctpArial',9);canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(48,24,'SLM juridique - Revue documentaire - '+analysis['date_reference'])
        canvas.drawRightString(page_size[0]-48,24,'Page '+str(doc.page))
    output=io.BytesIO()
    SimpleDocTemplate(output,pagesize=page_size,leftMargin=48,rightMargin=48,topMargin=42,bottomMargin=54,
        title='Rapport de revue du CCTP',author='SLM juridique local').build(flow,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()


def html_report(readings, analysis, format_report):
    from v4_9_report import excerpt,LABELS,DEFINITIONS,coverage_text,fallback_text,context_text
    title,value=document_title,document_value
    from slm_v6_presentation import prepared_rows
    h=lambda x:escape(clean(x),quote=True)
    rows,presentation=report_rows(analysis,readings);totals=result_totals(rows)
    reading_only=bool(presentation and presentation['mode']=='reading')
    groups={group['id']:group for group in (presentation or {}).get('groups',[])}
    css='''<style>
    *{box-sizing:border-box}body{margin:0;background:#f5f7fa;color:#172b3a;font:18px/1.7 Arial,sans-serif}
    main{max-width:1040px;margin:auto;padding:48px 32px;overflow-wrap:anywhere}
    h1{font-size:34px;line-height:1.2;letter-spacing:-.4px}h2{font-size:26px;line-height:1.35;margin:36px 0 18px}
    h3{font-size:22px;line-height:1.4;margin:8px 0 20px}h4{font-size:17px;line-height:1.5;color:#1d4ed8;margin:24px 0 10px}
    p{margin:8px 0 16px}.meta{color:#475569;font-size:16px;line-height:1.65}.document-name{font-size:22px}
    .summary,.colour-key,.urban-review{background:#fff;border:1px solid #c4cdd6;border-radius:14px;padding:24px;margin:24px 0}
    .summary h2,.colour-key h2{margin-top:0}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
    .metric{background:var(--tint);border-top:4px solid var(--accent);border-radius:8px;padding:14px 12px;font-size:16px;line-height:1.5}
    .metric strong{display:block;color:var(--accent);font-size:30px;line-height:1.3;margin-bottom:6px}
    .colour-key ul{list-style:none;margin:0;padding:0}.colour-key li{display:grid;grid-template-columns:180px 1fr;gap:18px;align-items:start;margin:14px 0;font-size:16px}
    .point{background:#fff;border:1px solid #c4cdd6;border-left:5px solid var(--accent);border-radius:12px;padding:28px;margin:28px 0;break-inside:avoid}
    .badge{font-size:16px;font-weight:bold;line-height:1.5;color:#fff;background:var(--accent);border-radius:6px;padding:8px 12px;display:inline-block}
    .status-help{font-size:16px;color:#475569;margin:14px 0 22px}.measure{font-size:24px;font-weight:bold;line-height:1.45}
    blockquote{background:#f8fafc;border:1px solid #c4cdd6;border-left:4px solid #64748b;border-radius:6px;margin:12px 0 20px;padding:18px;white-space:pre-wrap;overflow-wrap:anywhere}
    .action{background:#eff6ff;border:1px solid #c4cdd6;border-left:4px solid #1d4ed8;border-radius:8px;padding:18px 20px;margin-top:24px}
    .action h4{margin-top:0}.action p:last-child{margin-bottom:0}a{color:#1d4ed8;text-underline-offset:3px}
    a:focus-visible,summary:focus-visible{outline:3px solid #1d4ed8;outline-offset:4px;border-radius:3px}
    img{max-width:100%;max-height:950px;object-fit:contain}table{border-collapse:collapse;width:100%;font-size:17px;table-layout:fixed;background:#fff}
    th,td{padding:20px 18px;border:1px solid #c4cdd6;vertical-align:top;overflow-wrap:anywhere}th{background:#eff6ff;text-align:left;color:#172b3a}
    .report-table tr{border-left:5px solid var(--accent)}.report-table td:last-child{background:#eff6ff}.report-table .action{border:0;padding:0;margin-top:0}
    .review{background:#f8fafc;border:1px solid #c4cdd6;border-left:4px solid var(--accent);border-radius:6px;padding:16px;margin-top:20px}
    details{margin:18px 0;border:1px solid #c4cdd6;border-radius:8px;background:#fff;padding:16px 18px}
    summary{cursor:pointer;color:#172b3a;font-weight:bold;line-height:1.6}pre{font-size:16px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere}
    nav{padding:15px}nav a{margin-right:18px}section[id],article[id],h2[id]{scroll-margin-top:20px}
    @media print{body{background:#fff}main{max-width:none;padding:0}nav{display:none}.point{break-inside:auto}.badge,.metric{print-color-adjust:exact;-webkit-print-color-adjust:exact}a{color:inherit}pre{max-height:none;overflow:visible}details::details-content{display:block;content-visibility:visible}details>*:not(summary){display:block!important}h2,h3,h4{break-after:avoid}}
    @media(max-width:760px){main{padding:24px 16px}h1{font-size:28px}.point,.summary,.colour-key,.urban-review{padding:20px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.colour-key li{grid-template-columns:1fr;gap:8px}.colour-key .badge{justify-self:start}.report-table,.report-table tbody,.report-table tr,.report-table td{display:block;width:100%}.report-table thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.report-table tr{margin:24px 0}.report-table td::before{content:attr(data-label);display:block;font-weight:bold;color:#1d4ed8;margin-bottom:16px}.report-table .action{padding:0}}
    </style>'''
    reading_notice=('<section class="summary" aria-label="Mode de lecture"><h2>Lecture seule — aucun contrôle juridique exécuté</h2><p>Les passages du document ont été relevés. Aucune comparaison juridique ni conclusion de conformité n’a été réalisée.'+('' if presentation else ' Les mentions « à vérifier » concernent les données et leur lecture.')+'</p></section>' if analysis.get('controle_juridique') is False else '')
    out=[css,'<main><p class="meta">SLM JURIDIQUE / REVUE DOCUMENTAIRE</p><h1>Rapport d’analyse du CCTP</h1><p class="document-name"><strong>'+h(readings.get('filename','document'))+'</strong></p><p>Date juridique de référence : '+h(analysis['date_reference'])+'</p>'+''.join('<p class="meta">'+h(line)+'</p>' for line in report_identity(analysis))+reading_notice,
         '<section class="summary" aria-label="Synthèse des résultats"><h2>Les résultats en un coup d’œil</h2><div class="metrics">']
    metrics=[('total','points examinés',NAVY,BLUE_SOFT),('deviation','écarts confirmés','#991b1b','#fff1f2'),('pending','points à vérifier','#854d0e','#fff7d6'),('confirmed','respects confirmés','#166534','#ecfdf3')]
    if presentation:
        totals=presentation['counts']
        metrics=[('reading','passages relevés',NAVY,BLUE_SOFT)] if reading_only else [
            ('conclusions','conclusions automatiques',NAVY,BLUE_SOFT),('information','informations documentaires',NAVY,BLUE_SOFT),
            ('unresolved','contrôles non conclus','#854d0e','#fff7d6'),('interrupted','contrôles interrompus','#854d0e','#fff7d6')]
    for key,text,col,bg in metrics:
        out.append('<div class="metric" style="--accent:'+col+';--tint:'+bg+'"><strong>'+str(totals[key])+'</strong>'+text+'</div>')
    if presentation:
        out.append('</div><p class="meta">Tous les '+str(totals['total'])+' points sont conservés dans les groupes ci-dessous.</p>')
        if not reading_only:out.append('<p>'+str(totals['respect'])+' critères respectés et '+str(totals['deviations'])+' écarts confirmés automatiquement. '+str(totals['user_confirmations'])+' confirmations utilisateur présentées séparément.</p><p class="meta">'+h(conclusion_kinds_text(totals))+'</p><p>Chaque contrôle non conclu ou interrompu présente son motif. Une information documentaire n’est pas une alerte juridique.</p>')
        out.append('</section>')
    else:out.append('</div><p class="meta">'+str(totals['information'])+' autres points : information technique, lecture rejetée ou périmètre à confirmer.</p><p>Commencez par les écarts confirmés, puis les points à vérifier. Chaque fiche présente le constat, la source disponible et la suite à donner.</p></section>')
    if not presentation:out.append('<section class="colour-key"><h2>Comment lire les couleurs ?</h2><ul>'+''.join('<li><span class="badge" style="--accent:'+col+'">'+h(text)+'</span><span>'+h(explanation)+'</span></li>' for text,col,explanation in LEGEND)+'</ul><p class="meta">Cette revue porte sur les points recensés. Elle ne certifie pas l’ensemble du contrat.</p></section>')
    if presentation and not reading_only and analysis.get('verification_articles'):
        out.append('<p class="meta">'+h(semantic_activity_text(analysis))+'</p>')
    document_message=analysis.get('verification_articles',{}).get('document_profile',{}).get('message')
    if document_message:out.append('<section class="summary"><h2>Nature du document déposé</h2><p>'+h(document_message)+'</p></section>')
    out.append('<h2 id="faits">Les points examinés</h2>')
    urban=urban_for_report(readings,analysis)
    if urban and not reading_only:
        from slm_urban_review import html_review, presented_review
        out[-1]=out[-1].replace('<h2 id="faits">Les points examinés</h2>','')
        out += [html_review(presented_review(urban,analysis)),'<h2 id="faits">Les points examinés</h2>']
    if format_report=='tableau':out.append('<table class="report-table"><thead><tr><th scope="col">Constat et preuve</th><th scope="col">Résultat et source</th><th scope="col">Suite à donner</th></tr></thead><tbody>')
    last_group=None
    for row in rows:
        group=(row.get('_presentation') or {}).get('group')
        if group and group!=last_group:
            heading=h(groups[group]['label'])+' ('+str(groups[group]['count'])+')'
            out.append('<tr class="result-group"><th colspan="3" scope="rowgroup">'+heading+'</th></tr>' if format_report=='tableau' else '<h2 class="result-group">'+heading+'</h2>')
            last_group=group
        f=row['fait'];lab,col,bg=label(row);ql,quote=report_excerpt(row);src,url,version=source_info(row)
        status='<span class="badge">'+h(lab)+'</span><p class="status-help">'+h(status_help(row))+'</p>'
        identity='<p class="meta">'+h(f['id'])+' · document p. '+h(f['page'])+' · '+h(f.get('repere') or 'Repère non précisé')+' · '+h(f.get('etat','')).replace('_',' ')+'</p><h3>'+h(title(f))+'</h3>'
        if format_report!='tableau':
            identity+=status+'<div class="action"><strong>Source du résultat</strong><p>'+((('<a href="'+h(url)+'" target="_blank" rel="noopener">'+h(src)+'</a>') if url else h(src)))+'</p><p class="meta">'+h(version)+'</p></div>'
        identity+='<h4>1. Ce que dit le document</h4><p class="measure">'+h(value(f))+'</p><p class="meta">'+h(ql)+'</p><blockquote>'+h(quote)+'</blockquote>'
        if row.get('_report_parent'):
            parent=row['_report_parent']
            identity+='<details><summary>Lire le passage parent '+h(parent['parent_id'])+' et ses conditions</summary><blockquote>'+h(parent['parent_quote'])+'</blockquote><p>Le résultat porte sur cette unité ; les autres unités conservent leurs propres résultats.</p></details>'
        if any(pg['page']==f['page'] for pg in readings.get('pages_visuelles',[])):identity+='<a href="#preuve'+str(f['page'])+'">Voir l’image source</a>'
        result=status if format_report=='tableau' else ''
        if row.get('revue_utilisateur'):
            result+='<div class="review">'+h(reviewed_text(row))+'<p>'+h(row['revue_utilisateur'].get('note',''))+'</p></div><h4>Analyse automatique conservée</h4><p>'+h(automatic_label(row))+'</p>'
        result+='<h4>2. Pourquoi ce résultat ?</h4><p>'+h(row['explication'])+'</p>'
        result+='<h4>3. '+h(source_heading(row))+'</h4>'
        if row.get('regle') and source_heading(row) not in ('Passages du dossier','Preuve documentaire'):result+='<p>'+h(row['regle'])+'</p>'
        result+=(('<a target="_blank" rel="noopener" href="'+h(url)+'">'+h(src)+'</a>') if url else '<p>'+h(src)+'</p>')
        if url:result+='<p><a target="_blank" rel="noopener" href="'+h(url)+'">'+('Ouvrir le PDF utilisé à la page citée' if source_heading(row)=='Référence technique' else 'Ouvrir l’article sur Légifrance')+'</a></p>'
        if version:result+='<p class="meta">'+h(version)+'</p>'
        result+=''.join('<p>'+h(line)+'</p>' for line in source_evidence(row))
        scope=analysis.get('sources',{}).get('scope')
        if source_heading(row) == 'Règle et source juridique' and ((row.get('source') or {}).get('id')=='access' or (row.get('source') or {}).get('cle_regle')=='access') and scope:result+='<p><a target="_blank" rel="noopener" href="'+h(scope['url'])+'">Champ d’application - décret 2006-1657, article 1</a></p>'
        action='' if reading_only else '<div class="action"><h4>'+('4. Action proposée par l’analyse automatique' if row.get('revue_utilisateur') else '4. Que faire maintenant ?')+'</h4><p>'+h(row['action'])+'</p></div>'
        if f['type_fait'] in DEFINITIONS:action+='<p class="meta">'+h(DEFINITIONS[f['type_fait']])+'</p>'
        if reading_notes(row):action+='<p class="meta">Contrôles de lecture : '+h(reading_notes(row))+'</p>'
        if format_report=='tableau':out.append('<tr id="point-'+h(f['id'])+'" style="--accent:'+col+';--tint:'+bg+'"><td data-label="Constat et preuve">'+identity+'</td><td data-label="Résultat et source">'+result+'</td><td data-label="Suite à donner">'+action+'</td></tr>')
        else:out.append('<article class="point" id="point-'+h(f['id'])+'" style="--accent:'+col+';--tint:'+bg+'">'+identity+result+action+'</article>')
    if format_report=='tableau':out.append('</tbody></table>')
    out+=['<h2>Lecture et sources utilisées</h2><p>'+h(native_coverage(readings))+'</p><p>'+h(fallback_text(analysis))+'</p>']
    out+=['<p class="meta">'+h(x)+'</p>' for x in context_lines(readings,analysis)]
    if analysis.get('revue_native'):out+=['<p>'+h(analysis['revue_native']['resume'])+'</p><p>'+h(analysis['revue_native']['avertissement'])+'</p>']
    for page in readings.get('pages_visuelles',[]):
        out.append('<section id="preuve'+str(page['page'])+'"><h2>Image source - document p. '+str(page['page'])+'</h2><p class="meta">Agrandissement central ; consulter le PDF original pour la page entière.</p><img alt="Page source '+str(page['page'])+'" src="data:image/jpeg;base64,'+h(page.get('detail_base64') or page['apercu_base64'])+'"><p><a href="#faits">Retour aux points</a></p><details><summary>OCR brut</summary><pre>'+h(page.get('ocr',{}).get('text',''))+'</pre></details></section>')
    out+=['<h2>Périmètre de la revue</h2><ul>'+''.join('<li>'+h(x)+'</li>' for x in report_limits(analysis))+'</ul>']
    if readings.get('validation',{}).get('note'):out.append('<h3>Note de relecture</h3><p>'+h(readings['validation']['note'])+'</p>')
    out.append('</main>')
    return ''.join(out)
