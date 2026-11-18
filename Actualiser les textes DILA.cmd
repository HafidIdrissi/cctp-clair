@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Lancez CCTP Clair une premiere fois avant cette operation.
  pause
  exit /b 1
)
echo Cette option telecharge le stock officiel LEGI et ses mises a jour.
echo Prevoyez plusieurs Go libres et fermez les analyses en cours.
choice /C ON /M "Mettre a jour l'index local des textes de mobilite"
if errorlevel 2 exit /b 0
".venv\Scripts\python.exe" -B tools\sync_dila_local.py --scope cctp --with-deltas
if errorlevel 1 (echo Mise a jour interrompue.) else (echo Index local mis a jour.)
pause
