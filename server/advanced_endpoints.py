"""
advanced_endpoints.py — Endpoints avanzados del motor financiero modular.
Se registran como un router de FastAPI para mantener el app.py limpio.

Incluye:
- Generación de cashflow mes a mes con notificaciones contextualizadas
- Métricas financieras avanzadas
- Simulación Monte Carlo
- Búsqueda de mercado y estacionalidad
- Versionado de escenarios y comparación de planes
- Recomendaciones de financiamiento y optimización de caja
"""

import json
import re
import uuid
import threading
import time
import copy
from datetime import datetime, date
from pathlib import Path
from log_sanitize import sanitize_log
from path_guard import guarded_child
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, field_validator

# Imports del motor financiero (usa imports relativos al directorio server/)
import sys
import os
_server_dir = os.path.dirname(os.path.abspath(__file__))
if _server_dir not in sys.path:
    sys.path.insert(0, _server_dir)

from financial_engine.core import CashflowModel, BusinessProfile, MonthData as EngineMonthData
from financial_engine.metrics import FinancialMetrics
from financial_engine.monte_carlo import MonteCarloSimulator
from interview_manager import InterviewManager, INTERVIEW_TOPICS
from market_research import search_market_data, get_market_seasonality_factors, get_inflation_rate

# ---------------------------------------------------------------------------
# Utilidad para sanitizar inf/nan antes de serializar a JSON
# ---------------------------------------------------------------------------
import math as _math

def _sanitize_for_json(d):
    """Recursivamente reemplaza inf/nan con 0.0 para ser JSON-compatible."""
    if isinstance(d, dict):
        return {k: _sanitize_for_json(v) for k, v in d.items()}
    elif isinstance(d, list):
        return [_sanitize_for_json(item) for item in d]
    elif isinstance(d, float):
        if _math.isinf(d) or _math.isnan(d):
            return 0.0
        return d
    return d

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/api/v2", tags=["advanced"])

# Estado de generación avanzada (en memoria, compartido) — protegido con lock
import threading as _threading
_advanced_generation_status: Dict[str, dict] = {}
_advanced_gen_lock = _threading.Lock()

# ---------------------------------------------------------------------------
# Utilidades compartidas (importadas desde app.py al registrar)
# ---------------------------------------------------------------------------
_DATA_DIR: Path = None
_save_json = None
_load_json = None
_call_ollama = None
_call_ollama_chat = None
_get_agent = None
_get_prompt = None
_extract_json_from_llm = None
_get_timeout = None


def init_router(data_dir: Path, save_json_fn, load_json_fn, call_ollama_fn,
                call_ollama_chat_fn, get_agent_fn, get_prompt_fn,
                extract_json_fn, get_timeout_fn):
    """Inicializa el router con las dependencias del app principal."""
    global _DATA_DIR, _save_json, _load_json, _call_ollama, _call_ollama_chat
    global _get_agent, _get_prompt, _extract_json_from_llm, _get_timeout
    _DATA_DIR = data_dir
    _save_json = save_json_fn
    _load_json = load_json_fn
    _call_ollama = call_ollama_fn
    _call_ollama_chat = call_ollama_chat_fn
    _get_agent = get_agent_fn
    _get_prompt = get_prompt_fn
    _extract_json_from_llm = extract_json_fn
    _get_timeout = get_timeout_fn


# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------
class GenerateCashflowV2Request(BaseModel):
    """Request para generación avanzada de cashflow."""
    months: int = 12
    use_market_data: bool = True
    run_monte_carlo: bool = True
    monte_carlo_iterations: int = 500

    @field_validator("months")
    @classmethod
    def validate_months(cls, v):
        if v < 1 or v > 36:
            raise ValueError("El número de meses debe estar entre 1 y 36.")
        return v

    @field_validator("monte_carlo_iterations")
    @classmethod
    def validate_iterations(cls, v):
        if v < 100 or v > 5000:
            raise ValueError("Las iteraciones Monte Carlo deben estar entre 100 y 5000.")
        return v


class MonteCarloRequest(BaseModel):
    """Request para ejecutar simulación Monte Carlo."""
    iterations: int = 1000
    variability: Optional[Dict[str, float]] = None

    @field_validator("iterations")
    @classmethod
    def validate_iterations(cls, v):
        if v < 100 or v > 5000:
            raise ValueError("Las iteraciones deben estar entre 100 y 5000.")
        return v


class ScenarioCompareRequest(BaseModel):
    """Request para comparar escenarios."""
    scenario_ids: List[str]
    include_base: bool = True


class CustomScenarioRequest(BaseModel):
    """Request para crear escenario personalizado con multiplicadores."""
    nombre: str
    sales_mult: float = 1.0
    costs_mult: float = 1.0
    growth_mult: float = 1.0
    fixed_costs_mult: float = 1.0


class SensitivityRequest(BaseModel):
    """Request para análisis de sensibilidad."""
    variable: str = "ventas"
    range_pct: float = 30.0
    steps: int = 7

    @field_validator("variable")
    @classmethod
    def validate_variable(cls, v):
        allowed = ["ventas", "costos_variables", "costos_fijos"]
        if v not in allowed:
            raise ValueError(f"Variable debe ser una de: {allowed}")
        return v


# ---------------------------------------------------------------------------
# Endpoint: Generación Avanzada de Cashflow (Mes a Mes con Notificaciones)
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/generate-cashflow")
async def generate_cashflow_v2(company_id: str, request: GenerateCashflowV2Request,
                                background_tasks: BackgroundTasks):
    """
    Genera un flujo de caja avanzado mes a mes con:
    - Notificaciones contextualizadas al negocio
    - Búsqueda de datos de mercado (si use_market_data=True)
    - Simulación Monte Carlo (si run_monte_carlo=True)
    - Métricas financieras avanzadas
    """
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    if not company_dir.exists():
        raise HTTPException(404, "Empresa no encontrada")

    task_id = str(uuid.uuid4())[:8]
    _advanced_generation_status[task_id] = {
        "status": "generating",
        "progress": 0,
        "step": "Iniciando generación avanzada...",
        "notifications": [],
        "current_month": 0,
        "total_months": request.months,
        "error": None,
        "phase": "preparation",
    }

    background_tasks.add_task(
        _generate_cashflow_v2_task,
        company_id, task_id, request.months,
        request.use_market_data, request.run_monte_carlo,
        request.monte_carlo_iterations
    )

    return {"task_id": task_id, "status": "generating", "version": "v2"}


def _generate_cashflow_v2_task(company_id: str, task_id: str, num_months: int,
                                use_market_data: bool, run_monte_carlo: bool,
                                mc_iterations: int):
    """Tarea de fondo para generación avanzada de cashflow."""
    try:
        company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
        company = _load_json(company_dir / "company.json")

        # --- Fase 1: Recopilar datos de la entrevista ---
        _update_status(task_id, 5, "Recopilando información de entrevistas...", "preparation")

        sessions_dir = _DATA_DIR / "sessions"
        all_messages = []
        for f in sorted(sessions_dir.glob(f"{company_id}_*.json")):
            session = _load_json(f)
            for msg in session.get("messages", []):
                all_messages.append(msg)

        # --- Fase 2: Construir perfil del negocio con el LLM ---
        _update_status(task_id, 10, "Analizando perfil del negocio...", "profile_extraction")
        _add_notification(task_id, f"🔍 Analizando la información de {company.get('name', 'tu empresa')}...")

        profile = _extract_business_profile(company, all_messages, task_id)

        # --- Fase 3: Búsqueda de datos de mercado ---
        market_data = {}
        if use_market_data and profile.sector:
            _update_status(task_id, 20, f"Buscando datos de mercado para el sector {profile.sector}...", "market_research")
            _add_notification(task_id, f"🌐 Buscando tendencias del mercado de {profile.sector} en {profile.country or 'tu región'}...")

            try:
                market_data = search_market_data(
                    sector=profile.sector,
                    country=profile.country or "Chile",
                    data_dir=_DATA_DIR,
                    products=profile.products
                )
                profile.market_data = market_data

                # Aplicar estacionalidad de mercado si se encontró
                market_seasonality = get_market_seasonality_factors(market_data)
                if market_seasonality and not profile.seasonality_pattern:
                    profile.seasonality_pattern = market_seasonality

                # Aplicar inflación
                inflation = get_inflation_rate(market_data)
                if inflation > 0:
                    profile.market_data["inflation_annual_pct"] = inflation

                if market_data.get("search_successful"):
                    _add_notification(task_id, f"✅ Datos de mercado obtenidos: inflación {inflation:.1f}%, estacionalidad del sector aplicada")
                else:
                    _add_notification(task_id, f"📊 Usando datos de mercado estimados para {profile.sector}")

            except Exception as e:
                _add_notification(task_id, f"⚠️ No se pudieron obtener datos de mercado en tiempo real. Usando estimaciones del sector.")

        # --- Fase 4: Generar cashflow mes a mes ---
        _update_status(task_id, 30, "Iniciando generación mes a mes...", "month_generation")

        model = CashflowModel(profile=profile, initial_cash=profile.initial_cash)

        # Aplicar estacionalidad de mercado
        if market_data:
            market_seasonality = get_market_seasonality_factors(market_data)
            if market_seasonality:
                model.market_seasonality = market_seasonality

        # Generar mes a mes con notificaciones
        start_date = date.today().replace(day=1)

        def progress_callback(month_idx, total, month_data, notification):
            progress = 30 + int((month_idx / total) * 40)
            _update_status(task_id, progress,
                          f"Generando mes {month_idx + 1} de {total}: {month_data.label}...",
                          "month_generation")
            _advanced_generation_status[task_id]["current_month"] = month_idx + 1
            _add_notification(task_id, notification)

        months = model.generate_all_months(
            num_months=num_months,
            start_date=start_date,
            progress_callback=progress_callback
        )

        _add_notification(task_id, f"✅ {num_months} meses generados exitosamente para {company.get('name', 'tu empresa')}")

        # --- Fase 5: Calcular métricas financieras ---
        _update_status(task_id, 72, "Calculando métricas financieras avanzadas...", "metrics")
        _add_notification(task_id, f"📊 Calculando break-even, runway y márgenes de {company.get('name', '')}...")

        metrics_calculator = FinancialMetrics(model)
        metrics = metrics_calculator.calculate_all()

        # --- Fase 6: Simulación Monte Carlo (opcional) ---
        monte_carlo_results = None
        if run_monte_carlo:
            _update_status(task_id, 78, f"Ejecutando simulación Monte Carlo ({mc_iterations} iteraciones)...", "monte_carlo")
            _add_notification(task_id, f"🎲 Simulando {mc_iterations} escenarios probabilísticos para evaluar riesgo...")

            simulator = MonteCarloSimulator(model, iterations=mc_iterations)

            def mc_progress(iteration, total, msg):
                progress = 78 + int((iteration / total) * 15)
                _update_status(task_id, min(progress, 93), f"Monte Carlo: {msg}", "monte_carlo")

            monte_carlo_results = simulator.run(progress_callback=mc_progress)

            prob_insolvencia = monte_carlo_results.get("probabilidad_insolvencia_pct", 0)
            nivel_riesgo = monte_carlo_results.get("nivel_riesgo", {}).get("nivel", "desconocido")
            _add_notification(task_id,
                f"🎲 Monte Carlo completado: probabilidad de insolvencia {prob_insolvencia:.1f}% — Riesgo {nivel_riesgo}")

        # --- Fase 7: Guardar resultados ---
        _update_status(task_id, 95, "Guardando resultados...", "saving")

        cashflow_data = model.to_dict()
        cashflow_data["id"] = str(uuid.uuid4())[:8]
        cashflow_data["company_id"] = company_id
        cashflow_data["created_at"] = datetime.now().isoformat()
        cashflow_data["version"] = "v2"
        cashflow_data["metrics"] = metrics
        cashflow_data["monte_carlo"] = monte_carlo_results
        cashflow_data["market_data"] = market_data
        cashflow_data["generation_notifications"] = _advanced_generation_status[task_id].get("notifications", [])

        _save_json(company_dir / "cashflow.json", cashflow_data)

        # Actualizar estado de la empresa
        company["status"] = "complete"
        company["updated_at"] = datetime.now().isoformat()
        _save_json(company_dir / "company.json", company)

        _add_notification(task_id, f"🎉 Flujo de caja completo generado para {company.get('name', 'tu empresa')}")

        _advanced_generation_status[task_id].update({
            "status": "done",
            "progress": 100,
            "step": "Generación completada",
            "phase": "complete",
            "months_generated": num_months,
            "has_monte_carlo": run_monte_carlo,
            "has_market_data": use_market_data and bool(market_data),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        _advanced_generation_status[task_id].update({
            "status": "error",
            "progress": 0,
            "error": str(e),
            "step": "Error en generación",
        })


def _extract_business_profile(company: dict, messages: list, task_id: str) -> BusinessProfile:
    """
    Extrae el BusinessProfile de los datos de la empresa y las conversaciones.
    Usa el LLM para interpretar las respuestas de la entrevista y extraer datos estructurados.
    """
    # Crear InterviewManager con datos de la empresa
    im = InterviewManager(company_data=company)

    # Preparar texto de conversación para el LLM
    conversation_parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        conversation_parts.append(f"{role.upper()}: {content}")

    conversation_text = "\n".join(conversation_parts[-40:])  # Últimos 40 mensajes para no exceder contexto

    if not conversation_text.strip():
        # Sin entrevista, usar solo datos de la empresa
        profile, assumptions = im.build_profile()
        return profile

    # Usar LLM para extraer datos estructurados
    extraction_prompt = """Eres un extractor de datos financieros. Analiza la conversación y extrae los siguientes datos en formato JSON.
Si un dato no se menciona, usa null. NO inventes datos.

FORMATO DE RESPUESTA (solo JSON, sin texto adicional):
{
  "sector": "string o null",
  "products": ["lista de productos"] o null,
  "customer_segments": ["lista"] o null,
  "revenue_model": "string o null",
  "avg_price": numero o null,
  "monthly_volume": numero o null,
  "purchase_frequency": "string o null",
  "expected_growth_pct": numero o null,
  "churn_rate_pct": numero o null,
  "variable_cost_pct": numero o null,
  "fixed_costs_monthly": numero o null,
  "salaries_monthly": numero o null,
  "marketing_monthly": numero o null,
  "tax_rate_pct": numero o null,
  "collection_days": numero o null,
  "payment_days": numero o null,
  "inventory_days": numero o null,
  "debt_monthly_payment": numero o null,
  "initial_cash": numero o null,
  "main_risks": ["lista"] o null,
  "country": "string o null",
  "currency": "string o null"
}"""

    try:
        agent = _get_agent("cashflow_analyst")
        model = agent.get("model", "llama3.2:3b") if agent else "llama3.2:3b"

        response = _call_ollama(
            model=model,
            system_prompt=extraction_prompt,
            user_message=f"CONVERSACIÓN:\n{conversation_text}\n\nExtrae los datos financieros en JSON:",
            temperature=0.1,
            timeout=60
        )

        extracted = _extract_json_from_llm(response)
        if extracted and isinstance(extracted, dict):
            # Actualizar collected_data del InterviewManager
            for key, value in extracted.items():
                if value is not None:
                    im.collected_data[key] = value

            # Marcar temas cubiertos
            field_to_topic = {}
            for topic in INTERVIEW_TOPICS:
                for field in topic["fields"]:
                    field_to_topic[field] = topic["id"]

            for key in extracted:
                if extracted[key] is not None and key in field_to_topic:
                    im.mark_topic_covered(field_to_topic[key])

    except Exception as e:
        _add_notification(task_id, f"⚠️ Extracción parcial de datos: usando información disponible")

    # Construir perfil con datos extraídos + supuestos
    profile, assumptions = im.build_profile()

    # Agregar supuestos al status
    if assumptions:
        assumption_msgs = [a["message"] for a in assumptions[:5]]
        _add_notification(task_id, f"📋 Supuestos aplicados: {'; '.join(assumption_msgs[:3])}")

    return profile


# ---------------------------------------------------------------------------
# Endpoint: Progreso de Generación Avanzada
# ---------------------------------------------------------------------------
@router.get("/generation/{task_id}/progress")
async def get_advanced_progress(task_id: str):
    """Retorna el progreso detallado de la generación avanzada con notificaciones."""
    status = _advanced_generation_status.get(task_id)
    if not status:
        return {"status": "unknown", "progress": 0, "error": "Tarea no encontrada"}
    return status


# ---------------------------------------------------------------------------
# Endpoint: Métricas Financieras
# ---------------------------------------------------------------------------
@router.get("/companies/{company_id}/metrics")
async def get_financial_metrics(company_id: str):
    """Calcula y retorna métricas financieras avanzadas del cashflow actual."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja. Genera uno primero.")

    cashflow_data = _load_json(cashflow_path)

    # Si ya tiene métricas calculadas (v2), retornarlas
    if "metrics" in cashflow_data and cashflow_data.get("version") == "v2":
        return _sanitize_for_json(cashflow_data["metrics"])

    # Si es un cashflow legacy, recalcular
    try:
        model = CashflowModel.from_dict(cashflow_data)
        calculator = FinancialMetrics(model)
        metrics = calculator.calculate_all()
        return _sanitize_for_json(metrics)
    except Exception as e:
        raise HTTPException(500, f"Error calculando métricas: {str(e)}")


# ---------------------------------------------------------------------------
# Endpoint: Simulación Monte Carlo
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/monte-carlo")
async def run_monte_carlo(company_id: str, request: MonteCarloRequest,
                          background_tasks: BackgroundTasks):
    """Ejecuta simulación Monte Carlo sobre el cashflow existente."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja. Genera uno primero.")

    task_id = str(uuid.uuid4())[:8]
    _advanced_generation_status[task_id] = {
        "status": "generating",
        "progress": 0,
        "step": "Iniciando simulación Monte Carlo...",
        "notifications": [],
        "error": None,
        "phase": "monte_carlo",
    }

    background_tasks.add_task(_run_monte_carlo_task, company_id, task_id, request.iterations, request.variability)
    return {"task_id": task_id, "status": "generating"}


def _run_monte_carlo_task(company_id: str, task_id: str, iterations: int, variability: dict = None):
    """Tarea de fondo para Monte Carlo."""
    try:
        company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
        cashflow_data = _load_json(company_dir / "cashflow.json")

        model = CashflowModel.from_dict(cashflow_data)
        simulator = MonteCarloSimulator(model, iterations=iterations)

        if variability:
            simulator.variability.update(variability)

        def progress_cb(iteration, total, msg):
            progress = int((iteration / total) * 90)
            _update_status(task_id, progress, f"Monte Carlo: {msg}", "monte_carlo")

        results = simulator.run(progress_callback=progress_cb)

        # Guardar resultados en el cashflow
        cashflow_data["monte_carlo"] = results
        _save_json(company_dir / "cashflow.json", cashflow_data)

        _advanced_generation_status[task_id].update({
            "status": "done",
            "progress": 100,
            "step": "Monte Carlo completado",
            "result": results,
        })

    except Exception as e:
        _advanced_generation_status[task_id].update({
            "status": "error",
            "error": str(e),
            "step": "Error",
        })


# ---------------------------------------------------------------------------
# Endpoint: Análisis de Sensibilidad
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/sensitivity")
async def run_sensitivity(company_id: str, request: SensitivityRequest):
    """Ejecuta análisis de sensibilidad para una variable específica."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja.")

    cashflow_data = _load_json(cashflow_path)
    model = CashflowModel.from_dict(cashflow_data)
    simulator = MonteCarloSimulator(model, iterations=100)

    results = simulator.sensitivity_monte_carlo(
        variable=request.variable,
        range_pct=request.range_pct,
        steps=request.steps
    )

    return {"variable": request.variable, "range_pct": request.range_pct, "results": results}


# ---------------------------------------------------------------------------
# Endpoint: Búsqueda de Mercado
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/market-research")
async def do_market_research(company_id: str):
    """Busca datos de mercado para el sector de la empresa."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    if not company_dir.exists():
        raise HTTPException(404, "Empresa no encontrada")

    company = _load_json(company_dir / "company.json")
    sector = company.get("sector", "")
    if not sector:
        raise HTTPException(400, "La empresa no tiene sector definido. Completa la entrevista primero.")

    # Intentar obtener país de la conversación o usar default
    country = "Chile"  # Default

    market_data = search_market_data(
        sector=sector,
        country=country,
        data_dir=_DATA_DIR,
        products=[]
    )

    return market_data


# ---------------------------------------------------------------------------
# Endpoint: Comparación de Escenarios
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/compare-scenarios")
async def compare_scenarios(company_id: str, request: ScenarioCompareRequest):
    """Compara múltiples escenarios con el cashflow base."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    cashflow_path = company_dir / "cashflow.json"

    comparison = {"base": None, "scenarios": [], "comparison_metrics": {}}

    # Cargar base
    if request.include_base and cashflow_path.exists():
        base_data = _load_json(cashflow_path)
        comparison["base"] = {
            "name": "Plan Base",
            "months": [{"label": m.get("label", ""), "balance": m.get("cumulative_balance", 0),
                        "net_flow": m.get("net_flow", 0)} for m in base_data.get("months", [])],
            "summary": base_data.get("summary", {}),
        }

    # Cargar escenarios
    scenarios_dir = _DATA_DIR / "scenarios"
    for sid in request.scenario_ids:
        for f in scenarios_dir.glob(f"*_{sid}.json"):
            scenario = _load_json(f)
            comparison["scenarios"].append({
                "id": sid,
                "name": scenario.get("scenario_name", f"Escenario {sid}"),
                "months": [{"label": m.get("label", ""), "balance": m.get("cumulative_balance", 0),
                            "net_flow": m.get("net_flow", 0)} for m in scenario.get("months", [])],
                "summary": scenario.get("summary", {}),
                "changes_applied": scenario.get("changes_applied", []),
            })

    # Calcular métricas comparativas
    if comparison["base"] and comparison["scenarios"]:
        base_net = comparison["base"]["summary"].get("net_cashflow", 0)
        for sc in comparison["scenarios"]:
            sc_net = sc["summary"].get("net_cashflow", 0)
            sc["vs_base"] = {
                "net_difference": round(sc_net - base_net, 2),
                "pct_difference": round((sc_net - base_net) / abs(base_net) * 100, 1) if base_net != 0 else 0,
            }

    return comparison


# ---------------------------------------------------------------------------
# Endpoint: Crear Escenario Personalizado (con multiplicadores)
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/custom-scenario")
async def create_custom_scenario(company_id: str, request: CustomScenarioRequest):
    """Crea un escenario personalizado usando multiplicadores directos."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja base.")

    cashflow_data = _load_json(cashflow_path)
    model = CashflowModel.from_dict(cashflow_data)
    simulator = MonteCarloSimulator(model)

    params = {
        "nombre": request.nombre,
        "sales_mult": request.sales_mult,
        "costs_mult": request.costs_mult,
        "growth_mult": request.growth_mult,
        "fixed_costs_mult": request.fixed_costs_mult,
    }

    result = simulator.run_scenario_comparison([params])

    # Guardar como escenario
    if result.get("comparaciones"):
        scenario_result = result["comparaciones"][0]
        scenario_id = str(uuid.uuid4())[:8]

        scenario_data = {
            "id": scenario_id,
            "company_id": company_id,
            "scenario_name": request.nombre,
            "simulation_mode": "custom",
            "params": params,
            "caja_final": scenario_result["caja_final"],
            "months": scenario_result["meses"],
            "created_at": datetime.now().isoformat(),
        }

        scenarios_dir = _DATA_DIR / "scenarios"
        scenarios_dir.mkdir(parents=True, exist_ok=True)
        _save_json(scenarios_dir / f"{company_id}_{scenario_id}.json", scenario_data)

        return {"scenario_id": scenario_id, "result": scenario_data}

    raise HTTPException(500, "Error creando escenario personalizado")


# ---------------------------------------------------------------------------
# Endpoint: Entrevista Inteligente V2
# ---------------------------------------------------------------------------
@router.post("/chat/interview")
async def chat_interview_v2(company_id: str, message: str, session_id: str = ""):
    """
    Entrevista inteligente V2 con:
    - Máximo 8 preguntas por turno
    - Contexto del negocio en cada pregunta
    - Extracción automática de datos
    - Progreso de la entrevista
    """
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    if not company_dir.exists():
        raise HTTPException(404, "Empresa no encontrada")

    company = _load_json(company_dir / "company.json")

    # Crear InterviewManager
    im = InterviewManager(company_data=company)

    # Cargar sesiones previas para determinar progreso
    sessions_dir = _DATA_DIR / "sessions"
    for f in sorted(sessions_dir.glob(f"{company_id}_*.json")):
        session = _load_json(f)
        for msg in session.get("messages", []):
            if msg.get("role") == "user":
                extracted = im.extract_data_from_response(msg["content"], "")
                for key, value in extracted.items():
                    im.collected_data[key] = value

    # Generar system prompt contextualizado
    system_prompt = im.generate_system_prompt()

    # Cargar o crear sesión
    if not session_id:
        session_id = str(uuid.uuid4())[:8]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id or ""):
        raise HTTPException(400, "ID de sesion invalido.")
    session_path = guarded_child(sessions_dir, f"{company_id}_{session_id}.json")
    session = _load_json(session_path, {
        "id": session_id,
        "company_id": company_id,
        "type": "interview_v2",
        "messages": [],
        "created_at": datetime.now().isoformat()
    })

    # Construir mensajes para el LLM
    messages = [{"role": "system", "content": system_prompt}]
    for msg in session.get("messages", [])[-20:]:  # Últimos 20 mensajes para no exceder contexto
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": message})

    # Llamar al LLM
    agent = _get_agent("financial_interviewer")
    model = agent.get("model", "llama3.2:3b") if agent else "llama3.2:3b"

    response = _call_ollama_chat(
        model=model,
        messages=messages,
        temperature=0.7
    )

    # Guardar en sesión
    session["messages"].append({"role": "user", "content": message, "timestamp": datetime.now().isoformat()})
    session["messages"].append({"role": "assistant", "content": response, "timestamp": datetime.now().isoformat()})
    _save_json(session_path, session)

    # Extraer datos de la respuesta del usuario
    extracted = im.extract_data_from_response(message, response)

    return {
        "response": response,
        "session_id": session_id,
        "progress": im.get_interview_progress(),
        "extracted_data": extracted,
        "has_enough_data": im._has_minimum_data(),
    }


# ---------------------------------------------------------------------------
# Endpoint: Progreso de Entrevista
# ---------------------------------------------------------------------------
@router.get("/companies/{company_id}/interview-progress")
async def get_interview_progress(company_id: str):
    """Retorna el progreso de la entrevista y datos recopilados."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    if not company_dir.exists():
        raise HTTPException(404, "Empresa no encontrada")

    company = _load_json(company_dir / "company.json")
    im = InterviewManager(company_data=company)

    # Analizar sesiones para determinar progreso
    sessions_dir = _DATA_DIR / "sessions"
    for f in sorted(sessions_dir.glob(f"{company_id}_*.json")):
        session = _load_json(f)
        for msg in session.get("messages", []):
            if msg.get("role") == "user":
                extracted = im.extract_data_from_response(msg["content"], "")
                for key, value in extracted.items():
                    im.collected_data[key] = value

    progress = im.get_interview_progress()
    progress["collected_data_summary"] = {
        k: v for k, v in im.collected_data.items()
        if v is not None and v != "" and v != []
    }
    progress["contextual_notifications"] = im.get_contextual_notifications()[:5]

    return progress


# ---------------------------------------------------------------------------
# Endpoint: Versiones de Cashflow
# ---------------------------------------------------------------------------
@router.get("/companies/{company_id}/cashflow-versions")
async def list_cashflow_versions(company_id: str):
    """Lista todas las versiones guardadas del cashflow."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    versions_dir = company_dir / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)

    versions = []
    # Versión actual
    cashflow_path = company_dir / "cashflow.json"
    if cashflow_path.exists():
        current = _load_json(cashflow_path)
        versions.append({
            "id": "current",
            "name": "Versión Actual",
            "created_at": current.get("created_at", ""),
            "version": current.get("version", "v1"),
            "months": len(current.get("months", [])),
            "is_current": True,
        })

    # Versiones guardadas
    for f in sorted(versions_dir.glob("*.json"), reverse=True):
        v = _load_json(f)
        versions.append({
            "id": f.stem,
            "name": v.get("version_name", f.stem),
            "created_at": v.get("created_at", ""),
            "version": v.get("version", "v1"),
            "months": len(v.get("months", [])),
            "is_current": False,
        })

    return {"versions": versions}


@router.post("/companies/{company_id}/cashflow-versions")
async def save_cashflow_version(company_id: str, name: str = ""):
    """Guarda la versión actual del cashflow como una versión nombrada."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    cashflow_path = company_dir / "cashflow.json"
    if not cashflow_path.exists():
        raise HTTPException(404, "No hay flujo de caja para versionar.")

    versions_dir = company_dir / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)

    cashflow_data = _load_json(cashflow_path)
    version_id = str(uuid.uuid4())[:8]
    cashflow_data["version_id"] = version_id
    cashflow_data["version_name"] = name or f"Versión {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    cashflow_data["saved_at"] = datetime.now().isoformat()

    _save_json(versions_dir / f"{version_id}.json", cashflow_data)

    return {"version_id": version_id, "name": cashflow_data["version_name"]}


@router.put("/companies/{company_id}/cashflow-versions/{version_id}/restore")
async def restore_cashflow_version(company_id: str, version_id: str):
    """Restaura una versión guardada como la versión actual."""
    company_dir = guarded_child(_DATA_DIR / "companies", company_id, id_only=True)
    versions_dir = company_dir / "versions"
    version_path = versions_dir / f"{version_id}.json"

    if not version_path.exists():
        raise HTTPException(404, "Versión no encontrada")

    # Guardar actual como backup
    cashflow_path = company_dir / "cashflow.json"
    if cashflow_path.exists():
        backup_id = str(uuid.uuid4())[:8]
        current = _load_json(cashflow_path)
        current["version_name"] = f"Backup antes de restaurar {version_id}"
        current["saved_at"] = datetime.now().isoformat()
        _save_json(versions_dir / f"{backup_id}.json", current)

    # Restaurar versión
    version_data = _load_json(version_path)
    _save_json(cashflow_path, version_data)

    return {"status": "restored", "version_id": version_id}


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _update_status(task_id: str, progress: int, step: str, phase: str):
    """Actualiza el estado de una tarea de generación (thread-safe)."""
    with _advanced_gen_lock:
        if task_id in _advanced_generation_status:
            _advanced_generation_status[task_id]["progress"] = progress
            _advanced_generation_status[task_id]["step"] = step
            _advanced_generation_status[task_id]["phase"] = phase


def _add_notification(task_id: str, message: str):
    """Agrega una notificación al estado de la tarea (thread-safe)."""
    message = sanitize_log(message, limit=400)
    with _advanced_gen_lock:
        if task_id in _advanced_generation_status:
            _advanced_generation_status[task_id]["notifications"].append({
                "message": message,
                "timestamp": datetime.now().isoformat(),
            })
