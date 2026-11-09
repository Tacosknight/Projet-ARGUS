[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $DetectionModel,
    [Parameter(Mandatory = $true)] [string] $RecognitionModel,
    [string] $OrientationModel = "",
    [string] $PythonCommand = "py"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Invoke-Native([string] $Command, [string[]] $Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Echec de $Command (code $LASTEXITCODE)." }
}

function Copy-Model([string] $Source, [string] $Destination) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Dossier de modele introuvable : $Source"
    }
    # PaddleOCR v3 requires a configuration and inference model files.
    if (-not (Test-Path -LiteralPath (Join-Path $Source "inference.yml") -PathType Leaf)) {
        throw "Modele incomplet : inference.yml absent de $Source"
    }
    $hasWeights = (Test-Path -LiteralPath (Join-Path $Source "inference.pdiparams") -PathType Leaf)
    $hasGraph = (Test-Path -LiteralPath (Join-Path $Source "inference.json") -PathType Leaf) -or
                (Test-Path -LiteralPath (Join-Path $Source "inference.pdmodel") -PathType Leaf)
    if (-not $hasWeights -or -not $hasGraph) { throw "Modele incomplet : fichiers d'inference absents de $Source" }
    New-Item -ItemType Directory -Path $Destination | Out-Null
    Copy-Item -Path (Join-Path $Source "*") -Destination $Destination -Recurse -Force
}

# A unique staging directory prevents models and PyInstaller output from older builds
# being mixed into the new package. Never remove the caller's model directories.
$Stage = Join-Path ([System.IO.Path]::GetTempPath()) ("ARGUS-build-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Stage | Out-Null
$PreviousModels = $env:ARGUS_BUILD_MODELS_DIR
try {
    $Models = Join-Path $Stage "models"
    New-Item -ItemType Directory -Path $Models | Out-Null
    Copy-Model $DetectionModel (Join-Path $Models "text_detection")
    Copy-Model $RecognitionModel (Join-Path $Models "text_recognition")
    if ($OrientationModel) { Copy-Model $OrientationModel (Join-Path $Models "textline_orientation") }

    $BuildVenv = Join-Path $Stage "venv"
    Invoke-Native $PythonCommand @("-3.12", "-m", "venv", $BuildVenv)
    $Python = Join-Path $BuildVenv "Scripts\python.exe"
    Invoke-Native $Python @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Native $Python @("-m", "pip", "install", "-r", (Join-Path $Root "facture-checker\requirements-windows.lock.txt"))
    Invoke-Native $Python @("-m", "pip", "install", "pyinstaller==6.16.0")
    Invoke-Native $Python @("-m", "pip", "check")
    Invoke-Native $Python @("-I", (Join-Path $Root "packaging\validate_models.py"), $Models)
    & $Python -m pip freeze | Out-File -FilePath (Join-Path $Stage "requirements-resolved-windows.txt") -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Echec de pip freeze (code $LASTEXITCODE)." }

    $env:ARGUS_BUILD_MODELS_DIR = $Models
    $Dist = Join-Path $Stage "dist"
    Invoke-Native $Python @("-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", $Dist, "--workpath", (Join-Path $Stage "work"), (Join-Path $Root "packaging\argus.spec"))
    if (-not (Test-Path -LiteralPath (Join-Path $Dist "ARGUS\ARGUS.exe") -PathType Leaf)) {
        throw "PyInstaller n'a pas produit ARGUS.exe."
    }
    Copy-Item -LiteralPath (Join-Path $Stage "requirements-resolved-windows.txt") -Destination (Join-Path $Dist "ARGUS\requirements-resolved-windows.txt")
    foreach ($Launcher in @("lancer_serveur_windows.bat", "lancer_scanner_mobile_windows.bat")) {
        Copy-Item -LiteralPath (Join-Path $Root $Launcher) -Destination (Join-Path $Dist "ARGUS")
    }
    Copy-Item -LiteralPath (Join-Path $Root "packaging\README_WINDOWS.md") -Destination (Join-Path $Dist "ARGUS\README_WINDOWS.md")
    $Output = Join-Path $Root "dist\ARGUS"
    if (Test-Path -LiteralPath $Output) {
        throw "Un ancien package existe deja : $Output. Deplacez-le avant de reconstruire."
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist") | Out-Null
    Move-Item -LiteralPath (Join-Path $Dist "ARGUS") -Destination $Output
    Write-Host "Package cree dans $Output. Testez-le sur Windows avant diffusion." -ForegroundColor Green
} finally {
    $env:ARGUS_BUILD_MODELS_DIR = $PreviousModels
    Remove-Item -LiteralPath $Stage -Recurse -Force
}
