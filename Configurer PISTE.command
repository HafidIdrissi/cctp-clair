#!/bin/bash
set -eu
cd "$(dirname "$0")"
python=local/macos/python-3.11.18/python/bin/python3.11
[[ -x "$python" ]] || { echo "Ouvrez d’abord Lancer CCTP Clair.command."; exit 1; }
exec "$python" -B tools/configurer_piste.py
