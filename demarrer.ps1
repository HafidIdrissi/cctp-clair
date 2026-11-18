$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$url='http://127.0.0.1:8789'
function Ready {
    try { return (Invoke-RestMethod "$url/health" -TimeoutSec 2).service -eq 'cctp-clair-portable' } catch { return $false }
}
function Install-PackageWithWinget($id) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw "Installez $id (liens dans le guide), puis relancez ce fichier." }
    & winget.exe install --id $id --exact --source winget
    if ($LASTEXITCODE -ne 0) { throw "Installation de $id interrompue. Consultez le guide puis relancez." }
}
if (Ready) {
    try {
        $runningModels=Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
        if ($runningModels.models.name -contains 'ministral-3:3b') {Start-Process $url;exit 0}
    } catch {}
}
$py=Get-Command py.exe -ErrorAction SilentlyContinue
$python=$null
if ($py) {
    try {$python=& $py.Source -3.11 -c "import sys;print(sys.executable)" 2>$null} catch {$python=$null}
}
if (-not $python) {
    $known=@("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe","$env:ProgramFiles\Python311\python.exe")
    $python=$known | Where-Object {Test-Path $_} | Select-Object -First 1
    if (-not $python) { Install-PackageWithWinget 'Python.Python.3.11'; $python=$known | Where-Object {Test-Path $_} | Select-Object -First 1 }
    if (-not $python) { throw 'Python 3.11 installé ? Fermez cette fenêtre et relancez le fichier.' }
}
$venv=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venv)) { & $python -m venv .venv; if ($LASTEXITCODE) {throw 'Création du dossier Python interrompue.'} }
$stamp=Join-Path $PSScriptRoot '.venv\requirements.sha256'
$hash=(Get-FileHash requirements.txt).Hash
if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $hash) {
    & $venv -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE) {throw 'Téléchargement des composants interrompu. Vérifiez Internet et relancez.'}
    Set-Content $stamp $hash
}
$ollama=(Get-Command ollama.exe -ErrorAction SilentlyContinue).Source
if (-not $ollama) {$ollama="$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"}
if (-not (Test-Path $ollama)) {Install-PackageWithWinget 'Ollama.Ollama'}
if (-not (Test-Path $ollama)) {throw 'Installez Ollama puis relancez.'}
$env:OLLAMA_HOST='127.0.0.1:11434'
try {$tags=Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3}
catch {
    Start-Process $ollama -ArgumentList serve -WindowStyle Hidden
    foreach ($i in 1..20) {Start-Sleep -Seconds 1;try {$tags=Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2;break}catch{}}
    if (-not $tags) {throw 'Ouvrez Ollama depuis le menu Démarrer puis réessayez.'}
}
if ($tags.models.name -notcontains 'ministral-3:3b') {
    Write-Host 'Premier lancement : téléchargement du modèle sur votre PC. Gardez cette fenêtre ouverte.'
    & $ollama pull 'ministral-3:3b'
    if ($LASTEXITCODE) {throw 'Téléchargement du modèle interrompu. Relancez pour reprendre.'}
}
if (Ready) { Start-Process $url; exit 0 }
New-Item -ItemType Directory -Force local | Out-Null
$service=Start-Process $venv -ArgumentList '-B','clair.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardError 'local/erreur.log' -RedirectStandardOutput 'local/service.log'
foreach ($i in 1..45) {
    if (Ready) {Start-Process $url;exit 0}
    if ($service.HasExited) {break}
    Start-Sleep -Seconds 1
}
throw 'Ouverture impossible. Consultez local/erreur.log, notamment si le port 8789 est occupé.'
