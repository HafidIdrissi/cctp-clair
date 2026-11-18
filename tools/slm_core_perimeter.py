"""A documented scope exclusion, never a legal compliance verdict."""
import copy,re,hashlib,json
from slm_core_extraction import table_rows
from slm_core_programmed import native_passages
from slm_v6_visual_evidence import page_for,page_material,schema,observations,measure,fact_binding
from slm_m3_journal import emit
from v4_8_document_service import norm


def basis(fact,readings):
    if fact.get('origine')!='ministral_vision' or fact.get('etat')!='existant' or fact.get('hors_operation') is not True:return None
    marker=str(fact.get('repere') or '')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,14}',marker):return None
    page=page_for(fact,readings)
    if not page or not page.get('vision'):return None
    raw=page['vision'].get('observations_brutes_modele',[])
    rows=table_rows(page,raw)
    matched=[(r,raw[i]) for i,r in rows.items() if raw[i].get('repere')==marker]
    if len(matched)!=1 or matched[0][0]!=fact.get('preuve_ligne_ocr_core'):return None
    row,proposal=matched[0];state=re.sub(r'\s+',' ',norm(row['state_text']))
    if not ('existant' in state and 'hors operation' in state and 'non modifie' in state and not re.search(r'\bprojet\b',state)):return None
    datum=(fact.get('valeur'),fact.get('unite'))
    # table_rows has already required a unique numeric word and nearby unit.
    # Its display text can interleave columns between that number and unit.
    if datum not in measure(proposal.get('citation_visible','')):return None
    scopes=[]
    for piece in native_passages(readings):
        text=re.sub(r'\s+',' ',norm(piece['citation']))
        if (re.search(r'\brepere\s+'+re.escape(norm(marker))+r'\b.{0,90}existant.{0,50}hors.{0,20}operation.{0,30}non modifie',text)
            and not re.search(r'n.est pas.{0,20}(?:existant|hors)|ne.{0,15}designe pas',text)):
            scopes.append(piece)
    if len(scopes)!=1:return None
    return dict(row=row,native_scope=scopes[0],page=page,material=page_material(page))


def evidence_checks(fact,readings,proof):
    grounded=basis(fact,readings)
    if not grounded or not grounded['material']:return None
    material=grounded['material'];items=proof.get('observations')
    if not isinstance(items,list) or len(items)!=2:return None
    for item in items:
        valid=observations({'observations':[item]},[fact['id']],material['lines'])
        if fact['id'] not in valid:return None
    common=set(items[0]['citation_ids']) & set(items[1]['citation_ids'])
    datum=(fact.get('valeur'),fact.get('unite'))
    checks=dict(native_scope_exact=proof.get('native_scope')==grounded['native_scope'],
        row_exact=proof.get('row')==grounded['row'],
        image_hash=proof.get('image_sha256')==material['image_sha256'],
        ocr_hash=proof.get('ocr_sha256')==material['ocr_sha256'],
        fact_hash=proof.get('fact_sha256')==fact_binding(fact),
        two_objects=all(x['objet_confirme'] and not x['ambigu'] for x in items),
        two_existing_states=all(x['etat']=='existant' for x in items),
        two_measures=all(datum in measure(x['valeur_inscrite']) for x in items),
        common_literal_measure=any(datum in measure(material['lines'][k]) for k in common),
        existing_state_cited=all(any('existant' in norm(material['lines'].get(k,''))
            and not re.search(r'\bprojet\b',norm(material['lines'].get(k,''))) for k in x['etat_ids']) for x in items))
    return checks if all(checks.values()) else None


def verify(fact,readings,proof):
    checks=evidence_checks(fact,readings,proof)
    return bool(checks and proof.get('eligible') is True and proof.get('checks')==checks)


def establish(row,readings,info,caller):
    fact=row['fait'];grounded=basis(fact,readings)
    if not grounded or not grounded['material']:return False
    existing=row.get('verification_perimetre_core')
    if existing and verify(fact,readings,existing):
        apply_record(row,existing)
        emit('perimetre_documente','reused',fact_id=fact['id'],page=fact['page'],proof=existing,model_call=False)
        return True
    material=grounded['material'];page=grounded['page']
    state_ids=[k for k,v in material['lines'].items() if re.search(r'\bprojet\b|\bexistant\w*\b',norm(v))]
    spec=schema([fact['id']],list(material['lines']),state_ids)
    question=[dict(id=fact['id'],objet=str(fact.get('element') or '')+' — '+fact['type_fait'],repere_propose=fact['repere'])]
    values=[]
    for n in (1,2):
        raw=caller('perimetre_image_'+str(n),page,question,material,spec,info)
        parsed=observations(raw,[fact['id']],material['lines'])
        if fact['id'] not in parsed:return False
        values.append(parsed[fact['id']])
    proof=dict(method='core_perimetre_texte_et_deux_lectures_image',native_scope=grounded['native_scope'],row=grounded['row'],
        observations=values,model='ministral-3:3b',fact_sha256=fact_binding(fact),image_sha256=material['image_sha256'],ocr_sha256=material['ocr_sha256'],
        limitation='Exclusion des travaux de ce lot uniquement. Aucune certification de la valeur ni de la conformité juridique de l’existant.')
    checks=evidence_checks(fact,readings,proof)
    if not checks:return False
    proof.update(eligible=True,checks=checks)
    apply_record(row,proof)
    emit('perimetre_documente','done',fact_id=fact['id'],page=fact['page'],proof=proof)
    return True


def apply_record(row,proof):
    row.update(statut='hors_perimetre',comparaison=None,mode_verification='perimetre_documente',source=None,regle=None,
        verification_perimetre_core=proof,explication='Le texte désigne ce repère comme existant, hors opération et non modifié ; deux lectures de l’image concordent avec sa ligne OCR.',
        action='Cet ouvrage est exclu des travaux contrôlés. Aucune conformité de l’existant n’est affirmée.',
        verification_article=dict(method='core_exclusion_documentee',outcome='information',eligible=True,checks=proof['checks'],missing=[],
            resolution=dict(kind='hors_perimetre_documente',detail='Exclusion des travaux établie ; aucun verdict juridique sur l’existant.')))
