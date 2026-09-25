"""
Tests para las correcciones de:
1. Sanitización de inf/nan en JSON
2. Chips contextuales correctos según tipo de pregunta
3. Trigger de generación automática
"""
import sys
import os
import math

# Agregar server al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


# ============================================================================
# Test 1: Sanitización de inf/nan
# ============================================================================

def test_sanitize_for_json():
    """Verifica que _sanitize_for_json reemplaza inf/nan con 0.0"""
    # Importar desde advanced_endpoints
    from advanced_endpoints import _sanitize_for_json

    # Caso: float inf
    assert _sanitize_for_json(float('inf')) == 0.0
    assert _sanitize_for_json(float('-inf')) == 0.0
    assert _sanitize_for_json(float('nan')) == 0.0

    # Caso: número normal
    assert _sanitize_for_json(42.5) == 42.5
    assert _sanitize_for_json(0.0) == 0.0

    # Caso: dict con inf
    data = {"runway": float('inf'), "margin": 0.35, "name": "test"}
    result = _sanitize_for_json(data)
    assert result["runway"] == 0.0
    assert result["margin"] == 0.35
    assert result["name"] == "test"

    # Caso: lista con nan
    data = [1.0, float('nan'), 3.0]
    result = _sanitize_for_json(data)
    assert result == [1.0, 0.0, 3.0]

    # Caso: nested
    data = {"metrics": {"runway": float('inf'), "values": [float('nan'), 1.0]}}
    result = _sanitize_for_json(data)
    assert result["metrics"]["runway"] == 0.0
    assert result["metrics"]["values"] == [0.0, 1.0]

    print("✓ test_sanitize_for_json PASSED")


def test_sanitize_dict_in_app():
    """Verifica que _sanitize_dict en app.py funciona correctamente"""
    from app import _sanitize_dict

    data = {"a": float('inf'), "b": [float('nan'), 1.0], "c": {"d": float('-inf')}}
    result = _sanitize_dict(data)
    assert result["a"] == 0.0
    assert result["b"] == [0.0, 1.0]
    assert result["c"]["d"] == 0.0

    print("✓ test_sanitize_dict_in_app PASSED")


# ============================================================================
# Test 2: Chips contextuales
# ============================================================================

def test_chips_yes_no_question():
    """Verifica que preguntas sí/no generan chips de sí/no, no de montos"""
    from interview_manager import InterviewManager

    im = InterviewManager(
        company_data={"name": "Test", "sector": "panadería"},
        persisted_data={},
        persisted_topics=[]
    )

    # Pregunta sí/no sobre deuda
    chips = im._generate_contextual_chips("¿Tienes alguna deuda o crédito bancario?")
    assert "Sí, tengo deudas" in chips or "Sí" in chips
    # No debe tener valores de dinero
    for chip in chips:
        assert "$" not in chip, f"Chip incorrecto para pregunta sí/no: {chip}"

    print("✓ test_chips_yes_no_question PASSED")


def test_chips_money_question():
    """Verifica que preguntas de montos generan chips con valores numéricos"""
    from interview_manager import InterviewManager

    im = InterviewManager(
        company_data={"name": "Test", "sector": "panadería"},
        persisted_data={},
        persisted_topics=[]
    )

    # Pregunta de monto mensual
    chips = im._generate_contextual_chips("¿Cuánto pagas de arriendo al mes?")
    assert len(chips) > 0
    # Debe tener al menos un chip con $
    has_money = any("$" in chip for chip in chips)
    assert has_money, f"Chips para pregunta de monto no tienen $: {chips}"

    print("✓ test_chips_money_question PASSED")


def test_chips_confirmation_question():
    """Verifica que preguntas de confirmación generan chips apropiados"""
    from interview_manager import InterviewManager

    im = InterviewManager(
        company_data={"name": "Test", "sector": "panadería"},
        persisted_data={},
        persisted_topics=[]
    )

    # Pregunta de confirmación para generar cashflow
    chips = im._generate_contextual_chips("¿Quieres que genere tu flujo de caja ahora?")
    assert len(chips) > 0
    # Debe tener chip de "genera"
    has_generate = any("genera" in chip.lower() or "cashflow" in chip.lower() for chip in chips)
    assert has_generate, f"Chips para confirmación no tienen opción de generar: {chips}"

    print("✓ test_chips_confirmation_question PASSED")


def test_chips_percentage_question():
    """Verifica que preguntas de porcentaje generan chips con %"""
    from interview_manager import InterviewManager

    im = InterviewManager(
        company_data={"name": "Test", "sector": "panadería"},
        persisted_data={},
        persisted_topics=[]
    )

    chips = im._generate_contextual_chips("¿Qué porcentaje de tus ventas se va en costos variables?")
    assert len(chips) > 0
    has_pct = any("%" in chip for chip in chips)
    assert has_pct, f"Chips para pregunta de porcentaje no tienen %: {chips}"

    print("✓ test_chips_percentage_question PASSED")


def test_chips_frequency_question():
    """Verifica que preguntas de frecuencia generan chips de tiempo"""
    from interview_manager import InterviewManager

    im = InterviewManager(
        company_data={"name": "Test", "sector": "panadería"},
        persisted_data={},
        persisted_topics=[]
    )

    chips = im._generate_contextual_chips("¿Cada cuánto te compran tus clientes?")
    assert len(chips) > 0
    time_words = ["diario", "semanal", "quincenal", "mensual", "esporádico"]
    has_time = any(any(tw in chip.lower() for tw in time_words) for chip in chips)
    assert has_time, f"Chips para frecuencia no tienen opciones de tiempo: {chips}"

    print("✓ test_chips_frequency_question PASSED")


# ============================================================================
# Test 3: Memoria de datos en system prompt
# ============================================================================

def test_system_prompt_includes_all_numbers():
    """Verifica que el system prompt incluye todos los datos numéricos recopilados"""
    from interview_manager import InterviewManager

    im = InterviewManager(
        company_data={"name": "Panadería Test", "sector": "panadería"},
        persisted_data={
            "name": "Panadería Test",
            "sector": "panadería",
            "avg_price": 3500,
            "monthly_volume": 200,
            "fixed_costs_monthly": 1500000,
            "salaries_monthly": 2000000,
            "initial_cash": 5000000,
        },
        persisted_topics=["tipo_negocio", "productos_servicios", "precios_volumen"]
    )

    prompt = im.generate_system_prompt()

    # Verificar que los datos están en el prompt
    assert "3,500" in prompt or "3.500" in prompt, "Precio promedio no está en el prompt"
    assert "1,500,000" in prompt or "1.500.000" in prompt, "Costos fijos no están en el prompt"
    assert "2,000,000" in prompt or "2.000.000" in prompt, "Salarios no están en el prompt"
    assert "5,000,000" in prompt or "5.000.000" in prompt, "Caja inicial no está en el prompt"
    assert "MEMORIA" in prompt or "DATOS CONFIRMADOS" in prompt, "Sección de memoria no está en el prompt"
    assert "CONFIRMA" in prompt.upper() or "confirma" in prompt.lower(), "Regla de confirmación no está"

    print("✓ test_system_prompt_includes_all_numbers PASSED")


def test_company_seed_marks_topics_not_salaries():
    from interview_manager import InterviewManager

    im = InterviewManager(company_data={
        "name": "Panadería Don Pedro",
        "sector": "alimentos",
        "country": "Chile",
        "currency": "CLP",
        "initial_cash": 5000000,
        "employees": 4,
    })
    assert "tipo_negocio" in im.topics_covered
    assert "pais_moneda" in im.topics_covered
    assert "caja_inicial" in im.topics_covered
    assert "salarios" not in im.topics_covered
    progress = im.get_interview_progress()
    assert progress["covered"] >= 3
    assert progress["progress_pct"] == round(progress["covered"] / progress["total_topics"] * 100, 1)
    next_q = im.get_next_questions(1)
    assert next_q[0]["id"] == "productos_servicios"
    print("✓ test_company_seed_marks_topics_not_salaries PASSED")


def test_interview_follows_panel_order_and_focus():
    from interview_manager import InterviewManager, INTERVIEW_FLOW

    im = InterviewManager(company_data={"name": "Test", "sector": "comercio"})
    questions = im.get_next_questions(5)
    ids = [q["id"] for q in questions]
    assert ids[0] in INTERVIEW_FLOW
    assert "tipo_negocio" not in ids
    im.focus_topic = "salarios"
    focused = im.get_next_questions(1)
    assert focused[0]["id"] == "salarios"
    prompt = im.generate_system_prompt()
    assert "FORMULARIO" in prompt or "confirmar" in prompt.lower()
    assert "Generar Cashflow" in prompt or "botón" in prompt.lower()
    print("✓ test_interview_follows_panel_order_and_focus PASSED")


def test_glossary_and_risk_label():
    from interview_manager import GLOSSARY, interview_panel
    from financial_engine.monte_carlo import MonteCarloSimulator

    assert "costos_fijos" in GLOSSARY
    assert GLOSSARY["salarios"]["calculator"] == "salary_chile"
    panel = interview_panel()
    assert len(panel) == 5
    assert panel[0]["topics"][0]["id"] == "tipo_negocio"
    stub = MonteCarloSimulator.__new__(MonteCarloSimulator)
    assert stub._classify_risk(40)["nivel"] == "Crítico"
    assert stub._classify_risk(2)["nivel"] == "Bajo"
    print("✓ test_glossary_and_risk_label PASSED")


# ============================================================================
# Run all tests
# ============================================================================

if __name__ == "__main__":
    test_sanitize_for_json()
    test_sanitize_dict_in_app()
    test_chips_yes_no_question()
    test_chips_money_question()
    test_chips_confirmation_question()
    test_chips_percentage_question()
    test_chips_frequency_question()
    test_system_prompt_includes_all_numbers()
    test_company_seed_marks_topics_not_salaries()
    test_interview_follows_panel_order_and_focus()
    test_glossary_and_risk_label()
    print("\n✅ ALL TESTS PASSED")
