"""Repair typed proposals from literal OCR; visual attribution stays mandatory.

No benchmark answers, thresholds or expected verdicts are read here. A repair
creates a proposal, not a legal conclusion. Original responses are preserved.
"""
import copy,hashlib,json,re,base64,io
from PIL import Image
from v4_8_document_service import norm
from v4_9_document_service import annotate,assign_ids,spatial_ocr
from v4_9_evidence import TOKEN,tokens
from slm_m3_journal import emit


def words_digest(words):
    # JavaScript preserves numeric values but serializes integral floats as
    # integers. Normalize the hash input only; immutable OCR stays untouched.
    def portable(value):
        if type(value) is float and value.is_integer():return int(value)
        if isinstance(value,dict):return {k:portable(v) for k,v in value.items()}
        if isinstance(value,list):return [portable(v) for v in value]
        return value
    return hashlib.sha256(json.dumps(portable(words),sort_keys=True).encode()).hexdigest()


def attach_geometry(readings):
    # The PDF preparer renders at max side 2400, OCRs that image, then
    # encodes a max-side-2048 preview. These are pixel transforms only.
    if readings.get('type_document')!='pdf':return readings
    for page in readings.get('pages_visuelles',[]):
        if page.get('core_ocr_geometry'):continue
        encoded=page.get('image_base64')
        if encoded:
            w,h=Image.open(io.BytesIO(base64.b64decode(encoded))).size
        elif page.get('detail_base64'):
            w,ch=Image.open(io.BytesIO(base64.b64decode(page['detail_base64']))).size
            h=2048
            if w>=1600 or ch!=int(h*.87)-int(h*.14):continue
        else:continue
        page['core_ocr_geometry']=dict(base_width=w,base_height=h,ocr_to_base=max(w,h)/2400,
            source='preparateur_pdf_2400px_encodage_2048px',physical_measure=False)
    return readings


def typed_object(raw):
    label=norm(' '.join(str(raw.get(k) or '') for k in ('element','citation_visible')))
    if re.search(r'bande.{0,15}eveil',label):return 'bande_eveil'
    if re.search(r'grille|fente',label):return 'fente_grille'
    if 'ressaut' in label:return 'ressaut'
    if re.search(r'devers',label):return 'devers_pieton'
    if re.search(r'largeur',label):
        if re.search(r'piste|bidirection|cyclable',label):return 'largeur_cyclable'
        if re.search(r'cheminement|trottoir|pieton|largeur libre',label):return 'largeur_pieton'
    return raw.get('type_fait')


def table_rows(page,observations):
    """Use unique measure positions to separate OCR table rows, never pixels.

    Bounds are inferred from the written measure positions, not from model
    states. Conflicting/missing values do not establish a row or its state.
    """
    if not re.search(r'tableau',norm(page.get('ocr',{}).get('text',''))):return {}
    words=page.get('ocr',{}).get('words',[]);anchors=[]
    for index,raw in enumerate(observations):
        values=tokens(raw.get('citation_visible',''))
        if len(set(values))!=1:continue
        value,unit=values[0]
        matching=[]
        for w in words:
            if re.fullmatch(r'\d+(?:[.,]\d+)?',w['text']) and float(w['text'].replace(',','.'))==value:
                cy=w['y']+w['height']/2
                if any(norm(u['text']).strip(';,.:')==unit and 0<u['x']-w['x']-w['width']<100
                    and abs(u['y']+u['height']/2-cy)<max(w['height'],u['height']) for u in words):matching.append(cy)
        if len(matching)==1:anchors.append((matching[0],index))
    if len(anchors)<2 or len({a[0] for a in anchors})!=len(anchors):return {}
    anchors.sort();found={}
    for n,(y,index) in enumerate(anchors):
        top=(anchors[n-1][0]+y)/2 if n else y-(anchors[1][0]-y)/2
        bottom=(anchors[n+1][0]+y)/2 if n+1<len(anchors) else y+(y-anchors[n-1][0])/2
        row=[w for w in words if top<=w['y']+w['height']/2<bottom]
        text=spatial_ocr({'ocr':{'words':row}}).replace(' | ',' ')
        # Require the object's written name, not the model's category alone.
        obj=norm(observations[index].get('element',''))
        terms=re.findall(r'[a-z]{4,}',obj)
        if not terms or not all(t in norm(text) for t in terms):continue
        state_anchors=[w['x'] for w in row if norm(w['text']) in ('projet','existant')]
        state_text=''
        if state_anchors:
            state_text=spatial_ocr({'ocr':{'words':[w for w in row if w['x']>=min(state_anchors)-5]}}).replace(' | ',' ')
        found[index]=dict(text=text,state_text=state_text,top=top,bottom=bottom,
            words_sha256=words_digest(row))
    return found


def table_binding_matches(fact,readings):
    pages=[p for p in readings.get('pages_visuelles',[]) if p.get('page')==fact.get('page')]
    if len(pages)!=1:return False
    page=pages[0];raw=(page.get('vision') or {}).get('observations_brutes_modele',[])
    rows=table_rows(page,raw)
    matches=[row for index,row in rows.items() if raw[index].get('repere')==fact.get('repere')]
    return len(matches)==1 and matches[0]==fact.get('preuve_ligne_ocr_core')


def repair(readings):
    attach_geometry(readings)
    for page in readings.get('pages_visuelles',[]):
        if not page.get('vision'):continue
        original=copy.deepcopy(page['vision'])
        raw=copy.deepcopy(original.get('observations_brutes_modele') or original.get('observations',[]))
        rows=table_rows(page,raw);changes=[]
        for index,item in enumerate(raw):
            kind=typed_object(item)
            if kind!=item.get('type_fait'):
                changes.append(dict(index=index,field='type_fait',before=item.get('type_fait'),after=kind));item['type_fait']=kind
            quote=item.get('citation_visible','');values=list(TOKEN.finditer(quote))
            if kind not in ('bande_eveil','absence_amenagement_cyclable','autre') and len(values)==1:
                token=values[0][0]
                if norm(quote) in norm(page['ocr'].get('text','')):
                    item['valeur_inscrite']=token
            physical=rows.get(index)
            if physical:
                written=re.sub(r'\s+',' ',norm(physical['state_text']));state=None
                if re.search(r'\bprojet\b',written) and not re.search(r'existant',written):state='projet'
                if re.search(r'existant',written) and not re.search(r'\bprojet\b',written):state='existant'
                if state:
                    changes.append(dict(index=index,field='etat',before=item.get('etat'),after=state,evidence=physical));item['etat']=state
                # Only row-bound explicit phrases, not a global table flag.
                item['hors_operation']=bool(state=='existant' and re.search(r'hors\s+operation',written) and 'non modifie' in written) or None
                item['sans_obstacle_deux_cotes']=bool(re.search(r'aucun mur ni obstacle.{0,15}deux cotes',written,re.S)) or None
        # Recover a complete literal annotation missed by the model. It will
        # still need the normal visual attribution and source verification.
        for line in page.get('ocr',{}).get('lines',[]):
            n=norm(line);values=list(TOKEN.finditer(line))
            if not ('grille' in n and 'fente' in n and len(values)==1):continue
            if any(o.get('type_fait')=='fente_grille' and tokens(o.get('valeur_inscrite',''))==tokens(values[0][0])
                   and 'fente' in norm(o.get('citation_visible','')) for o in raw):continue
            proposal=dict(type_fait='fente_grille',repere=None,element='Fentes de grille',valeur_inscrite=values[0][0],
                information=None,citation_visible=line,etat='non_precise',hors_operation=None,sans_obstacle_deux_cotes=None,ambiguite=None)
            raw.append(proposal);changes.append(dict(field='proposition_ocr',after=proposal))
        page['vision_originale_core']=original
        normalized=[]
        if len(raw)>28:raise ValueError('Trop de propositions OCR à réparer ; aucune troncature.')
        for start in range(0,len(raw),14):
            normalized.extend(annotate(dict(resume=original.get('resume',''),observations=raw[start:start+14]),page,core_axes=True)['observations'])
        page['vision']=dict(resume=original.get('resume',''),observations=normalized,
            observations_brutes_modele=original.get('observations_brutes_modele',[]),observations_reparees_core=raw)
        for f in normalized:
            if 'pente longitudinale' in norm(f.get('citation_visible','')) and 'devers' not in norm(f.get('citation_visible','')):
                values=tokens(f['citation_visible'])
                if len(values)==1 and values[0][1]=='%' and norm(f['citation_visible']) in norm(page.get('ocr',{}).get('text','')):
                    f.update(type_fait='pente_longitudinale',valeur=values[0][0],unite='%',valeur_m=None)
                    changes.append(dict(field='type_fait_core_apres_normalisation',after='pente_longitudinale',citation=f['citation_visible']))
            for index,physical in rows.items():
                item=raw[index]
                if f.get('repere')==item.get('repere') and f.get('citation_visible')==item.get('citation_visible'):
                    f['preuve_ligne_ocr_core']=physical
                    # A row-bound exclusion is not a global Existant flag.
                    if item.get('etat')=='existant' and item.get('hors_operation') is True:
                        f['hors_operation']=True
        page['reparations_core']=changes
        emit('reparation_extraction','done',page=page['page'],changes=changes,
            scope='Propositions OCR réparées ; aucune conclusion ni attribution visuelle déduite.')
    return assign_ids(readings,retain_measurements=True)
