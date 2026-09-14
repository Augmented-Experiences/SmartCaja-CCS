#!/usr/bin/env bash
# ============================================================
# diagnose.sh — Diagnostico del entorno para SmartCaja.
# Ejecutar si la instalacion o el inicio fallan.
# ============================================================

echo "=== Diagnostico SmartCaja ==="
echo ""

# -- Sistema --
echo "[Sistema]"
echo "  OS: $(uname -s) $(uname -r)"
echo "  RAM: $(( $(sysctl -n hw.memsize 2>/dev/null || free -b 2>/dev/null | awk '/Mem:/{print $2}' || echo 0) / 1073741824 )) GB"
echo "  Shell: $SHELL"
echo ""

# -- Python --
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"

echo "[Python]"
if command -v python3 &>/dev/null; then
    echo "  Sistema: $(which python3) ($(python3 --version 2>&1))"
else
    echo "  Sistema: NO ENCONTRADO"
fi

if [ -f "$VENV_PYTHON" ]; then
    echo "  Venv: $VENV_PYTHON ($($VENV_PYTHON --version 2>&1))"
else
    echo "  Venv: NO EXISTE ($VENV_PYTHON)"
fi
echo ""

# -- Dependencias --
echo "[Dependencias Python]"
if [ -f "$VENV_PYTHON" ]; then
    for mod in requests fastapi uvicorn pydantic aiofiles openpyxl httpx; do
        if "$VENV_PYTHON" -c "import $mod" 2>/dev/null; then
            echo "  $mod: OK"
        else
            echo "  $mod: FALTA"
        fi
    done
else
    echo "  No se puede verificar (venv no existe)"
fi
echo ""

# -- Ollama --
echo "[Ollama]"
if command -v ollama &>/dev/null; then
    echo "  Binario: $(which ollama)"
else
    echo "  Binario: NO ENCONTRADO"
fi

if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "  Servicio: CORRIENDO"
    echo "  Modelos: $(curl -s http://localhost:11434/api/tags | python3 -c 'import sys,json; print(", ".join(m["name"] for m in json.load(sys.stdin).get("models",[])))' 2>/dev/null || echo 'N/A')"
else
    echo "  Servicio: NO RESPONDE"
fi
echo ""

# -- Puertos --
echo "[Puertos]"
for port in 11434 42000 42001 42002 42003; do
    if lsof -i ":$port" > /dev/null 2>&1; then
        proc=$(lsof -i ":$port" -t 2>/dev/null | head -1)
        echo "  Puerto $port: EN USO (PID $proc)"
    else
        echo "  Puerto $port: LIBRE"
    fi
done
echo ""

# -- Archivos del plugin --
echo "[Archivos del Plugin]"
for f in pinokio.js install.json start.json stop.json requirements.txt server/app.py app/index.html; do
    if [ -f "$PROJECT_DIR/$f" ]; then
        echo "  $f: OK"
    else
        echo "  $f: FALTA"
    fi
done
echo ""

# -- Directorio data --
echo "[Datos]"
if [ -d "$PROJECT_DIR/data" ]; then
    echo "  data/: $(ls -d "$PROJECT_DIR/data"/*/ 2>/dev/null | xargs -I{} basename {} | tr '\n' ', ')"
else
    echo "  data/: NO EXISTE"
fi
echo ""

echo "=== Fin del diagnostico ==="
