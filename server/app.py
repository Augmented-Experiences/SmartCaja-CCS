"""
SmartCaja — Backend FastAPI
Plugin de Pinokio para gestión de flujos de caja con IA local para PYMEs.

Seguridad aplicada:
  - Sanitización de IDs (prevención de path traversal)
  - CORS restringido a localhost
  - Rate limiting en endpoints de generación
  - Validación de tamaño de inputs
  - Nombres de archivo sanitizados en exportación
  - Datos financieros anonimizados en logs
  - Auto-recuperación de Ollama si no está corriendo
"""

import os
import sys
import json
import uuid
import re
import shutil
import asyncio
import logging
import threading
import argparse
import subprocess
import time
import unicodedata
import copy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from collections import defaultdict

# Forzar UTF-8 en stdout/stderr para Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import hashlib
import base64
import requests as http_requests
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, field_validator
from interview_manager import InterviewManager

# ---------------------------------------------------------------------------
# Configuración de rutas
#   - Modo normal: rutas relativas al código fuente (repo).
#   - Modo empaquetado (PyInstaller, p. ej. instalador Tauri): los recursos
#     de solo lectura (app/, defaults/) viven en el bundle (sys._MEIPASS) y
#     los datos escribibles (data/) en la carpeta de datos del usuario.
# ---------------------------------------------------------------------------
_IS_FROZEN = bool(getattr(sys, "frozen", False))


def _user_data_dir() -> Path:
    """Carpeta escribible por-usuario para 'data/' cuando la app está empaquetada."""
    app_name = "SmartCaja"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / app_name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / app_name


if _IS_FROZEN:
    # Recursos de solo lectura extraídos por PyInstaller
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)).resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

APP_DIR = BASE_DIR / "app"
DEFAULTS_DIR = BASE_DIR / "defaults"

_raw_data_dir = os.environ.get("DATA_DIR", "")
if _raw_data_dir and "{{" not in _raw_data_dir and Path(_raw_data_dir).is_absolute():
    DATA_DIR = Path(_raw_data_dir)
elif _IS_FROZEN:
    DATA_DIR = _user_data_dir()
else:
    DATA_DIR = BASE_DIR / "data"
    if _raw_data_dir and "{{" in _raw_data_dir:
        import logging as _early_log
        _early_log.getLogger(__name__).warning(
            "DATA_DIR contiene plantilla Pinokio sin resolver: %s. "
            "Usando fallback: %s", _raw_data_dir, DATA_DIR
        )

def _parse_port():
    """Obtener puerto: 1) argumento --port, 2) env PORT, 3) default 7860."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int, default=None)
    args, _ = parser.parse_known_args()
    if args.port is not None:
        return args.port
    raw = os.environ.get("PORT", "7860")
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 7860

PORT = _parse_port()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# Timeouts configurables (config.json > env var > default)
def _get_timeout(task_type: str = "default") -> int:
    """Lee timeout desde config.json, luego env var, luego default."""
    config = load_json(DATA_DIR / "config.json", {})
    timeout_map = {
        "default": ("OLLAMA_TIMEOUT", 300),
        "analysis": ("OLLAMA_TIMEOUT_ANALYSIS", 600),
        "simulation": ("OLLAMA_TIMEOUT_SIMULATION", 180),
    }
    env_key, default_val = timeout_map.get(task_type, ("OLLAMA_TIMEOUT", 300))
    config_key = f"ollama_timeout_{task_type}" if task_type != "default" else "ollama_timeout"
    return int(config.get(config_key) or os.getenv(env_key) or default_val)

# Límites de seguridad
MAX_MESSAGE_LENGTH = 10000
MAX_COMPANY_NAME_LENGTH = 200
MAX_MONTHS = 60
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX_REQUESTS = 20

# ---------------------------------------------------------------------------
# Logging (sin datos financieros sensibles)
# ---------------------------------------------------------------------------
# Logging mejorado para visibilidad en consola Pinokio
_log_format = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
_log_level = logging.DEBUG if os.environ.get("SMARTCAJA_DEBUG") else logging.INFO
logging.basicConfig(
    level=_log_level,
    format=_log_format,
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("smartcaja")
logger.setLevel(_log_level)

# Reducir ruido de librerías externas
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Banner de inicio visible en Pinokio
print("="*60)
print("  SMARTCAJA v2.1")
print("  Motor Financiero Modular con IA Local")
print("="*60)
print(f"  Log level: {logging.getLevelName(_log_level)}")
print(f"  Data dir: {DATA_DIR}")
print(f"  Platform: {sys.platform}")
print("="*60)

# ---------------------------------------------------------------------------
# Seguridad: Sanitización de IDs y nombres de archivo
# ---------------------------------------------------------------------------
_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_SAFE_FILENAME_CHARS = re.compile(r"[^\w\s\-.]", re.UNICODE)

def _sanitize_id(value: str) -> str:
    """Valida que un ID sea seguro (previene path traversal)."""
    if not value or not _SAFE_ID_PATTERN.match(value):
        raise HTTPException(400, f"ID inválido: solo se permiten caracteres alfanuméricos, guiones y guiones bajos (máx 64 chars).")
    return value

def _sanitize_filename(name: str) -> str:
    """Sanitiza un nombre para uso seguro en nombres de archivo."""
    if not name:
        return "empresa"
    name = unicodedata.normalize("NFKD", name)
    name = _SAFE_FILENAME_CHARS.sub("", name)
    name = name.strip().replace(" ", "_")
    name = name[:50] if name else "empresa"
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
                "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2",
                "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
    if name.upper().split(".")[0] in reserved:
        name = f"_{name}"
    return name

# ---------------------------------------------------------------------------
# Rate Limiting simple (en memoria) — protegido con lock
# ---------------------------------------------------------------------------
_rate_limit_store: Dict[str, list] = defaultdict(list)
_rate_limit_lock = threading.Lock()

def _check_rate_limit(key: str, max_requests: int = RATE_LIMIT_MAX_REQUESTS, window: int = RATE_LIMIT_WINDOW):
    """Verifica rate limit por clave. Lanza HTTPException 429 si se excede."""
    now = time.time()
    with _rate_limit_lock:
        _rate_limit_store[key] = [t for t in _rate_limit_store[key] if now - t < window]
        if len(_rate_limit_store[key]) >= max_requests:
            raise HTTPException(429, f"Demasiadas solicitudes. Espera {window} segundos.")
        _rate_limit_store[key].append(now)

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="SmartCaja", version="0.3.0")

# CORS restringido a localhost (Pinokio siempre corre en localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://0.0.0.0:*",
        "null",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$",
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ---------------------------------------------------------------------------
# Middleware de logging de errores (visible en consola Pinokio)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_errors_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            logger.warning(f"[HTTP {response.status_code}] {request.method} {request.url.path}")
        return response
    except Exception as e:
        import uuid as _uuid
        correlation_id = str(_uuid.uuid4())[:8]
        logger.error(f"[UNHANDLED ERROR][{correlation_id}] {request.method} {request.url.path}: {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={"detail": f"Error interno del servidor. Referencia: {correlation_id}"})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Generar ID de correlación para rastreo en logs sin exponer detalles al cliente
    import uuid as _uuid
    correlation_id = str(_uuid.uuid4())[:8]
    logger.error(f"[EXCEPTION][{correlation_id}] {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"detail": f"Error interno del servidor. Referencia: {correlation_id}"})

# ---------------------------------------------------------------------------
# Utilidades de persistencia
# ---------------------------------------------------------------------------
def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except (ValueError, OverflowError):
        # Sanitizar inf/nan si la serialización falla
        data = _sanitize_dict_safe(data)
        text = json.dumps(data, indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def _sanitize_dict_safe(d):
    """Versión segura de sanitización para usar antes de que _sanitize_dict esté definida."""
    import math
    if isinstance(d, dict):
        return {k: _sanitize_dict_safe(v) for k, v in d.items()}
    elif isinstance(d, list):
        return [_sanitize_dict_safe(item) for item in d]
    elif isinstance(d, float):
        if math.isinf(d) or math.isnan(d):
            return 0.0
        return d
    return d

def load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[load_json] Archivo corrupto o ilegible: {path}. Error: {e}. Retornando default.")
            return default if default is not None else {}
    return default if default is not None else {}

# ---------------------------------------------------------------------------
# Auditoría de llamadas LLM
# ---------------------------------------------------------------------------
def _log_audit_entry(agent_id: str, task: str, model: str, inputs_summary: str,
                     output_summary: str, latency_ms: int, success: bool, error: str = ""):
    """Registra una entrada de auditoría para trazabilidad de agentes."""
    import uuid as _uuid
    entry = {
        "id": str(_uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "task": task,
        "model": model,
        "inputs_summary": inputs_summary[:500],
        "output_summary": output_summary[:500] if output_summary else "",
        "latency_ms": latency_ms,
        "success": success,
        "error": error,
    }
    audit_dir = DATA_DIR / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_file = audit_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[AUDIT] Error escribiendo audit: {e}")

# ---------------------------------------------------------------------------
# Utilidades de Ollama con auto-recuperación
# ---------------------------------------------------------------------------
def _fix_encoding(text: str) -> str:
    """Repara texto UTF-8 mal interpretado como latin-1."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

def _extract_json_from_llm(text: str):
    """Extrae JSON robusto de respuestas del LLM."""
    if not text:
        return None
    # Estrategia 1: strip de bloques ```json ... ```
    clean = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    # Estrategia 2: parser balanceado
    start = text.find("{")
    if start != -1:
        depth, in_str, escape = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i+1])
                        except json.JSONDecodeError:
                            break
    # Estrategia 3: regex greedy
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None

def ensure_ollama_running() -> bool:
    """Verifica que Ollama esté corriendo; intenta iniciarlo si no lo está."""
    try:
        r = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        pass
    try:
        logger.info("Ollama no responde. Intentando iniciar...")
        if sys.platform == "win32":
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        else:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        for attempt in range(5):
            time.sleep(3)
            try:
                r = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
                if r.status_code == 200:
                    logger.info("Ollama iniciado correctamente.")
                    return True
            except Exception:
                continue
        logger.warning("No se pudo iniciar Ollama automáticamente.")
        return False
    except FileNotFoundError:
        logger.error("Ollama no está instalado en este sistema.")
        return False
    except Exception as e:
        logger.error(f"Error al intentar iniciar Ollama: {e}")
        return False

_pull_status: dict = {}
_pull_status_lock = threading.Lock()

def _is_model_available(model: str) -> bool:
    try:
        r = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        return model in models or any(m.startswith(model.split(":")[0]) for m in models)
    except Exception:
        return False

def _start_pull_background(model: str):
    with _pull_status_lock:
        if model in _pull_status and _pull_status[model].get("status") in ("pulling", "queued"):
            return
        _pull_status[model] = {"status": "queued", "progress": 0, "error": None}
    threading.Thread(target=_do_pull, args=(model,), daemon=True).start()

def _do_pull(model: str):
    with _pull_status_lock:
        _pull_status[model]["status"] = "pulling"
    try:
        with http_requests.post(f"{OLLAMA_URL}/api/pull",
                                json={"name": model, "stream": True},
                                stream=True, timeout=3600) as r:
            for line in r.iter_lines():
                if line:
                    data = json.loads(line)
                    if "completed" in data and "total" in data and data["total"] > 0:
                        with _pull_status_lock:
                            _pull_status[model]["progress"] = int(data["completed"] / data["total"] * 100)
        with _pull_status_lock:
            _pull_status[model] = {"status": "done", "progress": 100, "error": None}
    except Exception as e:
        with _pull_status_lock:
            _pull_status[model] = {"status": "error", "progress": 0, "error": str(e)}

def call_ollama(model: str, system_prompt: str, user_message: str,
                temperature: float = 0.7, timeout: int = None) -> str:
    if timeout is None:
        timeout = _get_timeout("default")
    if not ensure_ollama_running():
        raise HTTPException(503, "Ollama no está disponible. Verifica que esté instalado y ejecutándose.")
    try:
        resp = http_requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                "options": {"temperature": temperature},
                "stream": False
            },
            timeout=timeout
        )
        resp.encoding = "utf-8"
        if resp.status_code == 404:
            _start_pull_background(model)
            raise HTTPException(503, f"Modelo {model} no disponible. Descarga iniciada.")
        resp.raise_for_status()
        resp_data = resp.json()
        content = resp_data["message"]["content"]
        # Track token usage y audit para call_ollama
        try:
            latency_ms = int((resp.elapsed.total_seconds()) * 1000) if hasattr(resp, 'elapsed') else 0
            total_tokens = resp_data.get("eval_count", 0) + resp_data.get("prompt_eval_count", 0)
            agent_hint = "unknown"
            task_hint = "generation"
            sp_lower = system_prompt.lower()
            if "extrac" in sp_lower or "json" in sp_lower:
                agent_hint = "data_extractor"
                task_hint = "data_extraction"
            elif "cashflow" in sp_lower or "flujo" in sp_lower:
                agent_hint = "cashflow_analyst"
                task_hint = "cashflow_generation"
            elif "simulad" in sp_lower or "escenario" in sp_lower or "monte carlo" in sp_lower:
                agent_hint = "scenario_simulator"
                task_hint = "simulation"
            elif "entrevista" in sp_lower or "financiero" in sp_lower:
                agent_hint = "financial_interviewer"
                task_hint = "interview"
            if total_tokens > 0:
                track_token_usage(agent_hint, total_tokens)
            _log_audit_entry(
                agent_id=agent_hint,
                task=task_hint,
                model=model,
                inputs_summary=user_message[:500],
                output_summary=content[:500],
                latency_ms=latency_ms,
                success=True
            )
        except Exception:
            pass
        return _fix_encoding(content)
    except http_requests.exceptions.ConnectionError:
        raise HTTPException(503, "No se puede conectar con Ollama. Verifica que esté ejecutándose.")
    except http_requests.exceptions.Timeout:
        raise HTTPException(504, "Timeout al comunicarse con Ollama. Intenta de nuevo.")

def call_ollama_chat(model: str, messages: list, temperature: float = 0.7, timeout: int = None) -> str:
    """Llamada a Ollama con historial de mensajes completo."""
    if timeout is None:
        timeout = _get_timeout("default")
    if not ensure_ollama_running():
        raise HTTPException(503, "Ollama no está disponible.")
    try:
        resp = http_requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "options": {"temperature": temperature},
                "stream": False
            },
            timeout=timeout
        )
        resp.encoding = "utf-8"
        if resp.status_code == 404:
            _start_pull_background(model)
            raise HTTPException(503, f"Modelo {model} no disponible. Descarga iniciada.")
        resp.raise_for_status()
        resp_data = resp.json()
        content = resp_data["message"]["content"]
        # Track token usage y audit
        import time as _time
        latency_ms = int((resp.elapsed.total_seconds()) * 1000) if hasattr(resp, 'elapsed') else 0
        try:
            total_tokens = resp_data.get("eval_count", 0) + resp_data.get("prompt_eval_count", 0)
            agent_hint = "unknown"
            task_hint = "chat"
            for m in messages:
                if m.get("role") == "system":
                    sys_content = m["content"].lower()
                    if "entrevista" in sys_content or "financiero" in sys_content:
                        agent_hint = "financial_interviewer"
                        task_hint = "interview"
                    elif "cashflow" in sys_content or "flujo" in sys_content:
                        agent_hint = "cashflow_analyst"
                        task_hint = "cashflow_generation"
                    elif "simulador" in sys_content or "escenario" in sys_content:
                        agent_hint = "scenario_simulator"
                        task_hint = "simulation"
                    elif "extractor" in sys_content or "datos" in sys_content:
                        agent_hint = "data_extractor"
                        task_hint = "data_extraction"
                    break
            if total_tokens > 0:
                track_token_usage(agent_hint, total_tokens)
            # Log audit entry
            _log_audit_entry(
                agent_id=agent_hint,
                task=task_hint,
                model=model,
                inputs_summary=messages[-1].get("content", "")[:500] if messages else "",
                output_summary=content[:500],
                latency_ms=latency_ms,
                success=True
            )
        except Exception:
            pass
        return _fix_encoding(content)
    except http_requests.exceptions.ConnectionError:
        raise HTTPException(503, "No se puede conectar con Ollama.")
    except http_requests.exceptions.Timeout:
        raise HTTPException(504, "Timeout al comunicarse con Ollama.")

# ---------------------------------------------------------------------------
# Carga de agentes y prompts
# ---------------------------------------------------------------------------
def get_agents() -> dict:
    return load_json(DATA_DIR / "agents" / "agents.json", {"version": "0.2.0", "agents": []})

def get_agent(agent_id: str) -> dict:
    _sanitize_id(agent_id)
    agents = get_agents()
    for a in agents.get("agents", []):
        if a["id"] == agent_id:
            return a
    return None

def get_prompt(prompt_name: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", prompt_name)
    if not safe_name:
        return ""
    # Verificar que el path resuelto está dentro de los directorios permitidos
    path = DATA_DIR / "prompts" / "system" / f"{safe_name}.md"
    if path.resolve().is_relative_to(DATA_DIR.resolve()) and path.exists():
        return path.read_text(encoding="utf-8")
    path = DEFAULTS_DIR / "prompts" / f"{safe_name}.md"
    if path.resolve().is_relative_to(DEFAULTS_DIR.resolve()) and path.exists():
        return path.read_text(encoding="utf-8")
    return ""

# ---------------------------------------------------------------------------
# Modelos Pydantic con validación
# ---------------------------------------------------------------------------
class CompanyCreate(BaseModel):
    name: str
    sector: str = ""
    description: str = ""
    size: str = ""
    country: str = "Chile"
    currency: str = "CLP"
    initial_cash: float = 0
    employees: int = 0
    age: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("El nombre de la empresa es requerido.")
        if len(v) > MAX_COMPANY_NAME_LENGTH:
            raise ValueError(f"El nombre no puede exceder {MAX_COMPANY_NAME_LENGTH} caracteres.")
        return v.strip()

class ChatMessage(BaseModel):
    company_id: str
    message: str
    session_id: Optional[str] = ""

    @field_validator("session_id", mode="before")
    @classmethod
    def coerce_session_id(cls, v):
        if v is None:
            return ""
        return str(v)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError("El mensaje no puede estar vacío.")
        if len(v) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"El mensaje no puede exceder {MAX_MESSAGE_LENGTH} caracteres.")
        return v.strip()

class ScenarioRequest(BaseModel):
    instruction: str
    use_ai: Optional[bool] = False
    params: Optional[Dict[str, Any]] = None

    @field_validator("instruction")
    @classmethod
    def validate_instruction(cls, v):
        if not v or not v.strip():
            raise ValueError("La instrucción no puede estar vacía.")
        if len(v) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"La instrucción no puede exceder {MAX_MESSAGE_LENGTH} caracteres.")
        return v.strip()

class AgentConfigUpdate(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = None
    system_prompt: Optional[str] = None

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v):
        if v is not None and (v < 0.0 or v > 2.0):
            raise ValueError("La temperatura debe estar entre 0.0 y 2.0.")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v):
        if v is not None and len(v) > 50000:
            raise ValueError("El prompt del sistema no puede exceder 50000 caracteres.")
        return v

class MonthPayload(BaseModel):
    """Payload de entrada para edición de meses (renombrado para evitar colisión con core.MonthData)."""
    month: Optional[str] = None
    label: Optional[str] = None
    income: Optional[dict] = None
    expenses: Optional[dict] = None

# ---------------------------------------------------------------------------
# Normalización de datos de flujo de caja
# ---------------------------------------------------------------------------
import math as _math

def _sanitize_float(val) -> float:
    """Sanitiza un float para que sea JSON-compatible (sin inf/nan)."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        if _math.isinf(val) or _math.isnan(val):
            return 0.0
        return float(val)
    return 0.0


def _sanitize_dict(d):
    """Recursivamente sanitiza todos los floats en un dict/list para ser JSON-compatible."""
    if isinstance(d, dict):
        return {k: _sanitize_dict(v) for k, v in d.items()}
    elif isinstance(d, list):
        return [_sanitize_dict(item) for item in d]
    elif isinstance(d, float):
        if _math.isinf(d) or _math.isnan(d):
            return 0.0
        return d
    return d


def _to_num(val) -> float:
    """Convierte un valor a número de forma robusta."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        f = float(val)
        if _math.isinf(f) or _math.isnan(f):
            return 0.0
        return f
    if isinstance(val, str):
        clean = val.strip().replace("$", "").replace(" ", "")
        if clean.count(".") > 1:
            clean = clean.replace(".", "")
        elif "." in clean and "," in clean:
            clean = clean.replace(".", "").replace(",", ".")
        elif "," in clean and "." not in clean:
            parts = clean.split(",")
            if all(len(p) == 3 for p in parts[1:]):
                clean = clean.replace(",", "")
            else:
                clean = clean.replace(",", ".")
        clean = re.sub(r"[^\d.\-]", "", clean)
        try:
            return float(clean) if clean else 0.0
        except ValueError:
            return 0.0
    return 0.0

def _normalize_month(m: dict) -> dict:
    """Normaliza un mes individual: asegura estructura y recalcula totales."""
    income = m.get("income", {})
    if not isinstance(income, dict):
        income = {}
    expenses = m.get("expenses", {})
    if not isinstance(expenses, dict):
        expenses = {}

    sales = _to_num(income.get("sales", 0))
    other_income = _to_num(income.get("other_income", 0))
    income_total = sales + other_income

    variable_costs = _to_num(expenses.get("variable_costs", 0))
    fixed_costs = _to_num(expenses.get("fixed_costs", 0))
    variable_expenses = _to_num(expenses.get("variable_expenses", 0))
    debt_payments = _to_num(expenses.get("debt_payments", 0))
    taxes = _to_num(expenses.get("taxes", 0))
    investments = _to_num(expenses.get("investments", 0))
    expenses_total = variable_costs + fixed_costs + variable_expenses + debt_payments + taxes + investments

    net_flow = income_total - expenses_total

    return {
        "month": m.get("month", ""),
        "label": m.get("label", m.get("month", "")),
        "income": {
            "sales": sales,
            "other_income": other_income,
            "total": income_total
        },
        "expenses": {
            "variable_costs": variable_costs,
            "fixed_costs": fixed_costs,
            "variable_expenses": variable_expenses,
            "debt_payments": debt_payments,
            "taxes": taxes,
            "investments": investments,
            "total": expenses_total
        },
        "net_flow": net_flow,
        "cumulative_balance": 0
    }

def _rescue_cashflow_structure(data: dict) -> dict:
    """Busca la estructura de meses en cualquier nivel del JSON del LLM.
    Los LLMs a veces envuelven el resultado en campos extra como 'data', 'cashflow',
    'flujo_de_caja', 'result', etc. Esta función busca recursivamente."""
    if not isinstance(data, dict):
        return data
    
    # Si ya tiene months como lista con al menos un elemento, está bien
    months = data.get("months", None)
    if isinstance(months, list) and len(months) > 0:
        # Verificar que los elementos parecen meses (tienen income o expenses)
        first = months[0] if months else {}
        if isinstance(first, dict) and ("income" in first or "expenses" in first or "sales" in first or "ingresos" in first):
            return data
    
    # Buscar en campos comunes donde el LLM podría haber anidado los datos
    candidate_keys = ["data", "cashflow", "flujo_de_caja", "result", "resultado",
                      "flujo", "cash_flow", "projection", "proyeccion"]
    for key in candidate_keys:
        if key in data and isinstance(data[key], dict):
            inner = data[key]
            if isinstance(inner.get("months"), list) and len(inner["months"]) > 0:
                # Mover campos del wrapper al nivel superior
                for k, v in list(inner.items()):
                    data[k] = v
                return data
    
    # Buscar cualquier campo que sea una lista de dicts con estructura de mes
    for key, val in list(data.items()):
        if key == "months":
            continue
        if isinstance(val, list) and len(val) > 0:
            first = val[0] if val else {}
            if isinstance(first, dict) and ("income" in first or "expenses" in first or
                                            "sales" in first or "ingresos" in first or
                                            "month" in first or "mes" in first):
                data["months"] = val
                return data
    
    # Buscar meses con nombres en español
    if "meses" in data and isinstance(data["meses"], list):
        data["months"] = data["meses"]
        return data
    
    return data


def _normalize_month_from_spanish(m: dict) -> dict:
    """Intenta normalizar un mes que puede venir con campos en español."""
    if not isinstance(m, dict):
        return m
    
    # Mapear campos en español a inglés
    if "ingresos" in m and "income" not in m:
        inc = m["ingresos"]
        if isinstance(inc, dict):
            m["income"] = {
                "sales": _to_num(inc.get("ventas", inc.get("sales", 0))),
                "other_income": _to_num(inc.get("otros_ingresos", inc.get("otros", inc.get("other_income", 0)))),
            }
        elif isinstance(inc, (int, float, str)):
            m["income"] = {"sales": _to_num(inc), "other_income": 0}
    
    if "gastos" in m and "expenses" not in m:
        exp = m["gastos"]
        if isinstance(exp, dict):
            m["expenses"] = {
                "variable_costs": _to_num(exp.get("costos_variables", exp.get("variable_costs", 0))),
                "fixed_costs": _to_num(exp.get("costos_fijos", exp.get("fixed_costs", 0))),
                "variable_expenses": _to_num(exp.get("gastos_variables", exp.get("variable_expenses", 0))),
                "debt_payments": _to_num(exp.get("deudas", exp.get("debt_payments", exp.get("pagos_deuda", 0)))),
                "taxes": _to_num(exp.get("impuestos", exp.get("taxes", 0))),
                "investments": _to_num(exp.get("inversiones", exp.get("investments", 0))),
            }
        elif isinstance(exp, (int, float, str)):
            m["expenses"] = {"variable_costs": _to_num(exp), "fixed_costs": 0, "variable_expenses": 0, "debt_payments": 0, "taxes": 0, "investments": 0}
    
    if "mes" in m and "month" not in m:
        m["month"] = m["mes"]
    if "etiqueta" in m and "label" not in m:
        m["label"] = m["etiqueta"]
    
    # Si tiene ventas a nivel raíz (sin income wrapper)
    if "sales" in m and "income" not in m:
        m["income"] = {"sales": _to_num(m["sales"]), "other_income": _to_num(m.get("other_income", 0))}
    if "ventas" in m and "income" not in m:
        m["income"] = {"sales": _to_num(m["ventas"]), "other_income": _to_num(m.get("otros_ingresos", 0))}
    
    return m


def normalize_cashflow(data: dict) -> dict:
    """Normaliza un flujo de caja completo: recalcula totales, saldos acumulados y summary."""
    # Primero intentar rescatar la estructura si el LLM la anidó
    data = _rescue_cashflow_structure(data)
    
    months = data.get("months", [])
    if not isinstance(months, list):
        months = []
    months = months[:MAX_MONTHS]
    
    # Normalizar meses que pueden venir en español
    months = [_normalize_month_from_spanish(m) for m in months if isinstance(m, dict)]

    normalized_months = []
    cumulative = 0.0
    total_income = 0.0
    total_expenses = 0.0

    for m in months:
        nm = _normalize_month(m)
        cumulative += nm["net_flow"]
        nm["cumulative_balance"] = cumulative
        total_income += nm["income"]["total"]
        total_expenses += nm["expenses"]["total"]
        normalized_months.append(nm)

    num_months = len(normalized_months)
    net_cashflow = total_income - total_expenses
    avg_balance = cumulative / num_months if num_months > 0 else 0

    data["months"] = normalized_months
    data["summary"] = {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_cashflow": net_cashflow,
        "average_monthly_balance": avg_balance,
        "num_months": num_months
    }

    return data

# ---------------------------------------------------------------------------
# Motor de Simulación Local (sin LLM - rápido y determinístico)
# ---------------------------------------------------------------------------
def simulate_local(cashflow: dict, params: dict, task_id: str = None) -> dict:
    """
    Ejecuta simulación matemática local sin necesidad de LLM.
    Parámetros soportados:
      - sales_change_pct: % de cambio en ventas
      - costs_change_pct: % de cambio en costos variables
      - fixed_costs_change_pct: % de cambio en costos fijos
      - inflation_annual_pct: inflación anual (aplicada mensualmente)
      - new_hires: número de nuevas contrataciones
      - hire_cost: costo mensual por contratación (default 800000)
      - tax_change_pct: % de cambio en impuestos
      - debt_change_pct: % de cambio en pagos de deuda
      - investment_change_pct: % de cambio en inversiones
      - other_income_change_pct: % de cambio en otros ingresos
      - start_month: mes desde el cual aplicar cambios (0-based, default 0)
    """
    result = copy.deepcopy(cashflow)
    months = result.get("months", [])
    if not months:
        return result

    # Actualizar progreso
    if task_id:
        _generation_status[task_id]["progress"] = 20
        _generation_status[task_id]["step"] = "Preparando parámetros de simulación..."

    sales_pct = params.get("sales_change_pct", 0) / 100.0
    costs_pct = params.get("costs_change_pct", 0) / 100.0
    fixed_costs_pct = params.get("fixed_costs_change_pct", 0) / 100.0
    inflation_annual = params.get("inflation_annual_pct", 0) / 100.0
    new_hires = params.get("new_hires", 0)
    hire_cost = params.get("hire_cost", 800000)
    tax_pct = params.get("tax_change_pct", 0) / 100.0
    debt_pct = params.get("debt_change_pct", 0) / 100.0
    investment_pct = params.get("investment_change_pct", 0) / 100.0
    other_income_pct = params.get("other_income_change_pct", 0) / 100.0
    start_month = params.get("start_month", 0)

    # Inflación mensual compuesta
    monthly_inflation = (1 + inflation_annual) ** (1/12) - 1 if inflation_annual > 0 else 0

    total_months = len(months)
    changes_applied = []

    if task_id:
        _generation_status[task_id]["progress"] = 30
        _generation_status[task_id]["step"] = "Aplicando cambios a los meses..."

    # Guardar checkpoint inicial
    if task_id:
        _save_simulation_checkpoint(task_id, result, 0, total_months)

    for i in range(total_months):
        if i < start_month:
            continue

        month = months[i]
        income = month.get("income", {})
        expenses = month.get("expenses", {})

        # Calcular factor de inflación acumulada desde start_month
        months_elapsed = i - start_month
        inflation_factor = (1 + monthly_inflation) ** months_elapsed if monthly_inflation > 0 else 1.0

        # Aplicar cambios a ingresos
        if sales_pct != 0:
            income["sales"] = round(income.get("sales", 0) * (1 + sales_pct), 2)
        if other_income_pct != 0:
            income["other_income"] = round(income.get("other_income", 0) * (1 + other_income_pct), 2)

        # Aplicar cambios a gastos
        if costs_pct != 0:
            expenses["variable_costs"] = round(expenses.get("variable_costs", 0) * (1 + costs_pct), 2)
        if fixed_costs_pct != 0:
            expenses["fixed_costs"] = round(expenses.get("fixed_costs", 0) * (1 + fixed_costs_pct), 2)
        if tax_pct != 0:
            expenses["taxes"] = round(expenses.get("taxes", 0) * (1 + tax_pct), 2)
        if debt_pct != 0:
            expenses["debt_payments"] = round(expenses.get("debt_payments", 0) * (1 + debt_pct), 2)
        if investment_pct != 0:
            expenses["investments"] = round(expenses.get("investments", 0) * (1 + investment_pct), 2)

        # Nuevas contrataciones (afecta costos fijos)
        if new_hires > 0:
            expenses["fixed_costs"] = round(expenses.get("fixed_costs", 0) + (new_hires * hire_cost), 2)

        # Inflación (afecta costos fijos y gastos variables progresivamente)
        if monthly_inflation > 0:
            expenses["fixed_costs"] = round(expenses.get("fixed_costs", 0) * inflation_factor, 2)
            expenses["variable_expenses"] = round(expenses.get("variable_expenses", 0) * inflation_factor, 2)

        month["income"] = income
        month["expenses"] = expenses
        months[i] = month

        # Actualizar progreso cada 2 meses
        if task_id and (i % 2 == 0 or i == total_months - 1):
            progress = 30 + int((i / total_months) * 50)
            _generation_status[task_id]["progress"] = progress
            _generation_status[task_id]["step"] = f"Procesando mes {i + 1} de {total_months}..."
            # Guardar checkpoint cada 4 meses
            if i % 4 == 0:
                _save_simulation_checkpoint(task_id, result, i, total_months)

    result["months"] = months

    if task_id:
        _generation_status[task_id]["progress"] = 85
        _generation_status[task_id]["step"] = "Recalculando totales y alertas..."

    # Re-normalizar
    result = normalize_cashflow(result)

    # Generar descripción de cambios
    if sales_pct != 0:
        changes_applied.append(f"Ventas {'aumentadas' if sales_pct > 0 else 'reducidas'} en {abs(int(sales_pct*100))}%")
    if costs_pct != 0:
        changes_applied.append(f"Costos variables {'aumentados' if costs_pct > 0 else 'reducidos'} en {abs(int(costs_pct*100))}%")
    if fixed_costs_pct != 0:
        changes_applied.append(f"Costos fijos {'aumentados' if fixed_costs_pct > 0 else 'reducidos'} en {abs(int(fixed_costs_pct*100))}%")
    if inflation_annual > 0:
        changes_applied.append(f"Inflación anual del {int(inflation_annual*100)}% aplicada")
    if new_hires > 0:
        changes_applied.append(f"{new_hires} nuevas contrataciones (${hire_cost:,.0f} c/u)")
    if tax_pct != 0:
        changes_applied.append(f"Impuestos {'aumentados' if tax_pct > 0 else 'reducidos'} en {abs(int(tax_pct*100))}%")
    if debt_pct != 0:
        changes_applied.append(f"Pagos de deuda {'aumentados' if debt_pct > 0 else 'reducidos'} en {abs(int(debt_pct*100))}%")
    if investment_pct != 0:
        changes_applied.append(f"Inversiones {'aumentadas' if investment_pct > 0 else 'reducidas'} en {abs(int(investment_pct*100))}%")
    if other_income_pct != 0:
        changes_applied.append(f"Otros ingresos {'aumentados' if other_income_pct > 0 else 'reducidos'} en {abs(int(other_income_pct*100))}%")

    # Generar alertas automáticas
    alerts = []
    for i, m in enumerate(result["months"]):
        if m["cumulative_balance"] < 0:
            alerts.append({
                "month": m.get("label", m.get("month", f"Mes {i+1}")),
                "type": "danger",
                "message": f"Saldo acumulado negativo: ${m['cumulative_balance']:,.0f}"
            })
        elif m["net_flow"] < 0:
            alerts.append({
                "month": m.get("label", m.get("month", f"Mes {i+1}")),
                "type": "warning",
                "message": f"Flujo neto negativo: ${m['net_flow']:,.0f}"
            })

    # Generar nombre del escenario
    scenario_name = "Simulación: " + ", ".join(changes_applied[:3])
    if len(changes_applied) > 3:
        scenario_name += f" (+{len(changes_applied)-3} más)"

    # Calcular impacto
    base_summary = cashflow.get("summary", {})
    new_summary = result.get("summary", {})
    impact_income = new_summary.get("total_income", 0) - base_summary.get("total_income", 0)
    impact_expenses = new_summary.get("total_expenses", 0) - base_summary.get("total_expenses", 0)
    impact_net = new_summary.get("net_cashflow", 0) - base_summary.get("net_cashflow", 0)

    result["scenario_name"] = scenario_name
    result["changes_applied"] = changes_applied
    result["alerts"] = alerts
    result["impact_summary"] = {
        "income_change": impact_income,
        "expenses_change": impact_expenses,
        "net_change": impact_net,
        "description": f"Impacto neto: ${impact_net:+,.0f} en el período"
    }
    result["recommendations"] = _generate_recommendations(result, cashflow)

    if task_id:
        _generation_status[task_id]["progress"] = 95
        _generation_status[task_id]["step"] = "Finalizando simulación..."

    return result


def _generate_recommendations(simulated: dict, original: dict) -> list:
    """Genera recomendaciones basadas en la comparación entre simulado y original."""
    recs = []
    sim_summary = simulated.get("summary", {})
    orig_summary = original.get("summary", {})

    net_change = sim_summary.get("net_cashflow", 0) - orig_summary.get("net_cashflow", 0)

    if net_change < 0:
        recs.append("El escenario simulado reduce el flujo neto. Considere medidas compensatorias.")
    if net_change > 0:
        recs.append("El escenario simulado mejora el flujo neto. Evalúe su viabilidad de implementación.")

    # Verificar meses con saldo negativo
    negative_months = [m for m in simulated.get("months", []) if m.get("cumulative_balance", 0) < 0]
    if negative_months:
        recs.append(f"Hay {len(negative_months)} mes(es) con saldo acumulado negativo. Considere líneas de crédito o reducción de gastos.")

    # Verificar tendencia
    months = simulated.get("months", [])
    if len(months) >= 3:
        last_3_flows = [m.get("net_flow", 0) for m in months[-3:]]
        if all(f < 0 for f in last_3_flows):
            recs.append("Los últimos 3 meses muestran flujo negativo sostenido. Revise la estrategia financiera.")
        elif all(f > 0 for f in last_3_flows):
            recs.append("Los últimos 3 meses muestran flujo positivo sostenido. Buen momento para inversiones.")

    return recs


def _save_simulation_checkpoint(task_id: str, data: dict, month_index: int, total_months: int):
    """Guarda un checkpoint de la simulación en disco para recuperación."""
    checkpoints_dir = DATA_DIR / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "task_id": task_id,
        "timestamp": datetime.now().isoformat(),
        "month_index": month_index,
        "total_months": total_months,
        "partial_data": data
    }
    save_json(checkpoints_dir / f"{task_id}.json", checkpoint)


# ---------------------------------------------------------------------------
# Estado de generación (en memoria)
# ---------------------------------------------------------------------------
_generation_status: dict = {}

# ---------------------------------------------------------------------------
# Endpoints: Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    ollama_ok = False
    ollama_models = []
    try:
        r = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            ollama_ok = True
            ollama_models = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return {
        "status": "ok",
        "ollama": "connected" if ollama_ok else "disconnected",
        "ollama_models": ollama_models,
        "version": "0.3.0",
        "platform": sys.platform
    }

# ---------------------------------------------------------------------------
# Endpoints: Readiness (semáforo de sistema)
# ---------------------------------------------------------------------------
@app.get("/api/readiness")
async def check_readiness():
    issues = []
    ready = True

    ollama_ok = False
    models = []
    try:
        resp = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            ollama_ok = True
            models = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        pass

    if not ollama_ok:
        ready = False
        issues.append({
            "type": "ollama_unavailable",
            "message": "Ollama no está disponible. Asegúrate de que esté instalado y corriendo.",
            "severity": "critical",
        })

    if ollama_ok and not models:
        ready = False
        issues.append({
            "type": "no_models",
            "message": "No hay modelos de IA descargados. Se están descargando automáticamente...",
            "severity": "warning",
        })

    active_pulls = []
    for model_name, info in _pull_status.items():
        if info.get("status") in ("queued", "pulling"):
            active_pulls.append({
                "model": model_name,
                "status": info.get("status"),
                "progress": info.get("progress", 0),
            })

    if active_pulls:
        issues.append({
            "type": "models_downloading",
            "message": f"Descargando {len(active_pulls)} modelo(s) de IA...",
            "severity": "info",
            "pulls": active_pulls,
        })

    return {
        "ready": ready and not active_pulls,
        "ollama_available": ollama_ok,
        "models_count": len(models),
        "models": models,
        "active_pulls": active_pulls,
        "issues": issues,
    }

# ---------------------------------------------------------------------------
# Endpoints: Ollama Status
# ---------------------------------------------------------------------------
@app.get("/api/ollama/status")
async def ollama_status():
    try:
        resp = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"available": True, "models": models}
    except Exception:
        return {"available": False, "models": []}

# ---------------------------------------------------------------------------
# Endpoints: Hardware Performance (semáforo de modelos)
# ---------------------------------------------------------------------------
@app.get("/api/hardware/performance")
async def get_hardware_performance():
    import platform as plat

    hw = {
        "platform": sys.platform,
        "platform_name": plat.system(),
        "architecture": plat.machine(),
        "cpu_count": os.cpu_count() or 1,
        "ram_gb": 0,
        "gpu_name": "No detectada",
        "vram_gb": 0,
    }

    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            c_ulonglong = ctypes.c_ulonglong
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", c_ulonglong),
                            ("ullAvailPhys", c_ulonglong),
                            ("ullTotalPageFile", c_ulonglong),
                            ("ullAvailPageFile", c_ulonglong),
                            ("ullTotalVirtual", c_ulonglong),
                            ("ullAvailVirtual", c_ulonglong),
                            ("ullAvailExtendedVirtual", c_ulonglong)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            hw["ram_gb"] = round(stat.ullTotalPhys / (1024**3), 1)
        elif sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5)
            hw["ram_gb"] = round(int(out.strip()) / (1024**3), 1)
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        hw["ram_gb"] = round(kb / (1024**2), 1)
                        break
    except Exception as e:
        logger.debug(f"No se pudo detectar RAM: {e}")

    try:
        if sys.platform == "darwin" and plat.machine() == "arm64":
            hw["gpu_name"] = f"Apple Silicon ({plat.processor() or 'M-series'})"
            hw["vram_gb"] = hw["ram_gb"]
        else:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                timeout=5, stderr=subprocess.DEVNULL
            ).decode().strip()
            if out:
                parts = out.split(",")
                hw["gpu_name"] = parts[0].strip()
                hw["vram_gb"] = round(int(parts[1].strip()) / 1024, 1) if len(parts) > 1 else 0
    except Exception:
        pass

    models_perf = []
    try:
        resp = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            for m in resp.json().get("models", []):
                model_name = m.get("name", "")
                model_size_bytes = m.get("size", 0)
                model_size_gb = round(model_size_bytes / (1024**3), 1)

                params_b = _estimate_model_params(model_name)
                tps = _estimate_tokens_per_second(
                    params_b, hw["ram_gb"], hw["vram_gb"],
                    hw["cpu_count"], hw["gpu_name"]
                )
                grade = _compute_grade(tps, model_size_gb, hw["ram_gb"])

                models_perf.append({
                    "model": model_name,
                    "size_gb": model_size_gb,
                    "params_b": params_b,
                    "estimated_tps": tps,
                    "grade": grade["grade"],
                    "grade_label": grade["label"],
                    "grade_color": grade["color"],
                    "score": grade["score"],
                    "ram_pct": round((model_size_gb / hw["ram_gb"]) * 100, 1) if hw["ram_gb"] > 0 else 100,
                })
    except Exception as e:
        logger.debug(f"No se pudieron obtener modelos para performance: {e}")

    return {"hardware": hw, "models": models_perf}


def _estimate_model_params(model_name: str) -> float:
    name_lower = model_name.lower()
    match = re.search(r'(\d+\.?\d*)b', name_lower)
    if match:
        return float(match.group(1))
    if "1b" in name_lower or "1.1b" in name_lower:
        return 1.0
    if "3b" in name_lower:
        return 3.0
    if "7b" in name_lower or "8b" in name_lower:
        return 8.0
    if "13b" in name_lower or "14b" in name_lower:
        return 14.0
    if "32b" in name_lower or "34b" in name_lower:
        return 32.0
    if "70b" in name_lower:
        return 70.0
    return 7.0


def _estimate_tokens_per_second(
    params_b: float, ram_gb: float, vram_gb: float,
    cpu_count: int, gpu_name: str
) -> int:
    model_gb = params_b * 0.6
    is_apple_silicon = "apple" in gpu_name.lower() or "m1" in gpu_name.lower() or "m2" in gpu_name.lower() or "m3" in gpu_name.lower() or "m4" in gpu_name.lower()
    has_nvidia = "nvidia" in gpu_name.lower() or "geforce" in gpu_name.lower() or "rtx" in gpu_name.lower()

    if is_apple_silicon:
        available = ram_gb
        if model_gb > available * 0.8:
            return max(1, int(5 * (available / model_gb)))
        bandwidth_factor = min(2.0, ram_gb / 16.0)
        base_tps = 60 / (params_b / 8.0)
        return max(1, int(base_tps * bandwidth_factor))
    elif has_nvidia and vram_gb > 0:
        if model_gb <= vram_gb * 0.9:
            base_tps = 80 / (params_b / 8.0)
            return max(1, int(base_tps))
        elif model_gb <= vram_gb + ram_gb * 0.5:
            return max(1, int(20 / (params_b / 8.0)))
        else:
            return max(1, int(5 / (params_b / 8.0)))
    else:
        if model_gb > ram_gb * 0.7:
            return max(1, int(2 * (ram_gb / model_gb)))
        core_factor = min(2.0, cpu_count / 8.0)
        base_tps = 25 / (params_b / 8.0)
        return max(1, int(base_tps * core_factor))


def _compute_grade(tps: int, model_size_gb: float, ram_gb: float) -> dict:
    if ram_gb > 0 and model_size_gb > ram_gb * 0.9:
        return {"grade": "F", "label": "NO EJECUTABLE", "color": "#dc2626", "score": 0}
    if tps >= 30:
        score = min(100, 80 + int((tps - 30) * 0.5))
        return {"grade": "S", "label": "EXCELENTE", "color": "#22c55e", "score": score}
    elif tps >= 15:
        score = 65 + int((tps - 15) * 1.0)
        return {"grade": "A", "label": "MUY BUENO", "color": "#4ade80", "score": score}
    elif tps >= 8:
        score = 50 + int((tps - 8) * 2.0)
        return {"grade": "B", "label": "ACEPTABLE", "color": "#facc15", "score": score}
    elif tps >= 4:
        score = 30 + int((tps - 4) * 5.0)
        return {"grade": "C", "label": "AJUSTADO", "color": "#f97316", "score": score}
    elif tps >= 2:
        score = 15 + int((tps - 2) * 7.5)
        return {"grade": "D", "label": "MUY LENTO", "color": "#ef4444", "score": score}
    else:
        return {"grade": "F", "label": "NO RECOMENDADO", "color": "#dc2626", "score": max(0, tps * 7)}


# ---------------------------------------------------------------------------
# Endpoints: Empresas (con sanitización de IDs)
# ---------------------------------------------------------------------------
@app.post("/api/companies", status_code=201)
async def create_company(data: CompanyCreate):
    company_id = str(uuid.uuid4())[:8]
    company_dir = DATA_DIR / "companies" / company_id
    company_dir.mkdir(parents=True, exist_ok=True)
    company = {
        "id": company_id,
        "name": data.name,
        "sector": data.sector,
        "description": data.description,
        "size": data.size,
        "country": data.country,
        "currency": data.currency,
        "initial_cash": data.initial_cash,
        "employees": data.employees,
        "age": data.age,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    save_json(company_dir / "company.json", company)
    logger.info(f"Empresa creada: {company_id}")
    return company

def _reconcile_company_status(company: dict, company_dir: Path) -> dict:
    """Reconcilia el estado de la empresa basándose en archivos reales en disco.
    Si existe cashflow.json, la empresa está completa aunque company.json diga 'pending'.
    Si existe interview_state.json con datos, la empresa está en entrevista.
    """
    current_status = company.get("status", "pending")
    # Si ya tiene cashflow generado, marcar como complete
    cashflow_path = company_dir / "cashflow.json"
    if cashflow_path.exists():
        cashflow_data = load_json(cashflow_path, {})
        if cashflow_data.get("months") or cashflow_data.get("summary"):
            if current_status != "complete":
                company["status"] = "complete"
                save_json(company_dir / "company.json", company)
            return company
    # Si tiene interview_state con datos, marcar como interviewing
    interview_state_path = company_dir / "interview_state.json"
    if interview_state_path.exists():
        state = load_json(interview_state_path, {})
        if state.get("collected_data") and len(state["collected_data"]) > 0:
            if current_status == "pending":
                company["status"] = "interviewing"
                save_json(company_dir / "company.json", company)
    return company


@app.get("/api/companies")
async def list_companies():
    companies_dir = DATA_DIR / "companies"
    companies_dir.mkdir(parents=True, exist_ok=True)
    companies = []
    for d in sorted(companies_dir.iterdir()):
        if d.is_dir():
            company = load_json(d / "company.json")
            if company:
                company = _reconcile_company_status(company, d)
                companies.append(company)
    return {"companies": companies}

@app.get("/api/companies/{company_id}")
async def get_company(company_id: str):
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    if not company_dir.exists():
        raise HTTPException(404, "Empresa no encontrada")
    company = load_json(company_dir / "company.json")
    # Reconciliar estado basándose en archivos reales
    company = _reconcile_company_status(company, company_dir)
    return company


@app.get("/api/companies/{company_id}/interview-progress")
async def get_interview_progress(company_id: str):
    """Retorna el estado persistido de la entrevista para restaurar la UI."""
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    if not company_dir.exists():
        raise HTTPException(404, "Empresa no encontrada")
    interview_state_path = company_dir / "interview_state.json"
    persisted_state = load_json(interview_state_path, {"collected_data": {}, "topics_covered": []})
    company = load_json(company_dir / "company.json")
    # Recalcular progreso usando InterviewManager
    im = InterviewManager(
        company_data=company,
        persisted_data=persisted_state.get("collected_data", {}),
        persisted_topics=persisted_state.get("topics_covered", [])
    )
    progress = im.get_interview_progress()
    return {
        "progress": progress,
        "topics_covered": persisted_state.get("topics_covered", []),
        "collected_data_keys": list(persisted_state.get("collected_data", {}).keys()),
        "last_updated": persisted_state.get("last_updated"),
    }

@app.delete("/api/companies/{company_id}")
async def delete_company(company_id: str):
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    if company_dir.exists():
        shutil.rmtree(str(company_dir))
    # Limpiar sesiones
    sessions_dir = DATA_DIR / "sessions"
    if sessions_dir.exists():
        for f in sessions_dir.glob(f"{company_id}_*"):
            f.unlink()
    # Limpiar escenarios
    scenarios_dir = DATA_DIR / "scenarios"
    if scenarios_dir.exists():
        for f in scenarios_dir.glob(f"{company_id}_*"):
            f.unlink()
    return {"status": "deleted"}

# ---------------------------------------------------------------------------
# Endpoints: Chat / Entrevista
# ---------------------------------------------------------------------------
@app.post("/api/chat/interview")
async def chat_interview(data: ChatMessage):
    company_id = _sanitize_id(data.company_id)
    company_dir = DATA_DIR / "companies" / company_id
    if not company_dir.exists():
        raise HTTPException(404, "Empresa no encontrada")

    _check_rate_limit(f"chat_{company_id}")

    company = load_json(company_dir / "company.json")

    # --- Cargar estado persistido de la entrevista ---
    sessions_dir = DATA_DIR / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    interview_state_path = company_dir / "interview_state.json"
    persisted_state = load_json(interview_state_path, {"collected_data": {}, "topics_covered": []})

    # Inicializar InterviewManager con datos persistidos (NUNCA re-parsear sesiones)
    im = InterviewManager(
        company_data=company,
        persisted_data=persisted_state.get("collected_data", {}),
        persisted_topics=persisted_state.get("topics_covered", [])
    )

    # Extraer datos del mensaje actual ANTES de generar el prompt
    extracted = im.extract_data_from_response(data.message, "")

    # Generar system prompt contextualizado con el progreso real
    system_prompt = im.generate_system_prompt()

    session_id = data.session_id or str(uuid.uuid4())[:8]
    session_id = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:64]
    session_path = sessions_dir / f"{company_id}_{session_id}.json"
    session = load_json(session_path, {"id": session_id, "company_id": company_id, "type": "interview", "messages": [], "created_at": datetime.now().isoformat()})

    agent = get_agent("financial_interviewer")
    if not agent:
        raise HTTPException(500, "Agente entrevistador no configurado")

    # Construir mensajes para el LLM (limitar contexto a últimos 12 mensajes para eficiencia)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in session.get("messages", [])[-12:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": data.message})

    response = call_ollama_chat(
        model=agent.get("model", "llama3.2:3b"),
        messages=messages,
        temperature=agent.get("temperature", 0.7)
    )

    session["messages"].append({"role": "user", "content": data.message, "timestamp": datetime.now().isoformat()})
    session["messages"].append({"role": "assistant", "content": response, "timestamp": datetime.now().isoformat()})
    save_json(session_path, session)

    if company.get("status") == "pending":
        company["status"] = "interviewing"
        company["updated_at"] = datetime.now().isoformat()
        save_json(company_dir / "company.json", company)

    # Extraer datos también de la respuesta del LLM (puede contener datos implícitos)
    im.extract_data_from_response(response, "")

    # --- PERSISTIR estado de la entrevista (NUNCA retrocede) ---
    # Merge: solo agregar nuevos datos, nunca borrar existentes
    new_state = {
        "collected_data": im.collected_data,
        "topics_covered": list(set(im.topics_covered)),  # Deduplicar
        "last_updated": datetime.now().isoformat(),
    }
    save_json(interview_state_path, new_state)

    # Calcular progreso basado en datos recopilados
    progress = im.get_interview_progress()

    # --- Detectar si el usuario acepta generar el cashflow ---
    trigger_generation = False
    msg_lower = data.message.lower().strip()
    acceptance_phrases = [
        "sí", "si", "dale", "genera", "generar", "hazlo", "ok", "listo",
        "sí, genera", "si, genera", "genera el cashflow", "vamos",
        "perfecto", "adelante", "procede", "sí por favor",
    ]
    if progress.get("is_complete", False) or progress.get("has_enough_data", False):
        if any(phrase in msg_lower for phrase in acceptance_phrases):
            trigger_generation = True

    return {
        "response": response,
        "session_id": session_id,
        "company_status": company.get("status"),
        "progress": progress,
        "extracted_data": extracted,
        "has_enough_data": progress.get("has_enough_data", False),
        "is_complete": progress.get("is_complete", False),
        "trigger_generation": trigger_generation,
    }

# ---------------------------------------------------------------------------
# Endpoints: Generación de Flujo de Caja
# ---------------------------------------------------------------------------
@app.post("/api/companies/{company_id}/generate-cashflow")
async def generate_cashflow(company_id: str, background_tasks: BackgroundTasks):
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    if not company_dir.exists():
        raise HTTPException(404, "Empresa no encontrada")

    _check_rate_limit(f"gen_{company_id}", max_requests=5, window=120)

    task_id = str(uuid.uuid4())[:8]
    _generation_status[task_id] = {"status": "generating", "progress": 0, "error": None, "step": "Iniciando..."}

    background_tasks.add_task(_generate_cashflow_task, company_id, task_id)
    return {"task_id": task_id, "status": "generating"}

def _generate_cashflow_task(company_id: str, task_id: str):
    try:
        company_dir = DATA_DIR / "companies" / company_id
        company = load_json(company_dir / "company.json")

        _generation_status[task_id]["step"] = "Recopilando información de entrevistas..."
        _generation_status[task_id]["progress"] = 10

        sessions_dir = DATA_DIR / "sessions"
        all_messages = []
        for f in sorted(sessions_dir.glob(f"{company_id}_*.json")):
            session = load_json(f)
            for msg in session.get("messages", []):
                all_messages.append(f"{msg['role'].upper()}: {msg['content']}")

        conversation_text = "\n".join(all_messages)
        if len(conversation_text) > 50000:
            conversation_text = conversation_text[:50000] + "\n[... conversación truncada por longitud ...]"

        _generation_status[task_id]["progress"] = 25
        _generation_status[task_id]["step"] = "Preparando análisis financiero..."

        agent = get_agent("cashflow_analyst")
        if not agent:
            _generation_status[task_id] = {"status": "error", "progress": 0, "error": "Agente analista no configurado", "step": "Error"}
            return

        system_prompt = get_prompt("cashflow_analyst")
        if agent.get("system_prompt"):
            system_prompt = agent["system_prompt"]

        user_message = f"""Basándote en la siguiente conversación con el dueño de la empresa "{company.get('name', 'Sin nombre')}" del sector "{company.get('sector', 'No especificado')}",
construye un flujo de caja mensual proyectado a 12 meses.

CONVERSACIÓN COMPLETA:
{conversation_text}

Genera el JSON del flujo de caja siguiendo exactamente el formato indicado en tus instrucciones."""

        _generation_status[task_id]["progress"] = 40
        _generation_status[task_id]["step"] = "La IA está analizando los datos financieros..."

        response = call_ollama(
            model=agent.get("model", "llama3.1:8b"),
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=agent.get("temperature", 0.3),
            timeout=_get_timeout("analysis")
        )

        _generation_status[task_id]["progress"] = 75
        _generation_status[task_id]["step"] = "Procesando resultados..."

        cashflow_data = _extract_json_from_llm(response)
        if not cashflow_data:
            # Intentar extraer datos de la respuesta como texto estructurado
            logger.warning(f"No se pudo extraer JSON del LLM para {company_id}. Respuesta: {response[:200]}")
            _generation_status[task_id] = {"status": "error", "progress": 0, "error": "No se pudo generar el flujo de caja. La IA no devolvió datos en formato correcto. Intenta proporcionar más información en la entrevista.", "step": "Error"}
            return

        _generation_status[task_id]["progress"] = 85
        _generation_status[task_id]["step"] = "Normalizando y validando datos..."

        cashflow_data = normalize_cashflow(cashflow_data)
        
        # Validar que se generaron meses
        num_months = len(cashflow_data.get("months", []))
        if num_months == 0:
            logger.warning(f"Cashflow generado sin meses para {company_id}. JSON extraído: {json.dumps(cashflow_data, default=str)[:500]}")
            _generation_status[task_id] = {"status": "error", "progress": 0, "error": "La IA generó un flujo de caja vacío (0 meses). Esto puede ocurrir si no hay suficiente información. Vuelve a la entrevista y proporciona más detalles sobre ingresos y gastos mensuales.", "step": "Error"}
            return
        
        # Validar que los totales no sean todos 0 (indicaría datos corruptos)
        total_income = cashflow_data.get("summary", {}).get("total_income", 0)
        total_expenses = cashflow_data.get("summary", {}).get("total_expenses", 0)
        if total_income == 0 and total_expenses == 0 and num_months > 0:
            logger.warning(f"Cashflow con {num_months} meses pero totales en 0 para {company_id}")
            # No es un error fatal, pero loguear para debug

        cashflow_data["id"] = str(uuid.uuid4())[:8]
        cashflow_data["company_id"] = company_id
        cashflow_data["created_at"] = datetime.now().isoformat()
        save_json(company_dir / "cashflow.json", cashflow_data)
        logger.info(f"Flujo de caja generado: {num_months} meses, ingresos={total_income:,.0f}, gastos={total_expenses:,.0f} para empresa {company_id}")

        company["status"] = "complete"
        company["updated_at"] = datetime.now().isoformat()
        save_json(company_dir / "company.json", company)

        _generation_status[task_id] = {"status": "done", "progress": 100, "error": None, "step": "Completado", "months_generated": num_months}

    except Exception as e:
        logger.error(f"Error generando flujo de caja para {company_id}: {type(e).__name__}")
        _generation_status[task_id] = {"status": "error", "progress": 0, "error": str(e), "step": "Error"}

@app.get("/api/generation/{task_id}/progress")
async def get_generation_progress(task_id: str):
    task_id = re.sub(r"[^a-zA-Z0-9_-]", "", task_id)[:64]
    return _generation_status.get(task_id, {"status": "unknown", "progress": 0, "error": "Tarea no encontrada", "step": ""})

@app.get("/api/companies/{company_id}/cashflow")
async def get_cashflow(company_id: str):
    company_id = _sanitize_id(company_id)
    path = DATA_DIR / "companies" / company_id / "cashflow.json"
    if not path.exists():
        raise HTTPException(404, "Flujo de caja no encontrado. Genera uno primero.")
    data = load_json(path)
    data = normalize_cashflow(data)
    # Sanitizar inf/nan antes de serializar a JSON
    data = _sanitize_dict(data)
    return data

# ---------------------------------------------------------------------------
# Endpoints: Edición manual de meses del flujo de caja
# ---------------------------------------------------------------------------
@app.put("/api/companies/{company_id}/cashflow/months/{month_index}")
async def update_month(company_id: str, month_index: int, month_data: MonthPayload):
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja para editar.")

    cashflow = load_json(cashflow_path)
    months = cashflow.get("months", [])

    if month_index < 0 or month_index >= len(months):
        raise HTTPException(400, f"Índice de mes inválido: {month_index}. Rango válido: 0-{len(months)-1}")

    existing = months[month_index]
    if month_data.month:
        existing["month"] = month_data.month
    if month_data.label:
        existing["label"] = month_data.label
    if month_data.income is not None:
        existing["income"] = month_data.income
    if month_data.expenses is not None:
        existing["expenses"] = month_data.expenses

    months[month_index] = existing
    cashflow["months"] = months
    cashflow = normalize_cashflow(cashflow)
    save_json(cashflow_path, cashflow)

    return cashflow

@app.post("/api/companies/{company_id}/cashflow/months")
async def add_month(company_id: str, month_data: MonthPayload):
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja. Genera uno primero.")

    cashflow = load_json(cashflow_path)
    months = cashflow.get("months", [])

    if len(months) >= MAX_MONTHS:
        raise HTTPException(400, f"No se pueden agregar más de {MAX_MONTHS} meses.")

    new_month = {
        "month": month_data.month or "",
        "label": month_data.label or "",
        "income": month_data.income or {"sales": 0, "other_income": 0, "total": 0},
        "expenses": month_data.expenses or {"variable_costs": 0, "fixed_costs": 0, "variable_expenses": 0, "debt_payments": 0, "taxes": 0, "investments": 0, "total": 0}
    }
    months.append(new_month)
    cashflow["months"] = months
    cashflow = normalize_cashflow(cashflow)
    save_json(cashflow_path, cashflow)

    return cashflow

@app.delete("/api/companies/{company_id}/cashflow/months/{month_index}")
async def delete_month(company_id: str, month_index: int):
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja.")

    cashflow = load_json(cashflow_path)
    months = cashflow.get("months", [])

    if month_index < 0 or month_index >= len(months):
        raise HTTPException(400, f"Índice de mes inválido: {month_index}")

    months.pop(month_index)
    cashflow["months"] = months
    cashflow = normalize_cashflow(cashflow)
    save_json(cashflow_path, cashflow)

    return cashflow

# ---------------------------------------------------------------------------
# Endpoints: Simulación de Escenarios (OPTIMIZADA)
# ---------------------------------------------------------------------------
@app.post("/api/companies/{company_id}/simulate")
async def simulate_scenario(company_id: str, data: ScenarioRequest, background_tasks: BackgroundTasks):
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja base para simular.")

    _check_rate_limit(f"sim_{company_id}", max_requests=10, window=120)

    task_id = str(uuid.uuid4())[:8]
    _generation_status[task_id] = {
        "status": "generating",
        "progress": 0,
        "error": None,
        "step": "Iniciando simulación...",
        "mode": "local" if data.params else "ai"
    }

    if data.params:
        # Simulación local rápida (sin LLM)
        background_tasks.add_task(_simulate_local_task, company_id, data.instruction, data.params, task_id)
    else:
        # Simulación con IA (para instrucciones complejas en lenguaje natural)
        background_tasks.add_task(_simulate_ai_task, company_id, data.instruction, task_id)

    return {"task_id": task_id, "status": "generating"}


def _simulate_local_task(company_id: str, instruction: str, params: dict, task_id: str):
    """Simulación local rápida sin LLM."""
    try:
        company_dir = DATA_DIR / "companies" / company_id
        cashflow = load_json(company_dir / "cashflow.json")

        _generation_status[task_id]["progress"] = 10
        _generation_status[task_id]["step"] = "Cargando flujo de caja base..."

        # Ejecutar simulación matemática local
        scenario_data = simulate_local(cashflow, params, task_id)

        # Guardar escenario
        scenario_id = str(uuid.uuid4())[:8]
        scenario_data["id"] = scenario_id
        scenario_data["company_id"] = company_id
        scenario_data["instruction"] = instruction
        scenario_data["simulation_mode"] = "local"
        scenario_data["created_at"] = datetime.now().isoformat()

        scenarios_dir = DATA_DIR / "scenarios"
        scenarios_dir.mkdir(parents=True, exist_ok=True)
        save_json(scenarios_dir / f"{company_id}_{scenario_id}.json", scenario_data)

        _generation_status[task_id] = {
            "status": "done",
            "progress": 100,
            "error": None,
            "scenario_id": scenario_id,
            "step": "Simulación completada",
            "mode": "local"
        }
        logger.info(f"Simulación local completada para empresa {company_id}")

        # Limpiar checkpoint
        checkpoint_path = DATA_DIR / "checkpoints" / f"{task_id}.json"
        if checkpoint_path.exists():
            checkpoint_path.unlink()

    except Exception as e:
        logger.error(f"Error en simulación local para {company_id}: {type(e).__name__}: {e}")
        _generation_status[task_id] = {"status": "error", "progress": 0, "error": str(e), "step": "Error"}


def _simulate_ai_task(company_id: str, instruction: str, task_id: str):
    """Simulación con IA para instrucciones complejas en lenguaje natural."""
    try:
        company_dir = DATA_DIR / "companies" / company_id
        cashflow = load_json(company_dir / "cashflow.json")

        _generation_status[task_id]["progress"] = 15
        _generation_status[task_id]["step"] = "Preparando datos para la IA..."

        agent = get_agent("scenario_simulator")
        if not agent:
            _generation_status[task_id] = {"status": "error", "progress": 0, "error": "Agente simulador no configurado", "step": "Error"}
            return

        system_prompt = get_prompt("scenario_simulator")
        if agent.get("system_prompt"):
            system_prompt = agent["system_prompt"]

        # OPTIMIZACIÓN: Enviar solo un resumen compacto del cashflow, no el JSON completo
        months_compact = []
        for m in cashflow.get("months", []):
            months_compact.append({
                "month": m.get("month", ""),
                "label": m.get("label", ""),
                "income": m.get("income", {}),
                "expenses": m.get("expenses", {}),
                "net_flow": m.get("net_flow", 0),
                "cumulative_balance": m.get("cumulative_balance", 0)
            })

        cf_compact = {
            "months": months_compact,
            "summary": cashflow.get("summary", {})
        }

        user_message = f"""FLUJO DE CAJA ACTUAL:
{json.dumps(cf_compact, ensure_ascii=False)}

INSTRUCCIÓN DEL USUARIO:
{instruction}

Aplica los cambios solicitados y devuelve el flujo de caja completo actualizado en formato JSON."""

        _generation_status[task_id]["progress"] = 30
        _generation_status[task_id]["step"] = "La IA está calculando el escenario..."

        # Guardar checkpoint antes de llamar al LLM
        _save_simulation_checkpoint(task_id, cashflow, 0, len(cashflow.get("months", [])))

        response = call_ollama(
            model=agent.get("model", "llama3.1:8b"),
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=agent.get("temperature", 0.4),
            timeout=_get_timeout("simulation")
        )

        _generation_status[task_id]["progress"] = 75
        _generation_status[task_id]["step"] = "Procesando respuesta de la IA..."

        scenario_data = _extract_json_from_llm(response)
        if not scenario_data:
            _generation_status[task_id] = {"status": "error", "progress": 0, "error": "La IA no pudo generar una simulación válida. Intenta con una instrucción más específica.", "step": "Error"}
            return

        _generation_status[task_id]["progress"] = 85
        _generation_status[task_id]["step"] = "Normalizando resultados..."

        # Normalizar el resultado
        scenario_data = normalize_cashflow(scenario_data)

        # Generar alertas si no las tiene
        if "alerts" not in scenario_data:
            alerts = []
            for i, m in enumerate(scenario_data.get("months", [])):
                if m.get("cumulative_balance", 0) < 0:
                    alerts.append({
                        "month": m.get("label", m.get("month", f"Mes {i+1}")),
                        "type": "danger",
                        "message": f"Saldo acumulado negativo: ${m['cumulative_balance']:,.0f}"
                    })
            scenario_data["alerts"] = alerts

        # Guardar escenario
        scenario_id = str(uuid.uuid4())[:8]
        scenario_data["id"] = scenario_id
        scenario_data["company_id"] = company_id
        scenario_data["instruction"] = instruction
        scenario_data["simulation_mode"] = "ai"
        scenario_data["created_at"] = datetime.now().isoformat()

        scenarios_dir = DATA_DIR / "scenarios"
        scenarios_dir.mkdir(parents=True, exist_ok=True)
        save_json(scenarios_dir / f"{company_id}_{scenario_id}.json", scenario_data)

        _generation_status[task_id] = {
            "status": "done",
            "progress": 100,
            "error": None,
            "scenario_id": scenario_id,
            "step": "Simulación completada",
            "mode": "ai"
        }
        logger.info(f"Simulación AI completada para empresa {company_id}")

        # Limpiar checkpoint
        checkpoint_path = DATA_DIR / "checkpoints" / f"{task_id}.json"
        if checkpoint_path.exists():
            checkpoint_path.unlink()

    except Exception as e:
        logger.error(f"Error en simulación AI para {company_id}: {type(e).__name__}: {e}")
        _generation_status[task_id] = {"status": "error", "progress": 0, "error": str(e), "step": "Error"}


@app.get("/api/companies/{company_id}/scenarios")
async def list_scenarios(company_id: str):
    company_id = _sanitize_id(company_id)
    scenarios_dir = DATA_DIR / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    scenarios = []
    for f in sorted(scenarios_dir.glob(f"{company_id}_*.json")):
        scenarios.append(load_json(f))
    return {"scenarios": scenarios}

@app.get("/api/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str):
    scenario_id = _sanitize_id(scenario_id)
    scenarios_dir = DATA_DIR / "scenarios"
    for f in scenarios_dir.glob(f"*_{scenario_id}.json"):
        return load_json(f)
    raise HTTPException(404, "Escenario no encontrado")

@app.delete("/api/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str):
    scenario_id = _sanitize_id(scenario_id)
    scenarios_dir = DATA_DIR / "scenarios"
    for f in scenarios_dir.glob(f"*_{scenario_id}.json"):
        f.unlink()
        return {"status": "deleted"}
    raise HTTPException(404, "Escenario no encontrado")

# ---------------------------------------------------------------------------
# Endpoints: Chat de Simulación (conversacional)
# ---------------------------------------------------------------------------
@app.post("/api/chat/simulate")
async def chat_simulate(data: ChatMessage):
    company_id = _sanitize_id(data.company_id)
    company_dir = DATA_DIR / "companies" / company_id
    if not company_dir.exists():
        raise HTTPException(404, "Empresa no encontrada")

    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "Primero genera un flujo de caja base.")

    _check_rate_limit(f"simchat_{company_id}")

    cashflow = load_json(cashflow_path)

    session_id = data.session_id or f"sim_{str(uuid.uuid4())[:8]}"
    session_id = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:64]
    session_path = DATA_DIR / "sessions" / f"{company_id}_{session_id}.json"
    session = load_json(session_path, {"id": session_id, "company_id": company_id, "type": "simulation", "messages": [], "created_at": datetime.now().isoformat()})

    agent = get_agent("scenario_simulator")
    if not agent:
        raise HTTPException(500, "Agente simulador no configurado")

    system_prompt = get_prompt("scenario_simulator")

    cf_summary = f"La empresa tiene un flujo de caja proyectado a {len(cashflow.get('months', []))} meses. "
    summary = cashflow.get("summary", {})
    cf_summary += f"Ingresos totales: ${summary.get('total_income', 0):,.0f}, Gastos totales: ${summary.get('total_expenses', 0):,.0f}, Flujo neto: ${summary.get('net_cashflow', 0):,.0f}."

    messages = [{"role": "system", "content": system_prompt + "\n\nCONTEXTO: " + cf_summary}]
    for msg in session.get("messages", []):
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": data.message})

    response = call_ollama_chat(
        model=agent.get("model", "llama3.1:8b"),
        messages=messages,
        temperature=agent.get("temperature", 0.4),
        timeout=_get_timeout("simulation")
    )

    session["messages"].append({"role": "user", "content": data.message, "timestamp": datetime.now().isoformat()})
    session["messages"].append({"role": "assistant", "content": response, "timestamp": datetime.now().isoformat()})
    save_json(session_path, session)

    scenario_data = _extract_json_from_llm(response)
    has_scenario = scenario_data is not None and "months" in (scenario_data or {})

    return {
        "response": response,
        "session_id": session_id,
        "has_scenario": has_scenario,
        "scenario_data": scenario_data if has_scenario else None
    }

# ---------------------------------------------------------------------------
# Endpoints: Exportación (con nombres de archivo sanitizados)
# ---------------------------------------------------------------------------
@app.get("/api/companies/{company_id}/export/excel")
async def export_excel(company_id: str):
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja para exportar.")

    cashflow = load_json(cashflow_path)
    company = load_json(company_dir / "company.json")

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        raise HTTPException(500, "openpyxl no está instalado.")

    wb = Workbook()

    # --- Hoja 1: Flujo de Caja ---
    ws = wb.active
    ws.title = "Flujo de Caja"

    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="0D3DA6", end_color="0D3DA6", fill_type="solid")
    money_format = '#,##0'
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin")
    )

    ws.merge_cells("A1:H1")
    ws["A1"] = f"Flujo de Caja — {company.get('name', 'Empresa')}"
    ws["A1"].font = Font(name="Calibri", bold=True, size=14, color="0D3DA6")

    ws.merge_cells("A2:H2")
    ws["A2"] = f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws["A2"].font = Font(name="Calibri", size=10, color="666666")

    headers = ["Mes", "Ingresos", "Costos Variables", "Costos Fijos", "Gastos Variables", "Deudas", "Impuestos", "Flujo Neto", "Saldo Acumulado"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    for i, month in enumerate(cashflow.get("months", []), 5):
        expenses = month.get("expenses", {})
        income = month.get("income", {})
        ws.cell(row=i, column=1, value=month.get("label", month.get("month", ""))).border = thin_border
        ws.cell(row=i, column=2, value=income.get("total", 0)).number_format = money_format
        ws.cell(row=i, column=3, value=expenses.get("variable_costs", 0)).number_format = money_format
        ws.cell(row=i, column=4, value=expenses.get("fixed_costs", 0)).number_format = money_format
        ws.cell(row=i, column=5, value=expenses.get("variable_expenses", 0)).number_format = money_format
        ws.cell(row=i, column=6, value=expenses.get("debt_payments", 0)).number_format = money_format
        ws.cell(row=i, column=7, value=expenses.get("taxes", 0)).number_format = money_format
        ws.cell(row=i, column=8, value=month.get("net_flow", 0)).number_format = money_format
        ws.cell(row=i, column=9, value=month.get("cumulative_balance", 0)).number_format = money_format
        for col in range(1, 10):
            ws.cell(row=i, column=col).border = thin_border

    for col in range(1, 10):
        ws.column_dimensions[chr(64 + col)].width = 18

    # --- Hoja 2: Resumen ---
    ws2 = wb.create_sheet("Resumen")
    summary = cashflow.get("summary", {})
    ws2["A1"] = "Resumen Financiero"
    ws2["A1"].font = Font(name="Calibri", bold=True, size=14, color="0D3DA6")

    summary_data = [
        ("Ingresos Totales", summary.get("total_income", 0)),
        ("Gastos Totales", summary.get("total_expenses", 0)),
        ("Flujo Neto", summary.get("net_cashflow", 0)),
        ("Promedio Mensual", summary.get("average_monthly_balance", 0)),
    ]
    for i, (label, value) in enumerate(summary_data, 3):
        ws2.cell(row=i, column=1, value=label).font = Font(bold=True)
        ws2.cell(row=i, column=2, value=value).number_format = money_format

    alerts = cashflow.get("alerts", [])
    if alerts:
        ws2.cell(row=8, column=1, value="Alertas").font = Font(bold=True, size=12, color="DC2626")
        for i, alert in enumerate(alerts, 9):
            ws2.cell(row=i, column=1, value=alert.get("month", ""))
            ws2.cell(row=i, column=2, value=alert.get("message", ""))

    recs = cashflow.get("recommendations", [])
    if recs:
        row = 9 + len(alerts) + 1
        ws2.cell(row=row, column=1, value="Recomendaciones").font = Font(bold=True, size=12, color="3DAE2B")
        for i, rec in enumerate(recs, row + 1):
            ws2.cell(row=i, column=1, value=f"• {rec}")

    exports_dir = DATA_DIR / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_filename(company.get("name", "empresa"))
    filename = f"flujo_caja_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = exports_dir / filename
    wb.save(str(filepath))

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.get("/api/companies/{company_id}/export/csv")
async def export_csv(company_id: str):
    company_id = _sanitize_id(company_id)
    company_dir = DATA_DIR / "companies" / company_id
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja para exportar.")

    cashflow = load_json(cashflow_path)
    company = load_json(company_dir / "company.json")

    import csv

    exports_dir = DATA_DIR / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_filename(company.get("name", "empresa"))
    filename = f"flujo_caja_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = exports_dir / filename

    with open(str(filepath), "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Mes", "Ingresos", "Costos Variables", "Costos Fijos", "Gastos Variables", "Deudas", "Impuestos", "Flujo Neto", "Saldo Acumulado"])
        for month in cashflow.get("months", []):
            expenses = month.get("expenses", {})
            income = month.get("income", {})
            writer.writerow([
                month.get("label", month.get("month", "")),
                income.get("total", 0),
                expenses.get("variable_costs", 0),
                expenses.get("fixed_costs", 0),
                expenses.get("variable_expenses", 0),
                expenses.get("debt_payments", 0),
                expenses.get("taxes", 0),
                month.get("net_flow", 0),
                month.get("cumulative_balance", 0)
            ])

    return FileResponse(path=str(filepath), filename=filename, media_type="text/csv")


# Exportar escenario específico
@app.get("/api/scenarios/{scenario_id}/export/csv")
async def export_scenario_csv(scenario_id: str):
    scenario_id = _sanitize_id(scenario_id)
    scenarios_dir = DATA_DIR / "scenarios"
    scenario_data = None
    for f in scenarios_dir.glob(f"*_{scenario_id}.json"):
        scenario_data = load_json(f)
        break
    if not scenario_data:
        raise HTTPException(404, "Escenario no encontrado")

    import csv

    exports_dir = DATA_DIR / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    scenario_name = _sanitize_filename(scenario_data.get("scenario_name", "escenario"))
    filename = f"escenario_{scenario_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = exports_dir / filename

    with open(str(filepath), "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Mes", "Ingresos", "Costos Variables", "Costos Fijos", "Gastos Variables", "Deudas", "Impuestos", "Flujo Neto", "Saldo Acumulado"])
        for month in scenario_data.get("months", []):
            expenses = month.get("expenses", {})
            income = month.get("income", {})
            writer.writerow([
                month.get("label", month.get("month", "")),
                income.get("total", 0),
                expenses.get("variable_costs", 0),
                expenses.get("fixed_costs", 0),
                expenses.get("variable_expenses", 0),
                expenses.get("debt_payments", 0),
                expenses.get("taxes", 0),
                month.get("net_flow", 0),
                month.get("cumulative_balance", 0)
            ])

    return FileResponse(path=str(filepath), filename=filename, media_type="text/csv")


@app.get("/api/scenarios/{scenario_id}/export/excel")
async def export_scenario_excel(scenario_id: str):
    scenario_id = _sanitize_id(scenario_id)
    scenarios_dir = DATA_DIR / "scenarios"
    scenario_data = None
    for f in scenarios_dir.glob(f"*_{scenario_id}.json"):
        scenario_data = load_json(f)
        break
    if not scenario_data:
        raise HTTPException(404, "Escenario no encontrado")

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        raise HTTPException(500, "openpyxl no está instalado.")

    wb = Workbook()
    ws = wb.active
    ws.title = "Escenario"

    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="0D3DA6", end_color="0D3DA6", fill_type="solid")
    money_format = '#,##0'
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )

    ws.merge_cells("A1:I1")
    ws["A1"] = scenario_data.get("scenario_name", "Escenario Simulado")
    ws["A1"].font = Font(name="Calibri", bold=True, size=14, color="0D3DA6")

    ws.merge_cells("A2:I2")
    ws["A2"] = f"Generado: {scenario_data.get('created_at', datetime.now().isoformat())[:10]}"
    ws["A2"].font = Font(name="Calibri", size=10, color="666666")

    headers = ["Mes", "Ingresos", "Costos Variables", "Costos Fijos", "Gastos Variables", "Deudas", "Impuestos", "Flujo Neto", "Saldo Acumulado"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    for i, month in enumerate(scenario_data.get("months", []), 5):
        expenses = month.get("expenses", {})
        income = month.get("income", {})
        ws.cell(row=i, column=1, value=month.get("label", month.get("month", ""))).border = thin_border
        ws.cell(row=i, column=2, value=income.get("total", 0)).number_format = money_format
        ws.cell(row=i, column=3, value=expenses.get("variable_costs", 0)).number_format = money_format
        ws.cell(row=i, column=4, value=expenses.get("fixed_costs", 0)).number_format = money_format
        ws.cell(row=i, column=5, value=expenses.get("variable_expenses", 0)).number_format = money_format
        ws.cell(row=i, column=6, value=expenses.get("debt_payments", 0)).number_format = money_format
        ws.cell(row=i, column=7, value=expenses.get("taxes", 0)).number_format = money_format
        ws.cell(row=i, column=8, value=month.get("net_flow", 0)).number_format = money_format
        ws.cell(row=i, column=9, value=month.get("cumulative_balance", 0)).number_format = money_format
        for col in range(1, 10):
            ws.cell(row=i, column=col).border = thin_border

    for col in range(1, 10):
        ws.column_dimensions[chr(64 + col)].width = 18

    # Hoja de cambios aplicados
    ws2 = wb.create_sheet("Cambios")
    ws2["A1"] = "Cambios Aplicados"
    ws2["A1"].font = Font(name="Calibri", bold=True, size=14, color="0D3DA6")
    for i, change in enumerate(scenario_data.get("changes_applied", []), 3):
        ws2.cell(row=i, column=1, value=f"• {change}")

    impact = scenario_data.get("impact_summary", {})
    if isinstance(impact, dict):
        ws2.cell(row=len(scenario_data.get("changes_applied", [])) + 5, column=1, value="Impacto").font = Font(bold=True)
        ws2.cell(row=len(scenario_data.get("changes_applied", [])) + 6, column=1, value=impact.get("description", ""))

    exports_dir = DATA_DIR / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    scenario_name = _sanitize_filename(scenario_data.get("scenario_name", "escenario"))
    filename = f"escenario_{scenario_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = exports_dir / filename
    wb.save(str(filepath))

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------------------------------------------------------------------------
# Endpoints: Agentes
# ---------------------------------------------------------------------------
@app.get("/api/agents")
async def list_agents():
    """Lista agentes con system_prompt real desde disco y contenido de skills."""
    agents_data = get_agents()

    # Enriquecer cada agente con el prompt real y skills
    for agent in agents_data.get("agents", []):
        agent_id = agent.get("id", "")

        # 1. Leer system_prompt real desde disco
        prompt_file = DATA_DIR / "prompts" / "system" / f"{agent_id}.md"
        if prompt_file.exists():
            agent["system_prompt"] = prompt_file.read_text(encoding="utf-8")
        elif not agent.get("system_prompt"):
            default_prompt = DEFAULTS_DIR / "prompts" / f"{agent_id}.md"
            if default_prompt.exists():
                agent["system_prompt"] = default_prompt.read_text(encoding="utf-8")

        # 2. Leer contenido de cada skill file
        skill_contents = {}
        for skill_name in agent.get("skills", []):
            skill_paths = [
                DATA_DIR / "prompts" / "skills" / f"{skill_name}.md",
                DEFAULTS_DIR / "prompts" / "skills" / f"{skill_name}.md",
            ]
            for sp in skill_paths:
                if sp.exists():
                    skill_contents[skill_name] = sp.read_text(encoding="utf-8")
                    break
            else:
                skill_contents[skill_name] = ""

        agent["skill_contents"] = skill_contents

    return agents_data

@app.get("/api/agents/{agent_id}")
async def get_agent_endpoint(agent_id: str):
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agente no encontrado")
    return agent

@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, config: AgentConfigUpdate):
    agent_id = _sanitize_id(agent_id)
    agents_data = get_agents()
    for i, a in enumerate(agents_data.get("agents", [])):
        if a["id"] == agent_id:
            if config.model is not None:
                old_model = agents_data["agents"][i].get("model", "")
                agents_data["agents"][i]["model"] = config.model
            if config.temperature is not None:
                agents_data["agents"][i]["temperature"] = config.temperature
            if config.system_prompt is not None:
                # Guardar prompt en disco (como brand-assistant)
                prompt_dir = DATA_DIR / "prompts" / "system"
                prompt_dir.mkdir(parents=True, exist_ok=True)
                prompt_file = prompt_dir / f"{agent_id}.md"
                prompt_file.write_text(config.system_prompt, encoding="utf-8")
                agents_data["agents"][i]["system_prompt"] = config.system_prompt
                logger.info(f"[AGENTS] Prompt de '{agent_id}' guardado en disco ({len(config.system_prompt)} chars)")
            agents_data["agents"][i]["updated_at"] = datetime.now().isoformat()
            save_json(DATA_DIR / "agents" / "agents.json", agents_data)

            model = config.model or agents_data["agents"][i].get("model")
            if model and not _is_model_available(model):
                _start_pull_background(model)
                return {**agents_data["agents"][i], "pull_status": {"status": "queued", "model": model}}
            return agents_data["agents"][i]
    raise HTTPException(404, "Agente no encontrado")

@app.put("/api/agents/{agent_id}/skills/{skill_name}")
async def update_skill_content(agent_id: str, skill_name: str, request: Request):
    """Guarda el contenido editado de un skill file."""
    body = await request.json()
    content = body.get("content", "")
    skills_dir = DATA_DIR / "prompts" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skills_dir / f"{re.sub(r'[^a-zA-Z0-9_-]', '', skill_name)}.md"
    skill_file.write_text(content, encoding="utf-8")
    logger.info(f"[SKILLS] Skill '{skill_name}' guardado ({len(content)} chars)")
    return {"ok": True, "skill": skill_name, "agent_id": agent_id, "size": len(content)}

@app.get("/api/audit")
async def get_audit_log():
    """Retorna el log de auditoría con estimación de tokens y ahorro."""
    audit_dir = DATA_DIR / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for audit_file in sorted(audit_dir.glob("*.jsonl"), reverse=True)[:3]:
        for line in audit_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return {"entries": entries[:100], "total": len(entries)}

@app.get("/api/models/status")
async def models_status():
    return {"pull_status": _pull_status}

@app.get("/api/models/available")
async def available_models():
    try:
        r = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return {"models": [m["name"] for m in r.json().get("models", [])]}
    except Exception:
        return {"models": []}

# ---------------------------------------------------------------------------
# Endpoints: Token Usage — protegido con lock
# ---------------------------------------------------------------------------
_token_usage_file = DATA_DIR / "token_usage.json"
_token_usage_lock = threading.Lock()

def _load_token_usage():
    if _token_usage_file.exists():
        return load_json(_token_usage_file)
    return {"stats": {"total_tokens": 0, "total_requests": 0, "by_agent": {}, "active_sessions": 0}, "recent_sessions": []}

def _save_token_usage(data):
    save_json(_token_usage_file, data)

def track_token_usage(agent_id: str, tokens: int):
    """Llamar después de cada llamada a Ollama para trackear tokens (thread-safe)."""
    with _token_usage_lock:
        data = _load_token_usage()
        data["stats"]["total_tokens"] = data["stats"].get("total_tokens", 0) + tokens
        data["stats"]["total_requests"] = data["stats"].get("total_requests", 0) + 1
        if agent_id not in data["stats"].get("by_agent", {}):
            data["stats"]["by_agent"][agent_id] = {"tokens": 0, "requests": 0}
        data["stats"]["by_agent"][agent_id]["tokens"] += tokens
        data["stats"]["by_agent"][agent_id]["requests"] += 1
        data["recent_sessions"].insert(0, {
            "agent": agent_id,
            "tokens": tokens,
            "timestamp": datetime.now().isoformat()
        })
        data["recent_sessions"] = data["recent_sessions"][:100]  # Keep last 100
    _save_token_usage(data)

@app.get("/api/token-usage")
async def get_token_usage():
    return _load_token_usage()

@app.delete("/api/token-usage")
async def reset_token_usage():
    _save_token_usage({"stats": {"total_tokens": 0, "total_requests": 0, "by_agent": {}, "active_sessions": 0}, "recent_sessions": []})
    return {"status": "ok"}

@app.put("/api/agents")
async def update_agents_bulk(request: Request):
    body = await request.json()
    updates = body.get("agents", [])
    agents_data = get_agents()
    for update in updates:
        for i, a in enumerate(agents_data.get("agents", [])):
            if a["id"] == update.get("id"):
                if "model" in update:
                    agents_data["agents"][i]["model"] = update["model"]
                if "temperature" in update:
                    agents_data["agents"][i]["temperature"] = update["temperature"]
                if "system_prompt" in update:
                    agents_data["agents"][i]["system_prompt"] = update["system_prompt"]
                agents_data["agents"][i]["updated_at"] = datetime.now().isoformat()
                break
    save_json(DATA_DIR / "agents" / "agents.json", agents_data)
    return {"status": "ok", "agents_updated": len(updates)}

# ---------------------------------------------------------------------------
# Endpoints: Sesiones
# ---------------------------------------------------------------------------
@app.get("/api/companies/{company_id}/sessions")
async def list_sessions(company_id: str):
    company_id = _sanitize_id(company_id)
    sessions_dir = DATA_DIR / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    sessions = []
    for f in sorted(sessions_dir.glob(f"{company_id}_*.json")):
        s = load_json(f)
        sessions.append({
            "id": s.get("id"),
            "type": s.get("type", "interview"),
            "message_count": len(s.get("messages", [])),
            "created_at": s.get("created_at")
        })
    return {"sessions": sessions}

@app.get("/api/companies/{company_id}/sessions/{session_id}")
async def get_session(company_id: str, session_id: str):
    company_id = _sanitize_id(company_id)
    session_id = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:64]
    session_path = DATA_DIR / "sessions" / f"{company_id}_{session_id}.json"
    if not session_path.exists():
        raise HTTPException(404, "Sesión no encontrada")
    session = load_json(session_path)
    return {
        "id": session.get("id"),
        "type": session.get("type", "interview"),
        "messages": session.get("messages", []),
        "created_at": session.get("created_at")
    }

# ---------------------------------------------------------------------------
# Registrar Router Avanzado (Motor Financiero V2)
# ---------------------------------------------------------------------------
try:
    from advanced_endpoints import router as advanced_router, init_router
    init_router(
        data_dir=DATA_DIR,
        save_json_fn=save_json,
        load_json_fn=load_json,
        call_ollama_fn=call_ollama,
        call_ollama_chat_fn=call_ollama_chat,
        get_agent_fn=get_agent,
        get_prompt_fn=get_prompt,
        extract_json_fn=_extract_json_from_llm,
        get_timeout_fn=_get_timeout,
    )
    app.include_router(advanced_router)
    logger.info("Router avanzado V2 registrado correctamente")
except Exception as e:
    logger.warning(f"No se pudo registrar el router avanzado: {e}")

# ---------------------------------------------------------------------------
# Splash same-origin (Tauri) + UI estática
# ---------------------------------------------------------------------------

def _resolve_splash_dir() -> Path:
    """Archivos splash (desktop/ui) empaquetados como splash_ui en PyInstaller."""
    candidates: list[Path] = []
    if _IS_FROZEN:
        meipass = Path(getattr(sys, "_MEIPASS", str(BASE_DIR)))
        candidates.append(meipass / "splash_ui")
    candidates.extend(
        [
            BASE_DIR / "desktop" / "ui",
            Path(__file__).resolve().parent.parent / "desktop" / "ui",
        ]
    )
    for c in candidates:
        if (c / "index.html").is_file():
            return c.resolve()
    return (BASE_DIR / "desktop" / "ui").resolve()


_SPLASH_DIR = _resolve_splash_dir()
_SPLASH_INDEX = _SPLASH_DIR / "index.html"
_DESKTOP_STATUS_FILE = DATA_DIR / "desktop_status.json"
_INDEX_HTML = APP_DIR / "index.html"
logger.info(
    "UI splash: dir=%s index=%s app_index=%s frozen=%s",
    _SPLASH_DIR,
    _SPLASH_INDEX.is_file(),
    _INDEX_HTML.is_file(),
    _IS_FROZEN,
)


@app.get("/api/desktop-status")
async def desktop_status():
    """Estado del arranque (Ollama) escrito por Tauri en desktop_status.json."""
    default = {
        "phase": "starting",
        "message": "Iniciando servicios...",
        "percent": -1,
        "backendUrl": None,
        "canContinue": False,
        "ollamaDone": False,
        "backendError": None,
    }
    if not _DESKTOP_STATUS_FILE.is_file():
        return default
    try:
        raw = _DESKTOP_STATUS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return {**default, **data}
    except Exception as exc:
        logger.warning("desktop_status.json: %s", exc)
    return default


@app.get("/api/desktop-ui")
async def desktop_ui_status():
    """Diagnóstico para el instalador Tauri (UI empaquetada en el sidecar)."""
    return {
        "frozen": _IS_FROZEN,
        "baseDir": str(BASE_DIR),
        "appDir": str(APP_DIR),
        "indexExists": _INDEX_HTML.is_file(),
        "splashExists": _SPLASH_INDEX.is_file(),
        "port": PORT,
    }


if _SPLASH_INDEX.is_file():
    app.mount(
        "/__splash",
        StaticFiles(directory=str(_SPLASH_DIR), html=True),
        name="splash",
    )
else:
    logger.warning("splash index.html no encontrado en %s", _SPLASH_DIR)

if APP_DIR.exists() and _INDEX_HTML.is_file():
    app.mount("/ui", StaticFiles(directory=str(APP_DIR), html=True), name="ui")
    app.mount("/", StaticFiles(directory=str(APP_DIR), html=True), name="ui_root")
elif APP_DIR.exists():
    logger.warning("index.html no encontrado en %s", APP_DIR)
else:
    logger.warning(f"Directorio de UI no encontrado: {APP_DIR}")

@app.on_event("startup")
async def startup():
    for d in ["agents", "prompts/system", "sessions", "exports", "companies", "cashflows", "scenarios", "checkpoints"]:
        (DATA_DIR / d).mkdir(parents=True, exist_ok=True)
    agents_dst = DATA_DIR / "agents" / "agents.json"
    if not agents_dst.exists():
        agents_src = DEFAULTS_DIR / "agents.json"
        if agents_src.exists():
            shutil.copy2(str(agents_src), str(agents_dst))
    prompts_dst = DATA_DIR / "prompts" / "system"
    prompts_src = DEFAULTS_DIR / "prompts"
    if prompts_src.exists():
        for f in prompts_src.glob("*.md"):
            dst = prompts_dst / f.name
            if not dst.exists():
                shutil.copy2(str(f), str(dst))
    if os.environ.get("RUN_BY_TAURI") == "1":
        logger.info("RUN_BY_TAURI=1: Ollama lo gestiona el launcher (portable o sistema).")
    else:
        threading.Thread(target=ensure_ollama_running, daemon=True).start()
    logger.info(f"SmartCaja v2.0.0 iniciado en puerto {PORT} ({sys.platform})")


# ---------------------------------------------------------------------------
# Endpoints: Exportar / Importar datos globales
# ---------------------------------------------------------------------------
def _compute_data_hash(data_bytes: bytes) -> str:
    """Calcula SHA-256 del contenido para verificación de integridad."""
    return hashlib.sha256(data_bytes).hexdigest()


def _collect_export_data() -> dict:
    """Recolecta todos los datos del sistema para exportar."""
    export_data = {
        "export_version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "plugin_name": "smartcaja",
        "config": None,
        "agents": None,
        "companies": [],
        "prompts": {},
        "skills": {},
    }
    # Config
    config_file = DATA_DIR / "config.json"
    if config_file.exists():
        export_data["config"] = load_json(config_file)
    # Agentes
    agents_file = DATA_DIR / "agents" / "agents.json"
    if agents_file.exists():
        export_data["agents"] = load_json(agents_file)
    # Prompts del sistema
    prompts_dir = DATA_DIR / "prompts" / "system"
    if prompts_dir.exists():
        for f in prompts_dir.glob("*.md"):
            export_data["prompts"][f.stem] = f.read_text(encoding="utf-8")
    # Skills
    skills_dir = DATA_DIR / "prompts" / "skills"
    if skills_dir.exists():
        for f in skills_dir.glob("*.md"):
            export_data["skills"][f.stem] = f.read_text(encoding="utf-8")
    # Empresas con todo su contenido
    companies_dir = DATA_DIR / "companies"
    if companies_dir.exists():
        for company_dir in sorted(companies_dir.iterdir()):
            if company_dir.is_dir():
                company_export = {"id": company_dir.name, "files": {}}
                for json_file in company_dir.glob("*.json"):
                    company_export["files"][json_file.name] = load_json(json_file)
                export_data["companies"].append(company_export)
    # Sesiones
    sessions_dir = DATA_DIR / "sessions"
    if sessions_dir.exists():
        export_data["sessions"] = {}
        for f in sessions_dir.glob("*.json"):
            export_data["sessions"][f.name] = load_json(f)
    # Escenarios
    scenarios_dir = DATA_DIR / "scenarios"
    if scenarios_dir.exists():
        export_data["scenarios"] = {}
        for f in scenarios_dir.glob("*.json"):
            export_data["scenarios"][f.name] = load_json(f)
    return export_data


@app.get("/api/export")
async def export_all_data():
    """Exporta todos los datos del sistema en un archivo JSON firmado con hash SHA-256."""
    try:
        export_data = _collect_export_data()
        data_json = json.dumps(export_data, ensure_ascii=False, sort_keys=True, default=str)
        data_bytes = data_json.encode("utf-8")
        integrity_hash = _compute_data_hash(data_bytes)
        export_package = {
            "integrity_hash": integrity_hash,
            "hash_algorithm": "sha256",
            "data": export_data,
        }
        export_filename = f"smartcaja_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        exports_dir = DATA_DIR / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        export_file = exports_dir / export_filename
        save_json(export_file, export_package)
        logger.info(f"Exportaci\u00f3n completada: {export_filename}")
        return FileResponse(
            path=str(export_file),
            filename=export_filename,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{export_filename}"'},
        )
    except Exception as e:
        logger.error(f"Error en exportaci\u00f3n: {e}")
        raise HTTPException(status_code=500, detail=f"Error al exportar datos: {str(e)}")


MAX_IMPORT_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

@app.post("/api/import")
async def import_all_data(file: UploadFile = File(...)):
    """Importa datos desde un archivo de exportación, verificando integridad por hash."""
    try:
        content = await file.read()
        if len(content) > MAX_IMPORT_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"El archivo excede el tamaño máximo permitido ({MAX_IMPORT_FILE_SIZE // (1024*1024)} MB).")
        try:
            package = json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise HTTPException(status_code=400, detail=f"El archivo no es un JSON v\u00e1lido: {str(e)}")
        if "integrity_hash" not in package or "data" not in package:
            raise HTTPException(status_code=400, detail="Archivo inv\u00e1lido. No tiene la estructura de exportaci\u00f3n esperada.")
        stored_hash = package["integrity_hash"]
        export_data = package["data"]
        data_json = json.dumps(export_data, ensure_ascii=False, sort_keys=True, default=str)
        data_bytes = data_json.encode("utf-8")
        computed_hash = _compute_data_hash(data_bytes)
        if computed_hash != stored_hash:
            raise HTTPException(status_code=400, detail="Verificaci\u00f3n de integridad fallida. El archivo fue modificado.")
        if export_data.get("export_version", "unknown") != "1.0":
            raise HTTPException(status_code=400, detail=f"Versi\u00f3n no soportada: {export_data.get('export_version')}")
        imported_stats = {"companies": 0, "prompts": 0, "skills": 0, "sessions": 0, "skipped_existing": 0}
        # 1. Config (merge)
        if export_data.get("config"):
            config_file = DATA_DIR / "config.json"
            existing = load_json(config_file, {})
            for key, value in export_data["config"].items():
                if key not in existing:
                    existing[key] = value
            save_json(config_file, existing)
        # 2. Agentes
        if export_data.get("agents"):
            agents_file = DATA_DIR / "agents" / "agents.json"
            (DATA_DIR / "agents").mkdir(parents=True, exist_ok=True)
            existing_agents = load_json(agents_file, {"agents": []})
            imported_agents = export_data["agents"]
            if isinstance(imported_agents, dict) and "agents" in imported_agents:
                existing_ids = [a.get("id") for a in existing_agents.get("agents", [])]
                for agent in imported_agents["agents"]:
                    if agent.get("id") and agent["id"] not in existing_ids:
                        existing_agents.setdefault("agents", []).append(agent)
            save_json(agents_file, existing_agents)
        # 3. Prompts
        if export_data.get("prompts"):
            prompts_dir = DATA_DIR / "prompts" / "system"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            for name, content_text in export_data["prompts"].items():
                prompt_file = prompts_dir / f"{name}.md"
                if not prompt_file.exists():
                    prompt_file.write_text(content_text, encoding="utf-8")
                    imported_stats["prompts"] += 1
                else:
                    imported_stats["skipped_existing"] += 1
        # 4. Skills
        if export_data.get("skills"):
            skills_dir = DATA_DIR / "prompts" / "skills"
            skills_dir.mkdir(parents=True, exist_ok=True)
            for name, content_text in export_data["skills"].items():
                skill_file = skills_dir / f"{name}.md"
                if not skill_file.exists():
                    skill_file.write_text(content_text, encoding="utf-8")
                    imported_stats["skills"] += 1
                else:
                    imported_stats["skipped_existing"] += 1
        # 5. Empresas
        if export_data.get("companies"):
            companies_dir = DATA_DIR / "companies"
            companies_dir.mkdir(parents=True, exist_ok=True)
            for company_export in export_data["companies"]:
                company_id = company_export.get("id")
                if not company_id:
                    continue
                company_dir = companies_dir / company_id
                if company_dir.exists():
                    imported_stats["skipped_existing"] += 1
                    continue
                company_dir.mkdir(parents=True, exist_ok=True)
                for filename, file_data in company_export.get("files", {}).items():
                    if file_data:
                        save_json(company_dir / filename, file_data)
                imported_stats["companies"] += 1
        # 6. Sesiones
        if export_data.get("sessions"):
            sessions_dir = DATA_DIR / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            for s_name, s_data in export_data["sessions"].items():
                session_file = sessions_dir / s_name
                if not session_file.exists() and s_data:
                    save_json(session_file, s_data)
                    imported_stats["sessions"] += 1
                else:
                    imported_stats["skipped_existing"] += 1
        # 7. Escenarios
        if export_data.get("scenarios"):
            scenarios_dir = DATA_DIR / "scenarios"
            scenarios_dir.mkdir(parents=True, exist_ok=True)
            for s_name, s_data in export_data["scenarios"].items():
                scenario_file = scenarios_dir / s_name
                if not scenario_file.exists() and s_data:
                    save_json(scenario_file, s_data)
        logger.info(f"Importaci\u00f3n completada: {imported_stats}")
        return {"status": "success", "message": "Importaci\u00f3n completada exitosamente.", "stats": imported_stats}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en importaci\u00f3n: {e}")
        raise HTTPException(status_code=500, detail=f"Error al importar datos: {str(e)}")


@app.get("/api/export/info")
async def export_info():
    """Retorna informaci\u00f3n sobre qu\u00e9 se exportar\u00eda."""
    try:
        companies_dir = DATA_DIR / "companies"
        company_count = sum(1 for d in companies_dir.iterdir() if d.is_dir()) if companies_dir.exists() else 0
        sessions_dir = DATA_DIR / "sessions"
        session_count = len(list(sessions_dir.glob("*.json"))) if sessions_dir.exists() else 0
        prompts_dir = DATA_DIR / "prompts" / "system"
        prompt_count = len(list(prompts_dir.glob("*.md"))) if prompts_dir.exists() else 0
        skills_dir = DATA_DIR / "prompts" / "skills"
        skill_count = len(list(skills_dir.glob("*.md"))) if skills_dir.exists() else 0
        scenarios_dir = DATA_DIR / "scenarios"
        scenario_count = len(list(scenarios_dir.glob("*.json"))) if scenarios_dir.exists() else 0
        return {
            "companies": company_count,
            "sessions": session_count,
            "scenarios": scenario_count,
            "prompts": prompt_count,
            "skills": skill_count,
            "has_config": (DATA_DIR / "config.json").exists(),
            "has_agents": (DATA_DIR / "agents" / "agents.json").exists(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    if sys.platform == "win32":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    host = "127.0.0.1"
    print(f"http://{host}:{PORT}")
    uvicorn.run(app, host=host, port=PORT, log_level="info")
