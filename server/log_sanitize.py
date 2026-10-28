"""Una sola linea segura para logs. Quita CR, LF y el resto de controles."""
import re

_CONTROLS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_log(value, limit: int = 200) -> str:
    text = "" if value is None else str(value)
    text = _CONTROLS.sub(" ", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit] + "..."
    return text
