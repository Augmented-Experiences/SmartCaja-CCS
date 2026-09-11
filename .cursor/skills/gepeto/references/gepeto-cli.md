# Gepeto CLI — referencia

Fuente: `pinokiocomputer/gepeto` (`index.js`, v0.5.7). Docs: https://gepeto.pinokio.computer

## Invocación

```bash
npx gepeto@latest            # modo interactivo (prompts)
npx gepeto@latest --name ... # modo no interactivo (flags)
```

También existe un subcomando `add` para editar metadata de `pinokio.json`:

```bash
npx gepeto add link  --title "..." --value "..."   # añade un link
npx gepeto add post  --value "..."                  # añade un post
```

## Prompts (modo interactivo)

1. **Project name** (por defecto `my-app`).
2. **Icon URL** — vacío usa el `icon.png` por defecto; si se da una URL, la descarga y guarda como `icon.<ext>`.
3. **3rd party git URL** — vacío = proyecto propio; con valor = launcher para un repo externo.
4. **App python file** (por defecto `app.py`) → sustituye `<START_FILE>` en `start.js`.
5. **PIP install file** (por defecto `requirements.txt`) → sustituye `<INSTALL_FILE>` en `install.js`.

Flags equivalentes (todos URL-encoded): `--name`, `--icon`, `--git`, `--start`, `--install`.

## Selección de plantilla

- `git URL` vacío → `templates/2` (proyecto propio): copia también `app.py` y `requirements.txt`, y los renombra a los nombres indicados en los prompts `start`/`install`.
- `git URL` presente → `templates/1`: sustituye `<GIT_REPOSITORY>` en `install.js` (paso `git clone <GIT_REPOSITORY> app`) y genera un README.

## Pasos que ejecuta el CLI

1. Copia la plantilla elegida a `./<name>/`.
2. Si hay git URL: reemplaza `<GIT_REPOSITORY>` en `install.js`.
3. Descarga el icono (si se dio URL) o usa `icon.png`.
4. Escribe `pinokio.json` con `{ title, description, icon, links, posts }`.
5. Reemplaza `<INSTALL_FILE>` en `install.js` y `<START_FILE>` en `start.js`.
6. Si NO hay git URL: renombra `requirements.txt`→`<install>` y `app.py`→`<start>`.
7. Genera README (solo si hay git URL), `.gitignore` (`node_modules`, `.DS_Store`).
8. `git init`, `git add .`, `git commit -m "init"`, crea rama `main`.

## Placeholders a sustituir

| Placeholder | Archivo | Reemplazo |
|---|---|---|
| `<GIT_REPOSITORY>` | `install.js` | URL del repo externo (solo templates/1) |
| `<INSTALL_FILE>` | `install.js` | archivo pip (p. ej. `requirements.txt`) |
| `<START_FILE>` | `start.js` | archivo de arranque (p. ej. `server/app.py`) |

## Notas de multiplataforma

- Pinokio ejecuta los mismos scripts JS en Windows/macOS/Linux; la portabilidad la aporta Pinokio (venv `env`, `shell.run`, `script.start`, `local.set`).
- `torch.js` resuelve PyTorch por plataforma/GPU (CUDA/MPS/CPU). Eliminarlo si el proyecto no usa torch.
- Para GPUs, el código de la app puede necesitar adaptar `cuda`→`mps`/`cpu`.
