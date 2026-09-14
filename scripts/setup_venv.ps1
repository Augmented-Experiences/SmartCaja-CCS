# ============================================================
# setup_venv.ps1 — Crea el entorno virtual Python e instala
# las dependencias del proyecto SmartCaja.
# Compatible con entornos Pinokio (conda base).
# ============================================================

$ErrorActionPreference = "Stop"

Write-Host "=== Configurando entorno Python ===" -ForegroundColor Cyan

# Directorio de trabajo (raiz del plugin)
$projectDir = $PSScriptRoot | Split-Path -Parent
Set-Location $projectDir
Write-Host "Directorio del proyecto: $projectDir"

# -- Encontrar Python --
function Find-Python {
    # 1. python en PATH
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) {
        $ver = & python --version 2>&1
        Write-Host "Python encontrado en PATH: $($py.Source) ($ver)"
        return "python"
    }
    # 2. python3 en PATH
    $py3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($py3) {
        $ver = & python3 --version 2>&1
        Write-Host "Python3 encontrado: $($py3.Source) ($ver)"
        return "python3"
    }
    # 3. Rutas comunes de conda/Python en Windows
    $paths = @(
        "$env:USERPROFILE\miniconda3\python.exe",
        "$env:USERPROFILE\anaconda3\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe"
    )
    foreach ($p in $paths) {
        if (Test-Path $p) {
            $ver = & $p --version 2>&1
            Write-Host "Python encontrado en: $p ($ver)"
            return $p
        }
    }
    return $null
}

$pythonCmd = Find-Python

if (-not $pythonCmd) {
    Write-Host "ERROR: No se encontro Python. Instala Python 3.10+ desde https://python.org" -ForegroundColor Red
    exit 1
}

# -- Crear entorno virtual --
$venvDir = Join-Path $projectDir "venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip = Join-Path $venvDir "Scripts\pip.exe"

if (Test-Path $venvPython) {
    Write-Host "OK: Entorno virtual ya existe en: $venvDir" -ForegroundColor Green
} else {
    Write-Host "Creando entorno virtual en: $venvDir"
    & $pythonCmd -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: No se pudo crear el entorno virtual." -ForegroundColor Red
        exit 1
    }
    Write-Host "OK: Entorno virtual creado." -ForegroundColor Green
}

# -- Actualizar pip --
Write-Host "Actualizando pip..."
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "AVISO: No se pudo actualizar pip. Continuando..." -ForegroundColor Yellow
}

# -- Instalar dependencias --
$reqFile = Join-Path $projectDir "requirements.txt"
if (-not (Test-Path $reqFile)) {
    Write-Host "ERROR: No se encontro requirements.txt" -ForegroundColor Red
    exit 1
}

Write-Host "Instalando dependencias desde requirements.txt..."
& $venvPython -m pip install -r $reqFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Fallo la instalacion de dependencias." -ForegroundColor Red
    Write-Host "Intentando instalar dependencias una por una..." -ForegroundColor Yellow

    # Fallback: instalar cada dependencia individualmente
    $deps = Get-Content $reqFile | Where-Object { $_ -match '\S' -and $_ -notmatch '^\s*#' }
    foreach ($dep in $deps) {
        Write-Host "  Instalando: $dep"
        & $venvPython -m pip install $dep
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  AVISO: No se pudo instalar $dep" -ForegroundColor Yellow
        }
    }
}

# -- Verificar modulos criticos --
Write-Host ""
Write-Host "Verificando modulos criticos..." -ForegroundColor Cyan

$criticalModules = @("requests", "fastapi", "uvicorn", "pydantic", "aiofiles", "openpyxl", "httpx")
$allOk = $true

foreach ($mod in $criticalModules) {
    & $venvPython -c "import $mod; print('  OK: $mod v' + getattr($mod, '__version__', 'installed'))" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FALLO: $mod no se pudo importar. Reinstalando..." -ForegroundColor Red
        & $venvPython -m pip install $mod --force-reinstall --quiet
        & $venvPython -c "import $mod" 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR CRITICO: $mod no se pudo instalar." -ForegroundColor Red
            $allOk = $false
        } else {
            Write-Host "  OK: $mod reinstalado correctamente." -ForegroundColor Green
        }
    }
}

if (-not $allOk) {
    Write-Host ""
    Write-Host "ERROR: Algunos modulos criticos no se pudieron instalar." -ForegroundColor Red
    Write-Host "Intenta ejecutar manualmente:" -ForegroundColor Yellow
    Write-Host "  $venvPython -m pip install -r $reqFile" -ForegroundColor Yellow
    exit 1
}

# -- Verificacion final completa --
Write-Host ""
Write-Host "Verificacion final..." -ForegroundColor Cyan
& $venvPython -c "import requests, fastapi, uvicorn, pydantic, aiofiles, openpyxl, httpx; print('VERIFY_OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Verificacion final de modulos fallo." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "DEPS_OK" -ForegroundColor Green
Write-Host "=== Entorno Python configurado correctamente ===" -ForegroundColor Green
exit 0
