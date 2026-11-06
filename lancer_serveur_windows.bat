@echo off
chcp 65001 >nul
REM ==============================================================================
REM Lanceur du Serveur Facture-Checker pour Windows (.bat)
REM Double-cliquez simplement sur ce fichier sous Windows.
REM Installe automatiquement Python et les dépendances si absents,
REM puis démarre le serveur et ouvre directement le site dans le navigateur.
REM ==============================================================================

title Facture-Checker : Scanner & Audit Mobile
cd /d "%~dp0"

echo ============================================================
echo      PROJET ARGUS : SCANNER & AUDIT DE FACTURES (WINDOWS)    
echo ============================================================
echo.

REM 1. Detection et installation automatique de Python si absent
set "PYTHON_CMD="

REM Verification dans le PATH (python ou py launcher)
where python >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    where py >nul 2>nul && set "PYTHON_CMD=py -3"
)

REM Verification des chemins d'installation standards de Python
if not defined PYTHON_CMD (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "C:\Program Files\Python3*" "C:\Python3*") do (
        if exist "%%D\python.exe" (
            set "PATH=%%D;%%D\Scripts;%PATH%"
            set "PYTHON_CMD=%%D\python.exe"
        )
    )
)

REM Si Python n'est toujours pas present, installation automatique silencieuse
if not defined PYTHON_CMD (
    echo [INFO] Python n'a pas ete detecte sur ce PC.
    echo [INFO] Installation automatique de Python en cours...
    echo        Veuillez patienter quelques instants...
    
    where winget >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        echo [INFO] Installation via Windows Package Manager (winget)...
        winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
    ) else (
        echo [INFO] Telechargement de l'installateur officiel Python...
        set "TEMP_INSTALLER=%TEMP%\python_installer.exe"
        where curl >nul 2>nul
        if %ERRORLEVEL% equ 0 (
            curl -Lo "%TEMP_INSTALLER%" "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
        ) else (
            powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '$env:TEMP_INSTALLER'"
        )
        if exist "%TEMP_INSTALLER%" (
            echo [INFO] Execution de l'installation silencieuse...
            "%TEMP_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 SimpleInstall=1
            del "%TEMP_INSTALLER%" >nul 2>nul
        )
    )

    REM Recharger le PATH localement apres installation
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "C:\Program Files\Python3*" "C:\Python3*") do (
        if exist "%%D\python.exe" (
            set "PATH=%%D;%%D\Scripts;%PATH%"
            set "PYTHON_CMD=%%D\python.exe"
        )
    )
    where python >nul 2>nul && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo [ATTENTION] Impossible d'installer Python automatiquement.
    echo Rendez-vous sur https://www.python.org/downloads/
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 2. Gestion de l'environnement virtuel venv
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Creation de l'environnement virtuel venv...
    %PYTHON_CMD% -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERREUR] Echec de creation de l'environnement virtuel venv.
        pause
        exit /b 1
    )
)

echo [INFO] Activation de l'environnement virtuel...
call venv\Scripts\activate.bat

REM 3. Verification et installation automatique des dependances requises
python -c "import fastapi, uvicorn, PIL, pandas" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] Installation automatique des dependances requises (FastAPI, PaddleOCR, etc.)...
    echo        Cette etape s'effectue automatiquement avant le premier lancement.
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [ATTENTION] Des avertissements sont survenus pendant l'installation des dependances.
    )
) else (
    echo [INFO] Toutes les dependances sont deja installees et pretes.
)

REM 4. Ouverture automatique du navigateur par defaut sur la page locale
echo.
echo [INFO] Ouverture automatique de l'interface locale dans le navigateur...
echo        👉 http://localhost:8000
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"

REM 5. Demarrage du serveur web
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
    pause
)
