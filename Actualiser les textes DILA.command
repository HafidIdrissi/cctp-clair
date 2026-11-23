#!/bin/bash
set -eu
cd "$(dirname "$0")"
python=local/macos/python-3.11.18/python/bin/python3.11
[[ -x "$python" ]] || { echo "Ouvrez d’abord Lancer CCTP Clair.command."; exit 1; }
echo "Terminez les analyses en cours. Le téléchargement des textes de mobilité nécessite plusieurs Go."
read -r -p "Actualiser les textes DILA (O/N) ? " answer
case "$answer" in
  O|o) SSL_CERT_FILE=/etc/ssl/cert.pem "$python" -B tools/sync_dila_local.py --scope cctp --with-deltas
       echo "Index local mis à jour." ;;
esac
