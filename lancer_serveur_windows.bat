@echo off
REM ==============================================================================
REM Lanceur du Serveur Facture-Checker pour Windows (.bat)
REM Double-cliquez simplement sur ce fichier sous Windows
REM ==============================================================================

title Facture-Checker Serveur Mobile
cd /d "%~dp0"

echo ============================================================
echo    DEMARRAGE DU SERVEUR MOBILE FACTURE-CHECKER (WINDOWS)    
echo ============================================================

REM 1. Verifier si Python est installe
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERREUR] Python n'a pas ete trouve dans le PATH Windows.
    echo Veuillez installer Python depuis https://www.python.org/
    pause
    exit /b 1
)

REM 2. Verifier / Creer l'environnement virtuel venv
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Creation de l'environnement virtuel venv...
    python -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERREUR] Echec de creation du venv.
        pause
        exit /b 1
    )
    echo [INFO] Installation des dependances (OpenCV, PaddleOCR, FastAPI)...
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

REM 3. Lancer le serveur
echo [INFO] Lancement du serveur...
set PYTHONPATH=facture-checker;%PYTHONPATH%
python server.py

pause
