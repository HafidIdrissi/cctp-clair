#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
major=$(sw_vers -productVersion | cut -d. -f1)
if (( major < 14 )); then echo "CCTP Clair nécessite macOS Sonoma 14 ou ultérieur."; exit 1; fi
case "$(uname -m)" in
  arm64) arch=aarch64; python_sha=3afb0567b2a2b30b3a7341bd143cb4e8a69f3d8e95d4641218eaa45f0fabbd07 ;;
  x86_64) arch=x86_64; python_sha=c2e4b51e535ead2e526b8974909a1b1e00fbc2ebe2281087b9b8b14dad0cad5d ;;
  *) echo "Architecture Mac inconnue."; exit 1 ;;
esac
runtime="$PWD/local/macos"
mkdir -p "$runtime"
python="$runtime/python-3.11.18/python/bin/python3.11"
url=http://127.0.0.1:8789
export OLLAMA_HOST=127.0.0.1:11434
export SSL_CERT_FILE=/etc/ssl/cert.pem
stage=$(mktemp -d "$runtime/installation.XXXXXX")
service_pid=''
ollama_pid=''
cleanup() {
  if [[ -n "$service_pid" ]]; then kill "$service_pid" 2>/dev/null || true; fi
  if [[ -n "$ollama_pid" ]]; then kill "$ollama_pid" 2>/dev/null || true; fi
  rm -rf "$stage"
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP

install_archive() {
  local address=$1 digest=$2 destination=$3
  curl --fail --location --retry 3 --output "$stage/download.tgz" "$address"
  echo "$digest  $stage/download.tgz" | shasum -a 256 --check --status
  mkdir "$stage/unpacked"
  tar -xzf "$stage/download.tgz" -C "$stage/unpacked"
  mv "$stage/unpacked" "$destination"
}
if [[ ! -x "$python" ]]; then
  echo "Premier lancement : installation de Python dans le dossier CCTP Clair."
  install_archive "https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.11.18%2B20261110-$arch-apple-darwin-install_only_stripped.tar.gz" "$python_sha" "$runtime/python-3.11.18"
fi
fingerprint=$(shasum -a 256 requirements.txt)
stamp="$runtime/python-3.11.18/requirements.sha256"
if [[ ! -f "$stamp" || "$(cat "$stamp")" != "$fingerprint" ]]; then
  "$python" -m pip install --disable-pip-version-check --only-binary=:all: -r requirements.txt
  echo "$fingerprint" > "$stamp"
fi
ready() {
  curl -fsS --max-time 2 "$url/health" 2>/dev/null | "$python" -c 'import sys,json; sys.exit(json.load(sys.stdin).get("service")!="cctp-clair-portable")' 2>/dev/null
}
tags() { curl -fsS --max-time 4 "http://$OLLAMA_HOST/api/tags" 2>/dev/null; }
has_model() {
  tags | "$python" -c 'import json,sys;sys.exit(not any(m.get("name")=="ministral-3:3b" for m in json.load(sys.stdin)["models"]))' 2>/dev/null
}
if ! has_model; then
  ollama=$(command -v ollama || true)
  if [[ -z "$ollama" && -x /Applications/Ollama.app/Contents/Resources/ollama ]]; then
    ollama=/Applications/Ollama.app/Contents/Resources/ollama
  fi
  if [[ -z "$ollama" ]]; then
    bundle="$runtime/ollama-0.40.17"
    if [[ ! -d "$bundle" ]]; then
      echo "Installation locale d’Ollama…"
      install_archive 'https://github.com/ollama/ollama/releases/download/v0.40.17/ollama-darwin.tgz' '4b9db20d077c5a1e52fb4a6f2e6791f76ae945fd07c9b1a5647c82e927826653' "$bundle"
    fi
    ollama=$(find "$bundle" -type f -name ollama -print | head -n 1)
    [[ -x "$ollama" ]] || { echo "Le programme Ollama est introuvable dans son archive."; exit 1; }
  fi
  if ! tags >/dev/null; then
    "$ollama" serve > "$runtime/ollama.log" 2>&1 &
    ollama_pid=$!
    for ((i=0;i<40;i++)); do tags >/dev/null && break; sleep 1; done
    tags >/dev/null || { echo "Ollama ne démarre pas. Consultez local/macos/ollama.log."; exit 1; }
  fi
  echo "Préparation de Ministral 3B. Le premier téléchargement peut prendre plusieurs minutes."
  "$ollama" pull ministral-3:3b
fi
if ! ready; then
  "$python" -B clair.py > "$runtime/service.log" 2>&1 &
  service_pid=$!
  for ((i=0;i<45;i++)); do ready && break; kill -0 "$service_pid" 2>/dev/null || break; sleep 1; done
  ready || { echo "Ouverture impossible. Consultez local/macos/service.log."; exit 1; }
fi
echo "CCTP Clair est prêt sur $url. Gardez cette fenêtre ouverte pendant les analyses."
open "$url" || echo "Ouvrez $url dans votre navigateur."
if [[ -n "$service_pid" ]]; then wait "$service_pid"; elif [[ -n "$ollama_pid" ]]; then wait "$ollama_pid"; fi
