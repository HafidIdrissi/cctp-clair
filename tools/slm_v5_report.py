"""Render V5 evidence, with reviewed rules bound to their official version."""
import base64
import hashlib
import json
import re
from collections import Counter
from html import escape
from pathlib import Path

from v4_9_document_service import evaluate, approved_readings
from v4_9_laws import CATALOG
from v4_9_readable_report import pdf_report, html_report
from slm_v5_policy import grounded_readings, invalid_fact, compact, TOPICS
from slm_urban_review import build_review
from slm_v5_auto_review import confirm_supported_deviations

ROOT = Path(__file__).resolve().parents[1]


def normalized_legal(text):
    # Preserve decimal boundaries: 1,40 and 14,0 must never compare equal.
    tokens = re.findall(r'\d+(?:[.,]\d+)?|[a-z]+|[%≤≥<>]', compact(text))
    return ' '.join(t.replace(',', '.') if t[0].isdigit() else t for t in tokens)


def reviewed_sources(plan):
    """A new article/version does not silently inherit an old numeric rule."""
    selected = {**plan.get('sources_cache',{}), **plan.get('sources_piste',{}), **plan.get('sources_locales',{})}
    reviewed = json.loads((ROOT/'tools/slm_v5_sources_reviewed.json').read_text(encoding='utf-8'))
    rules, gates = {}, {}
    for key, source in selected.items():
        meta = CATALOG.get(key)
        if not meta:
            continue
        version = meta['url'].rsplit('/',1)[-1]
        sentences = re.split(r'(?<=[.!?])\s+', reviewed[key])
        text = normalized_legal(source.get('texte',''))
        exact = all(normalized_legal(s) in text for s in sentences if s.strip())
        checks = dict(identifiant_version_revue=source.get('id')==version,
            version_non_ambigue=not source.get('version_ambiguous') and not source.get('temporal_uncertain'),
            debut_version_revue=source.get('date_debut')==meta['debut'],
            passages_regle_retrouves=exact,
            source_dila=source.get('provenance')=='dila_open_data',
            periode_valide=source.get('date_debut','9999') <= plan['date_reference'] < (source.get('date_fin_exclusive') or '2999-01-01'))
        gates[key] = dict(checks=checks, eligible=all(checks.values()), version_attendue=version,
            sha256_texte=hashlib.sha256(str(source.get('texte','')).encode()).hexdigest())
        if all(checks.values()):
            rules[key] = dict(source, cle_regle=key, titre=source['nom_code'], url=source['source_url'],
                debut=source['date_debut'], canal='DILA open data · copie locale',
                controle='version_revue_et_passages_exacts_retrouves')
    return rules,gates,selected


def analyze(body, *, article_reviewer=None):
    plan = body['couverture_locale']
    if plan.get('mode') != 'dila_local_prioritaire_v5' or plan['date_reference'] != body['date_reference']:
        raise ValueError('Plan documentaire V5 daté obligatoire.')
    readings = grounded_readings(body['lectures'])
    if body.get('validation') is not None:
        readings = approved_readings(readings,body['validation'])
    rules,gates,selected = reviewed_sources(plan)
    analysis = evaluate(readings,body['date_reference'],body.get('controle_juridique',True) is True,sources_override=rules)
    points = {p['fait_id']:p for p in plan['points']}
    for row in analysis['lignes']:
        fact = row['fait']
        point = points.get(fact['id'],{})
        row['decision_documentaire'] = {t:plan['decisions'].get(t) for t in point.get('topics',[])}
        row['articles_complementaires'] = point.get('articles_complementaires',[])
        if invalid_fact(fact) or point.get('statut') == 'lecture_seule':
            continue
        missing = [t for t in point.get('topics',[]) if t not in selected]
        if point.get('statut') == 'hors_perimetre_automatise':
            row.update(statut='a_verifier',comparaison=None,regle=None,
                explication='Clause conservée, hors du périmètre des contrôles de voirie, mobilité et accessibilité.',
                action='Faire examiner cette clause et les pièces contractuelles associées.')
        elif missing:
            row.update(statut='non_verifiable',comparaison=None,regle=None,
                explication='Source datée non résolue : '+', '.join(missing)+'.',
                action='Actualiser la base DILA ou compléter la recherche officielle ; aucun verdict sur ce point.')
        elif not row.get('source') and point.get('topics'):
            source = next((selected[t] for t in point['topics'] if t in selected),None)
            if source:
                row.update(source=dict(source,titre=source.get('nom_code'),url=source.get('source_url'),debut=source.get('date_debut')),
                    statut='technique' if fact.get('type_fait')=='largeur_cyclable' else 'a_verifier',
                    comparaison=None,regle=None,article=source.get('numero'),
                    explication='Article daté retrouvé. Cette version ou ce contrôle ne dispose pas d’une règle automatique validée.',
                    action='Examiner le texte et son applicabilité ; aucune conclusion juridique n’est générée par le SLM.')
    analysis.update(revision='V5-DILA',regles_verifiees=gates,
        controle_juridique=body.get('controle_juridique',True) is True,
        recherche_automatique={k:v for k,v in plan.items() if k not in ('sources_locales','sources_cache','sources_piste')},
        extraction_native_v5=readings.get('extraction_native_v5',{}))
    analysis['limites'] = ['Contrôles programmés de voirie, mobilité et accessibilité. Le corpus documentaire plus large ne rend pas ces contrôles exhaustifs.',
        'Règles automatiques liées à une version officielle revue et à ses passages retrouvés. Les autres versions restent à examiner.',
        'Les normes NF/DTU et les pièces locales ne sont pas fournies par ce corpus DILA ; les vérifier dans les sources du projet.',
        'Une proposition du SLM, un résultat de recherche ou un silence du document ne prouvent pas une conformité globale.']
    confirm_supported_deviations(analysis, readings, gates)
    if article_reviewer is not None and analysis['controle_juridique']:
        article_reviewer(analysis, readings, plan)
        analysis['limites'][1] = ('Règles revues et comparaisons documentaires à partir des articles retrouvés. '
            'Ces dernières exigent des citations exactes, une comparaison contrôlable et une contre-lecture. '
            'Les limites de couverture et les points non conclus restent signalés dans l’inspection.')
    analysis['revue_mobilite_urbaine'] = build_review(readings, analysis)
    return readings,analysis


def dashboard(analysis):
    if analysis.get('controle_juridique') is False:
        from slm_v6_presentation import is_v6
        note='' if is_v6(analysis) else '<p>Les mentions « à vérifier » concernent les données et leur lecture ; elles ne sont pas des conclusions de comparaison juridique.</p>'
        return '<section class="v5"><div class="v5-tag">SLM JURIDIQUE / V5</div><h1>Lecture seule du document</h1><p><strong>Aucun contrôle juridique exécuté.</strong> Ce rapport présente les passages relevés. Aucune comparaison avec les articles ni conclusion de conformité n’a été réalisée dans ce mode.</p>'+note+'</section>'
    plan = analysis['recherche_automatique']
    state = plan['base_dila']
    decisions = plan.get('decisions',{})
    local = sum(x['canal']=='dila_local' for x in decisions.values())
    cached = sum(x['canal']=='cache_piste' for x in decisions.values())
    count = len(plan['requetes'])
    api = f'{count} recherches demandées' if plan.get('recherche_piste_executee') else '0 appel déclenché' if not count else f'{count} recherches prévues, exécution non établie'
    channels={'dila_local':'DILA locale','cache_piste':'Cache PISTE','piste':'Complément PISTE','aucun':'Source non résolue'}
    motives={'version_datee_retrouvee_localement':'Version datée trouvée dans la base',
        'version_exacte_en_cache_recent':'Version exacte déjà conservée dans le cache récent',
        'base_dila_vide':'La base DILA ne contient pas encore d’article',
        'base_dila_a_actualiser':'La mise à jour de la base doit être confirmée',
        'date_posterieure_au_corpus':'La date demandée dépasse celle du corpus',
        'reference_absente_du_perimetre_local':'Cette référence manque dans le corpus local',
        'versions_locales_ambigues':'Plusieurs versions demandent une vérification'}
    reasons = ''.join('<li><strong>'+escape(TOPICS.get(t,{}).get('label',t))+'</strong> · '+escape(channels.get(x['canal'],x['canal']))+' · '+escape(motives.get(x['motif'],x['motif']))+'</li>' for t,x in decisions.items())
    return '<section class="v5"><div class="v5-tag">SLM JURIDIQUE / V5</div><h1>Le contrôle, preuve à l’appui.</h1><p>Document → faits sourcés → DILA local → PISTE si nécessaire → critères vérifiés</p><div class="v5-stats">'+''.join('<div><b>'+escape(str(v))+'</b><span>'+escape(k)+'</span></div>' for k,v in [('versions exploitables',state.get('usable_article_count',state.get('article_count',0))),('thèmes résolus par DILA',local),('thèmes repris du cache',cached),('PISTE',api)])+'</div><p>Corpus : '+escape(str(state.get('coverage_scope','non chargé')))+' · Date du corpus : '+escape(str(state.get('verified_through') or state.get('snapshot_date') or 'inconnue'))+' · '+escape(str(state.get('quarantined_article_count',state.get('quarantined_count',0))))+' versions en quarantaine exclues des recherches · Couverture juridique non exhaustive.</p><details><summary>Pourquoi ce parcours documentaire ?</summary><ul>'+reasons+'</ul></details></section>'


def evidence_panels(analysis):
    blocks=[]
    for row in analysis['lignes']:
        fact=row['fait']; source=row.get('source') or {}
        quote=escape(str(fact.get('citation_visible') or 'Citation absente'))
        law=escape(str(source.get('texte') or 'Aucune source suffisante retrouvée.'))
        period=escape(str(source.get('date_debut') or source.get('debut') or '?'))+' → '+escape(str(source.get('date_fin_exclusive') or 'fin non bornée'))
        checks=(row.get('verification_article') or row.get('verification_automatique') or {}).get('checks',{})
        check_text=''.join('<li>'+('Vérifié' if valid else 'Non établi')+' · '+escape(key.replace('_',' '))+'</li>' for key,valid in checks.items())
        blocks.append('<details><summary>'+escape(str(fact['id']))+' · '+escape(str(fact['element']))+' · page '+escape(str(fact.get('page','?')))+'</summary><div class="v5-proof"><div><h3>Le passage du CCTP</h3><blockquote>'+quote+'</blockquote><p>Mesure : '+escape(str(fact.get('valeur_inscrite') or fact.get('information') or 'non établie'))+'</p></div><div><h3>Le texte officiel conservé</h3><p>'+escape(str(source.get('nom_code') or source.get('titre') or 'Source absente'))+'</p><p>'+escape(str(source.get('id','')))+' · '+period+'</p><pre>'+law+'</pre></div></div><h3>Conditions de ce contrôle</h3><ul>'+check_text+'</ul><p>'+escape(str(row['explication']))+'</p></details>')
    return '<section class="v5"><h2>Ouvrir les preuves, point par point</h2><p>Passages conservés dans le dossier. Le texte juridique ci-dessous provient de la source enregistrée ; il n’est pas rédigé par le modèle.</p>'+''.join(blocks)+'</section>'


def report(body, *, article_reviewer=None, workflow_version='V5', before_render=None,
           pdf_renderer=None, html_renderer=None):
    readings,analysis = analyze(body, article_reviewer=article_reviewer)
    if workflow_version.startswith('V6'):
        analysis['workflow_version'] = workflow_version
    kind = 'tableau' if 'tableau' in str(body.get('format_rapport','')).lower() else 'cartes'
    if before_render is not None:
        before_render(readings,analysis,kind)
    content = (html_renderer or html_report)(readings,analysis,kind)
    styles = '''<style>
.v5,.v5 *{box-sizing:border-box}
.v5{font:17px/1.7 Arial,sans-serif;color:#172b3a;max-width:1100px;margin:28px auto;padding:32px;border:1px solid #c4cdd6;border-top:5px solid #1d4ed8;border-radius:14px;background:#fff;overflow-wrap:anywhere}
.v5 h1,.v5 h2,.v5 h3{color:#172b3a;overflow-wrap:anywhere;line-height:1.3}
.v5 h1{font-size:32px;margin:12px 0 18px}.v5 h2{font-size:26px;margin:0 0 16px}.v5 h3{font-size:20px;margin:22px 0 12px}
.v5 p{margin:12px 0}.v5-tag{font-size:14px;font-weight:700;letter-spacing:1px;color:#1d4ed8}
.v5-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:26px 0}
.v5-stats div{min-width:0;background:#eff6ff;padding:20px;border:1px solid #c4cdd6;border-radius:10px}
.v5-stats b,.v5-stats span{display:block}.v5-stats b{font-size:24px;line-height:1.4;margin-bottom:10px;color:#172b3a}.v5-stats span{font-size:16px;line-height:1.5;color:#475569}
.v5 li{margin:10px 0}.v5 ul{padding-left:24px}.v5 a{color:#1d4ed8;font-weight:700;text-decoration:underline;text-underline-offset:3px;overflow-wrap:anywhere}
.v5 a:focus-visible,.v5 summary:focus-visible{outline:3px solid #1d4ed8;outline-offset:4px;border-radius:4px}
nav.v5{line-height:2.2}nav.v5 a{display:inline-block;margin-right:8px}
</style>'''
    styles+='''<style>
.v5-proof{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin:18px 0}
.v5-proof>div{min-width:0;padding:20px;border:1px solid #c4cdd6;border-radius:10px;background:#fff}
.v5-proof h3{margin-top:0;color:#1d4ed8}.v5-proof p{font-size:16px;line-height:1.7}
.v5-proof pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:480px;overflow:auto;font:16px/1.7 Arial,sans-serif;color:#172b3a;margin:16px 0 0;padding:18px;background:#eff6ff;border:1px solid #c4cdd6;border-radius:6px}
.v5 blockquote{margin:0;padding:18px;font-size:17px;line-height:1.7;color:#172b3a;border-left:4px solid #1d4ed8;background:#eff6ff;white-space:pre-wrap;overflow-wrap:anywhere}
.v5 details{margin-top:16px;padding:0 0 18px;border:1px solid #c4cdd6;border-radius:10px;background:#fff}
.v5 details>summary{cursor:pointer;padding:16px 20px;font-size:18px;line-height:1.5;font-weight:700;color:#172b3a;background:#eff6ff;border-radius:9px}
.v5 details[open]>summary{border-bottom:1px solid #c4cdd6;border-radius:9px 9px 0 0}
.v5 details>summary:hover{color:#1d4ed8;text-decoration:underline;text-underline-offset:3px}
.v5 details>:not(summary){margin-left:20px;margin-right:20px}
@media(max-width:800px){.v5-proof{grid-template-columns:1fr}.v5{margin:18px 12px;padding:20px}.v5 h1{font-size:28px}.v5 h2{font-size:23px}.v5-stats{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}.v5-proof>div{padding:16px}.v5 details>summary{padding:14px}.v5 details>:not(summary){margin-left:14px;margin-right:14px}}
@media print{nav.v5{display:none}.v5{max-width:none;margin:16px 0;padding:18px;border-radius:0;box-shadow:none;print-color-adjust:exact;-webkit-print-color-adjust:exact}.v5 h1,.v5 h2,.v5 h3,.v5 summary{break-after:avoid}.v5-proof{display:block}.v5-proof>div{margin:14px 0}.v5-proof pre{max-height:none!important;height:auto!important;overflow:visible!important}.v5 details{break-inside:auto}.v5 details::details-content{content-visibility:visible;display:block}.v5 details>:not(summary){display:block!important}.v5 details>summary{list-style:none}.v5 details>summary::-webkit-details-marker{display:none}.v5-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>'''
    panels = content if html_renderer else dashboard(analysis)+content+evidence_panels(analysis)
    html = '<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SLM juridique · DILA local V5</title>'+styles+'<body>'+panels+'</body></html>'
    pdf = (pdf_renderer or pdf_report)(readings,analysis,kind)
    revision=analysis.get('revision','V5-DILA')
    if workflow_version!='V5':
        html=html.replace('SLM JURIDIQUE / V5','SLM JURIDIQUE / '+escape(workflow_version)).replace('DILA local V5</title>','DILA local '+escape(workflow_version)+'</title>')
    proof = dict(version=workflow_version,revision=revision,analyse=analysis,lectures=readings,
        validation_juriste_realisee=False,provenance_sources=body['couverture_locale'])
    b64 = base64.b64encode(pdf).decode()
    json64 = base64.b64encode(json.dumps(proof,ensure_ascii=False).encode()).decode()
    html64 = base64.b64encode(html.encode()).decode()
    downloads = '<nav class="v5" aria-label="Téléchargements"><a download="rapport_CCTP_V5.pdf" href="data:application/pdf;base64,'+b64+'">Rapport PDF</a> · <a download="rapport_CCTP_V5.html" href="data:text/html;base64,'+html64+'">Rapport HTML</a> · <a download="preuves_CCTP_V5.json" href="data:application/json;base64,'+json64+'">Preuves JSON</a></nav>'
    if workflow_version!='V5': downloads=downloads.replace('_V5.', '_'+workflow_version+'.')
    return dict(version_workflow=workflow_version,revision=revision,html=html.replace('<body>','<body>'+downloads,1),rapport_html=html,
        pdf_base64=b64,preuves_json=proof,
        synthese=dict(Counter(r['statut'] for r in analysis['lignes'])),
        controle_juridique_images='controle_conditionnel_source_et_version')
