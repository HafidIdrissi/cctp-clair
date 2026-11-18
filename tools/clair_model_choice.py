"""Local comparison model selection for the single-job CCTP Clair worker."""
import json
import re
import urllib.request
from contextvars import ContextVar

DEFAULT = 'ministral-3:3b'
selected = ContextVar('comparison_model', default=DEFAULT)


def ollama(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request('http://127.0.0.1:11434/api/' + path, data,
                                     {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def local_models():
    models = []
    for tag in ollama('tags')['models']:
        name = tag['name']
        if 'cloud' in name.lower() or tag.get('remote_model'):
            continue
        info = ollama('show', {'model': name})
        if 'completion' in info.get('capabilities', []) and not (info.get('remote_model') or info.get('remote_host')):
            models.append(name)
    return models


def configure(service, jobs):
    import slm_core_engine as engine
    import slm_m3_engine as transport
    submit, execute, review = service.submit, service.execute, service.review

    def submit_selected(payload):
        meta = payload.get('metadata', {})
        job = meta.get('web_job_id')
        if job and re.fullmatch('[a-f0-9]{32}', str(job)):
            saved = json.loads((jobs / job / 'job.json').read_text(encoding='utf8'))
            meta['comparison_model'] = saved.get('comparison_model', DEFAULT)
        name = meta.get('comparison_model', DEFAULT)
        if name != DEFAULT and name not in local_models():
            raise ValueError('Modèle de comparaison indisponible dans Ollama.')
        return submit(payload)

    def execute_selected(ident, payload):
        token = selected.set(payload['metadata'].get('comparison_model', DEFAULT))
        try:
            return execute(ident, payload)
        finally:
            selected.reset(token)

    def review_selected(*args, **kwargs):
        # The worker accepts one active job. Vision retains its own model.
        prior = engine.MODEL, transport.MODEL
        engine.MODEL = transport.MODEL = selected.get()
        try:
            return review(*args, **kwargs)
        finally:
            engine.MODEL, transport.MODEL = prior

    service.submit, service.execute, service.review = submit_selected, execute_selected, review_selected
