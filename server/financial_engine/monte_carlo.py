"""
monte_carlo.py — Simulación probabilística Monte Carlo para flujo de caja.
Ejecuta N iteraciones variando aleatoriamente las variables clave del negocio
para calcular la probabilidad de insolvencia, distribución de resultados y
bandas de confianza.

Optimizado para hardware limitado de PYMEs (sin numpy/scipy, usa random stdlib).
"""

import random
import math
import copy
from typing import List, Dict, Optional, Tuple, Callable
from .core import CashflowModel, MonthData, BusinessProfile, IncomeData, ExpenseData
from datetime import date


class MonteCarloSimulator:
    """
    Simulador Monte Carlo para flujo de caja.
    Ejecuta múltiples iteraciones variando las variables del negocio
    según distribuciones de probabilidad configurables.
    """

    def __init__(self, model: CashflowModel, iterations: int = 1000, seed: int = None):
        """
        Args:
            model: CashflowModel base sobre el cual simular.
            iterations: Número de iteraciones Monte Carlo (default 1000).
            seed: Semilla para reproducibilidad (opcional).
        """
        self.model = model
        self.iterations = min(iterations, 5000)  # Limitar para hardware limitado
        self.seed = seed
        # Usar instancia propia de Random para thread-safety (no contamina estado global)
        self._rng = random.Random(seed)

        # Configuración de variabilidad por variable (desviación estándar como % del valor)
        self.variability = {
            "sales": 0.15,              # ±15% variación en ventas
            "variable_costs": 0.10,     # ±10% variación en costos variables
            "fixed_costs": 0.05,        # ±5% variación en costos fijos
            "new_customers": 0.20,      # ±20% variación en nuevos clientes
            "churn": 0.25,              # ±25% variación en churn
            "seasonality": 0.10,        # ±10% variación en estacionalidad
            "market": 0.12,             # ±12% variación por factores de mercado
            "inflation": 0.30,          # ±30% variación en inflación
        }

        # Escenarios predefinidos para simulación rápida
        self.scenarios_config = {
            "optimista": {"sales_mult": 1.2, "costs_mult": 0.95, "growth_mult": 1.3},
            "pesimista": {"sales_mult": 0.8, "costs_mult": 1.15, "growth_mult": 0.7},
            "crisis": {"sales_mult": 0.6, "costs_mult": 1.25, "growth_mult": 0.4},
            "boom": {"sales_mult": 1.4, "costs_mult": 1.05, "growth_mult": 1.5},
        }

    def run(self, progress_callback: Callable = None) -> dict:
        """
        Ejecuta la simulación Monte Carlo completa.
        
        Args:
            progress_callback: Función que recibe (iteration, total, message)
            
        Returns:
            Diccionario con resultados completos de la simulación.
        """
        results = []
        caja_final_distribution = []
        min_caja_distribution = []
        insolvency_count = 0
        monthly_distributions = [[] for _ in range(len(self.model.months))]

        for i in range(self.iterations):
            # Generar variaciones aleatorias para esta iteración
            iteration_result = self._run_single_iteration()
            results.append(iteration_result)

            caja_final = iteration_result["caja_final"]
            caja_final_distribution.append(caja_final)
            min_caja_distribution.append(iteration_result["caja_minima"])

            if iteration_result["tiene_insolvencia"]:
                insolvency_count += 1

            # Guardar distribución mensual
            for j, balance in enumerate(iteration_result["balances_mensuales"]):
                monthly_distributions[j].append(balance)

            # Notificar progreso cada 10% de iteraciones
            if progress_callback and (i % max(1, self.iterations // 10) == 0):
                pct = int((i / self.iterations) * 100)
                progress_callback(i, self.iterations, f"Iteración {i}/{self.iterations} ({pct}%)")

        # Calcular estadísticas
        prob_insolvencia = (insolvency_count / self.iterations) * 100

        # Percentiles de caja final
        caja_final_sorted = sorted(caja_final_distribution)
        p5 = caja_final_sorted[int(self.iterations * 0.05)]
        p25 = caja_final_sorted[int(self.iterations * 0.25)]
        p50 = caja_final_sorted[int(self.iterations * 0.50)]
        p75 = caja_final_sorted[int(self.iterations * 0.75)]
        p95 = caja_final_sorted[int(self.iterations * 0.95)]

        # Bandas de confianza mensuales (P10, P50, P90)
        bandas_mensuales = []
        for j, dist in enumerate(monthly_distributions):
            if not dist:
                continue
            dist_sorted = sorted(dist)
            n = len(dist_sorted)
            bandas_mensuales.append({
                "mes": self.model.months[j].label if j < len(self.model.months) else f"Mes {j+1}",
                "p10": round(dist_sorted[int(n * 0.10)], 2),
                "p25": round(dist_sorted[int(n * 0.25)], 2),
                "p50": round(dist_sorted[int(n * 0.50)], 2),
                "p75": round(dist_sorted[int(n * 0.75)], 2),
                "p90": round(dist_sorted[int(n * 0.90)], 2),
                "media": round(sum(dist) / len(dist), 2),
            })

        # Estadísticas de caja mínima
        min_caja_sorted = sorted(min_caja_distribution)

        # VaR (Value at Risk) al 95%
        var_95 = abs(min(0, caja_final_sorted[int(self.iterations * 0.05)]))

        return {
            "iteraciones": self.iterations,
            "probabilidad_insolvencia_pct": round(prob_insolvencia, 1),
            "caja_final": {
                "media": round(sum(caja_final_distribution) / len(caja_final_distribution), 2),
                "mediana": round(p50, 2),
                "p5": round(p5, 2),
                "p25": round(p25, 2),
                "p75": round(p75, 2),
                "p95": round(p95, 2),
                "min": round(min(caja_final_distribution), 2),
                "max": round(max(caja_final_distribution), 2),
                "desviacion_estandar": round(self._std_dev(caja_final_distribution), 2),
            },
            "caja_minima": {
                "media": round(sum(min_caja_distribution) / len(min_caja_distribution), 2),
                "p5": round(min_caja_sorted[int(self.iterations * 0.05)], 2),
                "p50": round(min_caja_sorted[int(self.iterations * 0.50)], 2),
                "p95": round(min_caja_sorted[int(self.iterations * 0.95)], 2),
            },
            "var_95": round(var_95, 2),
            "bandas_mensuales": bandas_mensuales,
            "escenarios_predefinidos": self._run_predefined_scenarios(),
            "distribucion_histograma": self._build_histogram(caja_final_distribution, bins=20),
            "nivel_riesgo": self._classify_risk(prob_insolvencia),
        }

    def _run_single_iteration(self) -> dict:
        """Ejecuta una iteración individual con variaciones aleatorias."""
        cumulative = self.model.initial_cash
        min_caja = cumulative
        tiene_insolvencia = False
        balances = []

        for i, month in enumerate(self.model.months):
            # Variación en ventas (distribución normal truncada)
            sales_var = self._random_normal(1.0, self.variability["sales"])
            sales = month.income.sales * sales_var

            # Variación en costos variables (correlacionada parcialmente con ventas)
            costs_var = self._random_normal(1.0, self.variability["variable_costs"])
            # Los costos variables se mueven parcialmente con las ventas
            cost_sales_correlation = 0.6
            costs_factor = cost_sales_correlation * sales_var + (1 - cost_sales_correlation) * costs_var
            variable_costs = month.expenses.variable_costs * costs_factor

            # Variación en costos fijos (menor variabilidad)
            fixed_var = self._random_normal(1.0, self.variability["fixed_costs"])
            fixed_costs = month.expenses.fixed_costs * fixed_var

            # Otros gastos con menor variación
            var_expenses = month.expenses.variable_expenses * self._random_normal(1.0, 0.08)
            debt = month.expenses.debt_payments  # Deuda es fija
            taxes = month.expenses.taxes * sales_var  # Impuestos correlacionados con ventas
            investments = month.expenses.investments  # Inversiones son planificadas

            # Calcular flujo neto
            income_total = sales + month.income.other_income
            expenses_total = variable_costs + fixed_costs + var_expenses + debt + taxes + investments
            net_flow = income_total - expenses_total

            cumulative += net_flow
            balances.append(cumulative)

            if cumulative < min_caja:
                min_caja = cumulative
            if cumulative < 0:
                tiene_insolvencia = True

        return {
            "caja_final": cumulative,
            "caja_minima": min_caja,
            "tiene_insolvencia": tiene_insolvencia,
            "balances_mensuales": balances,
        }

    def _run_predefined_scenarios(self) -> List[dict]:
        """Ejecuta los escenarios predefinidos (optimista, pesimista, crisis, boom)."""
        scenarios = []

        for name, config in self.scenarios_config.items():
            cumulative = self.model.initial_cash
            months_data = []
            min_caja = cumulative

            for i, month in enumerate(self.model.months):
                sales = month.income.sales * config["sales_mult"]
                # Crecimiento adicional mes a mes
                growth_monthly = config["growth_mult"] ** (1/12)
                sales *= growth_monthly ** i

                variable_costs = month.expenses.variable_costs * config["costs_mult"]
                fixed_costs = month.expenses.fixed_costs * (config["costs_mult"] * 0.5 + 0.5)

                income_total = sales + month.income.other_income
                expenses_total = (variable_costs + fixed_costs +
                                  month.expenses.variable_expenses +
                                  month.expenses.debt_payments +
                                  month.expenses.taxes * config["sales_mult"] +
                                  month.expenses.investments)

                net_flow = income_total - expenses_total
                cumulative += net_flow

                if cumulative < min_caja:
                    min_caja = cumulative

                months_data.append({
                    "mes": month.label,
                    "balance": round(cumulative, 2),
                    "net_flow": round(net_flow, 2),
                })

            scenarios.append({
                "nombre": name,
                "config": config,
                "caja_final": round(cumulative, 2),
                "caja_minima": round(min_caja, 2),
                "insolvente": min_caja < 0,
                "meses": months_data,
            })

        return scenarios

    def _random_normal(self, mean: float, std: float) -> float:
        """
        Genera un número aleatorio con distribución normal truncada.
        Trunca a ±3 desviaciones estándar para evitar valores extremos irreales.
        """
        value = self._rng.gauss(mean, std)
        # Truncar a ±3 std
        lower = mean - 3 * std
        upper = mean + 3 * std
        return max(lower, min(upper, value))

    def _std_dev(self, values: List[float]) -> float:
        """Calcula la desviación estándar de una lista de valores."""
        if not values:
            return 0
        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        return math.sqrt(variance)

    def _build_histogram(self, values: List[float], bins: int = 20) -> List[dict]:
        """Construye un histograma simple para visualización."""
        if not values:
            return []

        min_val = min(values)
        max_val = max(values)
        if min_val == max_val:
            return [{"rango_min": min_val, "rango_max": max_val, "frecuencia": len(values), "pct": 100}]

        bin_width = (max_val - min_val) / bins
        histogram = []

        for i in range(bins):
            lower = min_val + i * bin_width
            upper = lower + bin_width
            count = sum(1 for v in values if lower <= v < upper)
            if i == bins - 1:  # Último bin incluye el máximo
                count = sum(1 for v in values if lower <= v <= upper)

            histogram.append({
                "rango_min": round(lower, 0),
                "rango_max": round(upper, 0),
                "frecuencia": count,
                "pct": round(count / len(values) * 100, 1),
            })

        return histogram

    def _classify_risk(self, prob_insolvencia: float) -> dict:
        """Clasifica el nivel de riesgo según la probabilidad de insolvencia."""
        if prob_insolvencia < 5:
            return {"nivel": "Bajo", "color": "#22c55e", "emoji": "🟢",
                    "mensaje": "Riesgo bajo: la empresa tiene alta probabilidad de mantener solvencia."}
        elif prob_insolvencia < 15:
            return {"nivel": "Moderado", "color": "#facc15", "emoji": "🟡",
                    "mensaje": "Riesgo moderado: hay escenarios donde la caja podría ser insuficiente."}
        elif prob_insolvencia < 30:
            return {"nivel": "Alto", "color": "#f97316", "emoji": "🟠",
                    "mensaje": "Riesgo alto: probabilidad significativa de problemas de liquidez."}
        else:
            return {"nivel": "Crítico", "color": "#dc2626", "emoji": "🔴",
                    "mensaje": "Riesgo crítico: alta probabilidad de insolvencia. Se requiere acción inmediata."}

    def run_scenario_comparison(self, scenarios_params: List[dict]) -> dict:
        """
        Compara múltiples escenarios personalizados.
        Cada escenario es un dict con multiplicadores para variables.
        """
        comparisons = []

        for params in scenarios_params:
            name = params.get("nombre", "Escenario")
            cumulative = self.model.initial_cash
            months_results = []

            for i, month in enumerate(self.model.months):
                sales_mult = params.get("sales_mult", 1.0)
                costs_mult = params.get("costs_mult", 1.0)
                growth_mult = params.get("growth_mult", 1.0)

                sales = month.income.sales * sales_mult * (growth_mult ** (i / 12))
                variable_costs = month.expenses.variable_costs * costs_mult
                fixed_costs = month.expenses.fixed_costs * params.get("fixed_costs_mult", 1.0)

                income_total = sales + month.income.other_income
                expenses_total = (variable_costs + fixed_costs +
                                  month.expenses.variable_expenses +
                                  month.expenses.debt_payments +
                                  month.expenses.taxes +
                                  month.expenses.investments)

                net_flow = income_total - expenses_total
                cumulative += net_flow
                months_results.append({"balance": round(cumulative, 2), "net_flow": round(net_flow, 2)})

            comparisons.append({
                "nombre": name,
                "params": params,
                "caja_final": round(cumulative, 2),
                "meses": months_results,
            })

        return {"comparaciones": comparisons}

    def sensitivity_monte_carlo(self, variable: str, range_pct: float = 30.0,
                                 steps: int = 7) -> List[dict]:
        """
        Análisis de sensibilidad con Monte Carlo para una variable específica.
        Varía la variable desde -range_pct% hasta +range_pct% y ejecuta
        mini-Monte Carlo (100 iteraciones) en cada punto.
        """
        results = []
        step_size = (2 * range_pct) / (steps - 1) if steps > 1 else 0

        for s in range(steps):
            change_pct = -range_pct + s * step_size

            # Mini Monte Carlo con la variable fijada
            insolvency_count = 0
            caja_finals = []
            mini_iterations = min(100, self.iterations // 10)

            for _ in range(mini_iterations):
                cumulative = self.model.initial_cash

                for month in self.model.months:
                    # Aplicar el cambio fijo a la variable objetivo
                    sales = month.income.sales
                    variable_costs = month.expenses.variable_costs
                    fixed_costs = month.expenses.fixed_costs

                    if variable == "ventas":
                        sales *= (1 + change_pct / 100)
                    elif variable == "costos_variables":
                        variable_costs *= (1 + change_pct / 100)
                    elif variable == "costos_fijos":
                        fixed_costs *= (1 + change_pct / 100)

                    # Agregar ruido aleatorio a las demás variables
                    sales *= self._random_normal(1.0, 0.05)
                    variable_costs *= self._random_normal(1.0, 0.05)

                    income_total = sales + month.income.other_income
                    expenses_total = (variable_costs + fixed_costs +
                                      month.expenses.variable_expenses +
                                      month.expenses.debt_payments +
                                      month.expenses.taxes +
                                      month.expenses.investments)

                    cumulative += income_total - expenses_total

                caja_finals.append(cumulative)
                if cumulative < 0:
                    insolvency_count += 1

            results.append({
                "cambio_pct": round(change_pct, 1),
                "caja_final_media": round(sum(caja_finals) / len(caja_finals), 2),
                "prob_insolvencia_pct": round(insolvency_count / mini_iterations * 100, 1),
            })

        return results
