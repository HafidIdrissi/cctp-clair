"""Offline DILA LEGI store; importing never downloads data or calls PISTE.

Use the latest official stock, then each subsequent delta in publication order.
Archive processing is streaming and transactional; XML members are never extracted.
The parser follows DILA's ARTICLE XML, including historical versions and title dates:
https://echanges.dila.gouv.fr/OPENDATA/DTD_LEGIFRANCE/
https://echanges.dila.gouv.fr/OPENDATA/LEGI/

Only article documents are indexed, not the full hierarchy or other legal fonds.
``coverage_scope`` is an operator declaration, never a proof of completeness.
An unverified delta chain never advances ``verified_through`` beyond the stock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sqlite3
import tarfile
import unicodedata
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import date, datetime, timezone
from functools import lru_cache
from html import unescape
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / 'RAG_RER_V' / 'dila' / '.local' / 'legi.sqlite'
OFFICIAL_DIRECTORY = 'https://echanges.dila.gouv.fr/OPENDATA/LEGI/'
MAX_XML_BYTES = 16 * 1024 * 1024
ARTICLE_ID = re.compile(r'LEGIARTI\d{12}\Z')
DELETE_NAMES = {'liste_suppression.txt', 'liste_suppressions.txt',
                'suppression.txt', 'suppressions.txt', 'liste_suppression_legi.dat'}
DIRECTORY_DELETE_NAME = 'liste_suppression_legi_dossier.dat'
CCTP_TITLES = ('code de l environnement', 'code de la route', 'code de la voirie routiere',
               'code des transports', 'code de la commande publique',
               '2006 1657', '2006 1658', '15 janvier 2007',
               'accessibilite de la voirie', 'accessibilite des espaces publics')


class DilaError(ValueError):
    """Invalid input or import requiring an explicit operator correction."""


def _day(value, *, allow_none=False):
    if value in (None, '') and allow_none:
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise DilaError('Date attendue au format AAAA-MM-JJ.') from exc
    if parsed.isoformat() != value:
        raise DilaError('Date attendue au format AAAA-MM-JJ.')
    return value


@lru_cache(maxsize=16384)
def _norm(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[^\W_]+', value, re.UNICODE))


def _number(value):
    value = re.sub(r'^article\s+', '', str(value or ''), flags=re.I)
    return re.sub(r'[\s.\-–—]+', '', value).upper()


def _safe_name(name):
    name = name.replace('\\', '/')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or ':' in name or '\x00' in name:
        raise DilaError('Chemin dangereux dans l’archive : ' + repr(name))
    return name


def _safe_ignored_link(name, target, *, hardlink=False):
    """Validate an inert link lexically; never resolve it on the filesystem."""
    target = target.replace('\\', '/')
    if not target or target.startswith('/') or ':' in target or '\x00' in target:
        raise DilaError('Cible de lien dangereuse dans l’archive : ' + repr(target))
    resolved = posixpath.normpath(target if hardlink else posixpath.join(posixpath.dirname(name), target))
    if resolved == '..' or resolved.startswith('../'):
        raise DilaError('Cible de lien hors archive : ' + repr(target))


def _canonical_source_path(name):
    name = posixpath.normpath(_safe_name(name))
    return re.sub(r'^\d{8}-\d{6}/(?=legi/global/)', '', name)


def _text(node):
    if node is None:
        return ''
    pieces = [node.text or '']
    for child in node:
        if child.tag.lower() in {'p', 'br', 'div', 'li', 'tr', 'blockquote'}:
            pieces.append('\n')
        pieces.append(_text(child))
        if child.tag.lower() in {'p', 'div', 'li', 'tr', 'blockquote'}:
            pieces.append('\n')
        pieces.append(child.tail or '')
    return ''.join(pieces)


def _plain(node):
    return '\n'.join(' '.join(line.split()) for line in _text(node).splitlines()
                     if line.strip())


def _parse_xml(raw):
    if len(raw) > MAX_XML_BYTES:
        raise DilaError('Document XML trop volumineux.')
    # ElementTree does not retrieve external DTDs. Reject internal entities and
    # UTF-16/32 tricks rather than expanding attacker-controlled declarations.
    if b'\x00' in raw or re.search(br'<!ENTITY|<!DOCTYPE[^>]*\[', raw, re.I):
        raise DilaError('Entités XML internes interdites.')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DilaError('XML invalide : ' + str(exc)) from exc
    for element in root.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    if root.tag != 'ARTICLE':
        return None
    common = 'META/META_COMMUN/'
    article = 'META/META_SPEC/META_ARTICLE/'
    identity = root.findtext(common + 'ID', '').strip()
    if not ARTICLE_ID.fullmatch(identity):
        raise DilaError('Identifiant LEGIARTI absent ou invalide.')
    start_raw = root.findtext(article + 'DATE_DEBUT', '').strip()
    end_raw = root.findtext(article + 'DATE_FIN', '').strip()
    temporal_reasons = []
    def source_day(value, label):
        try:
            return _day(value, allow_none=True)
        except DilaError:
            temporal_reasons.append('invalid_' + label)
            return None
    start = source_day(start_raw, 'date_debut')
    end = source_day(end_raw, 'date_fin')
    # 2999 is DILA's unknown/infinite sentinel, never a known effective start.
    if start and start.startswith('2999-'):
        start = None
    if end and end.startswith('2999-'):
        end = None
    if start is None:
        temporal_reasons.append('unknown_date_debut')
    if not end_raw:
        temporal_reasons.append('unknown_date_fin')
    if start and end and end <= start:
        temporal_reasons.append('inverted_interval' if end < start else 'empty_interval')
    state = root.findtext(article + 'ETAT', '').strip()
    # Delayed abrogation can have a valid bounded interval before its future
    # end; transferred/repealed texts can still be evidence historically.
    # An open interval for these states does not establish an effective date.
    if state in {'ABROGE', 'ABROGE_DIFF', 'TRANSFERE', 'MODIFIE', 'PERIME', 'ANNULE'} and end is None:
        temporal_reasons.append('non_current_state_without_known_end')
    if state not in {'VIGUEUR', 'VIGUEUR_DIFF', 'ABROGE', 'ABROGE_DIFF', 'TRANSFERE', 'MODIFIE'}:
        temporal_reasons.append('unsupported_legal_state')
    contexts = root.findall('CONTEXTE/TEXTE')
    context = contexts[0] if contexts else None
    titles = []
    text_aliases = []
    for current_context in contexts:
        cid = current_context.get('cid', '')
        if cid:
            text_aliases.append({'id': cid, 'debut': None, 'fin': None})
        for title in current_context.findall('TITRE_TXT'):
            name = _plain(title) or title.get('c_titre_court', '')
            title_start = source_day(title.get('debut'), 'title_date_debut')
            title_end = source_day(title.get('fin'), 'title_date_fin')
            title_end = None if title_end and title_end.startswith('2999-') else title_end
            title_id = title.get('id_txt', cid)
            titles.append({'name': name, 'debut': title_start, 'fin': title_end,
                           'text_id': title_id, 'cid': cid})
            if title_id:
                text_aliases.append({'id': title_id, 'debut': title_start, 'fin': title_end})
    content = _plain(root.find('BLOC_TEXTUEL/CONTENU'))
    if not content:
        # Empty/repealed records are preserved for version chronology, but are
        # not offered as legal evidence by search().
        content = ''
    text_id = context.get('cid', '') if context is not None else ''
    nature = context.get('nature', '') if context is not None else ''
    return {
        'id': identity, 'numero': root.findtext(article + 'NUM', '').strip(),
        'text_id': text_id, 'nature': nature,
        'text_aliases': text_aliases,
        'nom_code': titles[-1]['name'] if titles else '', 'titles': titles,
        'texte': content, 'nota': _plain(root.find('NOTA/CONTENU')),
        'etat': state,
        'date_debut': start, 'date_fin_exclusive': end,
        'date_debut_raw': start_raw, 'date_fin_raw': end_raw,
        'temporal_uncertain': bool(temporal_reasons),
        'quarantined': bool(temporal_reasons),
        'quarantine_reasons': sorted(set(temporal_reasons)),
        'source_xml_url': root.findtext(common + 'URL', '').strip(),
        'source_url': 'https://www.legifrance.gouv.fr/' +
                      ('codes' if nature == 'CODE' else 'loda') + '/article_lc/' + identity,
        'sha256': hashlib.sha256(raw).hexdigest(),
        'text_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
        'version_links': [dict(link.attrib) for link in root.findall('VERSIONS/VERSION/LIEN_ART')],
        'provenance': 'dila_open_data',
    }


class DilaStore:
    def __init__(self, db_path=DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS articles(
                    id TEXT PRIMARY KEY, numero TEXT NOT NULL, numero_norm TEXT NOT NULL,
                    text_id TEXT NOT NULL, nom_code TEXT NOT NULL, texte TEXT NOT NULL,
                    date_debut TEXT, date_fin TEXT, temporal_uncertain INTEGER NOT NULL,
                    record TEXT NOT NULL, sha256 TEXT NOT NULL, import_id INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS articles_lookup ON articles(text_id, numero_norm, date_debut, date_fin);
                CREATE INDEX IF NOT EXISTS articles_number_date ON articles(numero_norm, date_debut, date_fin);
                CREATE TABLE IF NOT EXISTS titles(
                    article_id TEXT NOT NULL, title_norm TEXT NOT NULL, debut TEXT, fin TEXT);
                CREATE INDEX IF NOT EXISTS titles_lookup ON titles(title_norm, article_id);
                CREATE INDEX IF NOT EXISTS titles_article ON titles(article_id);
                CREATE TABLE IF NOT EXISTS article_contexts(
                    article_id TEXT NOT NULL, text_id TEXT NOT NULL, debut TEXT, fin TEXT);
                CREATE INDEX IF NOT EXISTS contexts_lookup ON article_contexts(text_id, article_id);
                CREATE INDEX IF NOT EXISTS contexts_article ON article_contexts(article_id);
                CREATE TABLE IF NOT EXISTS source_paths(
                    article_id TEXT NOT NULL, canonical_path TEXT NOT NULL,
                    source_file TEXT NOT NULL, sha256 TEXT NOT NULL, archive_url TEXT,
                    snapshot_date TEXT, import_id INTEGER NOT NULL,
                    PRIMARY KEY(article_id, canonical_path));
                CREATE INDEX IF NOT EXISTS source_path_lookup ON source_paths(canonical_path);
                CREATE TABLE IF NOT EXISTS directory_deletions(
                    import_id INTEGER NOT NULL, directory_path TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS file_deletions(
                    import_id INTEGER NOT NULL, file_path TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS imports(
                    id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, kind TEXT NOT NULL,
                    snapshot_date TEXT, source_url TEXT, source_file TEXT NOT NULL,
                    imported_at TEXT NOT NULL, result TEXT NOT NULL,
                    generation INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS imports_hash ON imports(sha256, generation);
                CREATE TABLE IF NOT EXISTS revisions(
                    article_id TEXT NOT NULL, sha256 TEXT NOT NULL, record TEXT NOT NULL,
                    raw_xml BLOB NOT NULL, first_import_id INTEGER NOT NULL,
                    PRIMARY KEY(article_id, sha256));
                CREATE TABLE IF NOT EXISTS deletions(
                    import_id INTEGER NOT NULL, article_id TEXT NOT NULL, reason TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                    id UNINDEXED, numero, nom_code, texte, tokenize='unicode61 remove_diacritics 2');
            ''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=60)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _metadata(db):
        return {row['key']: json.loads(row['value']) for row in db.execute('SELECT * FROM metadata')}

    @staticmethod
    def _set(db, **values):
        db.executemany('INSERT OR REPLACE INTO metadata VALUES (?, ?)',
                       [(key, json.dumps(value, ensure_ascii=False)) for key, value in values.items()])

    @staticmethod
    def _remove(db, identity, import_id, reason):
        previous = db.execute('SELECT rowid FROM articles WHERE id=?', (identity,)).fetchone()
        db.execute('DELETE FROM articles WHERE id=?', (identity,))
        db.execute('DELETE FROM titles WHERE article_id=?', (identity,))
        db.execute('DELETE FROM article_contexts WHERE article_id=?', (identity,))
        db.execute('DELETE FROM source_paths WHERE article_id=?', (identity,))
        if previous:
            db.execute('DELETE FROM articles_fts WHERE rowid=?', (previous['rowid'],))
        db.execute('INSERT INTO deletions VALUES (?, ?, ?)', (import_id, identity, reason))

    @staticmethod
    def _track_source(db, record, source_file, import_id):
        db.execute('INSERT OR REPLACE INTO source_paths VALUES(?,?,?,?,?,?,?)',
                   (record['id'], _canonical_source_path(source_file), source_file,
                    record['sha256'], record.get('archive_url'), record.get('snapshot_date'), import_id))

    def _ensure_source_paths(self, db):
        """Upgrade existing stores using only attested paths, never guessed aliases."""
        if self._metadata(db).get('source_paths_version') == 1:
            return
        for row in db.execute('SELECT record,import_id FROM articles').fetchall():
            record = json.loads(row['record'])
            for source in record.get('source_variants', [record]):
                if source.get('sha256'):
                    self._track_source(db, dict(record, sha256=source['sha256'],
                                                archive_url=source.get('archive_url', record.get('archive_url'))),
                                       source['source_file'], row['import_id'])
        self._set(db, source_paths_version=1,
                  source_path_inventory='attested_imported_paths_only')

    def _upsert(self, db, raw, *, source_url, source_file, snapshot_date, import_id,
                include_titles=None, indexed_ids=None):
        if include_titles:
            # Filter only title text (never an incidental citation in CONTENU),
            # before parsing the many unrelated articles of a global stock.
            title_text = ' '.join(unescape(part.decode('utf-8')) for part in
                                  re.findall(br'<TITRE_TXT\b[^>]*>(.*?)</TITRE_TXT>', raw, re.S))
            normalized_titles = _norm(title_text)
            if not any(term in normalized_titles for term in include_titles):
                # A correction can move an already indexed article outside the
                # selected scope. Do not retain its stale earlier content.
                filename_id = PurePosixPath(source_file).stem
                if indexed_ids is not None and filename_id not in indexed_ids:
                    return 'skipped'
                previous = db.execute('SELECT id,import_id FROM articles WHERE id=?', (filename_id,)).fetchone()
                if previous:
                    # Another contextual copy in this same archive can have a
                    # title outside scope without moving the article itself.
                    if previous['import_id'] == import_id:
                        include_titles = None
                    else:
                        parsed = _parse_xml(raw)
                        if parsed is None or parsed['id'] != filename_id:
                            raise DilaError('Identifiant XML différent du fichier source.')
                        self._remove(db, filename_id, import_id, 'moved_outside_selected_scope')
                        if indexed_ids is not None:
                            indexed_ids.discard(filename_id)
                        return 'deleted'
                if include_titles:
                    return 'skipped'
        record = _parse_xml(raw)
        if record is None:
            return 'skipped'
        filename_id = PurePosixPath(source_file).stem
        if ARTICLE_ID.fullmatch(filename_id) and filename_id != record['id']:
            raise DilaError('Identifiant XML différent du fichier source.')
        record.update(archive_url=source_url, source_file=source_file,
                      snapshot_date=snapshot_date, publisher='DILA')
        previous = None
        if indexed_ids is None or record['id'] in indexed_ids:
            previous = db.execute('SELECT rowid,sha256,import_id,record FROM articles WHERE id=?', (record['id'],)).fetchone()
        if previous and previous['sha256'] == record['sha256']:
            # The first copy of a delta may be byte-identical to the stock;
            # mark it as seen so a later conflicting copy in this same delta
            # is quarantined rather than silently replacing it.
            db.execute('UPDATE articles SET import_id=? WHERE id=?', (import_id, record['id']))
            self._track_source(db, record, source_file, import_id)
            return 'unchanged'
        encoded = json.dumps(record, ensure_ascii=False)
        db.execute('INSERT OR IGNORE INTO revisions VALUES (?, ?, ?, ?, ?)',
                   (record['id'], record['sha256'], encoded, raw, import_id))
        self._track_source(db, record, source_file, import_id)
        if previous and previous['import_id'] == import_id:
            original = json.loads(previous['record'])
            record = self._merge_contextual_copy(original, record)
            encoded = json.dumps(record, ensure_ascii=False)
        db.execute('INSERT OR REPLACE INTO articles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                   (record['id'], record['numero'], _number(record['numero']), record['text_id'],
                    record['nom_code'], record['texte'], record['date_debut'], record['date_fin_exclusive'],
                    int(record['temporal_uncertain']), encoded, record['sha256'], import_id))
        if previous:
            db.execute('DELETE FROM titles WHERE article_id=?', (record['id'],))
            db.execute('DELETE FROM article_contexts WHERE article_id=?', (record['id'],))
        db.executemany('INSERT INTO titles VALUES (?, ?, ?, ?)',
                       [(record['id'], _norm(t['name']), t['debut'], t['fin']) for t in record['titles']])
        db.executemany('INSERT INTO article_contexts VALUES (?, ?, ?, ?)',
                       [(record['id'], alias['id'], alias['debut'], alias['fin'])
                        for alias in record.get('text_aliases', [])])
        if previous:
            db.execute('DELETE FROM articles_fts WHERE rowid=?', (previous['rowid'],))
        rowid = db.execute('SELECT rowid FROM articles WHERE id=?', (record['id'],)).fetchone()['rowid']
        db.execute('INSERT INTO articles_fts(rowid,id,numero,nom_code,texte) VALUES (?, ?, ?, ?, ?)',
                   (rowid, record['id'], record['numero'], ' '.join(t['name'] for t in record['titles']), record['texte']))
        if indexed_ids is not None:
            indexed_ids.add(record['id'])
        return 'updated' if previous else 'inserted'

    @staticmethod
    def _merge_contextual_copy(original, incoming):
        """Keep all XML variants; never select a conflicting legal version."""
        def unique(items):
            values = {json.dumps(item, sort_keys=True, ensure_ascii=False): item for item in items}
            return [values[key] for key in sorted(values)]
        merged = dict(original)
        merged['titles'] = unique(original['titles'] + incoming['titles'])
        merged['text_aliases'] = unique(original.get('text_aliases', []) + incoming.get('text_aliases', []))
        merged['version_links'] = unique(original['version_links'] + incoming['version_links'])
        source = lambda item: {'sha256': item['sha256'], 'source_file': item['source_file'],
                               'archive_url': item.get('archive_url')}
        merged['source_variants'] = unique(original.get('source_variants', [source(original)]) + [source(incoming)])
        merged['merged_contexts'] = True
        reasons = set(original.get('quarantine_reasons', [])) | set(incoming.get('quarantine_reasons', []))
        semantic_fields = ('id', 'numero', 'texte', 'nota', 'date_debut_raw', 'date_fin_raw', 'etat')
        if any(original.get(key) != incoming.get(key) for key in semantic_fields):
            reasons.add('conflicted_same_archive')
        if 'conflicted_same_archive' in reasons:
            # The revisions table retains each exact candidate. The active
            # search record deliberately has no chosen text or effective date.
            merged.update(texte='', nota='', text_sha256=None, date_debut=None,
                          date_fin_exclusive=None, date_debut_raw=None, date_fin_raw=None,
                          etat='CONFLICTED', sha256='', sha256_role='no_single_xml_conflicting_variants')
            if original.get('numero') != incoming.get('numero'):
                merged['numero'] = ''
        merged['temporal_uncertain'] = bool(reasons)
        merged['quarantined'] = bool(reasons)
        merged['quarantine_reasons'] = sorted(reasons)
        return merged

    @staticmethod
    def _delete_manifest(raw):
        """Explicit UTF-8 list: one LEGI ID or XML path per line, no wildcards.

        Unknown deletion formats abort the transaction; they are never ignored.
        Non-article LEGI identifiers concern hierarchy documents not indexed here.
        """
        try:
            lines = raw.decode('utf-8-sig').splitlines()
        except UnicodeError as exc:
            raise DilaError('Liste de suppressions non UTF-8.') from exc
        result = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            name = PurePosixPath(_safe_name(line)).name
            identity = name[:-4] if name.lower().endswith('.xml') else name
            if not re.fullmatch(r'(?:LEGI(?:ARTI|TEXT|SCTA)|JORF(?:ARTI|TEXT))\d{12}', identity):
                raise DilaError('Suppression non reconnue : ' + repr(line))
            if ARTICLE_ID.fullmatch(identity):
                result.append(identity)
        return result

    @staticmethod
    def _delete_directory_manifest(raw):
        try:
            lines = raw.decode('utf-8-sig').splitlines()
        except UnicodeError as exc:
            raise DilaError('Liste de dossiers non UTF-8.') from exc
        paths = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.rsplit(None, 1)
            if len(parts) != 2 or parts[1] != 'D':
                raise DilaError('Suppression de dossier non reconnue : ' + repr(line))
            path = _canonical_source_path(parts[0]).rstrip('/')
            if not path.startswith('legi/global/') or len(PurePosixPath(path).parts) < 4:
                raise DilaError('Dossier de suppression hors périmètre LEGI : ' + repr(path))
            paths.append(path)
        return paths

    @staticmethod
    def _delete_file_manifest(raw):
        """Distinguish global bare IDs from exact DILA source-file removals.

        DILA's .dat lists often omit .xml and move an article between the
        en_vigueur/non_vigueur directories without deleting its identity.
        """
        # Reuse strict ID/path validation, without discarding path information.
        DilaStore._delete_manifest(raw)
        identities, paths = set(), set()
        for line in raw.decode('utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            canonical = _canonical_source_path(line)
            name = PurePosixPath(canonical).name
            identity = name[:-4] if name.lower().endswith('.xml') else name
            if not ARTICLE_ID.fullmatch(identity):
                continue
            if canonical == identity:
                identities.add(identity)
            else:
                paths.add(canonical if name.lower().endswith('.xml') else canonical + '.xml')
        return identities, paths

    def _apply_directory_deletions(self, db, paths, import_id, indexed_ids, file_paths=()):
        affected = set()
        for path in sorted(paths):
            # Binary interval includes descendants only (not similarly named
            # neighbouring directories). No filesystem operation is performed.
            lower, upper = path + '/', path + '0'
            affected.update(row['article_id'] for row in db.execute(
                'SELECT article_id FROM source_paths WHERE canonical_path>=? AND canonical_path<?', (lower, upper)))
            db.execute('DELETE FROM source_paths WHERE canonical_path>=? AND canonical_path<?', (lower, upper))
            db.execute('INSERT INTO directory_deletions VALUES (?,?)', (import_id, path))
        for path in sorted(file_paths):
            affected.update(row['article_id'] for row in db.execute(
                'SELECT article_id FROM source_paths WHERE canonical_path=?', (path,)))
            db.execute('DELETE FROM source_paths WHERE canonical_path=?', (path,))
            db.execute('INSERT INTO file_deletions VALUES (?,?)', (import_id, path))
        removed = rebuilt = 0
        for identity in sorted(affected):
            sources = db.execute('SELECT * FROM source_paths WHERE article_id=? ORDER BY import_id DESC,canonical_path',
                                 (identity,)).fetchall()
            # Prefer the newest attested copies. An older copy cannot resurrect
            # a superseded text merely because its old directory still exists.
            active = db.execute('SELECT import_id,sha256 FROM articles WHERE id=?', (identity,)).fetchone()
            if active:
                sources = [source for source in sources if source['import_id'] >= active['import_id'] or
                           (len(active['sha256']) == 64 and source['sha256'] == active['sha256'])]
            candidates = []
            for source in sources:
                revision = db.execute('SELECT raw_xml FROM revisions WHERE article_id=? AND sha256=?',
                                      (identity, source['sha256'])).fetchone()
                if revision:
                    candidates.append((source, revision['raw_xml']))
            self._remove(db, identity, import_id, 'source_path_deleted')
            indexed_ids.discard(identity)
            if not candidates:
                removed += int(active is not None)
                continue
            # Reconstruct from surviving XML variants, pruning deleted titles
            # and CIDs as well as paths. Conflicting survivors stay quarantined.
            for source, raw in candidates:
                self._upsert(db, raw, source_url=source['archive_url'], source_file=source['source_file'],
                             snapshot_date=source['snapshot_date'], import_id=import_id, indexed_ids=indexed_ids)
            rebuilt += 1
        return removed, rebuilt

    def import_archive(self, path, source_url=None, snapshot_date=None, *,
                       kind='stock', coverage_scope='unspecified', deleted_ids=(), include_titles=None):
        """Atomically replace a stock or apply a delta to an existing stock.

        A stock is the complete *provided archive*, not an assertion that it is
        the complete official LEGI corpus. XML-only imports remain partial.
        Dates are explicit or taken from DILA's YYYYMMDD-HHMMSS filename.
        Same-content replay in the current stock generation is a no-op.
        """
        path = Path(path)
        if kind not in {'stock', 'delta'}:
            raise DilaError('kind doit valoir stock ou delta.')
        if not isinstance(coverage_scope, str) or len(coverage_scope) > 500:
            raise DilaError('Périmètre de couverture invalide.')
        title_filter = tuple(sorted({_norm(term) for term in include_titles})) if include_titles else None
        if title_filter and any(not term for term in title_filter):
            raise DilaError('Filtre de titres vide.')
        inferred = re.search(r'(\d{8})-\d{6}', path.name)
        if snapshot_date is None and inferred:
            compact = inferred.group(1)
            snapshot_date = compact[:4] + '-' + compact[4:6] + '-' + compact[6:]
        snapshot_date = _day(snapshot_date, allow_none=True)
        source_url = str(source_url) if source_url else None
        deletes = tuple(deleted_ids)
        if any(not isinstance(x, str) or not ARTICLE_ID.fullmatch(x) for x in deletes):
            raise DilaError('Identifiant de suppression invalide.')
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        # Explicit deletions and declaration are part of the import identity.
        import_key = hashlib.sha256((digest.hexdigest() + json.dumps(
            [kind, snapshot_date, coverage_scope, source_url, sorted(deletes), title_filter])).encode()).hexdigest()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            meta = self._metadata(db)
            generation = int(meta.get('generation', 0))
            replay = db.execute('SELECT result FROM imports WHERE sha256=? AND generation=?',
                                (import_key, generation)).fetchone()
            if replay:
                return dict(json.loads(replay['result']), replayed=True)
            if kind == 'delta':
                if not meta.get('has_stock'):
                    raise DilaError('Importer un stock avant les deltas.')
                if not snapshot_date or not meta.get('snapshot_date'):
                    raise DilaError('Dates du stock et du delta nécessaires pour vérifier leur ordre.')
                if snapshot_date < meta['snapshot_date']:
                    raise DilaError('Delta antérieur au dernier import : reconstruire depuis le stock.')
                if list(title_filter or []) != meta.get('include_titles', []):
                    raise DilaError('Le delta doit conserver le filtre de titres du stock.')
                if inferred and meta.get('archive_order') and inferred[0] < meta['archive_order']:
                    raise DilaError('Delta antérieur au dernier import du même jour.')
            elif meta.get('snapshot_date') and snapshot_date and snapshot_date < meta['snapshot_date']:
                raise DilaError('Stock antérieur à la base courante : utiliser une autre base pour reconstruire.')
            if kind == 'stock':
                generation += 1
            now = datetime.now(timezone.utc).isoformat()
            cursor = db.execute('INSERT INTO imports(sha256,kind,snapshot_date,source_url,source_file,imported_at,result,generation) '
                                'VALUES(?,?,?,?,?,?,?,?)',
                                (import_key, kind, snapshot_date, source_url, path.name, now, '{}', generation))
            import_id = cursor.lastrowid
            counts = dict(inserted=0, updated=0, unchanged=0, skipped=0, deleted=0,
                          ignored_links=0, ignored_eli_links=0, deleted_directories=0,
                          rebuilt_after_directory_deletion=0, deleted_files=0,
                          rebuilt_after_source_deletion=0)
            if kind == 'stock':
                db.execute("INSERT INTO deletions SELECT ?, id, 'stock_replaced' FROM articles", (import_id,))
                db.execute('DELETE FROM articles')
                db.execute('DELETE FROM titles')
                db.execute('DELETE FROM article_contexts')
                db.execute('DELETE FROM source_paths')
                db.execute('DELETE FROM articles_fts')
                self._set(db, source_paths_version=1, source_path_inventory='attested_imported_paths_only')
            else:
                self._ensure_source_paths(db)
            indexed_ids = {row['id'] for row in db.execute('SELECT id FROM articles')}
            pending_deletes = set(deletes)
            pending_directory_deletes = set()
            pending_file_deletes = set()
            actual_xml_ids = set()
            # The input is a local seekable archive. GzipFile's buffered path
            # avoids _Stream's repeated buffer copies. Iteration and clearing
            # members keep memory bounded; no getmembers/extractall is used.
            with tarfile.open(path, mode='r:*') as archive:
                for member in archive:
                    name = _safe_name(member.name)
                    basename = PurePosixPath(name).name
                    if member.isdir():
                        archive.members.clear()
                        continue
                    if member.issym() or member.islnk():
                        # DILA supplies many ELI aliases. We index real XML
                        # members only; no link is extracted, opened or followed.
                        _safe_ignored_link(name, member.linkname, hardlink=member.islnk())
                        counts['ignored_links'] += 1
                        if '/legi/global/eli/' in '/' + name:
                            counts['ignored_eli_links'] += 1
                        archive.members.clear()
                        continue
                    if not member.isfile():
                        raise DilaError('Membre spécial interdit dans l’archive : ' + name)
                    suppression = 'suppr' in basename.casefold() or 'delet' in basename.casefold()
                    is_article = bool(re.fullmatch(r'LEGIARTI\d{12}\.xml', basename, re.I))
                    if suppression and basename.casefold() not in DELETE_NAMES | {DIRECTORY_DELETE_NAME}:
                        raise DilaError('Format de suppression non pris en charge : ' + name)
                    if not is_article and not suppression:
                        counts['skipped'] += 1
                        archive.members.clear()
                        continue
                    if member.size > MAX_XML_BYTES:
                        raise DilaError('Membre trop volumineux : ' + name)
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise DilaError('Membre illisible : ' + name)
                    raw = handle.read(MAX_XML_BYTES + 1)
                    if suppression:
                        if basename.casefold() == DIRECTORY_DELETE_NAME:
                            pending_directory_deletes.update(self._delete_directory_manifest(raw))
                        else:
                            deleted_identities, deleted_paths = self._delete_file_manifest(raw)
                            pending_deletes.update(deleted_identities)
                            pending_file_deletes.update(deleted_paths)
                    else:
                        action = self._upsert(db, raw, source_url=source_url, source_file=name,
                                              snapshot_date=snapshot_date, import_id=import_id,
                                              include_titles=title_filter, indexed_ids=indexed_ids)
                        counts[action] += 1
                        if action in {'inserted', 'updated', 'unchanged'}:
                            actual_xml_ids.add(PurePosixPath(name).stem)
                    archive.members.clear()
            if kind == 'stock' and counts['inserted'] == 0:
                raise DilaError('Stock sans article LEGI : la base précédente est conservée.')
            removed, rebuilt = self._apply_directory_deletions(db, pending_directory_deletes, import_id,
                                                               indexed_ids, pending_file_deletes)
            counts['deleted'] += removed
            counts['deleted_directories'] = len(pending_directory_deletes)
            counts['deleted_files'] = len(pending_file_deletes)
            counts['rebuilt_after_source_deletion'] = rebuilt
            counts['rebuilt_after_directory_deletion'] = rebuilt if pending_directory_deletes else 0
            for identity in sorted(pending_deletes):
                current = db.execute('SELECT import_id FROM articles WHERE id=?', (identity,)).fetchone()
                if current and identity in actual_xml_ids:
                    raise DilaError('Même article mis à jour et supprimé dans le même import : ' + identity)
                self._remove(db, identity, import_id, 'explicit_deletion')
                counts['deleted'] += int(current is not None)
            if kind == 'stock':
                self._set(db, stock_date=snapshot_date, coverage_scope=coverage_scope,
                          has_stock=True, generation=generation, verified_through=snapshot_date,
                          continuity_verified=True, include_titles=list(title_filter or []))
            else:
                # Publication may skip days or publish multiple deltas daily;
                # adjacent dates alone do not prove a complete archive sequence.
                self._set(db, continuity_verified=False)
            self._set(db, snapshot_date=snapshot_date, last_import_at=now,
                      last_archive=path.name, last_archive_url=source_url,
                      archive_order=inferred[0] if inferred else None)
            result = dict(counts, import_id=import_id, kind=kind, snapshot_date=snapshot_date,
                          archive_sha256=digest.hexdigest(), replayed=False)
            db.execute('UPDATE imports SET result=? WHERE id=?', (json.dumps(result), import_id))
            return result

    def verify_archive_sequence(self, expected_archives, through_date):
        """Compare successful imports with an externally checked DILA manifest.

        The caller must derive the ordered list from the official directory,
        starting with the current stock. This does not contact DILA and does not
        turn the selected article scope into exhaustive legal coverage.
        """
        through_date = _day(through_date)
        expected = list(expected_archives)
        if not expected or any(not isinstance(name, str) or PurePosixPath(name).name != name for name in expected):
            raise DilaError('Manifeste attendu : noms exacts stock puis deltas dans l’ordre.')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            meta = self._metadata(db)
            self._ensure_source_paths(db)
            rows = db.execute('SELECT source_file,kind FROM imports WHERE generation=? ORDER BY id',
                              (meta.get('generation', 0),)).fetchall()
            actual = [row['source_file'] for row in rows]
            if actual != expected or rows[0]['kind'] != 'stock' or any(r['kind'] != 'delta' for r in rows[1:]):
                raise DilaError('La liste importée ne correspond pas exactement au manifeste attendu.')
            if through_date != meta.get('snapshot_date'):
                raise DilaError('La date attestée doit être celle du dernier import.')
            self._set(db, verified_through=through_date, continuity_verified=True,
                      sequence_manifest_sha256=hashlib.sha256('\n'.join(expected).encode()).hexdigest(),
                      sequence_verification='compared_with_caller_provided_official_directory_manifest')
        return self.status()

    def import_xml(self, xml, source_url=None, snapshot_date=None, *, source_file='<memory>'):
        """Import one ARTICLE for a deliberately partial corpus (no download).

        Accept XML bytes/string, Path, or a binary stream. This operation lowers
        coverage assurance when used on a stock; it cannot certify freshness.
        """
        if isinstance(xml, Path):
            source_file = xml.name
            with xml.open('rb') as handle:
                raw = handle.read(MAX_XML_BYTES + 1)
        elif hasattr(xml, 'read'):
            raw = xml.read(MAX_XML_BYTES + 1)
        else:
            raw = xml.encode('utf-8') if isinstance(xml, str) else xml
        if not isinstance(raw, bytes):
            raise DilaError('XML attendu sous forme de texte UTF-8 ou octets.')
        snapshot_date = _day(snapshot_date, allow_none=True)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            now = datetime.now(timezone.utc).isoformat()
            meta = self._metadata(db)
            self._ensure_source_paths(db)
            if meta.get('has_stock') and (snapshot_date is None or
                    (meta.get('snapshot_date') and snapshot_date < meta['snapshot_date'])):
                raise DilaError('Un XML ajouté au stock doit porter une date au moins égale au dernier import.')
            cursor = db.execute('INSERT INTO imports(sha256,kind,snapshot_date,source_url,source_file,imported_at,result,generation) '
                                'VALUES(?,?,?,?,?,?,?,?)',
                                (hashlib.sha256(raw).hexdigest(), 'xml', snapshot_date, source_url,
                                 source_file, now, '{}', int(meta.get('generation', 0))))
            action = self._upsert(db, raw, source_url=source_url, source_file=source_file,
                                  snapshot_date=snapshot_date, import_id=cursor.lastrowid)
            if action == 'skipped':
                raise DilaError('Le document XML doit être un ARTICLE LEGI.')
            self._set(db, coverage_scope='partial_xml', continuity_verified=False,
                      verified_through=None, last_import_at=now,
                      snapshot_date=max(filter(None, [meta.get('snapshot_date'), snapshot_date]), default=None))
            result = {'action': action, 'import_id': cursor.lastrowid, 'snapshot_date': snapshot_date}
            db.execute('UPDATE imports SET result=? WHERE id=?', (json.dumps(result), cursor.lastrowid))
            return result

    def status(self):
        with self._connect() as db:
            meta = self._metadata(db)
            article_count = db.execute('SELECT count(*) FROM articles').fetchone()[0]
            usable_count = db.execute("SELECT count(*) FROM articles WHERE temporal_uncertain=0 AND texte<>''").fetchone()[0]
            quarantine_count = db.execute('SELECT count(*) FROM articles WHERE temporal_uncertain=1').fetchone()[0]
            quarantine_reasons = {}
            quarantined = []
            for row in db.execute('SELECT id,record FROM articles WHERE temporal_uncertain=1'):
                record = json.loads(row['record'])
                reasons = record.get('quarantine_reasons', ['legacy_temporal_uncertainty'])
                for reason in reasons:
                    quarantine_reasons[reason] = quarantine_reasons.get(reason, 0) + 1
                if len(quarantined) < 20:
                    quarantined.append({'id': row['id'], 'reasons': reasons,
                                        'date_debut_raw': record.get('date_debut_raw'),
                                        'date_fin_raw': record.get('date_fin_raw'),
                                        'etat': record.get('etat')})
            return dict(meta, db_path=str(self.db_path), article_count=article_count,
                        usable_article_count=usable_count,
                        temporal_uncertain_count=quarantine_count,
                        quarantined_count=quarantine_count,
                        quarantine_reason_counts=quarantine_reasons,
                        quarantine_examples=quarantined,
                        import_count=db.execute('SELECT count(*) FROM imports').fetchone()[0],
                        ready=usable_count > 0, corpus_complete=False,
                        coverage_scope=meta.get('coverage_scope', 'empty'),
                        snapshot_date=meta.get('snapshot_date'),
                        verified_through=meta.get('verified_through'),
                        continuity_verified=meta.get('continuity_verified', False),
                        source='dila_open_data', network_calls=0,
                        coverage_note='Seuls les articles des fichiers importés sont indexés. '
                                      'La couverture juridique et la présence de tous les deltas ne sont pas certifiées.')

    def search(self, query, reference_date, code=None, article=None, limit=10):
        reference_date = _day(reference_date)
        if not isinstance(query, str) or len(query) > 4000:
            raise DilaError('Requête invalide ou trop longue.')
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise DilaError('limit doit être compris entre 1 et 100.')
        tokens = re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', query), re.UNICODE)[:64]
        if not tokens and not article:
            return []
        clauses = ['a.date_debut<=?', '(a.date_fin IS NULL OR ?<a.date_fin)',
                   'a.temporal_uncertain=0', "a.texte<>''"]
        args = [reference_date, reference_date]
        join = ''
        order = 'a.id'
        if tokens:
            # Quote every lexical token. User punctuation cannot become FTS SQL.
            join = 'JOIN articles_fts ON articles_fts.id=a.id'
            clauses.append('articles_fts MATCH ?')
            args.append(' AND '.join('"' + token.replace('"', '""') + '"' for token in tokens))
            order = 'bm25(articles_fts), a.id'
        if article:
            if ARTICLE_ID.fullmatch(str(article)):
                clauses.append('a.id=?')
                args.append(str(article))
            else:
                clauses.append('a.numero_norm=?')
                args.append(_number(article))
        if code:
            clauses.append('(a.text_id=? OR EXISTS (SELECT 1 FROM titles t WHERE t.article_id=a.id AND t.title_norm=? '
                           'AND (t.debut IS NULL OR t.debut<=?) AND (t.fin IS NULL OR ?<t.fin)) '
                           'OR EXISTS (SELECT 1 FROM article_contexts c WHERE c.article_id=a.id AND c.text_id=? '
                           'AND (c.debut IS NULL OR c.debut<=?) AND (c.fin IS NULL OR ?<c.fin)))')
            args.extend([str(code), _norm(code), reference_date, reference_date,
                         str(code), reference_date, reference_date])
        with self._connect() as db:
            meta = self._metadata(db)
            rows = db.execute('SELECT a.* FROM articles a ' + join + ' WHERE ' + ' AND '.join(clauses) +
                              ' ORDER BY ' + order + ' LIMIT ?', args + [limit]).fetchall()
            results = []
            for row in rows:
                record = json.loads(row['record'])
                # Count all same-number active candidates, not just the FTS hit
                # subset, so a differing keyword cannot hide an overlap.
                relevant_ids = sorted({row['text_id']} | {alias['id'] for alias in record.get('text_aliases', []) if
                                     (not alias['debut'] or alias['debut'] <= reference_date) and
                                     (not alias['fin'] or reference_date < alias['fin'])})
                placeholders = ','.join('?' for _ in relevant_ids)
                overlapping = db.execute('SELECT b.id FROM articles b WHERE b.numero_norm=? '
                                         'AND b.date_debut<=? AND (b.date_fin IS NULL OR ?<b.date_fin) '
                                         'AND b.temporal_uncertain=0 AND (b.text_id IN (' + placeholders + ') '
                                         'OR EXISTS (SELECT 1 FROM article_contexts c WHERE c.article_id=b.id '
                                         'AND c.text_id IN (' + placeholders + ') '
                                         'AND (c.debut IS NULL OR c.debut<=?) AND (c.fin IS NULL OR ?<c.fin)))',
                                         [row['numero_norm'], reference_date, reference_date] + relevant_ids + relevant_ids +
                                         [reference_date, reference_date]).fetchall()
                title_matches = [t['name'] for t in record['titles'] if
                                 (not t['debut'] or t['debut'] <= reference_date) and
                                 (not t['fin'] or reference_date < t['fin'])]
                if title_matches:
                    record['nom_code'] = title_matches[-1]
                    if code:
                        matching_code = [name for name in title_matches if _norm(name) == _norm(str(code))]
                        if matching_code:
                            record['nom_code'] = matching_code[-1]
                verified = meta.get('verified_through')
                record.update(date_reference=reference_date,
                              version_ambiguous=len(overlapping) > 1,
                              overlapping_version_ids=[r['id'] for r in overlapping],
                              freshness_confirmed=bool(verified and reference_date <= verified),
                              verified_through=verified,
                              coverage_scope=meta.get('coverage_scope', 'empty'),
                              corpus_complete=False)
                results.append(record)
            return results


def main(argv=None):
    parser = argparse.ArgumentParser(description='Base locale DILA LEGI : aucun appel réseau.')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB_PATH)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    commands.add_parser('status')
    importing = commands.add_parser('import')
    importing.add_argument('path', type=Path)
    importing.add_argument('--kind', choices=('stock', 'delta'), default='stock')
    importing.add_argument('--snapshot-date')
    importing.add_argument('--source-url')
    importing.add_argument('--coverage-scope', default='unspecified')
    importing.add_argument('--scope', choices=('all', 'cctp'), default='all')
    searching = commands.add_parser('search')
    searching.add_argument('query', nargs='?', default='')
    searching.add_argument('--date', required=True, dest='reference_date')
    searching.add_argument('--code')
    searching.add_argument('--article')
    searching.add_argument('--limit', type=int, default=10)
    args = parser.parse_args(argv)
    try:
        store = DilaStore(args.db)
        if args.command in {'status', 'init'}:
            answer = store.status()
        elif args.command == 'import':
            if args.path.suffix.casefold() == '.xml':
                answer = store.import_xml(args.path, source_url=args.source_url, snapshot_date=args.snapshot_date)
            else:
                answer = store.import_archive(args.path, source_url=args.source_url, snapshot_date=args.snapshot_date,
                                              kind=args.kind,
                                              coverage_scope='cctp_mobilite_partial' if args.scope == 'cctp' else args.coverage_scope,
                                              include_titles=CCTP_TITLES if args.scope == 'cctp' else None)
        else:
            answer = store.search(args.query, args.reference_date, args.code, args.article, args.limit)
        print(json.dumps(answer, ensure_ascii=True, indent=2))
        return 0
    except (DilaError, OSError, sqlite3.Error, tarfile.TarError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
