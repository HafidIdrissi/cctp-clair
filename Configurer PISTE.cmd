@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ouvrez d'abord Lancer CCTP Clair.cmd pour installer le moteur.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -B tools\configurer_piste.py
pause
