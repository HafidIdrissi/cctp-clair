"""Create the Finder archive from tracked release files with POSIX permissions."""
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def pack(destination):
    root = Path(__file__).resolve().parents[1]
    snapshot = subprocess.check_output(['git', 'archive', '--format=tar', 'HEAD'], cwd=root)
    with tarfile.open(fileobj=io.BytesIO(snapshot)) as source, zipfile.ZipFile(destination, 'w') as output:
        for member in source:
            if not member.isfile() or member.name.startswith(('.git', 'tests/')):
                continue
            if member.name.endswith(('.cmd', '.ps1')):
                continue
            entry = zipfile.ZipInfo('CCTP Clair/' + member.name)
            entry.create_system = 3
            entry.external_attr = (0o100755 if member.mode & 0o111 else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(entry, source.extractfile(member).read())


if __name__ == '__main__':
    pack(sys.argv[1])
