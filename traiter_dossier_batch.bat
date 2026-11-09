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

echo Le traitement par lot est maintenant integre a ARGUS.
echo Importez plusieurs fichiers depuis l'interface, sans installer Python.
call lancer_serveur_windows.bat
