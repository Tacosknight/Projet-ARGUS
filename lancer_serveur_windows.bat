@echo off
chcp 65001 >nul
REM ==============================================================================
REM Lanceur du Serveur Facture-Checker pour Windows (.bat)
REM Double-cliquez simplement sur ce fichier sous Windows.
REM Configure l'environnement, lance le serveur et ouvre automatiquement le navigateur.
REM ==============================================================================

title Facture-Checker : Scanner & Audit Mobile
cd /d "%~dp0"

echo ============================================================
echo      PROJET ARGUS : SCANNER & AUDIT DE FACTURES (WINDOWS)    
echo ============================================================
echo.

REM 1. Verifier si Python est installe (python ou py launcher)
set "PYTHON_CMD="
where python >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    where py >nul 2>nul && set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    echo [ERREUR] Python n'a pas ete trouve dans le PATH Windows.
    echo Rendez-vous sur https://www.python.org/downloads/
    echo N'oubliez pas de cocher "Add Python to PATH" lors de l'installation.
    echo.
    echo Ouverture du site officiel de Python...
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 2. Verifier / Creer l'environnement virtuel venv
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Creation de l'environnement virtuel venv...
    %PYTHON_CMD% -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERREUR] Echec de creation de l'environnement virtuel venv.
        pause
        exit /b 1
    )
    echo [INFO] Activation de l'environnement virtuel...
    call venv\Scripts\activate.bat
    echo [INFO] Mise a jour de pip et installation des dependances (OpenCV, PaddleOCR, FastAPI)...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [ATTENTION] Des avertissements sont survenus pendant l'installation des dependances.
    )
) else (
    echo [INFO] Activation de l'environnement virtuel...
    call venv\Scripts\activate.bat
)

REM 3. Ouvrir automatiquement le navigateur par defaut sur la page locale
echo [INFO] Ouverture automatique de l'interface locale dans le navigateur...
echo        👉 http://localhost:8000
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"

REM 4. Lancer le serveur uvicorn / FastAPI
echo.
echo [INFO] Demarrage du serveur web mobile...
echo [INFO] Pour arreter le serveur, fermez cette fenetre ou appuyez sur Ctrl+C.
echo ============================================================
echo.
set PYTHONPATH=facture-checker;%PYTHONPATH%
python server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERREUR] Le serveur s'est arrete avec un code erreur %ERRORLEVEL%.
)

pause
