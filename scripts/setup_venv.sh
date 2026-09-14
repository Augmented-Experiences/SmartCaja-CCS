#!/usr/bin/env bash
# ============================================================
# setup_venv.sh — Crea el entorno virtual Python e instala
# las dependencias del proyecto SmartCaja.
# Compatible con entornos Pinokio (conda base).
# ============================================================
set -e

echo "=== Configurando entorno Python ==="

# Directorio de trabajo (raiz del plugin)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"
echo "Directorio del proyecto: $PROJECT_DIR"

# -- Crear entorno virtual --
VENV_DIR="$PROJECT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ -f "$VENV_PYTHON" ]; then
    echo "OK: Entorno virtual ya existe en: $VENV_DIR"
else
    echo "Creando entorno virtual en: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    echo "OK: Entorno virtual creado."
fi

# -- Actualizar pip --
echo "Actualizando pip..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet || echo "AVISO: No se pudo actualizar pip."

# -- Instalar dependencias --
REQ_FILE="$PROJECT_DIR/requirements.txt"
if [ ! -f "$REQ_FILE" ]; then
    echo "ERROR: No se encontro requirements.txt"
    exit 1
fi

echo "Instalando dependencias desde requirements.txt..."
"$VENV_PYTHON" -m pip install -r "$REQ_FILE"
echo "DEPS_INSTALLED"

# -- Verificar modulos criticos --
echo ""
echo "Verificando modulos criticos..."

CRITICAL_MODULES="requests fastapi uvicorn pydantic aiofiles openpyxl httpx"
ALL_OK=true

for mod in $CRITICAL_MODULES; do
    if "$VENV_PYTHON" -c "import $mod; print('  OK: $mod')" 2>/dev/null; then
        true
    else
        echo "  FALLO: $mod no se pudo importar. Reinstalando..."
        "$VENV_PYTHON" -m pip install "$mod" --force-reinstall --quiet
        if "$VENV_PYTHON" -c "import $mod" 2>/dev/null; then
            echo "  OK: $mod reinstalado correctamente."
        else
            echo "  ERROR CRITICO: $mod no se pudo instalar."
            ALL_OK=false
        fi
    fi
done

if [ "$ALL_OK" = false ]; then
    echo ""
    echo "ERROR: Algunos modulos criticos no se pudieron instalar."
    exit 1
fi

# -- Verificacion final completa --
echo ""
echo "Verificacion final..."
"$VENV_PYTHON" -c "import requests, fastapi, uvicorn, pydantic, aiofiles, openpyxl, httpx; print('VERIFY_OK')"

echo ""
echo "DEPS_OK"
echo "=== Entorno Python configurado correctamente ==="
exit 0
