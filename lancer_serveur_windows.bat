@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if exist "ARGUS.exe" (
    start "" "ARGUS.exe"
    exit /b 0
)
if exist "dist\ARGUS\ARGUS.exe" (
    start "" "dist\ARGUS\ARGUS.exe"
    exit /b 0
)
if exist "ARGUS\ARGUS.exe" (
    start "" "ARGUS\ARGUS.exe"
    exit /b 0
)
echo [ERREUR] Le package Windows ARGUS n'est pas present.
echo Utilisez la version livree par le responsable du logiciel.
echo Aucune installation automatique n'est effectuee sur ce poste.
pause
exit /b 1
