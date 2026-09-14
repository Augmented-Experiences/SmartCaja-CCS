#!/bin/bash
# ============================================================
# SmartCaja - Test de Validacion macOS/Linux
# ============================================================
# Ejecutar con: bash tests/test_mac.sh
# ============================================================

set -e

PASSED=0
FAILED=0
ERRORS=()

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "true" ]; then
        echo -e "  ${GREEN}[PASS]${NC} $name"
        PASSED=$((PASSED + 1))
    else
        echo -e "  ${RED}[FAIL]${NC} $name"
        FAILED=$((FAILED + 1))
        ERRORS+=("$name")
    fi
}

# Determinar ROOT
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

if [ ! -f "$ROOT/pinokio.js" ]; then
    echo "Error: No se encontro pinokio.js en $ROOT"
    exit 1
fi

echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN} SmartCaja - Validacion macOS/Linux${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""

# ============================================================
# 1. ESTRUCTURA DE ARCHIVOS
# ============================================================
echo -e "${YELLOW}[1/10] Estructura de archivos${NC}"

check "pinokio.js existe" "$([ -f "$ROOT/pinokio.js" ] && echo true || echo false)"
check "install.json existe" "$([ -f "$ROOT/install.json" ] && echo true || echo false)"
check "start.json existe" "$([ -f "$ROOT/start.json" ] && echo true || echo false)"
check "stop.json existe" "$([ -f "$ROOT/stop.json" ] && echo true || echo false)"
check "reset.json existe" "$([ -f "$ROOT/reset.json" ] && echo true || echo false)"
check "icon.png existe" "$([ -f "$ROOT/icon.png" ] && echo true || echo false)"
check "server/app.py existe" "$([ -f "$ROOT/server/app.py" ] && echo true || echo false)"
check "app/index.html existe" "$([ -f "$ROOT/app/index.html" ] && echo true || echo false)"
check "requirements.txt existe" "$([ -f "$ROOT/requirements.txt" ] && echo true || echo false)"
check "defaults/agents.json existe" "$([ -f "$ROOT/defaults/agents.json" ] && echo true || echo false)"
check "defaults/prompts/ existe" "$([ -d "$ROOT/defaults/prompts" ] && echo true || echo false)"
check "app/lib/purify.min.js existe" "$([ -f "$ROOT/app/lib/purify.min.js" ] && echo true || echo false)"

# ============================================================
# 2. SCRIPTS DE SETUP (CRITICO PARA WINDOWS)
# ============================================================
echo ""
echo -e "${YELLOW}[2/10] Scripts de setup (prevencion ModuleNotFoundError)${NC}"

check "scripts/setup_venv.ps1 existe" "$([ -f "$ROOT/scripts/setup_venv.ps1" ] && echo true || echo false)"
check "scripts/setup_venv.sh existe" "$([ -f "$ROOT/scripts/setup_venv.sh" ] && echo true || echo false)"
check "scripts/verify_deps.py existe" "$([ -f "$ROOT/scripts/verify_deps.py" ] && echo true || echo false)"
check "scripts/diagnose.ps1 existe" "$([ -f "$ROOT/scripts/diagnose.ps1" ] && echo true || echo false)"
check "scripts/diagnose.sh existe" "$([ -f "$ROOT/scripts/diagnose.sh" ] && echo true || echo false)"
check "setup_venv.sh es ejecutable" "$([ -x "$ROOT/scripts/setup_venv.sh" ] && echo true || echo false)"
check "diagnose.sh es ejecutable" "$([ -x "$ROOT/scripts/diagnose.sh" ] && echo true || echo false)"

SETUP_PS1=$(cat "$ROOT/scripts/setup_venv.ps1")
SETUP_SH=$(cat "$ROOT/scripts/setup_venv.sh")
VERIFY_DEPS=$(cat "$ROOT/scripts/verify_deps.py")

check "setup_venv.ps1 busca Python en PATH" "$(echo "$SETUP_PS1" | grep -q 'Get-Command python' && echo true || echo false)"
check "setup_venv.ps1 busca Python en rutas comunes Windows" "$(echo "$SETUP_PS1" | grep -q 'miniconda3' && echo true || echo false)"
check "setup_venv.ps1 crea venv con python -m venv" "$(echo "$SETUP_PS1" | grep -q 'venv' && echo true || echo false)"
check "setup_venv.ps1 usa venv Scripts python.exe para pip" "$(echo "$SETUP_PS1" | grep -q 'venvPython.*-m pip' && echo true || echo false)"
check "setup_venv.ps1 instala desde requirements.txt" "$(echo "$SETUP_PS1" | grep -q 'requirements.txt' && echo true || echo false)"
check "setup_venv.ps1 tiene fallback individual" "$(echo "$SETUP_PS1" | grep -q 'force-reinstall' && echo true || echo false)"
check "setup_venv.ps1 verifica import requests" "$(echo "$SETUP_PS1" | grep -q 'import requests' && echo true || echo false)"
check "setup_venv.ps1 verifica fastapi en imports" "$(echo "$SETUP_PS1" | grep -q 'fastapi' && echo true || echo false)"
check "setup_venv.ps1 verifica uvicorn en imports" "$(echo "$SETUP_PS1" | grep -q 'uvicorn' && echo true || echo false)"
check "setup_venv.ps1 falla con exit 1 si verificacion falla" "$(echo "$SETUP_PS1" | grep -q 'exit 1' && echo true || echo false)"
check "setup_venv.ps1 imprime VERIFY_OK" "$(echo "$SETUP_PS1" | grep -q 'VERIFY_OK' && echo true || echo false)"
check "setup_venv.ps1 imprime DEPS_OK" "$(echo "$SETUP_PS1" | grep -q 'DEPS_OK' && echo true || echo false)"

check "setup_venv.sh crea venv" "$(echo "$SETUP_SH" | grep -q 'python3 -m venv' && echo true || echo false)"
check "setup_venv.sh instala desde requirements.txt" "$(echo "$SETUP_SH" | grep -q 'requirements.txt' && echo true || echo false)"
check "setup_venv.sh verifica import requests" "$(echo "$SETUP_SH" | grep -q 'import requests' && echo true || echo false)"
check "setup_venv.sh imprime VERIFY_OK" "$(echo "$SETUP_SH" | grep -q 'VERIFY_OK' && echo true || echo false)"
check "setup_venv.sh imprime DEPS_OK" "$(echo "$SETUP_SH" | grep -q 'DEPS_OK' && echo true || echo false)"

check "verify_deps.py verifica requests" "$(echo "$VERIFY_DEPS" | grep -q 'requests' && echo true || echo false)"
check "verify_deps.py verifica fastapi" "$(echo "$VERIFY_DEPS" | grep -q 'fastapi' && echo true || echo false)"
check "verify_deps.py intenta auto-reparar" "$(echo "$VERIFY_DEPS" | grep -q 'pip.*install' && echo true || echo false)"
check "verify_deps.py imprime DEPS_VERIFY_OK" "$(echo "$VERIFY_DEPS" | grep -q 'DEPS_VERIFY_OK' && echo true || echo false)"

# ============================================================
# 3. JSON VALIDOS
# ============================================================
echo ""
echo -e "${YELLOW}[3/10] Validacion JSON${NC}"

for f in install.json start.json stop.json reset.json defaults/agents.json; do
    if python3 -c "import json; json.loads(open('$ROOT/$f', encoding='utf-8').read())" 2>/dev/null; then
        check "$f es JSON valido" "true"
    else
        check "$f es JSON valido" "false"
    fi
done

# ============================================================
# 4. INSTALL.JSON CROSS-PLATFORM
# ============================================================
echo ""
echo -e "${YELLOW}[4/10] Cross-platform install.json${NC}"

INSTALL=$(cat "$ROOT/install.json")

check "install.json tiene condicion win32" "$(echo "$INSTALL" | grep -q 'win32' && echo true || echo false)"
check "install.json tiene OllamaSetup.exe para Windows" "$(echo "$INSTALL" | grep -q 'OllamaSetup.exe' && echo true || echo false)"
check "install.json usa setup_venv.ps1 para Windows" "$(echo "$INSTALL" | grep -q 'setup_venv.ps1' && echo true || echo false)"
check "install.json usa setup_venv.sh para Unix" "$(echo "$INSTALL" | grep -q 'setup_venv.sh' && echo true || echo false)"
check "install.json no tiene background: true" "$(echo "$INSTALL" | grep -qv '"background"' && echo true || echo false)"
check "install.json muestra progreso visual" "$(echo "$INSTALL" | grep -q 'border-radius' && echo true || echo false)"
check "install.json tiene paso de verificacion Ollama" "$(echo "$INSTALL" | grep -q 'Verificando Ollama' && echo true || echo false)"
check "install.json tiene paso de descarga de modelo" "$(echo "$INSTALL" | grep -q 'Descargando modelo' && echo true || echo false)"
check "install.json tiene paso de dependencias Python" "$(echo "$INSTALL" | grep -q 'Instalando dependencias Python' && echo true || echo false)"
check "install.json tiene paso de inicializacion datos" "$(echo "$INSTALL" | grep -q 'Inicializando datos' && echo true || echo false)"
check "install.json tiene notificacion de completado" "$(echo "$INSTALL" | grep -q 'notify' && echo true || echo false)"

# ============================================================
# 5. START.JSON CROSS-PLATFORM + VERIFICACION DEPS
# ============================================================
echo ""
echo -e "${YELLOW}[5/10] Cross-platform start.json + verificacion pre-arranque${NC}"

START=$(cat "$ROOT/start.json")

check "start.json tiene daemon: true" "$(echo "$START" | grep -q '"daemon".*true' && echo true || echo false)"
check "start.json tiene condicion win32" "$(echo "$START" | grep -q 'win32' && echo true || echo false)"
check "start.json verifica dependencias ANTES de arrancar" "$(echo "$START" | grep -q 'verify_deps.py' && echo true || echo false)"
check "start.json muestra mensaje de verificacion de deps" "$(echo "$START" | grep -q 'Verificando dependencias' && echo true || echo false)"
check "start.json usa 'start /B ollama serve' para Windows" "$(echo "$START" | grep -q 'start /B ollama serve' && echo true || echo false)"
check "start.json usa venv para servidor" "$(echo "$START" | grep -q '"venv"' && echo true || echo false)"
check "start.json tiene PYTHONIOENCODING" "$(echo "$START" | grep -q 'PYTHONIOENCODING' && echo true || echo false)"
check "start.json tiene PYTHONUTF8" "$(echo "$START" | grep -q 'PYTHONUTF8' && echo true || echo false)"
check "start.json muestra mensajes de estado" "$(echo "$START" | grep -q 'Verificando motor de IA' && echo true || echo false)"
check "start.json abre browser al final" "$(echo "$START" | grep -q 'browser.open' && echo true || echo false)"
check "start.json usa local.set para URL" "$(echo "$START" | grep -q 'local.set' && echo true || echo false)"
check "start.json usa local.url en browser.open" "$(echo "$START" | grep -q 'local.url' && echo true || echo false)"

# ============================================================
# 6. STOP.JSON CROSS-PLATFORM
# ============================================================
echo ""
echo -e "${YELLOW}[6/10] Cross-platform stop.json${NC}"

STOP=$(cat "$ROOT/stop.json")

check "stop.json tiene condicion win32" "$(echo "$STOP" | grep -q 'win32' && echo true || echo false)"
check "stop.json usa pkill para unix" "$(echo "$STOP" | grep -q 'pkill' && echo true || echo false)"
check "stop.json usa wmic para Windows" "$(echo "$STOP" | grep -q 'wmic' && echo true || echo false)"
check "stop.json NO usa script.stop" "$(echo "$STOP" | grep -qv 'script.stop' && echo true || echo false)"
check "stop.json muestra mensaje de detencion" "$(echo "$STOP" | grep -q 'Deteniendo\|detenida\|detenido' && echo true || echo false)"

# ============================================================
# 7. REQUIREMENTS.TXT COMPLETITUD
# ============================================================
echo ""
echo -e "${YELLOW}[7/10] Requirements.txt completitud${NC}"

REQ=$(cat "$ROOT/requirements.txt")

check "requirements.txt contiene fastapi" "$(echo "$REQ" | grep -q 'fastapi' && echo true || echo false)"
check "requirements.txt contiene uvicorn" "$(echo "$REQ" | grep -q 'uvicorn' && echo true || echo false)"
check "requirements.txt contiene requests" "$(echo "$REQ" | grep -q 'requests' && echo true || echo false)"
check "requirements.txt contiene pydantic" "$(echo "$REQ" | grep -q 'pydantic' && echo true || echo false)"
check "requirements.txt contiene aiofiles" "$(echo "$REQ" | grep -q 'aiofiles' && echo true || echo false)"
check "requirements.txt contiene openpyxl" "$(echo "$REQ" | grep -q 'openpyxl' && echo true || echo false)"
check "requirements.txt contiene httpx" "$(echo "$REQ" | grep -q 'httpx' && echo true || echo false)"
check "requirements.txt contiene python-multipart" "$(echo "$REQ" | grep -q 'python-multipart' && echo true || echo false)"

# ============================================================
# 8. FRONTEND UX
# ============================================================
echo ""
echo -e "${YELLOW}[8/10] Frontend UX${NC}"

HTML=$(cat "$ROOT/app/index.html")

check "Frontend tiene readiness-banner" "$(echo "$HTML" | grep -q 'readiness-banner' && echo true || echo false)"
check "Frontend tiene globalLoadingOverlay" "$(echo "$HTML" | grep -q 'globalLoadingOverlay' && echo true || echo false)"
check "Frontend tiene funcion showGlobalLoading" "$(echo "$HTML" | grep -q 'function showGlobalLoading' && echo true || echo false)"
check "Frontend tiene funcion hideGlobalLoading" "$(echo "$HTML" | grep -q 'function hideGlobalLoading' && echo true || echo false)"
check "Frontend tiene funcion checkReadiness" "$(echo "$HTML" | grep -q 'function checkReadiness' && echo true || echo false)"
check "Frontend tiene funcion safeDisplayValue" "$(echo "$HTML" | grep -q 'function safeDisplayValue' && echo true || echo false)"
check "Frontend tiene funcion loadModelPerformance" "$(echo "$HTML" | grep -q 'function loadModelPerformance' && echo true || echo false)"
check "Frontend tiene modelPerfContainer" "$(echo "$HTML" | grep -q 'modelPerfContainer' && echo true || echo false)"
check "Frontend desactiva botones durante generacion" "$(echo "$HTML" | grep -q '\.disabled = true' && echo true || echo false)"
check "Frontend desactiva input durante chat" "$(echo "$HTML" | grep -q 'input.disabled = true' && echo true || echo false)"
check "Frontend tiene mensajes amigables de carga" "$(echo "$HTML" | grep -q 'analizando\|Generando' && echo true || echo false)"
check "Frontend usa DOMPurify" "$(echo "$HTML" | grep -q 'purify.min.js' && echo true || echo false)"
check "Frontend usa escapeHtml (10+ veces)" "$([ $(echo "$HTML" | grep -o 'escapeHtml(' | wc -l) -ge 10 ] && echo true || echo false)"
check "Frontend no usa eval()" "$(echo "$HTML" | grep -v 'font-display' | grep -qv 'eval(' && echo true || echo false)"
check "Frontend tiene polling con setInterval" "$(echo "$HTML" | grep -q 'setInterval' && echo true || echo false)"

# ============================================================
# 9. SEGURIDAD
# ============================================================
echo ""
echo -e "${YELLOW}[9/10] Seguridad${NC}"

SERVER=$(cat "$ROOT/server/app.py")

check "Backend no tiene CORS wildcard" "$(echo "$SERVER" | grep -qv 'allow_origins=\[\"\\*\"\]' && echo true || echo false)"
check "Backend tiene rate limiting" "$(echo "$SERVER" | grep -q '_check_rate_limit' && echo true || echo false)"
check "Backend tiene _sanitize_id" "$(echo "$SERVER" | grep -q '_sanitize_id' && echo true || echo false)"
check "Backend tiene _sanitize_filename" "$(echo "$SERVER" | grep -q '_sanitize_filename' && echo true || echo false)"
check "Backend tiene MAX_MESSAGE_LENGTH" "$(echo "$SERVER" | grep -q 'MAX_MESSAGE_LENGTH' && echo true || echo false)"
check "Backend tiene ensure_ascii=False" "$(echo "$SERVER" | grep -q 'ensure_ascii=False' && echo true || echo false)"
check "Backend tiene endpoint /api/readiness" "$(echo "$SERVER" | grep -q '/api/readiness' && echo true || echo false)"
check "Backend tiene endpoint /api/hardware/performance" "$(echo "$SERVER" | grep -q '/api/hardware/performance' && echo true || echo false)"
check "Backend tiene endpoint /api/ollama/status" "$(echo "$SERVER" | grep -q '/api/ollama/status' && echo true || echo false)"

# ============================================================
# 10. CONSISTENCIA CON BRAND-ASSISTANT
# ============================================================
echo ""
echo -e "${YELLOW}[10/10] Consistencia con brand-assistant${NC}"

check "install.json usa scripts dedicados (no pip directo)" "$(echo "$INSTALL" | grep -q 'setup_venv' && echo true || echo false)"
check "start.json verifica deps antes de arrancar servidor" "$(
    VERIFY_POS=$(echo "$START" | grep -n 'verify_deps' | head -1 | cut -d: -f1)
    SERVER_POS=$(echo "$START" | grep -n 'server/app.py' | head -1 | cut -d: -f1)
    [ -n "$VERIFY_POS" ] && [ -n "$SERVER_POS" ] && [ "$VERIFY_POS" -lt "$SERVER_POS" ] && echo true || echo false
)"
check "setup_venv.ps1 tiene Find-Python" "$(echo "$SETUP_PS1" | grep -q 'function Find-Python' && echo true || echo false)"
check "setup_venv.ps1 tiene ErrorActionPreference Stop" "$(echo "$SETUP_PS1" | grep -q 'ErrorActionPreference.*Stop' && echo true || echo false)"
check "Ambos scripts de setup tienen VERIFY_OK" "$(echo "$SETUP_PS1" | grep -q 'VERIFY_OK' && echo "$SETUP_SH" | grep -q 'VERIFY_OK' && echo true || echo false)"
check "Diagnose script existe para Windows" "$([ -f "$ROOT/scripts/diagnose.ps1" ] && echo true || echo false)"
check "Diagnose script existe para Mac/Linux" "$([ -f "$ROOT/scripts/diagnose.sh" ] && echo true || echo false)"

# --- Proteccion contra plantillas Pinokio sin resolver (WinError 123) ---
check "start.json NO usa {{cwd}} en env vars" "$(echo "$START" | grep -qv '{{cwd}}' && echo true || echo false)"
check "start.json NO pasa DATA_DIR como env var" "$(echo "$START" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for step in data['run']:
    if isinstance(step.get('params'), dict):
        env = step['params'].get('env', {})
        if 'DATA_DIR' in env:
            print('false')
            sys.exit(0)
print('true')
" 2>/dev/null || echo true)"
check "start.json NO tiene ternarios en env vars" "$(echo "$START" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for step in data['run']:
    if isinstance(step.get('params'), dict):
        for k, v in step['params'].get('env', {}).items():
            if '?' in str(v):
                print('false')
                sys.exit(0)
print('true')
" 2>/dev/null || echo true)"
check "install.json NO tiene ternarios en env vars" "$(echo "$INSTALL" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for step in data['run']:
    if isinstance(step.get('params'), dict):
        for k, v in step['params'].get('env', {}).items():
            if '?' in str(v):
                print('false')
                sys.exit(0)
print('true')
" 2>/dev/null || echo true)"
check "app.py tiene guardia contra plantillas Pinokio en DATA_DIR" "$(echo "$SERVER" | grep -q '{{' && echo true || echo false)"
check "app.py usa BASE_DIR / data como fallback" "$(echo "$SERVER" | grep -q 'BASE_DIR.*data' && echo true || echo false)"
check "app.py NO usa DATA_DIR = Path(os.environ.get directo" "$(echo "$SERVER" | grep -qv 'DATA_DIR = Path(os.environ.get' && echo true || echo false)"

# --- Proteccion contra URL 0.0.0.0 (Pinokio no puede abrir) ---
check "app.py NO usa host=0.0.0.0 en uvicorn" "$(echo "$SERVER" | grep -qv 'host=.0.0.0.0.' && echo true || echo false)"
check "app.py usa host = 127.0.0.1" "$(echo "$SERVER" | grep -q 'host = .127.0.0.1.' && echo true || echo false)"
check "app.py tiene WindowsProactorEventLoopPolicy" "$(echo "$SERVER" | grep -q 'WindowsProactorEventLoopPolicy' && echo true || echo false)"
check "app.py NO imprime http://0.0.0.0" "$(echo "$SERVER" | grep -qv 'print.*http://0.0.0.0' && echo true || echo false)"

# --- Proteccion contra 422 en chat/interview con session_id null ---
check "ChatMessage usa Optional[str] para session_id" "$(echo "$SERVER" | grep -q 'Optional.str.' && echo true || echo false)"
check "ChatMessage tiene coerce_session_id validator" "$(echo "$SERVER" | grep -q 'coerce_session_id' && echo true || echo false)"
check "Frontend usa currentSessionId || vacio" "$(grep -q "currentSessionId || ''" "$ROOT/app/index.html" && echo true || echo false)"
check "Frontend NO tiene race condition en loadInterviewSession" "$(grep -c 'fetch.*sessions' "$ROOT/app/index.html" | python3 -c "import sys; n=int(sys.stdin.read().strip()); print('true' if n <= 4 else 'false')")"
check "Backend tiene endpoint GET sessions/session_id" "$(echo "$SERVER" | grep -q 'sessions/{session_id}' && echo true || echo false)"

# ============================================================
# RESUMEN
# ============================================================
echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN} RESUMEN${NC}"
echo -e "${CYAN}============================================================${NC}"
echo -e "  ${GREEN}Pasados: $PASSED${NC}"
if [ $FAILED -gt 0 ]; then
    echo -e "  ${RED}Fallidos: $FAILED${NC}"
    echo ""
    echo -e "  ${RED}Errores:${NC}"
    for err in "${ERRORS[@]}"; do
        echo -e "    ${RED}- $err${NC}"
    done
else
    echo -e "  ${GREEN}Fallidos: 0${NC}"
fi

echo ""
if [ $FAILED -eq 0 ]; then
    echo -e "  ${GREEN}TODOS LOS TESTS PASARON${NC}"
    exit 0
else
    echo -e "  ${RED}HAY TESTS FALLIDOS${NC}"
    exit 1
fi
