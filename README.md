# SmartCaja v2.0

Herramienta de flujo de caja inteligente con IA local para PYMEs, desarrollada como plugin para [Pinokio](https://pinokio.computer). Utiliza agentes conversacionales basados en **Ollama** y modelos **Meta Llama** para crear, analizar y proyectar flujos de caja de manera completamente offline. Un producto de la **Cámara de Comercio de Santiago (CCS)**.

## Novedades v2.0

La versión 2.0 introduce un **motor financiero modular** completamente nuevo con capacidades avanzadas de simulación y análisis:

| Característica | Descripción |
|---|---|
| **Motor Financiero Modular** | Generación mes a mes con estacionalidad, fluctuaciones de mercado y crecimiento compuesto |
| **Simulación Monte Carlo** | Hasta 5.000 iteraciones para evaluar probabilidad de insolvencia y riesgo |
| **Entrevista Inteligente v2** | 22 áreas financieras, máximo 8 preguntas por turno, supuestos explícitos |
| **Búsqueda de Mercado** | Datos de estacionalidad e inflación obtenidos de internet |
| **Notificaciones Contextuales** | Mensajes personalizados al negocio durante la generación |
| **Métricas Avanzadas** | Break-even, runway, margen EBITDA, sensibilidad por variable |
| **Versionado de Escenarios** | Guardar, restaurar y comparar múltiples planes |
| **Dashboard Interactivo** | Gráficos dinámicos con Chart.js y panel de métricas |

## Funcionalidades Principales

### Entrevista Financiera Inteligente
Un agente conversacional guía al usuario para recopilar datos financieros cubriendo 22 áreas críticas priorizadas por impacto en flujo de caja. Propone supuestos razonables cuando falta información y muestra el progreso de la entrevista en tiempo real.

### Generación de Cashflow con Contexto
El sistema genera un flujo de caja mes a mes con:
- Estacionalidad aplicada según el tipo de negocio
- Fluctuaciones de mercado basadas en datos reales
- Notificaciones contextualizadas (ej: "Simulando aumento de demanda de pan de masa madre por temporada invernal")
- Crecimiento compuesto y efecto churn

### Simulación Probabilística (Monte Carlo)
- Evaluación de riesgo con miles de escenarios aleatorios
- Probabilidad de insolvencia calculada
- Bandas de confianza (P5, P25, P50, P75, P95)
- Escenarios predefinidos (optimista, pesimista, estanflación, boom)
- Análisis de sensibilidad por variable

### Métricas Financieras
- **Caja mínima** — Saldo más bajo proyectado y cuándo ocurre
- **Mes de caja negativa** — Primer mes con déficit
- **Break-even operativo** — Ventas necesarias para cubrir costos
- **Runway** — Meses de supervivencia con caja actual
- **Margen bruto** — Rentabilidad antes de costos fijos
- **Margen EBITDA** — Rentabilidad operativa
- **Necesidad de financiamiento** — Monto máximo requerido
- **Probabilidad de insolvencia** — Vía Monte Carlo
- **Sensibilidad por variable** — Impacto de cambios en ventas/costos

### Versionado y Comparación
- Guardar múltiples versiones del cashflow
- Crear escenarios personalizados con multiplicadores
- Comparación visual lado a lado
- Restaurar versiones anteriores

## Arquitectura

```
smartcaja/
├── server/
│   ├── app.py                    # Backend principal FastAPI
│   ├── advanced_endpoints.py     # Router V2 (motor financiero)
│   ├── interview_manager.py      # Gestor de entrevista inteligente
│   ├── market_research.py        # Búsqueda de datos de mercado
│   └── financial_engine/
│       ├── __init__.py
│       ├── core.py               # Modelo de cashflow y BusinessProfile
│       ├── metrics.py            # Métricas financieras avanzadas
│       └── monte_carlo.py        # Simulación probabilística
├── app/
│   ├── index.html                # Interfaz web v2
│   └── app.js                    # Lógica del frontend
├── defaults/
│   ├── agents.json               # Configuración de agentes LLM
│   └── prompts/
│       ├── financial_interviewer.md
│       └── cashflow_analyst.md
├── tests/
│   ├── test_app.py               # Tests del backend
│   └── test_engine.py            # Tests del motor financiero
├── scripts/
│   ├── setup_venv.sh             # Setup Linux/Mac
│   ├── setup_venv.ps1            # Setup Windows
│   ├── verify_deps.py            # Verificación de dependencias
│   ├── diagnose.sh               # Diagnóstico Linux/Mac
│   └── diagnose.ps1              # Diagnóstico Windows
├── install.json                  # Instalación 1-click Pinokio
├── start.json                    # Arranque del servidor
├── reset.json                    # Desinstalación
├── pinokio.js                    # Configuración del plugin
└── requirements.txt              # Dependencias Python
```

## Requisitos del Sistema

| Requisito | Mínimo | Recomendado |
|---|---|---|
| RAM | 4 GB | 8 GB o más |
| Disco | 5 GB libres | 10 GB libres |
| SO | Windows 10, macOS 12, Ubuntu 20.04 | Última versión |
| Pinokio | v2.0+ | Última versión |

## Modelos de IA según RAM

| RAM disponible | Modelo descargado | Uso |
|---|---|---|
| Menos de 6 GB | `llama3.2:1b` | Tareas simples |
| 6-12 GB | `llama3.2:3b` | Uso general (entrevista + extracción) |
| Más de 12 GB | `llama3.1:8b` | Análisis complejo (cashflow + simulación) |

## Instalación

### Vía Pinokio (Recomendado)
1. Abre **Pinokio** en tu computador.
2. Ve a la sección de descarga de plugins.
3. Ingresa la URL de este repositorio.
4. Haz click en **Instalar**. El proceso es completamente automático.
5. Una vez instalado, haz click en **Iniciar**.

### Manual
```bash
git clone https://github.com/vtomasv/smartcaja.git
cd smartcaja
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
python server/app.py --port 7860
```

## API Endpoints

### V1 (Legacy — compatible)
| Método | Endpoint | Descripción |
|---|---|---|
| POST | `/api/companies` | Crear empresa |
| POST | `/api/chat/{company_id}` | Chat con entrevistador |
| POST | `/api/companies/{id}/generate-cashflow` | Generar cashflow |
| GET | `/api/companies/{id}/cashflow` | Obtener cashflow |
| POST | `/api/companies/{id}/simulate` | Simular escenario |

### V2 (Motor Financiero Avanzado)
| Método | Endpoint | Descripción |
|---|---|---|
| POST | `/api/v2/companies/{id}/generate-cashflow` | Generación avanzada con Monte Carlo |
| GET | `/api/v2/generation/{task_id}/progress` | Progreso con notificaciones |
| GET | `/api/v2/companies/{id}/metrics` | Métricas financieras |
| POST | `/api/v2/companies/{id}/monte-carlo` | Simulación Monte Carlo |
| POST | `/api/v2/companies/{id}/sensitivity` | Análisis de sensibilidad |
| POST | `/api/v2/companies/{id}/market-research` | Búsqueda de mercado |
| POST | `/api/v2/companies/{id}/compare-scenarios` | Comparar escenarios |
| POST | `/api/v2/companies/{id}/custom-scenario` | Crear escenario personalizado |
| GET | `/api/v2/companies/{id}/cashflow-versions` | Listar versiones |
| POST | `/api/v2/companies/{id}/cashflow-versions` | Guardar versión |
| PUT | `/api/v2/companies/{id}/cashflow-versions/{vid}/restore` | Restaurar versión |
| POST | `/api/v2/chat/interview` | Entrevista inteligente v2 |
| GET | `/api/v2/companies/{id}/interview-progress` | Progreso de entrevista |

## Agentes de IA

| Agente | Rol | Modelo |
|---|---|---|
| Entrevistador Financiero v2 | Entrevista inteligente con 22 áreas | `llama3.2:3b` |
| Analista de Flujo de Caja v2 | Generación con estacionalidad y mercado | `llama3.1:8b` |
| Simulador de Escenarios v2 | Monte Carlo y sensibilidad | `llama3.1:8b` |
| Extractor de Datos | Extracción JSON de conversaciones | `llama3.2:3b` |

## Stack Tecnológico

| Componente | Tecnología |
|---|---|
| Plataforma | Pinokio |
| Backend | FastAPI + Uvicorn |
| Frontend | HTML5 + Chart.js + TailwindCSS |
| IA Local | Ollama + Meta Llama |
| Simulación | NumPy + Monte Carlo |
| Persistencia | JSON en disco |
| Exportación | openpyxl (Excel), CSV, PDF |

## Desarrollo

### Ejecutar tests
```bash
cd smartcaja
pip install pytest numpy
python -m pytest tests/ -v
python tests/test_engine.py
```

### Ejecutar servidor en desarrollo
```bash
cd smartcaja
pip install -r requirements.txt
python server/app.py --port 7860
```

## Licencia

MIT License

## Créditos

Desarrollado para la **Cámara de Comercio de Santiago (CCS)** como parte del programa de digitalización de PYMEs con inteligencia artificial local.
