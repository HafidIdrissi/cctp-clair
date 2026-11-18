"""Download official LEGI archives, then import them without PISTE credentials.

The initial stock is large. Downloads are staged and bounded, never extracted.
The manifest distinguishes the downloaded release from verified completeness.
"""
import argparse
import hashlib
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://echanges.dila.gouv.fr/OPENDATA/LEGI/'
DOWNLOADS = ROOT / 'RAG_RER_V/dila/downloads'


def listing():
    with urllib.request.urlopen(BASE, timeout=45) as response:
        html = response.read(2_000_000).decode('utf-8')
    names = re.findall(r'href="([^"/]+\.tar\.gz)"', html)
    return sorted(set(n for n in names if re.fullmatch(r'(?:Freemium_legi_global_|LEGI_)\d{8}-\d{6}\.tar\.gz', n)))


def download(name):
    if not re.fullmatch(r'(?:Freemium_legi_global_|LEGI_)\d{8}-\d{6}\.tar\.gz', name):
        raise ValueError('Nom d’archive DILA non autorisé.')
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    target = DOWNLOADS / name
    manifest_path = target.with_suffix(target.suffix + '.json')
    if target.exists() and manifest_path.exists():
        saved = json.loads(manifest_path.read_text(encoding='utf-8'))
        if target.stat().st_size == saved['bytes']:
            cached_digest = hashlib.sha256()
            with target.open('rb') as cached_file:
                for block in iter(lambda: cached_file.read(1024*1024),b''):
                    cached_digest.update(block)
            if cached_digest.hexdigest() == saved.get('sha256') and saved.get('url') == BASE+name:
                return target
            raise ValueError('Empreinte du cache DILA incohérente : '+name)
    temporary = target.with_suffix(target.suffix + '.part')
    digest = hashlib.sha256()
    count = 0
    with urllib.request.urlopen(urllib.request.Request(BASE+name,method='HEAD'),timeout=45) as response:
        expected = int(response.headers.get('Content-Length','0'))
    if not 0 < expected <= 3_000_000_000:
        raise ValueError('Taille officielle absente ou archive supérieure à 3 Go.')
    # Bounded range requests avoid intermediaries buffering a gigabyte response.
    with temporary.open('wb') as out:
        while count < expected:
            end = min(count + 8*1024*1024,expected)-1
            request = urllib.request.Request(BASE+name,headers={'Range':f'bytes={count}-{end}'})
            with urllib.request.urlopen(request,timeout=90) as response:
                if response.status != 206 or response.headers.get('Content-Range') != f'bytes {count}-{end}/{expected}':
                    raise ValueError('Le serveur n’a pas confirmé le segment demandé.')
                chunk = response.read(end-count+2)
            if len(chunk) != end-count+1:
                raise ValueError('Segment incomplet.')
            count += len(chunk)
            out.write(chunk)
            digest.update(chunk)
            if count % (64*1024*1024) == 0:
                out.flush()
                print(json.dumps({'archive':name,'downloaded_MB':round(count/1e6),'total_MB':round(expected/1e6)}),flush=True)
    temporary.replace(target)
    manifest_path.write_text(json.dumps(dict(url=BASE + name, bytes=count,
        sha256=digest.hexdigest(), downloaded_at=datetime.now(timezone.utc).isoformat(),
        integrity='Empreinte locale ; aucune signature éditeur vérifiée.'), indent=2), encoding='utf-8')
    print(json.dumps({'downloaded': name, 'bytes': count}), flush=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--download-workers', type=int, choices=[1,2,3,4], default=1)
    parser.add_argument('--with-deltas', action='store_true')
    parser.add_argument('--db', type=Path, default=ROOT/'RAG_RER_V/dila/.local/legi.sqlite')
    parser.add_argument('--scope', choices=['cctp', 'all'], default='cctp')
    args = parser.parse_args()
    names = listing()
    stocks = [n for n in names if n.startswith('Freemium_legi_global_')]
    if not stocks:
        raise RuntimeError('Aucun stock officiel repéré dans le dépôt.')
    stock = stocks[-1]
    stamp = re.search(r'(\d{8})-(\d{6})', stock).group(0)
    selected = [stock]
    if args.with_deltas:
        selected += [n for n in names if n.startswith('LEGI_') and re.search(r'(\d{8})-(\d{6})', n).group(0) > stamp]
    print(json.dumps({'archives_planned': len(selected), 'stock': stock, 'scope': args.scope}), flush=True)
    if args.download_only and args.download_workers > 1:
        with ThreadPoolExecutor(max_workers=args.download_workers) as pool:
            list(pool.map(download, selected))
        print(json.dumps({'downloads_complete':len(selected)}),flush=True)
        return
    store = None
    if not args.download_only:
        from dila_local_store import DilaStore, CCTP_TITLES
        store = DilaStore(args.db)
    for name in selected:
        path = download(name)
        if not args.download_only:
            release = datetime.strptime(re.search(r'\d{8}', name).group(0), '%Y%m%d').date().isoformat()
            kwargs = dict(source_url=BASE + name, snapshot_date=release,
                kind='stock' if name == stock else 'delta', coverage_scope='cctp' if args.scope == 'cctp' else 'all')
            if args.scope == 'cctp':
                kwargs['include_titles'] = CCTP_TITLES
            result = store.import_archive(path, **kwargs)
            print(json.dumps({'import': name, 'result': result}, ensure_ascii=True), flush=True)
    if not args.download_only:
        if args.with_deltas:
            store.verify_archive_sequence(selected,release)
        print(json.dumps(store.status(), ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
