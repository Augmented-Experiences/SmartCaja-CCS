"""Confina un nombre de archivo a un directorio. Rechaza .., absolutas y symlinks que escapen."""
import re
from pathlib import Path

from fastapi import HTTPException

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def guarded_child(root: Path, name: str, id_only: bool = False) -> Path:
    if not isinstance(name, str) or not name or name != Path(name).name or name in {".", ".."}:
        raise HTTPException(400, "Nombre de archivo no permitido.")
    if id_only and not _ID.fullmatch(name):
        raise HTTPException(400, "ID inválido.")
    root_resolved = Path(root).resolve()
    resolved = (root_resolved / name).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise HTTPException(400, "Ruta fuera del directorio permitido.")
    return resolved
