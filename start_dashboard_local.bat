@echo off
REM Lanceur local du dashboard Flask (Windows)
REM Port 5050 pour éviter les conflits

cd /d %~dp0

echo.
echo =========================================
echo Dashboard HelloPro Scoring
echo =========================================
echo.

REM Installer Flask si nécessaire
pip install flask --quiet >nul 2>&1

REM Lancer Flask sur port 5050
echo Demarrage du dashboard sur http://127.0.0.1:5050
echo.
echo Appuyez sur Ctrl+C pour arreter
echo.

python dashboard/app.py

pause
