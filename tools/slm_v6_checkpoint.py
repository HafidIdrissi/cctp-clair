"""Local per-point checkpoints. Never reuse evidence across engine identities."""
import ast
import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def code_snapshot(entry):
    """Hash the local import graph, including dynamically read rule data."""
    entry = Path(entry).resolve()
    root = entry.parent
    pending = [entry]
    found = {}
    while pending:
        path = pending.pop()
        if path.name in found:
            continue
        raw = path.read_bytes()
        found[path.name] = hashlib.sha256(raw).hexdigest()
        tree = ast.parse(raw.decode('utf-8-sig'), filename=str(path))
        for node in ast.walk(tree):
            names = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                     [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                local = root / (name.split('.')[0] + '.py')
                if local.is_file() and local.name not in found:
                    pending.append(local)
    rule_data = root / 'slm_v5_sources_reviewed.json'
    if rule_data.is_file():
        found[rule_data.name] = hashlib.sha256(rule_data.read_bytes()).hexdigest()
    reference_catalogue = root.parent / 'RAG_RER_V/references/catalogue.json'
    if reference_catalogue.is_file():
        raw=reference_catalogue.read_bytes()
        found['references/catalogue.json']=hashlib.sha256(raw).hexdigest()
        for item in json.loads(raw).get('references',[]):
            source=(reference_catalogue.parent/item['file']).resolve()
            if not source.is_relative_to(reference_catalogue.parent.resolve()):
                raise ValueError('Référence hors du catalogue local.')
            found['references/'+item['file']]=hashlib.sha256(source.read_bytes()).hexdigest()
    return dict(sorted(found.items()))


def make_manifest(request, code, model):
    identity = dict(version=VERSION, request_sha256=digest(request), code_sha256=digest(code),
                    code_files=code, model=model,
                    inference_policy='Code hash binds inference settings; effective options remain in each exchange.request.options.')
    return dict(identity, identity_sha256=digest(identity), created_at=now())


def compatible(stored, expected):
    if not isinstance(stored, dict) or stored.get('version') != VERSION:
        return False
    identity = {k: v for k, v in stored.items() if k not in ('created_at', 'identity_sha256')}
    return (stored.get('identity_sha256') == digest(identity) == expected.get('identity_sha256')
            and identity == {k: v for k, v in expected.items() if k not in ('created_at', 'identity_sha256')})


class PointStore:
    """A missing/corrupt point is recomputed, never interpreted as a verdict."""
    def __init__(self, folder, manifest, attempt, guard=None):
        self.folder = Path(folder) / 'points'
        self.manifest = manifest
        self.attempt = attempt
        self.guard = guard
        self.events = []
        self.previous = {}
        self.reused = 0
        self.saved = 0

    def key(self, inputs):
        return digest(inputs)

    def restore(self, inputs):
        if self.guard:
            self.guard()
        key = self.key(inputs)
        path = self.folder / (key + '.json')
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(record,dict) or not isinstance(record.get('content'),dict):
                raise ValueError('Point incomplet')
            content = record['content']
            if record['sha256'] != digest(content):
                raise ValueError('Empreinte du point invalide')
            if (content['version'] != VERSION or content['identity_sha256'] != self.manifest['identity_sha256']
                    or content['input_sha256'] != key or content['fact_id'] != inputs['row']['fait']['id']):
                raise ValueError('Identité du point incompatible')
            attempts = content['attempts']
            if not isinstance(attempts, list) or not attempts:
                raise ValueError('Historique absent')
            current = attempts[-1]
            row = current['row']
            exchanges = current['exchanges']
            if (not isinstance(row, dict) or row.get('fait') != inputs['row']['fait']
                    or not isinstance(exchanges, list) or not all(isinstance(e, dict) for e in exchanges)):
                raise ValueError('Résultat incomplet')
            result = row['verification_article']
            if not isinstance(result, dict) or result.get('outcome') not in ('respecte', 'ecart', 'information', 'indetermine', 'erreur_technique'):
                raise ValueError('Contrôle incomplet')
            self.previous[key] = copy.deepcopy(attempts)
            if (result.get('outcome') == 'erreur_technique' or result.get('review_state') != 'completed'
                    or result.get('resolution_attempt',{}).get('status')=='error'
                    or any(e.get('status')=='error' and not e.get('recovered_by_retry') for e in exchanges)):
                self.events.append(dict(fact_id=content['fact_id'], action='recomputed_technical_error', attempts=copy.deepcopy(attempts)))
                return None
            self.reused += 1
            reuse = dict(input_sha256=key, saved_at=current['saved_at'], attempt=current['attempt'])
            self.events.append(dict(fact_id=content['fact_id'], action='reused', **reuse))
            return dict(row=copy.deepcopy(row), exchanges=copy.deepcopy(exchanges), provenance=reuse)
        except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            self.events.append(dict(fact_id=inputs['row']['fait']['id'], action='recomputed_invalid_checkpoint', reason=str(exc)[:200]))
            return None

    def save(self, inputs, row, exchanges):
        if self.guard:
            self.guard()
        key = self.key(inputs)
        attempt = dict(attempt=self.attempt, saved_at=now(), row=copy.deepcopy(row), exchanges=copy.deepcopy(exchanges))
        content = dict(version=VERSION, identity_sha256=self.manifest['identity_sha256'], input_sha256=key,
                       fact_id=inputs['row']['fait']['id'], attempts=self.previous.get(key, []) + [attempt])
        atomic_json(self.folder / (key + '.json'), dict(content=content, sha256=digest(content)))
        self.saved += 1

    def summary(self):
        return dict(version=VERSION, identity_sha256=self.manifest['identity_sha256'], attempt=self.attempt,
                    reused=self.reused, recomputed=self.saved, events=copy.deepcopy(self.events))
