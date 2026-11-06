@echo off
chcp 65001 >nul
REM ==============================================================================
REM Traitement automatique par lot des factures (CLI Batch Windows)
REM Analyse les images du dossier 'input_photos', verifie l'integrite legale,
REM effectue le rapprochement S/N et ouvre la synthese Excel.
REM ==============================================================================

title Facture-Checker : Audit Batch & Export Excel
cd /d "%~dp0"

echo ============================================================
echo   PROJET ARGUS : AUDIT AUTOMATIQUE DU DOSSIER INPUT_PHOTOS
echo ============================================================
echo.

REM 1. Verifier si Python est installe
set "PYTHON_CMD="
where python >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    where py >nul 2>nul && set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    echo [ERREUR] Python n'a pas ete detecte dans votre systeme.
    echo Rendez-vous sur https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 2. Verifier l'environnement virtuel
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Environnement virtuel absent, execution du script d'initialisation...
    call lancer_serveur_windows.bat
    exit /b 0
)

call venv\Scripts\activate.bat

REM 3. Lancer l'analyse batch
echo [INFO] Traitement des images du dossier 'input_photos'...
set PYTHONPATH=facture-checker;%PYTHONPATH%
python main.py --input-dir input_photos --output-excel factures_synthese.xlsx

if %ERRORLEVEL% EQU 0 (
    if exist "factures_synthese.xlsx" (
        echo.
        echo ============================================================
        echo [SUCCES] Synthese generee avec succes : factures_synthese.xlsx
        echo [INFO] Ouverture automatique du fichier Excel...
        echo ============================================================
        start factures_synthese.xlsx
    )
) else (
    echo.
    echo [ERREUR] Une erreur s'est produite lors de l'analyse du dossier.
)

pause
