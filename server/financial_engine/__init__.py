"""
Motor Financiero Modular — SmartCaja
Proporciona simulación determinista, probabilística (Monte Carlo),
cálculo de métricas avanzadas y análisis de sensibilidad.
"""

from .core import CashflowModel, MonthData
from .metrics import FinancialMetrics
from .monte_carlo import MonteCarloSimulator

__all__ = ["CashflowModel", "MonthData", "FinancialMetrics", "MonteCarloSimulator"]
