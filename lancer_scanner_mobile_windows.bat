@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if exist "ARGUS.exe" (
    start "" "ARGUS.exe" --mobile
    exit /b 0
)
if exist "dist\ARGUS\ARGUS.exe" (
    start "" "dist\ARGUS\ARGUS.exe" --mobile
    exit /b 0
)
if exist "ARGUS\ARGUS.exe" (
    start "" "ARGUS\ARGUS.exe" --mobile
    exit /b 0
)
echo [ERREUR] Le package Windows ARGUS n'est pas present.
pause
exit /b 1
