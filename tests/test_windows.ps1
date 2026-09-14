# ============================================================
# SmartCaja - Test de Validacion Windows
# ============================================================
# Ejecutar con: powershell -ExecutionPolicy Bypass -File tests/test_windows.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$script:passed = 0
$script:failed = 0
$script:errors = @()

function Test-Check {
    param([string]$Name, [scriptblock]$Test)
    try {
        $result = & $Test
        if ($result) {
            Write-Host "  [PASS] $Name" -ForegroundColor Green
            $script:passed++
        } else {
            Write-Host "  [FAIL] $Name" -ForegroundColor Red
            $script:failed++
            $script:errors += $Name
        }
    } catch {
        Write-Host "  [ERROR] $Name : $_" -ForegroundColor Red
        $script:failed++
        $script:errors += "$Name (Exception: $_)"
    }
}

$ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "$ROOT/pinokio.js")) {
    $ROOT = Split-Path -Parent $PSScriptRoot
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " SmartCaja - Validacion Windows" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 1. ESTRUCTURA DE ARCHIVOS
# ============================================================
Write-Host "[1/10] Estructura de archivos" -ForegroundColor Yellow

Test-Check "pinokio.js existe" { Test-Path "$ROOT/pinokio.js" }
Test-Check "install.json existe" { Test-Path "$ROOT/install.json" }
Test-Check "start.json existe" { Test-Path "$ROOT/start.json" }
Test-Check "stop.json existe" { Test-Path "$ROOT/stop.json" }
Test-Check "reset.json existe" { Test-Path "$ROOT/reset.json" }
Test-Check "icon.png existe" { Test-Path "$ROOT/icon.png" }
Test-Check "server/app.py existe" { Test-Path "$ROOT/server/app.py" }
Test-Check "app/index.html existe" { Test-Path "$ROOT/app/index.html" }
Test-Check "requirements.txt existe" { Test-Path "$ROOT/requirements.txt" }
Test-Check "defaults/agents.json existe" { Test-Path "$ROOT/defaults/agents.json" }
Test-Check "defaults/prompts/ existe" { Test-Path "$ROOT/defaults/prompts" }
Test-Check "app/lib/purify.min.js existe" { Test-Path "$ROOT/app/lib/purify.min.js" }

# ============================================================
# 2. SCRIPTS DE SETUP (CRITICO PARA WINDOWS)
# ============================================================
Write-Host ""
Write-Host "[2/10] Scripts de setup (prevencion ModuleNotFoundError)" -ForegroundColor Yellow

Test-Check "scripts/setup_venv.ps1 existe" { Test-Path "$ROOT/scripts/setup_venv.ps1" }
Test-Check "scripts/setup_venv.sh existe" { Test-Path "$ROOT/scripts/setup_venv.sh" }
Test-Check "scripts/verify_deps.py existe" { Test-Path "$ROOT/scripts/verify_deps.py" }
Test-Check "scripts/diagnose.ps1 existe" { Test-Path "$ROOT/scripts/diagnose.ps1" }
Test-Check "scripts/diagnose.sh existe" { Test-Path "$ROOT/scripts/diagnose.sh" }

$setupPs1 = Get-Content "$ROOT/scripts/setup_venv.ps1" -Raw -Encoding UTF8
Test-Check "setup_venv.ps1 busca Python en PATH" {
    $setupPs1 -match "Get-Command python"
}
Test-Check "setup_venv.ps1 busca Python en rutas comunes Windows" {
    $setupPs1 -match "miniconda3" -and $setupPs1 -match "anaconda3" -and $setupPs1 -match "LOCALAPPDATA"
}
Test-Check "setup_venv.ps1 crea venv con python -m venv" {
    $setupPs1 -match "python.*-m venv"
}
Test-Check "setup_venv.ps1 usa venv\Scripts\python.exe para pip" {
    $setupPs1 -match "venvPython.*-m pip install"
}
Test-Check "setup_venv.ps1 instala desde requirements.txt" {
    $setupPs1 -match "pip install -r.*requirements"
}
Test-Check "setup_venv.ps1 tiene fallback individual de dependencias" {
    $setupPs1 -match "Instalando dependencias una por una" -or $setupPs1 -match "force-reinstall"
}
Test-Check "setup_venv.ps1 verifica modulos criticos con import" {
    $setupPs1 -match "import requests" -and $setupPs1 -match "import fastapi" -and $setupPs1 -match "import uvicorn"
}
Test-Check "setup_venv.ps1 verifica TODOS los modulos criticos" {
    $setupPs1 -match "import.*pydantic" -and $setupPs1 -match "import.*aiofiles" -and $setupPs1 -match "import.*openpyxl"
}
Test-Check "setup_venv.ps1 falla con exit 1 si verificacion falla" {
    $setupPs1 -match "exit 1"
}
Test-Check "setup_venv.ps1 imprime VERIFY_OK al final" {
    $setupPs1 -match "VERIFY_OK"
}
Test-Check "setup_venv.ps1 imprime DEPS_OK al final" {
    $setupPs1 -match "DEPS_OK"
}

$verifyDeps = Get-Content "$ROOT/scripts/verify_deps.py" -Raw -Encoding UTF8
Test-Check "verify_deps.py verifica requests" {
    $verifyDeps -match "requests"
}
Test-Check "verify_deps.py verifica fastapi" {
    $verifyDeps -match "fastapi"
}
Test-Check "verify_deps.py verifica uvicorn" {
    $verifyDeps -match "uvicorn"
}
Test-Check "verify_deps.py intenta auto-reparar dependencias faltantes" {
    $verifyDeps -match "pip.*install" -and $verifyDeps -match "Instalando automaticamente"
}
Test-Check "verify_deps.py imprime DEPS_VERIFY_OK" {
    $verifyDeps -match "DEPS_VERIFY_OK"
}

# ============================================================
# 3. JSON VALIDOS
# ============================================================
Write-Host ""
Write-Host "[3/10] Validacion JSON" -ForegroundColor Yellow

$jsonFiles = @("install.json", "start.json", "stop.json", "reset.json", "defaults/agents.json")
foreach ($f in $jsonFiles) {
    Test-Check "$f es JSON valido" {
        $content = Get-Content "$ROOT/$f" -Raw -Encoding UTF8
        try { $null = $content | ConvertFrom-Json; $true } catch { $false }
    }
}

# ============================================================
# 4. INSTALL.JSON CROSS-PLATFORM
# ============================================================
Write-Host ""
Write-Host "[4/10] Cross-platform install.json" -ForegroundColor Yellow

$installContent = Get-Content "$ROOT/install.json" -Raw -Encoding UTF8

Test-Check "install.json tiene condicion win32" {
    $installContent -match "win32"
}
Test-Check "install.json tiene OllamaSetup.exe para Windows" {
    $installContent -match "OllamaSetup.exe"
}
Test-Check "install.json usa setup_venv.ps1 para Windows" {
    $installContent -match "setup_venv\.ps1"
}
Test-Check "install.json usa setup_venv.sh para Unix" {
    $installContent -match "setup_venv\.sh"
}
Test-Check "install.json no tiene background: true" {
    -not ($installContent -match '"background"')
}
Test-Check "install.json muestra progreso visual (step numbers)" {
    $installContent -match "border-radius" -and $installContent -match "background"
}
Test-Check "install.json tiene paso de verificacion Ollama" {
    $installContent -match "Verificando Ollama"
}
Test-Check "install.json tiene paso de descarga de modelo" {
    $installContent -match "Descargando modelo"
}
Test-Check "install.json tiene paso de dependencias Python" {
    $installContent -match "Instalando dependencias Python"
}
Test-Check "install.json tiene paso de inicializacion datos" {
    $installContent -match "Inicializando datos"
}
Test-Check "install.json tiene notificacion de completado" {
    $installContent -match "notify"
}

# ============================================================
# 5. START.JSON CROSS-PLATFORM + VERIFICACION DEPS
# ============================================================
Write-Host ""
Write-Host "[5/10] Cross-platform start.json + verificacion pre-arranque" -ForegroundColor Yellow

$startContent = Get-Content "$ROOT/start.json" -Raw -Encoding UTF8

Test-Check "start.json tiene daemon: true" {
    $startContent -match '"daemon"\s*:\s*true'
}
Test-Check "start.json tiene condicion win32" {
    $startContent -match "win32"
}
Test-Check "start.json verifica dependencias ANTES de arrancar" {
    $startContent -match "verify_deps\.py"
}
Test-Check "start.json muestra mensaje de verificacion de deps" {
    $startContent -match "Verificando dependencias"
}
Test-Check "start.json usa 'start /B ollama serve' para Windows" {
    $startContent -match "start /B ollama serve"
}
Test-Check "start.json usa venv para verificacion de deps" {
    $startContent -match '"venv"\s*:\s*"venv".*verify_deps' -or ($startContent -match '"venv"\s*:\s*"venv"' -and $startContent -match "verify_deps")
}
Test-Check "start.json usa venv para servidor" {
    $startContent -match '"venv"\s*:\s*"venv"'
}
Test-Check "start.json tiene PYTHONIOENCODING" {
    $startContent -match "PYTHONIOENCODING"
}
Test-Check "start.json tiene PYTHONUTF8" {
    $startContent -match "PYTHONUTF8"
}
Test-Check "start.json muestra mensajes de estado" {
    $startContent -match "Verificando motor de IA" -and $startContent -match "Aplicaci"
}
Test-Check "start.json abre browser al final" {
    $startContent -match "browser.open"
}
Test-Check "start.json usa local.set para URL" {
    $startContent -match "local\.set"
}
Test-Check "start.json usa local.url en browser.open" {
    $startContent -match "local\.url"
}

# ============================================================
# 6. STOP.JSON CROSS-PLATFORM
# ============================================================
Write-Host ""
Write-Host "[6/10] Cross-platform stop.json" -ForegroundColor Yellow

$stopContent = Get-Content "$ROOT/stop.json" -Raw -Encoding UTF8

Test-Check "stop.json tiene condicion win32" {
    $stopContent -match "win32"
}
Test-Check "stop.json usa pkill para unix" {
    $stopContent -match "pkill"
}
Test-Check "stop.json usa wmic para Windows" {
    $stopContent -match "wmic"
}
Test-Check "stop.json NO usa script.stop" {
    -not ($stopContent -match "script\.stop")
}
Test-Check "stop.json muestra mensaje de detencion" {
    $stopContent -match "Deteniendo" -or $stopContent -match "detenida" -or $stopContent -match "detenido"
}

# ============================================================
# 7. REQUIREMENTS.TXT COMPLETITUD
# ============================================================
Write-Host ""
Write-Host "[7/10] Requirements.txt completitud" -ForegroundColor Yellow

$reqContent = Get-Content "$ROOT/requirements.txt" -Raw -Encoding UTF8

Test-Check "requirements.txt contiene fastapi" {
    $reqContent -match "fastapi"
}
Test-Check "requirements.txt contiene uvicorn" {
    $reqContent -match "uvicorn"
}
Test-Check "requirements.txt contiene requests" {
    $reqContent -match "requests"
}
Test-Check "requirements.txt contiene pydantic" {
    $reqContent -match "pydantic"
}
Test-Check "requirements.txt contiene aiofiles" {
    $reqContent -match "aiofiles"
}
Test-Check "requirements.txt contiene openpyxl" {
    $reqContent -match "openpyxl"
}
Test-Check "requirements.txt contiene httpx" {
    $reqContent -match "httpx"
}
Test-Check "requirements.txt contiene python-multipart" {
    $reqContent -match "python-multipart"
}

# ============================================================
# 8. FRONTEND UX
# ============================================================
Write-Host ""
Write-Host "[8/10] Frontend UX" -ForegroundColor Yellow

$htmlContent = Get-Content "$ROOT/app/index.html" -Raw -Encoding UTF8

Test-Check "Frontend tiene readiness-banner" {
    $htmlContent -match "readiness-banner"
}
Test-Check "Frontend tiene globalLoadingOverlay" {
    $htmlContent -match "globalLoadingOverlay"
}
Test-Check "Frontend tiene funcion showGlobalLoading" {
    $htmlContent -match "function showGlobalLoading"
}
Test-Check "Frontend tiene funcion hideGlobalLoading" {
    $htmlContent -match "function hideGlobalLoading"
}
Test-Check "Frontend tiene funcion checkReadiness" {
    $htmlContent -match "function checkReadiness"
}
Test-Check "Frontend tiene funcion safeDisplayValue" {
    $htmlContent -match "function safeDisplayValue"
}
Test-Check "Frontend tiene funcion loadModelPerformance" {
    $htmlContent -match "function loadModelPerformance"
}
Test-Check "Frontend tiene modelPerfContainer" {
    $htmlContent -match "modelPerfContainer"
}
Test-Check "Frontend desactiva botones durante generacion" {
    $htmlContent -match "\.disabled\s*=\s*true"
}
Test-Check "Frontend desactiva input durante chat" {
    $htmlContent -match "input\.disabled\s*=\s*true"
}
Test-Check "Frontend tiene mensajes amigables de carga" {
    $htmlContent -match "analizando" -or $htmlContent -match "Generando"
}
Test-Check "Frontend usa DOMPurify" {
    $htmlContent -match "purify\.min\.js"
}
Test-Check "Frontend usa escapeHtml" {
    ($htmlContent | Select-String -Pattern "escapeHtml\(" -AllMatches).Matches.Count -ge 10
}
Test-Check "Frontend no usa eval()" {
    -not ($htmlContent -match "(?<!font-display.*)\beval\(")
}
Test-Check "Frontend tiene polling de readiness con setInterval" {
    $htmlContent -match "setInterval" -and $htmlContent -match "checkReadiness"
}
Test-Check "Frontend tiene padding-right para controles Windows" {
    $htmlContent -match "titlebar-area-width" -or $htmlContent -match "padding-right.*140"
}

# ============================================================
# 9. SEGURIDAD
# ============================================================
Write-Host ""
Write-Host "[9/10] Seguridad" -ForegroundColor Yellow

$serverContent = Get-Content "$ROOT/server/app.py" -Raw -Encoding UTF8

Test-Check "Backend no tiene CORS wildcard" {
    -not ($serverContent -match 'allow_origins=\["\*"\]')
}
Test-Check "Backend tiene rate limiting" {
    $serverContent -match "_check_rate_limit"
}
Test-Check "Backend tiene _sanitize_id" {
    $serverContent -match "_sanitize_id"
}
Test-Check "Backend tiene _sanitize_filename" {
    $serverContent -match "_sanitize_filename"
}
Test-Check "Backend tiene MAX_MESSAGE_LENGTH" {
    $serverContent -match "MAX_MESSAGE_LENGTH"
}
Test-Check "Backend tiene ensure_ascii=False" {
    $serverContent -match "ensure_ascii=False"
}
Test-Check "Backend tiene endpoint /api/readiness" {
    $serverContent -match "/api/readiness"
}
Test-Check "Backend tiene endpoint /api/hardware/performance" {
    $serverContent -match "/api/hardware/performance"
}
Test-Check "Backend tiene endpoint /api/ollama/status" {
    $serverContent -match "/api/ollama/status"
}

# ============================================================
# 10. CONSISTENCIA CON BRAND-ASSISTANT
# ============================================================
Write-Host ""
Write-Host "[10/10] Consistencia con brand-assistant" -ForegroundColor Yellow

Test-Check "install.json usa scripts dedicados (no pip directo)" {
    $installContent -match "setup_venv\.(ps1|sh)"
}
Test-Check "start.json verifica deps antes de arrancar servidor" {
    # verify_deps.py debe aparecer ANTES de server/app.py en el archivo
    $verifyPos = $startContent.IndexOf("verify_deps")
    $serverPos = $startContent.IndexOf("server/app.py")
    $verifyPos -lt $serverPos -and $verifyPos -ge 0
}
Test-Check "setup_venv.ps1 tiene Find-Python (busqueda robusta)" {
    $setupPs1 -match "function Find-Python"
}
Test-Check "setup_venv.ps1 tiene ErrorActionPreference Stop" {
    $setupPs1 -match 'ErrorActionPreference.*=.*"Stop"'
}
Test-Check "Todos los scripts de setup tienen verificacion de imports" {
    $setupSh = Get-Content "$ROOT/scripts/setup_venv.sh" -Raw -Encoding UTF8
    ($setupPs1 -match "VERIFY_OK") -and ($setupSh -match "VERIFY_OK")
}
Test-Check "Diagnose script existe para Windows" {
    Test-Path "$ROOT/scripts/diagnose.ps1"
}
Test-Check "Diagnose script existe para Mac/Linux" {
    Test-Path "$ROOT/scripts/diagnose.sh"
}

# --- Proteccion contra plantillas Pinokio sin resolver (WinError 123) ---
Test-Check "start.json NO usa {{cwd}} en env vars" {
    -not ($startContent -match '\{\{cwd\}\}')
}
Test-Check "start.json NO pasa DATA_DIR como env var" {
    $startJson = $startContent | ConvertFrom-Json
    $found = $false
    foreach ($step in $startJson.run) {
        if ($step.params -and $step.params.env) {
            $envObj = $step.params.env
            if ($envObj.PSObject.Properties.Name -contains 'DATA_DIR') {
                $found = $true
            }
        }
    }
    -not $found
}
Test-Check "start.json NO tiene operadores ternarios en env vars" {
    $startJson = $startContent | ConvertFrom-Json
    $hasTernary = $false
    foreach ($step in $startJson.run) {
        if ($step.params -and $step.params.env) {
            $envObj = $step.params.env
            foreach ($prop in $envObj.PSObject.Properties) {
                if ($prop.Value -match '\?') {
                    $hasTernary = $true
                }
            }
        }
    }
    -not $hasTernary
}
Test-Check "install.json NO tiene operadores ternarios en env vars" {
    $installJson = $installContent | ConvertFrom-Json
    $hasTernary = $false
    foreach ($step in $installJson.run) {
        if ($step.params -and $step.params.env) {
            $envObj = $step.params.env
            foreach ($prop in $envObj.PSObject.Properties) {
                if ($prop.Value -match '\?') {
                    $hasTernary = $true
                }
            }
        }
    }
    -not $hasTernary
}
Test-Check "app.py tiene guardia contra plantillas Pinokio en DATA_DIR" {
    $serverContent -match '\{\{'
}
Test-Check "app.py usa BASE_DIR / data como fallback" {
    $serverContent -match 'BASE_DIR.*"data"'
}
Test-Check "app.py NO usa DATA_DIR = Path(os.environ.get directo" {
    -not ($serverContent -match 'DATA_DIR = Path\(os\.environ\.get')
}

# --- Proteccion contra URL 0.0.0.0 (Pinokio no puede abrir) ---
Test-Check "app.py NO usa host=0.0.0.0 en uvicorn" {
    -not ($serverContent -match 'host=["'']0\.0\.0\.0["'']')
}
Test-Check "app.py usa host = 127.0.0.1" {
    $serverContent -match 'host = "127\.0\.0\.1"'
}
Test-Check "app.py tiene WindowsProactorEventLoopPolicy" {
    $serverContent -match 'WindowsProactorEventLoopPolicy'
}
Test-Check "app.py NO imprime http://0.0.0.0" {
    -not ($serverContent -match 'print.*http://0\.0\.0\.0')
}

# --- Proteccion contra 422 en chat/interview con session_id null ---
Test-Check "ChatMessage usa Optional[str] para session_id" {
    $serverContent -match 'Optional\[str\]'
}
Test-Check "ChatMessage tiene coerce_session_id validator" {
    $serverContent -match 'coerce_session_id'
}
$htmlContent = Get-Content "$ROOT/app/index.html" -Raw -Encoding UTF8
Test-Check "Frontend usa currentSessionId || vacio" {
    $htmlContent -match "currentSessionId \|\| ''"
}
Test-Check "Backend tiene endpoint GET sessions/session_id" {
    $serverContent -match 'sessions/\{session_id\}'
}

# ============================================================
# RESUMEN
# ============================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " RESUMEN" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Pasados: $($script:passed)" -ForegroundColor Green
Write-Host "  Fallidos: $($script:failed)" -ForegroundColor $(if ($script:failed -gt 0) { "Red" } else { "Green" })

if ($script:errors.Count -gt 0) {
    Write-Host ""
    Write-Host "  Errores:" -ForegroundColor Red
    foreach ($err in $script:errors) {
        Write-Host "    - $err" -ForegroundColor Red
    }
}

Write-Host ""
if ($script:failed -eq 0) {
    Write-Host "  TODOS LOS TESTS PASARON" -ForegroundColor Green
    exit 0
} else {
    Write-Host "  HAY TESTS FALLIDOS" -ForegroundColor Red
    exit 1
}
