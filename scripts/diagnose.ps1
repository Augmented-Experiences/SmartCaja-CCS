# ============================================================
# diagnose.ps1 — Diagnostico del entorno para SmartCaja.
# Ejecutar si la instalacion o el inicio fallan.
# ============================================================

Write-Host "=== Diagnostico SmartCaja ===" -ForegroundColor Cyan
Write-Host ""

# -- Sistema --
Write-Host "[Sistema]" -ForegroundColor Yellow
Write-Host "  OS: $([System.Environment]::OSVersion.VersionString)"
Write-Host "  RAM: $([math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)) GB"
Write-Host "  PowerShell: $($PSVersionTable.PSVersion)"
Write-Host ""

# -- Python --
Write-Host "[Python]" -ForegroundColor Yellow
$sysPy = Get-Command python -ErrorAction SilentlyContinue
if ($sysPy) {
    $ver = & python --version 2>&1
    Write-Host "  Sistema: $($sysPy.Source) ($ver)"
} else {
    Write-Host "  Sistema: NO ENCONTRADO" -ForegroundColor Red
}

$projectDir = $PSScriptRoot | Split-Path -Parent
$venvPython = Join-Path $projectDir "venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $ver = & $venvPython --version 2>&1
    Write-Host "  Venv: $venvPython ($ver)" -ForegroundColor Green
} else {
    Write-Host "  Venv: NO EXISTE ($venvPython)" -ForegroundColor Red
}
Write-Host ""

# -- Dependencias --
Write-Host "[Dependencias Python]" -ForegroundColor Yellow
if (Test-Path $venvPython) {
    $criticalModules = @("requests", "fastapi", "uvicorn", "pydantic", "aiofiles", "openpyxl", "httpx", "multipart")
    foreach ($mod in $criticalModules) {
        $result = & $venvPython -c "import $mod; print('OK')" 2>&1
        if ($result -match "OK") {
            Write-Host "  $mod : OK" -ForegroundColor Green
        } else {
            Write-Host "  $mod : FALTA" -ForegroundColor Red
        }
    }
} else {
    Write-Host "  No se puede verificar (venv no existe)" -ForegroundColor Red
}
Write-Host ""

# -- Ollama --
Write-Host "[Ollama]" -ForegroundColor Yellow
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) {
    Write-Host "  Binario: $($ollamaCmd.Source)" -ForegroundColor Green
} else {
    Write-Host "  Binario: NO ENCONTRADO" -ForegroundColor Red
}

try {
    $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    Write-Host "  Servicio: CORRIENDO" -ForegroundColor Green
    $tags = $response.Content | ConvertFrom-Json
    $models = $tags.models | ForEach-Object { $_.name }
    Write-Host "  Modelos: $($models -join ', ')"
} catch {
    Write-Host "  Servicio: NO RESPONDE" -ForegroundColor Red
}
Write-Host ""

# -- Puertos --
Write-Host "[Puertos]" -ForegroundColor Yellow
$ports = @(11434, 42000, 42001, 42002, 42003)
foreach ($port in $ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        $proc = Get-Process -Id $conn[0].OwningProcess -ErrorAction SilentlyContinue
        Write-Host "  Puerto $port : EN USO ($($proc.ProcessName))" -ForegroundColor Yellow
    } else {
        Write-Host "  Puerto $port : LIBRE" -ForegroundColor Green
    }
}
Write-Host ""

# -- Archivos del plugin --
Write-Host "[Archivos del Plugin]" -ForegroundColor Yellow
$requiredFiles = @("pinokio.js", "install.json", "start.json", "stop.json", "requirements.txt", "server/app.py", "app/index.html")
foreach ($f in $requiredFiles) {
    $fullPath = Join-Path $projectDir $f
    if (Test-Path $fullPath) {
        Write-Host "  $f : OK" -ForegroundColor Green
    } else {
        Write-Host "  $f : FALTA" -ForegroundColor Red
    }
}
Write-Host ""

# -- Directorio data --
Write-Host "[Datos]" -ForegroundColor Yellow
$dataDir = Join-Path $projectDir "data"
if (Test-Path $dataDir) {
    $subdirs = Get-ChildItem -Path $dataDir -Directory | ForEach-Object { $_.Name }
    Write-Host "  data/: $($subdirs -join ', ')" -ForegroundColor Green
} else {
    Write-Host "  data/: NO EXISTE" -ForegroundColor Red
}
Write-Host ""

Write-Host "=== Fin del diagnostico ===" -ForegroundColor Cyan
