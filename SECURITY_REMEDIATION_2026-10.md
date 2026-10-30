# Remediacion Checkmarx — SmartCaja — 2026-10-14

Escaneo de origen: zip de `SmartCaja-CCS-main`, 14 oct 2026, 62 hallazgos nuevos, todos en estado To Verify (0 criticos, 5 altos, 14 medios, 43 bajos). 43 SAST, 18 SCA, 1 IaC. 22k LOC. El zip incluye el repositorio completo, no el artefacto del instalador.

La app es de escritorio, un usuario, backend en loopback. Este documento distingue lo que entra al instalador de lo que solo estaba en el zip.

## 1. Antes y despues

| Item | Antes | Despues |
|---|---|---|
| DOMPurify | 3.4.1 vendido en `app/lib/purify.min.js`, sin manifiesto npm de la UI | 3.4.17 fijado en `frontend/package.json` y `frontend/package-lock.json`. El archivo entregado es `app/lib/purify.min.js` (cabecera `DOMPurify 3.4.17`). |
| gradio | No esta en `requirements.txt` ni en `requirements-desktop.txt`. Solo en `.cursor/skills/gepeto/references/templates/2/requirements.txt` y `import gradio` en la plantilla `templates/2/app.py`. | Fuera del instalador. El 30 de octubre esos archivos y `templates/requirements-templates.txt` se eliminaron de la rama. |
| transformers | Igual que gradio: no hay import en `server/`. | Fuera del instalador y, desde el 30 de octubre, fuera del repositorio. No hay carga de modelo en el producto. |
| accelerate | Igual que gradio. | Fuera del instalador y, desde el 30 de octubre, fuera del repositorio. |

`pip freeze` del venv del instalador no lista gradio, transformers ni accelerate. Ver seccion 5.

## 2. Archivos del instalador

El spec de PyInstaller (`desktop/backend/backend.spec`) empaqueta tres arboles: `app/`, `desktop/ui/` y `defaults/`. No copia `.cursor/` ni `templates/`.

Conteo antes del filtro explicito: **36 archivos**. Conteo despues: **36 archivos**. La lista es la misma. El unico nombre que contiene "template" es `desktop/ui/splash.template.html`, que es la pantalla de arranque del producto, no una plantilla Gepeto.

Despues se agrego un filtro en el spec que descarta cualquier entrada cuyo path tenga `.cursor`, `node_modules` o `__pycache__`. `frontend/node_modules/` (creado al instalar DOMPurify) no entra en esos tres arboles, asi que no esta en el conteo.

Lista (antes = despues):

- app/app.js
- app/favicon.ico
- app/fonts/Brushwell.otf
- app/fonts/DMSans-Bold.ttf
- app/fonts/DMSans-ExtraBold.ttf
- app/fonts/DMSans-Light.ttf
- app/fonts/DMSans-Medium.ttf
- app/fonts/DMSans-Regular.ttf
- app/fonts/DMSans-SemiBold.ttf
- app/fonts/FeelingPassionate.otf
- app/index.html
- app/lib/purify.min.js
- app/logo-ccs.png
- defaults/agents.json
- defaults/prompts/cashflow_analyst.md
- defaults/prompts/financial_interviewer.md
- defaults/prompts/scenario_simulator.md
- defaults/prompts/skills/cashflow_modeling.md
- defaults/prompts/skills/contextual_questions.md
- defaults/prompts/skills/conversation.md
- defaults/prompts/skills/data_extraction.md
- defaults/prompts/skills/financial_analysis.md
- defaults/prompts/skills/financial_discovery.md
- defaults/prompts/skills/json_generation.md
- defaults/prompts/skills/market_research.md
- defaults/prompts/skills/monte_carlo.md
- defaults/prompts/skills/risk_assessment.md
- defaults/prompts/skills/scenario_analysis.md
- defaults/prompts/skills/seasonality.md
- defaults/prompts/skills/sensitivity_analysis.md
- desktop/ui/accent.css
- desktop/ui/ccs-theme.css
- desktop/ui/favicon.ico
- desktop/ui/index.html
- desktop/ui/splash-logo.png
- desktop/ui/splash.template.html

## 3. Archivos modificados

| Archivo | Por que |
|---|---|
| `app/lib/purify.min.js` | Reemplazo del vendido 3.4.1 por 3.4.17. |
| `frontend/package.json` | Manifiesto de la UI con DOMPurify 3.4.17. No se empaqueta. |
| `frontend/package-lock.json` | Lockfile de esa dependencia. |
| `frontend/scripts/sync-purify.js` | Copia el build de npm a `app/lib` y exige la version 3.4.17. |
| `frontend/scripts/verify-chat-sanitize.js` | Repite la configuracion del chat contra jsdom. |
| `requirements.txt` | Comentario: gradio, transformers y accelerate no son dependencias del producto. |
| `requirements-desktop.txt` | Deja explicito que este es el unico manifiesto del instalador. |
| `requirements-dev.txt` | Manifiesto de pruebas, separado del instalador. |
| `templates/requirements-templates.txt` | Manifiesto de las plantillas Gepeto. No lo instala el sidecar. |
| `server/log_sanitize.py` | Helper que deja cada valor de log en una sola linea. |
| `server/path_guard.py` | Confina nombres de archivo al directorio permitido. |
| `server/app.py` | Logs sin saltos de linea ni cuerpos de respuesta; CORS e Host de loopback; importacion confinada. |
| `server/advanced_endpoints.py` | IDs de empresa confinados; notificaciones de una sola linea; sesion confinada. |
| `server/market_research.py` | Logs de sector y consulta sin el texto crudo ni saltos de linea. |
| `desktop/backend/backend.spec` | El datas del instalador rechaza `.cursor`, `node_modules` y `__pycache__`. |
| `.gitignore` | Ignora `frontend/node_modules/`. |
| `.github/workflows/desktop-build.yml` | `permissions: contents: read`. |
| `.github/workflows/macos-installer.yml` | `permissions: contents: read`. |
| `tests/test_security_remediation.py` | Log forging, path traversal y Host ajeno. |
| `SECURITY_REMEDIATION_2026-10.md` | Este informe. |

No se borro `.cursor/` ni las plantillas en esa pasada del 14 de octubre.

El 30 de octubre se eliminaron de la rama `.cursor/skills/gepeto/` y `templates/requirements-templates.txt`. Esos archivos no entran al instalador y eran el unico sitio del repositorio con `gradio`, `transformers`, `accelerate` y `diffusers`. Pillow no estaba declarado: el SCA lo resolvia como dependencia de Gradio. El skill de Gepeto sigue disponible fuera de este repo, en el equipo. `requirements-dev.txt` (pytest) se mantiene porque las pruebas lo usan; no va en el instalador.

## 4. Tests ejecutados

`python -m unittest tests.test_security_remediation -v`

```
test_injection_becomes_one_line ... ok
test_rejects_foreign_host ... ok
test_accepts_plain_name ... ok
test_rejects_dotdot_and_absolute ... ok
test_rejects_symlink_escape ... skipped 'el sistema no permite crear symlinks'
Ran 5 tests in 1.080s
OK (skipped=1)
```

El caso de symlink no se pudo ejecutar en este Windows: `os.symlink` lanzo `OSError`. La funcion `guarded_child` resuelve la ruta y exige `relative_to` del directorio raiz; el caso no quedo demostrado en esta maquina.

Host de loopback del cliente de pruebas: `GET /api/health` sin Host ajeno respondio **200**. Con `Host: evil.example` respondio **400**.

`python tests/test_fixes.py` termino con `ALL TESTS PASSED` (10 pruebas de chips, prompt y glosario).

No se abrio la ventana de escritorio. La verificacion del chat es el script de jsdom, que usa la misma llamada que `app/app.js`.

## 5. DOMPurify, IN_PLACE y auditoria

Busqueda en el codigo de la UI (fuera del propio `purify.min.js`, que implementa la opcion):

- `app/app.js` llama `DOMPurify.sanitize` una vez, con `ALLOWED_TAGS: ['strong', 'em', 'br', 'p', 'ul', 'ol', 'li', 'code']` y `ALLOWED_ATTR: []`.
- No hay `IN_PLACE: true` en esa llamada.
- No hay `setConfig` en `app.js` ni en `index.html`.

`npm run verify-chat-sanitize` (en `frontend/`):

```
chat sanitize ok: <strong>ok</strong>x
```

El payload de prueba tenia `onerror`, `<script>`, `<img>` y `<a href>`. Quedo solo `<strong>ok</strong>` y el texto suelto. Exit code 0.

`npm audit --omit=dev` en `frontend/`: `found 0 vulnerabilities`.

`npm view dompurify version` en el momento del cambio: **3.4.17**.

## 6. Dependencias del instalador

`venv\Scripts\pip.exe freeze` (entorno que empaqueta el sidecar). No aparecen gradio, transformers ni accelerate:

```
aiofiles==23.2.1
altgraph==0.17.5
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
certifi==2026.7.22
charset-normalizer==3.5.1
click==8.5.0
et_xmlfile==2.0.0
fastapi==0.141.1
h11==0.16.0
httpcore==1.0.9
httptools==0.8.0
httpx==0.28.1
idna==3.19
numpy==1.26.4
openpyxl==3.1.5
packaging==26.3
pefile==2024.8.26
pydantic==2.13.5
pydantic_core==2.46.5
pyinstaller==6.22.3
pyinstaller-hooks-contrib==2026.7
python-dotenv==1.2.3
python-multipart==0.0.32
pywin32-ctypes==0.2.3
PyYAML==6.0.3
requests==2.34.2
setuptools==84.0.0
starlette==1.6.0
typing-inspection==0.4.4
typing_extensions==4.16.0
urllib3==2.8.0
uvicorn==0.53.0
watchfiles==1.2.0
websockets==17.1
```

Busqueda de imports en `server/`: ninguna coincidencia de `gradio`, `transformers`, `accelerate` ni `trust_remote_code`.

## 7. Logs

`sanitize_log` reemplaza CR, LF y el resto de controles `\x00-\x1f` y `\x7f` por espacio, y colapsa el resultado a una linea. Se usa en los logs de `server/app.py`, `server/advanced_endpoints.py` (notificaciones de generacion) y `server/market_research.py`.

Los logs de generacion ya no guardan el cuerpo de la respuesta del modelo ni el JSON del flujo. Quedan el id de empresa, el numero de meses y el tipo de excepcion. Los montos de ingresos y gastos salieron de esa linea.

## 8. Loopback, sesion e IaC

CORS acepta solo `http`/`https` de `localhost`, `127.0.0.1` y `[::1]`, con puerto opcional. Se quitaron `0.0.0.0` y el origen `null`. Metodos: GET, POST, PUT, DELETE. Headers: `Content-Type` y `Accept`. Sin credenciales.

El middleware rechaza un header `Host` que no sea esos tres nombres. `testserver` solo se acepta si corre pytest o si `unittest` ya esta importado, para no romper el cliente de pruebas. El proceso de escritorio enlaza `127.0.0.1`.

No hay token de sesion local. Propuesta, sin implementar: un token aleatorio creado al arrancar el sidecar, inyectado en la pagina que sirve el propio backend, y exigido en mutaciones. Hacerlo a medias dejaria al frontend sin poder guardar. No se hizo.

Workflows `desktop-build.yml` y `macos-installer.yml`: `permissions: contents: read`. Las actions siguen en tag de version (`@v4`, `@v5`, `@stable`), no en SHA. No se imprime el valor de los secretos de Apple; el script solo dice si el certificado esta vacio. El hallazgo IaC del informe no nombra regla, archivo ni linea, asi que no hay mas correccion atribuible.

## 9. Pendiente del export detallado de Checkmarx

Hace falta el export con query, archivo, linea y data flow para:

- Los 43 SAST de baja severidad que el PDF no ubica mas alla de `server/app.py` (33) y `server/advanced_endpoints.py` (10). El unico tipo nombrado es Log Forging, y ese bloque se trato arriba. El resto de queries no se puede cerrar sin el detalle.
- El 1 hallazgo IaC/CI (regla no nombrada).
- Confirmar que un re-escaneo del artefacto del instalador, y no del zip del repositorio, deja en cero los CVE de Gradio, Transformers y Accelerate.
- Los CVE de DOMPurify asociados a `IN_PLACE` quedan mitigados por la version 3.4.17 y por no usar esa opcion. Cualquier CVE que el export marque en otro flujo hay que revisarlo con la linea exacta.
