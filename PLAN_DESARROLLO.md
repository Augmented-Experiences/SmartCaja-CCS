# Plan de Desarrollo: SmartCaja

## 1. Visión del Producto
Un plugin para Pinokio que permite a las PYMEs crear, analizar y proyectar flujos de caja de manera inteligente usando un agente local basado en Ollama y un modelo de Meta Llama. Funciona 100% offline y no requiere conocimientos financieros previos.

## 2. Arquitectura Técnica
- **Plataforma:** Pinokio (Localhost Cloud)
- **Backend:** FastAPI (Python)
- **Frontend:** HTML/CSS/JS Vanilla (autocontenido en `index.html`)
- **IA Local:** Ollama (modelos `llama3.2:3b` y `llama3.1:8b`)
- **Persistencia:** Archivos JSON en disco (`data/`)

## 3. Módulos Funcionales
1. **Onboarding / Entrevista:** Agente conversacional que recopila datos de la empresa (ingresos, costos, deudas, etc.).
2. **Flujo de Caja:** Generación automática de la estructura financiera basada en la entrevista.
3. **Dashboard:** Visualización de ingresos, egresos, margen, caja disponible y alertas.
4. **Simulador de Escenarios:** Permite ajustar variables (precios, costos, inflación) y ver el impacto en tiempo real.
5. **Exportación:** Generación de reportes en Excel/CSV.

## 4. Estructura de Datos (JSON)
- `company.json`: Datos básicos de la empresa.
- `cashflow.json`: Estructura del flujo de caja (ingresos, egresos, periodos).
- `scenarios.json`: Simulaciones guardadas.

## 5. Agentes (Ollama)
- **Entrevistador Financiero:** Recopila datos iniciales.
- **Analista de Flujo:** Construye la estructura financiera.
- **Simulador:** Calcula el impacto de los escenarios.

## 6. Interfaz de Usuario (UI)
- Estilo visual basado en la identidad de marca de la CCCE (colores corporativos, tipografía DM Sans).
- Layout con sidebar de navegación y área principal.
- Chat interactivo para la entrevista y simulaciones.
- Dashboard con gráficos (Chart.js) para visualizar el flujo de caja.
