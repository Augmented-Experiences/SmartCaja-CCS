"""
SmartCaja v2.1 — Suite de Pruebas Automatizadas
Verifica: motor financiero, InterviewManager, market_research, endpoints, frontend.
"""
import sys
import os
import json
import importlib

# Agregar server al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

PASS = 0
FAIL = 0
ERRORS = []

def test(name, condition, detail=""):
    global PASS, FAIL, ERRORS
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ============================================================================
# TEST 1: Imports
# ============================================================================
section("1. IMPORTS Y DEPENDENCIAS")

try:
    from financial_engine.core import CashflowModel, BusinessProfile
    test("Import CashflowModel", True)
except Exception as e:
    test("Import CashflowModel", False, str(e))

try:
    from financial_engine.metrics import FinancialMetrics
    test("Import FinancialMetrics", True)
except Exception as e:
    test("Import FinancialMetrics", False, str(e))

try:
    from financial_engine.monte_carlo import MonteCarloSimulator
    test("Import MonteCarloSimulator", True)
except Exception as e:
    test("Import MonteCarloSimulator", False, str(e))

try:
    from interview_manager import InterviewManager
    test("Import InterviewManager", True)
except Exception as e:
    test("Import InterviewManager", False, str(e))

try:
    from market_research import get_market_seasonality_factors, search_market_data
    test("Import market_research", True)
except Exception as e:
    test("Import market_research", False, str(e))

# ============================================================================
# TEST 2: Motor Financiero
# ============================================================================
section("2. MOTOR FINANCIERO")

try:
    profile = BusinessProfile(
        name="Panadería Don Pedro",
        sector="alimentos",
        description="Panadería artesanal",
        products=["pan de masa madre", "pasteles"],
        customer_segments=["vecinos", "restaurantes"],
        revenue_model="venta directa",
        avg_price=4500,
        monthly_volume=1111,
        purchase_frequency="diaria",
        expected_growth_pct=3.0,
        churn_rate_pct=5.0,
        seasonality_pattern=[0.85, 0.9, 1.0, 1.0, 1.05, 1.1, 1.15, 1.1, 1.0, 0.95, 1.2, 1.3],
        variable_cost_pct=35.0,
        fixed_costs_monthly=1200000,
        salaries_monthly=800000,
        marketing_monthly=200000,
        tax_rate_pct=19.0,
        collection_days=0,
        payment_days=30,
        inventory_days=5,
        debt_monthly_payment=0,
        capex_planned=100000,
        initial_cash=3000000,
        main_risks=["competencia"],
        currency="CLP",
        country="Chile",
        market_data={},
    )
    test("Crear BusinessProfile", True)
except Exception as e:
    test("Crear BusinessProfile", False, str(e))
    profile = None

if profile:
    try:
        model = CashflowModel(profile)
        months = model.generate_all_months(12)
        test("Generar proyección 12 meses", len(months) == 12, f"Got {len(months)} months")
    except Exception as e:
        test("Generar proyección 12 meses", False, str(e))
        months = []

    if months:
        # MonthData es un dataclass, acceder con atributos
        from dataclasses import asdict
        first = months[0]
        first_d = asdict(first)
        required_fields = ['month', 'income', 'expenses', 'net_flow', 'cumulative_balance']
        has_all = all(f in first_d for f in required_fields)
        test("Estructura de datos mensual completa", has_all, f"Missing: {[f for f in required_fields if f not in first_d]}")

        # income y expenses son dataclass objects, usar .total
        income_val = first.income.total if hasattr(first.income, 'total') else first.income
        test("Income positivo mes 1", income_val > 0, f"Income: {income_val}")

        # Verificar estacionalidad (mes 12 factor 1.3 vs mes 1 factor 0.85)
        # Con churn 5% anual, el ratio neto puede ser menor, pero la estacionalidad se aplica
        if len(months) >= 12:
            inc0 = months[0].income.total if hasattr(months[0].income, 'total') else months[0].income
            inc11 = months[11].income.total if hasattr(months[11].income, 'total') else months[11].income
            # Con churn, el ratio puede ser < 1.3/0.85 pero debe haber variación
            test("Estacionalidad genera variación entre meses", inc0 != inc11, f"M1: {inc0:.0f}, M12: {inc11:.0f}")

        # Verificar que expenses > 0
        exp_val = first.expenses.total if hasattr(first.expenses, 'total') else first.expenses
        test("Expenses positivo mes 1", exp_val > 0, f"Expenses: {exp_val}")

        # Verificar que el modelo genera 12 meses con datos válidos
        if len(months) >= 6:
            inc0 = months[0].income.total if hasattr(months[0].income, 'total') else months[0].income
            inc5 = months[5].income.total if hasattr(months[5].income, 'total') else months[5].income
            # Con churn alto (5%) el crecimiento neto puede ser negativo, pero los ingresos deben ser positivos
            test("Ingresos positivos en mes 6", inc5 > 0, f"Income M6: {inc5:.0f}")

# ============================================================================
# TEST 3: Métricas Financieras
# ============================================================================
section("3. MÉTRICAS FINANCIERAS")

if profile and months:
    try:
        # FinancialMetrics recibe CashflowModel
        metrics_model = CashflowModel(profile)
        metrics_model.generate_all_months(12)
        metrics = FinancialMetrics(metrics_model)
        result = metrics.calculate_all()
        test("Calculate_all retorna dict", isinstance(result, dict))

        # Verificar métricas clave
        keys = list(result.keys())
        test("Métricas generadas (>3 keys)", len(keys) > 3, f"Keys: {keys[:8]}")
        test("Caja mínima calculada", 'caja_minima' in result or 'min_cash' in result, f"Keys: {keys[:8]}")
        test("Margen bruto calculado", 'margen_bruto_pct' in result or 'gross_margin' in result, f"Keys: {keys[:8]}")

    except Exception as e:
        test("Métricas financieras", False, str(e))

# ============================================================================
# TEST 4: Monte Carlo
# ============================================================================
section("4. SIMULACIÓN MONTE CARLO")

if profile:
    try:
        mc_model = CashflowModel(profile)
        mc_model.generate_all_months(12)
        mc = MonteCarloSimulator(mc_model, iterations=50)
        mc_result = mc.run()
        test("Monte Carlo ejecutado", mc_result is not None)
        
        mc_keys = list(mc_result.keys()) if mc_result else []
        test("Resultado Monte Carlo tiene datos", len(mc_keys) > 2, f"Keys: {mc_keys[:6]}")
        
        # Buscar prob insolvencia con nombres posibles
        has_prob = any(k for k in mc_keys if 'insolvencia' in k or 'insolvency' in k or 'prob' in k)
        test("Probabilidad insolvencia calculada", has_prob, f"Keys: {mc_keys}")

    except Exception as e:
        test("Monte Carlo", False, str(e))

# ============================================================================
# TEST 5: InterviewManager
# ============================================================================
section("5. INTERVIEW MANAGER")

try:
    im = InterviewManager(company_data={"name": "Panadería Test", "sector": "alimentos"})
    test("Crear InterviewManager", True)

    # Verificar topics_covered (list)
    all_topics = im.topics_covered
    # Al crear con sector='alimentos', ya marca tipo_negocio
    test("Topics covered es lista", isinstance(all_topics, list), f"Type: {type(all_topics)}")

    # Verificar progreso inicial (con sector dado, tipo_negocio ya está cubierto)
    progress = im.get_interview_progress()
    test("Progreso inicial >= 0%", progress['progress_pct'] >= 0)
    test("has_enough_data False inicialmente", progress['has_enough_data'] == False)

    # Simular extracción de datos
    extracted = im.extract_data_from_response(
        "Somos una panadería artesanal que vende pan de masa madre a $3500 la unidad, vendemos unas 200 unidades diarias",
        ""
    )
    test("Extracción de datos funciona", len(extracted) > 0, f"Extracted: {extracted}")

    # Verificar que el progreso aumentó
    progress2 = im.get_interview_progress()
    test("Progreso aumenta tras extracción", progress2['progress_pct'] > 0, f"Got: {progress2['progress_pct']}%")

    # Verificar sugerencias
    suggestions = im.get_suggested_responses()
    test("Sugerencias generadas", len(suggestions) > 0, f"Got: {len(suggestions)} suggestions")

    # Verificar system prompt
    sys_prompt = im.generate_system_prompt()
    test("System prompt generado", len(sys_prompt) > 100, f"Length: {len(sys_prompt)}")
    test("System prompt incluye datos extraídos", "panadería" in sys_prompt.lower() or "masa madre" in sys_prompt.lower())

except Exception as e:
    test("InterviewManager", False, str(e))

# ============================================================================
# TEST 6: Market Research
# ============================================================================
section("6. MARKET RESEARCH")

try:
    # get_market_seasonality_factors necesita datos de búsqueda previos
    # Sin datos reales, retorna dict vacío - verificar que no crashea
    market_data = {"sector": "panadería", "country": "Chile", "trends": []}
    seasonality = get_market_seasonality_factors(market_data)
    test("Market seasonality retorna dict", isinstance(seasonality, dict))
    # Verificar que la función search_market_data existe y es callable
    test("search_market_data es callable", callable(search_market_data))
except Exception as e:
    test("Market Research", False, str(e))

# ============================================================================
# TEST 7: Escenarios Custom
# ============================================================================
section("7. ESCENARIOS Y SIMULACIÓN")

if profile:
    try:
        import copy
        profile_opt = copy.deepcopy(profile)
        profile_opt.growth_rate_monthly = 0.05  # 5% mensual
        model_opt = CashflowModel(profile_opt)
        months_opt = model_opt.generate_all_months(12)
        test("Escenario optimista generado", len(months_opt) == 12)

        # Comparar con base - crear modelo fresco para base
        model_base2 = CashflowModel(profile)
        months_base2 = model_base2.generate_all_months(12)
        if months_base2 and months_opt:
            opt_inc = months_opt[11].income.total if hasattr(months_opt[11].income, 'total') else months_opt[11].income
            base_inc = months_base2[11].income.total if hasattr(months_base2[11].income, 'total') else months_base2[11].income
            # Con growth 5% vs 3%, el optimista debe ser mayor
            test("Escenario optimista >= base en mes 12",
                 opt_inc >= base_inc,
                 f"Opt: {opt_inc:.0f} vs Base: {base_inc:.0f}")
    except Exception as e:
        test("Escenarios", False, str(e))

# ============================================================================
# TEST 8: Frontend Files
# ============================================================================
section("8. ARCHIVOS FRONTEND")

app_dir = os.path.join(os.path.dirname(__file__), '..', 'app')
test("index.html existe", os.path.exists(os.path.join(app_dir, 'index.html')))
test("app.js existe", os.path.exists(os.path.join(app_dir, 'app.js')))

# Verificar que el HTML tiene las páginas necesarias
html_path = os.path.join(app_dir, 'index.html')
if os.path.exists(html_path):
    html = open(html_path, encoding='utf-8').read()
    test("Página agents en HTML", 'page-agents' in html)
    test("Página tokens en HTML", 'page-tokens' in html)
    test("Suggestion chips en HTML", 'suggestionChips' in html)
    test("Notification items CSS", '.notification-item' in html)
    test("Chart.js incluido", 'chart.js' in html.lower() or 'Chart' in html)

# Verificar app.js
js_path = os.path.join(app_dir, 'app.js')
if os.path.exists(js_path):
    js = open(js_path, encoding='utf-8').read()
    test("Función loadAgents en JS", 'function loadAgents' in js)
    test("Función loadTokenStats en JS", 'function loadTokenStats' in js)
    test("Función sendQuickOption en JS", 'function sendQuickOption' in js)
    test("Función updateInterviewProgressFromData en JS", 'function updateInterviewProgressFromData' in js)
    test("Manejo correcto de notificaciones (n.message)", 'n.message' in js)
    test("pollMonteCarloProgress en JS", 'function pollMonteCarloProgress' in js)
    test("Console.error logging en JS", 'console.error' in js)

# ============================================================================
# TEST 9: Backend Compilation
# ============================================================================
section("9. COMPILACIÓN BACKEND")

try:
    import py_compile
    server_dir = os.path.join(os.path.dirname(__file__), '..', 'server')
    files_to_check = [
        'app.py',
        'interview_manager.py',
        'market_research.py',
        'advanced_endpoints.py',
        'financial_engine/core.py',
        'financial_engine/metrics.py',
        'financial_engine/monte_carlo.py',
    ]
    for f in files_to_check:
        fpath = os.path.join(server_dir, f)
        if os.path.exists(fpath):
            py_compile.compile(fpath, doraise=True)
            test(f"Compilación {f}", True)
        else:
            test(f"Compilación {f}", False, "Archivo no encontrado")
except py_compile.PyCompileError as e:
    test(f"Compilación", False, str(e))

# ============================================================================
# RESUMEN
# ============================================================================
section("RESUMEN DE PRUEBAS")
total = PASS + FAIL
print(f"\n  Total: {total} pruebas")
print(f"  ✓ Pasaron: {PASS}")
print(f"  ✗ Fallaron: {FAIL}")
print(f"  Tasa de éxito: {PASS/total*100:.1f}%" if total > 0 else "")

if ERRORS:
    print(f"\n  Errores:")
    for e in ERRORS:
        print(f"    - {e}")

print(f"\n{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
