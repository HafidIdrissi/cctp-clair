"""Prefer a uniquely replayable native quotation over a weaker OCR copy.

This changes reading provenance only. No state, object association, threshold
or legal verdict is inferred from the presence of a native quotation.
"""
import copy
import hashlib
from slm_v6_evidence_completion import native_occurrences
from v4_9_evidence import tokens
from slm_m3_journal import emit


def prefer_native(analysis, readings):
    events=[]
    for row in analysis.get('lignes',[]):
        fact=row['fait'];page=fact.get('page');quote=fact.get('citation_visible','')
        if (fact.get('origine')!='ministral_vision' or len(quote)<20
            or any(fact.get(k) for k in ('rejet_humain','correction_humaine','validation_humaine'))
            or type(page) is not int or not 1<=page<=len(readings.get('text',[]))):continue
        text=readings['text'][page-1];matches=native_occurrences(quote,text)
        if len(matches)!=1:continue
        match=matches[0];native=text[match.start():match.end()]
        if tokens(native)!=tokens(quote):continue
        value,unit=fact.get('valeur'),fact.get('unite')
        if value is not None and (value,unit) not in tokens(native):continue
        old=copy.deepcopy(fact)
        proof=dict(method='citation_native_unique_rejouee',page=page,start=match.start(),end=match.end(),
            page_sha256=hashlib.sha256(text.encode()).hexdigest(),citation=native,original_fact=old,
            limitation='Preuve de lecture uniquement ; état projeté et applicabilité non déduits.')
        fact.update(origine='texte_natif',type_fait='clause_a_examiner',citation_visible=native,
            lecture_statut='citation_native_exacte',core_native_preference=proof,
            etat='non_precise',valeur=None,valeur_m=None,unite=None,valeur_inscrite=None,
            ambiguite=None,hors_operation=None,association_valeur_element_verifiee=False)
        fact.pop('preuve_visuelle_v6',None)
        row.pop('verification_article',None)
        row.update(statut='a_verifier',comparaison=None,source=None,regle=None,article=None,
            explication='Citation native retrouvée ; objet, question et conditions restent à qualifier.')
        events.append(dict(fact_id=fact['id'],page=page,citation=native,legal_verdict=False))
        emit('preuve_native_prioritaire','done',**events[-1])
    analysis['core_native_preference']=events
    return events
