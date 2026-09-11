---
name: gepeto
description: Genera scripts de launcher/instalador de Pinokio multiplataforma (Windows, macOS, Linux) para una app — install.js, start.js, update.js, reset.js, link.js, pinokio.js y torch.js — usando el generador Gepeto (npx gepeto@latest, https://gepeto.pinokio.computer). Úsalo cuando necesites empaquetar o publicar una app como plugin/launcher de Pinokio instalable en 1 clic.
---

# Gepeto — Generador de instaladores/launchers de Pinokio

[Gepeto](https://gepeto.pinokio.computer) (`pinokiocomputer/gepeto`) es un CLI creado por cocktailpeanut que **genera automáticamente el conjunto mínimo de scripts que Pinokio necesita para instalar y lanzar una app en 1 clic**, de forma multiplataforma (Windows / macOS / Linux). No es un skill de planificación; es un scaffolder de launchers de Pinokio.

No confundir con `gepetto` (doble "t") de `softaworks/agent-toolkit`, que es un skill de planificación de features y NO genera instaladores.

## Cuándo usar este skill

- Cuando se pide "crear un instalador con gepeto", empaquetar una app para Pinokio, o generar los scripts `install.js`/`start.js`/`pinokio.js` de un launcher.
- Cuando un proyecto Pinokio usa el formato antiguo JSON (`install.json`, `start.json`) y se quiere migrar/complementar con el formato de scripts JS que genera Gepeto.

## Qué genera Gepeto

Gepeto tiene dos plantillas (ver `references/templates/`):

- **templates/1 (con git URL externo):** clona un repo de terceros en `app/` y crea el launcher alrededor. Incluye `install.js`, `start.js`, `update.js`, `reset.js`, `link.js`, `pinokio.js`, `torch.js`.
- **templates/2 (proyecto propio, sin git URL):** asume que el código vive en el mismo repo. Además de los scripts anteriores, genera `app.py` y `requirements.txt` de ejemplo.

Archivos y su propósito:

| Archivo | Propósito |
|---|---|
| `pinokio.js` | UI/menú del launcher en Pinokio (Install / Start / Update / Reset / Open Web UI). `version: "5.0"`, menú dinámico según estado (`info.exists("env")`, `info.running(...)`). |
| `install.js` | Instala dependencias en un venv (`venv: "env"`), típicamente `uv pip install -r <INSTALL_FILE>`; opcionalmente llama a `torch.js`. |
| `start.js` | `daemon: true`; lanza la app (`python <START_FILE>`), detecta la URL con el regex `/http:\/\/\\S+/` y la publica con `local.set` para el botón "Open Web UI". |
| `update.js` | `git pull` (y en templates/1 también `git pull` dentro de `app/`). |
| `reset.js` | Borra el entorno (`fs.rm` de `env`/`app`) para reinstalar limpio. |
| `link.js` | `fs.link` para deduplicar librerías y ahorrar disco. |
| `torch.js` | Instalación cross-platform de PyTorch (CUDA/MPS/CPU). Solo si el proyecto usa torch. |

## Cómo ejecutarlo

Requisitos: Node.js 16+ (verificar `node --version`).

```bash
# Interactivo (pregunta: Project name, Icon URL, git URL, App python file, PIP install file)
npx gepeto@latest

# No interactivo (todos los args son URL-encoded)
npx gepeto@latest --name "SmartCaja" \
  --start "server/app.py" \
  --install "requirements.txt" \
  --icon "<url-al-icono>" \
  --git "<git-url-o-vacío>"
```

Comportamiento (ver `references/gepeto-cli.md`):

- Si dejas el `git URL` vacío → usa `templates/2` (proyecto propio).
- Si pasas un `git URL` → usa `templates/1` y sustituye `<GIT_REPOSITORY>` en `install.js`.
- Sustituye `<INSTALL_FILE>` y `<START_FILE>` en `install.js`/`start.js`.
- Escribe `pinokio.json` (metadata: `title`, `description`, `icon`, `links`, `posts`).
- Genera README, `.gitignore` e inicializa un repo git con rama `main`.

Gepeto crea todo dentro de un subdirectorio nuevo `<name>/`. Para aplicarlo a un repo existente, genera en un directorio temporal y copia/adapta los scripts, o ejecútalo desde el directorio `api` de Pinokio.

## Aplicarlo a este proyecto (SmartCaja, plugin Pinokio)

Este repo ya es un plugin de Pinokio con formato JSON (`install.json`, `start.json`, `stop.json`, `reset.json`, `pinokio.js`) y arranca `server/app.py` con un venv + Ollama. Al generar el launcher con Gepeto:

- `--name "SmartCaja"`, `--start "server/app.py"`, `--install "requirements.txt"`, `--icon` con el isotipo de CCCE (`app/logo-ccce.png` / `icon.png`).
- Mantener intacta la lógica actual de Pinokio/Ollama: reproducir en `install.js`/`start.js` los pasos existentes (verificación/inicio de Ollama, `verify_deps.py`, `python server/app.py --port {{port}}`) en vez de los comandos de ejemplo.
- Este proyecto **no** usa torch: eliminar el paso de `torch.js`/`torch.js` del `install.js`.
- El resultado es multiplataforma automáticamente porque Pinokio abstrae el SO; verificar rutas y comandos en Windows/macOS/Linux.

## Referencias

- `references/gepeto-cli.md` — detalle del CLI (prompts, flags, mapeo de placeholders y pasos que ejecuta).
- `references/templates/1/` y `references/templates/2/` — plantillas reales de Gepeto (copiadas de `pinokiocomputer/gepeto`) para consultar u obtener offline.
- Docs oficiales: https://gepeto.pinokio.computer · Repo: https://github.com/pinokiocomputer/gepeto
