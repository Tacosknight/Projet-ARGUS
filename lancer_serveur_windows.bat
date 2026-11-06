@echo off
setlocal EnableExtensions
title Facture-Checker : Scanner ^& Audit Mobile

:: Positionnement dans le repertoire du script
cd /d "%~dp0"

echo ============================================================
echo      PROJET ARGUS : SCANNER ^& AUDIT DE FACTURES (WINDOWS)
echo ============================================================
echo.

:: ------------------------------------------------------------------
:: 1. Detection de Python
:: ------------------------------------------------------------------
echo [1/4] Recherche de Python sur votre systeme...
set "PYTHON_EXEC="

:: Test 1 : Commande 'python' dans le PATH
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PYTHON_EXEC=python"
    goto :python_ok
)

:: Test 2 : Commande 'py' (lanceur Python Windows officiel)
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PYTHON_EXEC=py -3"
    goto :python_ok
)

:: Test 3 : Chemins d'installation standards utilisateur (AppData)
for /d %%I in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%I\python.exe" (
        set "PYTHON_EXEC=%%I\python.exe"
        goto :python_ok
    )
)

:: Test 4 : Chemins d'installation standards machine (Program Files)
for /d %%I in ("C:\Program Files\Python3*") do (
    if exist "%%I\python.exe" (
        set "PYTHON_EXEC=%%I\python.exe"
        goto :python_ok
    )
)

for /d %%I in ("C:\Python3*") do (
    if exist "%%I\python.exe" (
        set "PYTHON_EXEC=%%I\python.exe"
        goto :python_ok
    )
)

:: ------------------------------------------------------------------
:: 2. Installation automatique si Python est absent
:: ------------------------------------------------------------------
echo [INFO] Python n'a pas ete detecte dans le PATH.
echo [INFO] Demarrage de l'installation automatique de Python...
echo        Veuillez patienter pendant le telechargement...
echo.

:: Tentative via winget (Windows Package Manager inclus sur Windows 10/11)
where winget >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [INFO] Installation via Windows Package Manager (winget)...
    winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
    goto :recheck_python
)

:: Tentative de telechargement direct de l'installateur officiel
echo [INFO] Telechargement de l'installateur officiel Python 3.12...
set "TEMP_INSTALLER=%TEMP%\python_installer_%RANDOM%.exe"

where curl >nul 2>nul
if %ERRORLEVEL% equ 0 (
    curl -Lo "%TEMP_INSTALLER%" "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    goto :run_installer
)

:: Fallback PowerShell pour telecharger
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe', '%TEMP_INSTALLER%')"

:run_installer
if exist "%TEMP_INSTALLER%" (
    echo [INFO] Installation silencieuse en cours...
    "%TEMP_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 SimpleInstall=1
    del "%TEMP_INSTALLER%" >nul 2>nul
)

:recheck_python
:: Re-verification apres tentative d'installation
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PYTHON_EXEC=python"
    goto :python_ok
)
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PYTHON_EXEC=py -3"
    goto :python_ok
)
for /d %%I in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%I\python.exe" (
        set "PYTHON_EXEC=%%I\python.exe"
        goto :python_ok
    )
)
for /d %%I in ("C:\Program Files\Python3*") do (
    if exist "%%I\python.exe" (
        set "PYTHON_EXEC=%%I\python.exe"
        goto :python_ok
    )
)

echo [ERREUR] Impossible de detecter Python apres tentative d'installation.
echo Veuillez telecharger manuellement Python sur : https://www.python.org/downloads/
echo (Important : cochez bien la case 'Add Python to PATH' lors de l'installation).
pause
exit /b 1

:python_ok
for /f "tokens=*" %%V in ('"%PYTHON_EXEC%" -V 2^>^&1') do echo [OK] %%V detecte (%PYTHON_EXEC%)
echo.

:: ------------------------------------------------------------------
:: 3. Creation et activation de l'environnement virtuel venv
:: ------------------------------------------------------------------
echo [2/4] Verification de l'environnement virtuel venv...
if exist "venv\Scripts\activate.bat" goto :activate_venv

echo [INFO] Creation de l'environnement virtuel venv...
%PYTHON_EXEC% -m venv venv
if %ERRORLEVEL% neq 0 (
    echo [ERREUR] Echec lors de la creation du venv.
    pause
    exit /b 1
)

:activate_venv
echo [OK] Activation de venv...
call "venv\Scripts\activate.bat"
if %ERRORLEVEL% neq 0 (
    echo [ERREUR] Impossible d'activer l'environnement virtuel.
    pause
    exit /b 1
)

for /f "tokens=*" %%V in ('python -V 2^>^&1') do echo [INFO] Environnement virtuel actif : %%V

:: ------------------------------------------------------------------
:: 4. Resolution et nettoyage automatique de requirements.txt
:: ------------------------------------------------------------------
set "REQ_FILE=requirements.txt"
if exist "facture-checker\requirements.txt" (
    set "REQ_FILE=facture-checker\requirements.txt"
)

set "SERVER_FILE=server.py"
if exist "facture-checker\server.py" (
    set "SERVER_FILE=facture-checker\server.py"
)

:: Nettoyage automatique des anciennes contraintes bloquantes dans requirements.txt
python -c "
import os
for path in ['requirements.txt', r'facture-checker\requirements.txt']:
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if 'numpy' in line:
                    new_lines.append('numpy>=1.24.0\n')
                elif 'python-Levenshtein' in line:
                    new_lines.append('Levenshtein>=0.23.0\n')
                else:
                    new_lines.append(line)
            with open(path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
        except Exception:
            pass
" >nul 2>&1

:: ------------------------------------------------------------------
:: 5. Verification et installation des dependances Python
:: ------------------------------------------------------------------
echo [3/4] Verification des dependances requises...
python -c "import fastapi, uvicorn, PIL, pandas" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Toutes les dependances sont deja installees.
    goto :start_services
)

echo [INFO] Installation des dependances (FastAPI, OpenCV, PaddleOCR...)...
echo        Cette operation est automatique et se fait une seule fois.
python -m pip install --upgrade pip setuptools wheel

:: Installation stricte avec binaires precompiles (.whl) uniquement pour eviter tout compilateur C++
pip install --no-cache-dir --only-binary :all: -r "%REQ_FILE%"
if %ERRORLEVEL% neq 0 (
    echo.
    echo ============================================================
    echo [INFO] Installation alternative des composants serveur essentiels...
    echo ============================================================
    pip install --no-cache-dir --only-binary :all: fastapi uvicorn "numpy>=1.24.0" Pillow openpyxl pandas python-multipart qrcode Levenshtein thefuzz opencv-python-headless paddleocr paddlepaddle
)

:: Verification finale des dependances du serveur
python -c "import fastapi, uvicorn" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERREUR] Le serveur web ne peut pas demarrer car FastAPI/Uvicorn n'ont pas pu s'installer.
    echo Verifiez votre connexion Internet ou les messages d'erreur ci-dessus.
    pause
    exit /b 1
)

:start_services
:: ------------------------------------------------------------------
:: 6. Ouverture du navigateur et demarrage du serveur
:: ------------------------------------------------------------------
echo.
echo [4/4] Lancement des services...
echo [INFO] Ouverture automatique de l'interface locale : http://localhost:8000
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"

echo [INFO] Demarrage du serveur web mobile...
echo [INFO] Pour arreter le serveur, fermez cette fenetre ou faites Ctrl+C.
echo ============================================================
echo.

set "PYTHONPATH=%~dp0facture-checker;%PYTHONPATH%"
python "%SERVER_FILE%"

if %ERRORLEVEL% neq 0 (
    echo.
    echo ============================================================
    echo [ERREUR] Le serveur s'est arrete avec le code erreur %ERRORLEVEL%.
    echo ============================================================
)

pause
