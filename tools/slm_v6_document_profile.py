"""Recognize a submitted catalogue reference by all native pages, not its name.

This annotates the scope of review. It never suppresses a point or confers a
verdict. Comparing a reference against itself is explicitly excluded.
"""
import hashlib
import json
from pathlib import Path
import re
from io import BytesIO
from pypdf import PdfReader
from slm_v6_references import CATALOGUE


def native_signature(pages):
    return hashlib.sha256(json.dumps([re.sub(r'\s+','',p) for p in pages],ensure_ascii=False).encode()).hexdigest()


def profile(readings,catalogue_path=CATALOGUE):
    pages=readings.get('text') or []
    result=dict(kind='document_a_controler',reference_identity=None,does_not_establish_compliance=True)
    if not pages:return result
    catalogue_path=Path(catalogue_path)
    for entry in json.loads(catalogue_path.read_text(encoding='utf-8')).get('references',[]):
        if entry.get('page_count')!=len(pages):continue
        path=(catalogue_path.parent/entry['file']).resolve()
        if not path.is_relative_to(catalogue_path.parent.resolve()):raise ValueError('Référence hors catalogue')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Référence modifiée')
        reader=PdfReader(BytesIO(raw))
        native=[p.extract_text(extraction_mode='layout') or '' for p in reader.pages]
        if native_signature(native)!=native_signature(pages):continue
        result.update(kind='referentiel_technique_soumis',reference_identity=dict(id=entry['id'],
            title=entry['title'],sha256=entry['sha256'],date=entry['source_date'],pages=len(pages)),
            native_sha256=native_signature(pages),
            message='Le document déposé est le référentiel technique lui-même. Le contrôle porte sur ses prescriptions écrites ; il ne démontre pas le respect de ces prescriptions par un projet. Il ne sera pas comparé à lui-même pour produire des validations.',
            evidence=dict(method='identite_de_toutes_les_pages_natives',pages_matched=len(pages)))
        break
    return result
