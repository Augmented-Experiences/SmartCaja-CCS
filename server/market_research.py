"""
market_research.py — Módulo de búsqueda de mercado y estacionalidad.
Realiza búsquedas en internet para obtener datos reales del mercado
del usuario y aplicarlos a la proyección del flujo de caja.

Funcionalidades:
- Búsqueda de tendencias del sector
- Extracción de datos de estacionalidad por industria
- Obtención de indicadores macroeconómicos (inflación, tipo de cambio)
- Cache de resultados para evitar consultas repetidas
"""

import json
import os
import logging
import time
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

try:
    import requests as http_requests
except ImportError:
    http_requests = None

logger = logging.getLogger("cashflow-market-research")

# Directorio para cache de datos de mercado
_CACHE_DIR = None


def _get_cache_dir(data_dir: Path) -> Path:
    """Obtiene el directorio de cache para datos de mercado."""
    cache_dir = data_dir / "market_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _load_cache(cache_dir: Path, key: str, max_age_hours: int = 24) -> Optional[dict]:
    """Carga datos del cache si no han expirado."""
    cache_file = cache_dir / f"{key}.json"
    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
        if datetime.now() - cached_at < timedelta(hours=max_age_hours):
            return data.get("result")
    except Exception:
        pass
    return None


def _save_cache(cache_dir: Path, key: str, result: dict):
    """Guarda datos en el cache."""
    cache_file = cache_dir / f"{key}.json"
    data = {"cached_at": datetime.now().isoformat(), "result": result}
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def search_market_data(sector: str, country: str, data_dir: Path,
                       products: List[str] = None) -> dict:
    """
    Busca datos de mercado relevantes para el sector y país del usuario.
    Intenta obtener:
    - Estacionalidad del sector
    - Tasa de inflación actual
    - Tendencias de crecimiento del sector
    - Factores de riesgo del mercado
    
    Args:
        sector: Sector del negocio (ej: "panadería", "consultora IT")
        country: País de operación (ej: "Chile", "Colombia")
        data_dir: Directorio de datos para cache
        products: Lista de productos/servicios principales
        
    Returns:
        Diccionario con datos de mercado encontrados y su fuente.
    """
    cache_dir = _get_cache_dir(data_dir)
    cache_key = f"market_{_sanitize_key(sector)}_{_sanitize_key(country)}"

    # Intentar cargar del cache (válido por 48 horas)
    cached = _load_cache(cache_dir, cache_key, max_age_hours=48)
    if cached:
        logger.info(f"Datos de mercado cargados del cache para {sector}/{country}")
        return cached

    result = {
        "sector": sector,
        "country": country,
        "timestamp": datetime.now().isoformat(),
        "seasonality": {},
        "inflation": {},
        "growth_trend": {},
        "risks": [],
        "sources": [],
        "search_successful": False,
    }

    # Intentar búsqueda web
    try:
        market_info = _search_web_for_market(sector, country, products)
        if market_info:
            result.update(market_info)
            result["search_successful"] = True
    except Exception as e:
        logger.warning(f"Error en búsqueda de mercado: {e}")

    # Si no se pudo buscar en internet, usar datos predefinidos
    if not result["search_successful"]:
        result = _get_fallback_market_data(sector, country, result)

    # Guardar en cache
    _save_cache(cache_dir, cache_key, result)
    return result


def _search_web_for_market(sector: str, country: str, products: List[str] = None) -> Optional[dict]:
    """
    Realiza búsqueda web para obtener datos de mercado.
    Usa DuckDuckGo Instant Answer API (no requiere API key).
    """
    if http_requests is None:
        return None

    result = {}
    queries = [
        f"{sector} {country} estacionalidad ventas",
        f"inflación {country} 2025 2026 proyección",
        f"crecimiento sector {sector} {country}",
    ]

    if products:
        queries.append(f"{products[0]} tendencia mercado {country}")

    search_results = []
    for query in queries:
        try:
            # Usar DuckDuckGo Instant Answer API (gratuita, sin key)
            resp = http_requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                timeout=10,
                headers={"User-Agent": "SmartCaja/1.0"}
            )
            if resp.status_code == 200:
                data = resp.json()
                abstract = data.get("AbstractText", "")
                if abstract:
                    search_results.append({"query": query, "text": abstract, "source": data.get("AbstractSource", "")})

                # También revisar topics relacionados
                for topic in data.get("RelatedTopics", [])[:3]:
                    if isinstance(topic, dict) and "Text" in topic:
                        search_results.append({"query": query, "text": topic["Text"], "source": "DuckDuckGo"})

            time.sleep(0.5)  # Rate limiting cortés
        except Exception as e:
            logger.debug(f"Error buscando '{query}': {e}")
            continue

    if search_results:
        result["raw_search_results"] = search_results[:10]
        result["sources"] = list(set(r.get("source", "") for r in search_results if r.get("source")))

        # Intentar extraer datos numéricos de los resultados
        all_text = " ".join(r["text"] for r in search_results)
        result["inflation"] = _extract_inflation(all_text, country)
        result["growth_trend"] = _extract_growth(all_text, sector)
        result["risks"] = _extract_risks(all_text, sector, country)

    return result if search_results else None


def _extract_inflation(text: str, country: str) -> dict:
    """Extrae datos de inflación del texto de búsqueda."""
    # Buscar patrones como "inflación del X%", "IPC X%", "X% anual"
    patterns = [
        r'inflaci[oó]n\s+(?:del?\s+)?(\d+[.,]\d+)\s*%',
        r'IPC\s+(?:de\s+)?(\d+[.,]\d+)\s*%',
        r'(\d+[.,]\d+)\s*%\s+(?:anual|interanual)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = float(match.group(1).replace(",", "."))
            return {
                "annual_pct": value,
                "monthly_pct": round((1 + value / 100) ** (1 / 12) - 1, 4) * 100,
                "source": "búsqueda web",
                "confidence": "media",
            }

    # Valores por defecto por país
    country_inflation = {
        "chile": 4.5, "colombia": 7.0, "mexico": 5.5, "argentina": 60.0,
        "peru": 3.5, "uruguay": 6.0, "españa": 3.0, "default": 5.0,
    }
    country_key = country.lower().replace("é", "e").replace("á", "a")
    default_val = country_inflation.get(country_key, country_inflation["default"])

    return {
        "annual_pct": default_val,
        "monthly_pct": round((1 + default_val / 100) ** (1 / 12) - 1, 4) * 100,
        "source": "estimación por país",
        "confidence": "baja",
    }


def _extract_growth(text: str, sector: str) -> dict:
    """Extrae datos de crecimiento del sector."""
    patterns = [
        r'creci(?:miento|ó)\s+(?:del?\s+)?(\d+[.,]\d+)\s*%',
        r'(\d+[.,]\d+)\s*%\s+de\s+crecimiento',
        r'aument[oó]\s+(?:del?\s+)?(\d+[.,]\d+)\s*%',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = float(match.group(1).replace(",", "."))
            return {
                "annual_pct": value,
                "source": "búsqueda web",
                "confidence": "media",
            }

    return {
        "annual_pct": 5.0,
        "source": "estimación general",
        "confidence": "baja",
    }


def _extract_risks(text: str, sector: str, country: str) -> List[dict]:
    """Extrae factores de riesgo mencionados en los resultados."""
    risks = []
    risk_keywords = {
        "inflación": "Presión inflacionaria puede aumentar costos operativos",
        "recesión": "Riesgo de recesión económica puede reducir la demanda",
        "competencia": "Aumento de competencia en el sector",
        "regulación": "Cambios regulatorios pueden afectar la operación",
        "tipo de cambio": "Volatilidad cambiaria puede afectar costos de importación",
        "desempleo": "Aumento del desempleo puede reducir el consumo",
        "sequía": "Condiciones climáticas adversas pueden afectar la producción",
        "pandemia": "Riesgos sanitarios pueden restringir la operación",
    }

    text_lower = text.lower()
    for keyword, description in risk_keywords.items():
        if keyword in text_lower:
            risks.append({"factor": keyword, "descripcion": description, "source": "búsqueda web"})

    return risks[:5]  # Máximo 5 riesgos


def _get_fallback_market_data(sector: str, country: str, result: dict) -> dict:
    """
    Proporciona datos de mercado predefinidos cuando no hay internet.
    Basados en promedios regionales y sectoriales conocidos.
    """
    # Estacionalidad por sector (factores mensuales)
    sector_seasonality = {
        "panaderia": {1: 0.85, 2: 0.80, 3: 0.90, 4: 0.95, 5: 1.0, 6: 1.05,
                      7: 1.0, 8: 0.95, 9: 1.05, 10: 1.0, 11: 1.05, 12: 1.20},
        "restaurante": {1: 0.80, 2: 0.85, 3: 0.95, 4: 1.0, 5: 1.0, 6: 0.90,
                        7: 0.85, 8: 0.90, 9: 1.05, 10: 1.05, 11: 1.10, 12: 1.25},
        "retail": {1: 0.70, 2: 0.75, 3: 1.0, 4: 0.90, 5: 1.10, 6: 0.85,
                   7: 0.80, 8: 0.85, 9: 1.0, 10: 1.0, 11: 1.20, 12: 1.45},
        "servicios": {1: 0.75, 2: 0.85, 3: 1.05, 4: 1.05, 5: 1.05, 6: 1.0,
                      7: 0.85, 8: 0.80, 9: 1.05, 10: 1.10, 11: 1.05, 12: 0.85},
        "tecnologia": {1: 0.85, 2: 0.90, 3: 1.0, 4: 1.05, 5: 1.05, 6: 1.10,
                       7: 0.90, 8: 0.85, 9: 1.10, 10: 1.10, 11: 1.05, 12: 0.90},
        "default": {1: 0.90, 2: 0.85, 3: 0.95, 4: 1.0, 5: 1.0, 6: 0.95,
                    7: 0.90, 8: 0.90, 9: 1.05, 10: 1.05, 11: 1.10, 12: 1.15},
    }

    # Inflación por país (estimaciones 2025-2026)
    country_inflation = {
        "chile": {"annual_pct": 4.5, "source": "estimación BCCh"},
        "colombia": {"annual_pct": 7.0, "source": "estimación BanRep"},
        "mexico": {"annual_pct": 5.5, "source": "estimación Banxico"},
        "argentina": {"annual_pct": 60.0, "source": "estimación BCRA"},
        "peru": {"annual_pct": 3.5, "source": "estimación BCRP"},
        "uruguay": {"annual_pct": 6.0, "source": "estimación BCU"},
        "españa": {"annual_pct": 3.0, "source": "estimación BCE"},
        "default": {"annual_pct": 5.0, "source": "estimación general"},
    }

    # Determinar sector para estacionalidad
    sector_key = _match_sector_key(sector)
    seasonality = sector_seasonality.get(sector_key, sector_seasonality["default"])

    # Determinar inflación por país
    country_key = country.lower().replace("é", "e").replace("á", "a") if country else "default"
    inflation_data = country_inflation.get(country_key, country_inflation["default"])

    result["seasonality"] = {
        "monthly_factors": seasonality,
        "source": f"promedio histórico sector {sector_key}",
        "confidence": "media",
    }
    result["inflation"] = {
        "annual_pct": inflation_data["annual_pct"],
        "monthly_pct": round((1 + inflation_data["annual_pct"] / 100) ** (1 / 12) - 1, 4) * 100,
        "source": inflation_data["source"],
        "confidence": "media",
    }
    result["growth_trend"] = {
        "annual_pct": 5.0,
        "source": "promedio PYME regional",
        "confidence": "baja",
    }
    result["risks"] = [
        {"factor": "inflación", "descripcion": "Presión inflacionaria puede aumentar costos operativos"},
        {"factor": "competencia", "descripcion": "Aumento de competencia en el sector"},
    ]
    result["search_successful"] = False
    result["fallback_used"] = True

    return result


def _match_sector_key(sector: str) -> str:
    """Mapea el sector del usuario a una clave de estacionalidad."""
    if not sector:
        return "default"

    sector_lower = sector.lower()
    mappings = {
        "panaderia": ["panaderia", "panadería", "pan", "bakery", "pasteleria", "pastelería"],
        "restaurante": ["restaurante", "restaurant", "comida", "food", "cocina", "cafeteria", "café", "bar"],
        "retail": ["ropa", "tienda", "comercio", "retail", "boutique", "calzado", "ferreteria", "farmacia"],
        "servicios": ["consultoria", "consultoría", "servicios", "asesoria", "asesoría", "abogado", "contador"],
        "tecnologia": ["tecnologia", "tecnología", "software", "it", "digital", "saas", "app"],
    }

    for key, keywords in mappings.items():
        if any(kw in sector_lower for kw in keywords):
            return key

    return "default"


def _sanitize_key(text: str) -> str:
    """Sanitiza texto para usar como clave de cache."""
    if not text:
        return "unknown"
    # Remover caracteres especiales y limitar longitud
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', text.lower())
    return clean[:30]


def get_market_seasonality_factors(market_data: dict) -> Dict[int, float]:
    """
    Extrae los factores de estacionalidad del resultado de búsqueda de mercado.
    Retorna un diccionario {mes: factor} para aplicar al modelo.
    """
    seasonality = market_data.get("seasonality", {})
    factors = seasonality.get("monthly_factors", {})

    if factors:
        # Asegurar que las claves son enteros
        return {int(k): float(v) for k, v in factors.items()}

    return {}


def get_inflation_rate(market_data: dict) -> float:
    """Extrae la tasa de inflación anual del resultado de búsqueda."""
    inflation = market_data.get("inflation", {})
    return inflation.get("annual_pct", 0)
