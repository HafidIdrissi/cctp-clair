"""Readable V4.9 report, cards or table. No silent legal certification."""
import base64,io,json,re,urllib.parse
from collections import Counter
from html import escape
from pathlib import Path
from v4_9_document_service import evaluate,approved_readings
from v4_8_document_service import norm
from v4_9_evidence import coverage

LABELS={
 'validation_utilisateur':('Respect confirmé par l’utilisateur','#166534','#ecfdf3'),
 'non_verifiable':('Impossible de conclure : source manquante','#854d0e','#fff7d6'),
 'lecture_rejetee':('Lecture rejetée — aucun verdict','#475569','#f1f5f9'),
 'ecart_confirme_sur_critere':('Règle non respectée sur ce point vérifié','#991b1b','#fff1f2'),
 'ecart_potentiel':('Problème repéré : à examiner','#854d0e','#fff7d6'),
 'critere_atteint':('Critère vérifié — pas une conformité globale','#166534','#ecfdf3'),
 'critere_auto_respecte':('Règle respectée sur ce point · vérifié automatiquement','#166534','#ecfdf3'),
 'critere_a_confirmer':('Valeur acceptable : conditions à vérifier','#854d0e','#fff7d6'),
 'a_verifier':('Vérification nécessaire avant de conclure','#854d0e','#fff7d6'),
 'technique':('Point de conception — pas un seuil légal','#1d4ed8','#eff6ff'),
 'hors_perimetre':('Existant hors opération déclaré — à confirmer','#475569','#f1f5f9'),
}
BLUE='#16324f'
REVISION='V4.9.1'
DEFINITIONS={
 'devers_pieton':'Dévers : inclinaison du cheminement vers un côté, différente de la pente dans le sens de marche.',
 'ressaut':'Ressaut : petite différence de hauteur, par exemple entre le trottoir et la chaussée.',
 'bande_eveil':'Bande d’éveil : surface tactile qui avertit les personnes aveugles ou malvoyantes avant une traversée.',
 'distance_stationnement_amont':'En amont : avant le passage piéton, dans le sens de circulation des véhicules.',
}

def excerpt(f):
    if f.get('origine')=='texte_natif':return 'Extrait exact du texte PDF',f.get('citation_visible') or 'Aucun extrait'
    proof=f.get('preuve_visuelle_v6') or {}
    if proof.get('eligible') is True and proof.get('checks') and all(v is True for v in proof['checks'].values()):
        from slm_v6_visual_evidence import fact_binding
        if proof.get('fact_sha256')==fact_binding(f):
            return 'Annotation image vérifiée · deux relectures et citation OCR',proof['citation']
    if f.get('preuve_ocr'):return 'Annotation OCR rapprochée - à vérifier sur l’image',f.get('preuve_citation_ocr') or f['preuve_ocr']
    return 'Description proposée par le modèle - non corroborée',f.get('citation_visible') or 'Aucune citation précise'

def coverage_text(readings):
    c=coverage(readings)
    listing=lambda xs:', '.join(map(str,xs)) or 'aucune'
    return ('Vision exécutée : '+listing(c['visual'])+'. OCR seul : '+listing(c['ocr_only'])+
        '. Vision en échec : '+listing(c['failed'])+'. Candidates non sélectionnées : '+listing(c['not_selected'])+'.')

def fallback_text(analysis):
    usage=(analysis.get('verification_articles') or {}).get('piste_usage') or {}
    if usage.get('calls') or usage.get('cache_hits'):
        return ('Complément ciblé aux recherches initiales : '+str(usage.get('calls',0))+
            ' appels au relais PISTE, '+str(usage.get('cache_hits',0))+' réponses réutilisées et '+
            str(usage.get('errors',0))+' erreurs. Les recherches, consultations et motifs sont conservés dans l’inspection. '
            'Ces compteurs concernent le complément ciblé ; une source trouvée ne prouve pas la conformité globale.')
    search=analysis.get('recherche_automatique')
    if not search:return ''
    stats=search.get('couverture_recherche') or {}
    count=len(search.get('requetes',[]))
    if search.get('mode')=='dila_local_prioritaire_v5':
        decisions=search.get('decisions',{})
        local=sum(d.get('canal')=='dila_local' for d in decisions.values())
        cached=sum(d.get('canal')=='cache_piste' for d in decisions.values())
        api=(str(count)+' recherches PISTE demandées.' if search.get('recherche_piste_executee') else
            str(count)+' recherches prévues, exécution non établie.' if count else
            'PISTE désactivé pour ce parcours.' if not search.get('piste_autorise') else 'Aucun recours à PISTE nécessaire pour les thèmes contrôlés.')
        return ('DILA locale prioritaire : '+str(local)+' thèmes résolus localement ; '+str(cached)+' thèmes repris du cache. '+api+
            ' Les lacunes et les motifs sont enregistrés dans les preuves. Corpus et contrôles non exhaustifs.')
    if search.get('mode')=='catalogue_et_recherche_elargie':
        state=(str(count)+' recherches PISTE ; '+str(stats.get('queries_successful',0))+' recherches exploitables ; '+str(stats.get('candidates_selected',0))+' candidats sélectionnés pour consultation. ') if search.get('recherche_piste_executee') else (str(count)+' recherches complémentaires prévues, mais leur exécution n’est pas établie dans ce rapport. ' if count else 'Aucune recherche complémentaire déclenchée pour cette lecture. ')
        return ('Catalogue et recherche complémentaire à la date du document. '+state+
            ('Limite de recherche atteinte : couverture partielle. ' if stats.get('consultation_limit_reached') or any(q.get('limite_atteinte') for q in stats.get('query_results',[])) else '')+
            ('Des recherches ont échoué. ' if stats.get('query_errors') else '')+
            'Les résultats de chaque recherche et les articles complémentaires sont disponibles dans l’inspection. Une source trouvée ne prouve pas son applicabilité. Recherche non exhaustive.')
    return ('Sources locales recherchées en premier. '+
        (str(count)+' recherches PISTE demandées ; '+str(stats.get('queries_successful',0))+' réponses de recherche exploitables. ' if search.get('recherche_piste_executee') else 'Aucun appel PISTE effectué : sources disponibles, lecture seule ou preuves insuffisantes pour une recherche. ')+
        str(len(search.get('cache_hits',[])))+' thèmes retrouvés dans le cache PISTE. Une source trouvée ne prouve pas la conformité. Recherche non exhaustive.')

def context_text(analysis):
    names={'travaux':'Travaux','agglomeration':'Agglomération / voirie urbaine','public':'Usage public'}
    return [names[k]+(' : indice trouvé p. '+str(v['page'])+' ('+v['origine']+'). '+v['extrait_normalise'] if v else ' : non établi par l’extraction ciblée.') for k,v in analysis.get('contexte_indices',{}).items()]

def value(f):
    if f['type_fait']=='bande_eveil' and re.search(r'aucun|absen',norm((f.get('information') or '')+' '+f.get('citation_visible',''))):
        return 'Aucune bande d’éveil prévue (mention écrite)'
    if f['type_fait']=='absence_amenagement_cyclable':
        return 'Absence d’aménagement cyclable proposée'+(' — tronçon '+str(f['valeur_inscrite']) if f.get('valeur_inscrite') else '')
    if f['type_fait']=='derogation_par_visa':return 'Le seul visa est présenté comme une dérogation'
    return str(f.get('valeur_inscrite') or f.get('information') or 'Information qualitative / donnée non établie')

def title(f):
    if f.get('origine')=='texte_natif' and f.get('element')=='Clause native à examiner':
        first=(f.get('citation_visible') or '').strip().split('\n')[0].strip()
        if first and len(first)<=140:
            return first
    return {'largeur_pieton':'Largeur du cheminement piéton','devers_pieton':'Dévers du cheminement piéton',
            'ressaut':'Hauteur du ressaut','fente_grille':'Largeur des fentes de grille',
            'bande_eveil':'Bande d’éveil de vigilance','distance_stationnement_amont':'Stationnement avant le passage piéton',
            'absence_amenagement_cyclable':'Continuité de l’itinéraire cyclable',
            'largeur_cyclable':'Largeur de l’aménagement cyclable','derogation_par_visa':'Clause sur la dérogation'}.get(f['type_fait'],f['element'])

from v4_9_readable_report import pdf_report, html_report

def report(body):
    readings=body['lectures']
    if body.get('validation') is not None:readings=approved_readings(readings,body['validation'])
    reference=body.get('date_reference') or '2024-07-01'
    if not body.get('date_reference'):raise ValueError('Date de référence obligatoire, aucune date implicite.')
    analysis=evaluate(readings,reference,body.get('controle_juridique',True) is True)
    if body.get('couverture_locale'):
        from v4_9_fallback import enrich_analysis
        analysis=enrich_analysis(analysis,body['couverture_locale'])
    native=body.get('rapport_natif') or {}
    proof_native=native.get('preuves_json') or {}
    if native.get('pdf_base64'):
        summary=proof_native.get('synthese_v4') or {}
        analysis['revue_native']={'resume':str(summary.get('texte') or 'Revue native disponible dans le téléchargement distinct.'),
            'avertissement': 'Conformité juridique non établie. '+('Extraction native du SLM non validée ; le rapport natif repose sur des constats documentaires reconstruits, à relire.' if proof_native.get('extraction_slm_verifiee') is False else 'Les constats et conditions doivent être relus avant utilisation.')}
    kind='tableau' if 'tableau' in str(body.get('format_rapport','')).lower() else 'cartes'
    pdf=pdf_report(readings,analysis,kind);section=html_report(readings,analysis,kind)
    full='<!doctype html><html lang="fr"><meta charset="utf-8"><title>Revue CCTP '+REVISION+'</title><body>'+section+'</body></html>'
    proof={'version':'V4.9','revision':REVISION,'analyse':analysis,'lectures':readings,'rapport_natif_preuves':native.get('preuves_json'),'validation_juriste_realisee':False}
    stem=re.sub('[^A-Za-z0-9_-]','_',Path(readings.get('filename','document')).stem)[:80]
    b64=base64.b64encode(pdf).decode()
    links='<nav><a download="'+stem+'_rapport_V4_9_1.pdf" href="data:application/pdf;base64,'+b64+'">Télécharger le PDF</a>'
    links+='<a download="'+stem+'_rapport_V4_9_1.html" href="data:text/html;charset=utf-8,'+urllib.parse.quote(full)+'">Télécharger le HTML</a>'
    links+='<a download="'+stem+'_preuves_V4_9_1.json" href="data:application/json;charset=utf-8,'+urllib.parse.quote(json.dumps(proof,ensure_ascii=False))+'">Télécharger les preuves</a>'
    if native.get('pdf_base64'):
        base64.b64decode(native['pdf_base64'],validate=True)
        links+='<a download="'+stem+'_revue_texte_natif.pdf" href="data:application/pdf;base64,'+native['pdf_base64']+'">Revue native / PISTE séparée</a>'
    links+='</nav>'
    return {'version_workflow':'V4.9','revision':REVISION,'html':links+section,'rapport_html':full,'pdf_base64':b64,
            'preuves_json':proof,'synthese':dict(Counter(r['statut'] for r in analysis['lignes'])),'controle_juridique_images':'pre_analyse_conditionnelle'}
