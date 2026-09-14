# Plan de Desarrollo de Mejoras de Seguridad y Robustez (Basado en Auditoría)

Este documento detalla el plan de acción para abordar las falencias reportadas en el análisis de código y seguridad de SmartCaja v2.1. Las mejoras han sido priorizadas para un entorno on-premise de Pinokio, descartando o degradando riesgos que no aplican a una arquitectura local de único usuario (ej. exigir TLS intra-host o autenticación estricta de sesión).

## Criterios de Priorización
1. **Estabilidad y Concurrencia:** Errores que rompen la aplicación offline o corrompen datos.
2. **Integridad y XSS:** Vulnerabilidades explotables incluso en local (ej. prompt injection, XSS vía datos guardados, corrupción de JSON).
3. **Validaciones y Errores:** Exposición de stack traces, falta de validaciones robustas (Pydantic).
4. **Deuda Técnica:** Código muerto, imports frágiles, magic numbers.

---

## Plan de Sprints

### Sprint 1: Mejoras Críticas (Estabilidad, XSS y Exposición de Errores)
**Objetivo:** Resolver bugs que corrompen el estado, fugan errores internos al frontend, y mitigar las inyecciones más críticas.

- **1.1. Mutación de diccionario durante iteración (Bug Real 1):** Corregir `_rescue_cashflow_structure` en `server/app.py:759` usando `list(data.items())`.
- **1.2. Exception handling global (Control de Flujo 2 / Misconfig A05):** Modificar `global_exception_handler` en `server/app.py:208` para no exponer `str(exc)` completo al cliente en producción; loggear el detalle y devolver un ID de correlación o mensaje genérico.
- **1.3. Concurrencia en Rate Limit y Token Usage (Concurrencia 1):** Añadir `threading.Lock` para `_rate_limit_store`, `_pull_status` y `_token_usage_file` en `server/app.py`.
- **1.4. XSS en Frontend (Inyección A03 / Improper Output LLM05):** Revisar `app/app.js` y `app/index.html`. Reemplazar asignaciones inseguras de `innerHTML` por `textContent` o envolver el contenido dinámico con `DOMPurify.sanitize()`.

### Sprint 2: Mejoras Importantes (Validaciones, Integridad y Concurrencia Secundaria)
**Objetivo:** Migrar Pydantic, asegurar validaciones de entrada, e integridad de datos persistentes.

- **2.1. Migración Pydantic v1 a v2 (Bug Real 2 / A06):** Reemplazar `@validator` por `@field_validator` en todos los modelos Pydantic (`server/app.py`, `server/advanced_endpoints.py`).
- **2.2. Validación de Entrada (Validación 1 y 2):** 
  - Limitar tamaño de archivo en `/api/import` (`server/app.py:2707`).
  - Mejorar validación de `prompt_name` contra path traversal (`server/app.py:545`).
- **2.3. Manejo de Excepciones Silenciosas (Control de Flujo 1 / JSON Corruption A08):** Corregir `load_json` en `server/app.py:243` para que loggee el error si el JSON está corrupto, en lugar de engullirlo silenciosamente.
- **2.4. Concurrencia en Endpoints Avanzados (Concurrencia 2):** Proteger `_advanced_generation_status` en `server/advanced_endpoints.py:60` con locks.
- **2.5. Concurrencia en Monte Carlo (Concurrencia 4):** Instanciar `random.Random(seed)` por simulación en `server/financial_engine/monte_carlo.py` en lugar de usar el módulo global.

### Sprint 3: Mejoras Menores, Refactor y Tests Finales
**Objetivo:** Limpiar deuda técnica, código muerto, magic numbers y asegurar la cobertura.

- **3.1. Código Muerto y Complejidad (Complejidad 1.6):** Eliminar `app/index_v1_backup.html`.
- **3.2. Colisión de Tipos (Bug Real 5):** Renombrar `MonthData` en `server/app.py` a `MonthPayload` para evitar colisión con el de `core.py`.
- **3.3. Imports Frágiles (Bug Real 6):** Eliminar el `sys.path.insert` en `server/advanced_endpoints.py:29` y usar imports relativos o empaquetado.
- **3.4. Auditoría de Dependencias y SRI (A06):** Actualizar `requirements.txt` y evaluar servir librerías JS locales en lugar de CDN.
- **3.5. Pruebas Unitarias y de Integración:** Actualizar y ejecutar la suite de pruebas (`test_all.py`, `test_app.py`, `test_fixes.py`) para asegurar que las mejoras no rompen funcionalidades existentes y cubren los casos de borde añadidos.

---
El trabajo comenzará ejecutando el **Sprint 1**.
