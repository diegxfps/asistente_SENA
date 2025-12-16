"""Sanity checks for general SENA info matching."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import _match_general_info_entry  # noqa: E402


def run_checks():
    cases = {
        "inscripción": "como_inscribirme",
        "que es el sena": "que_es_sena",
        "contacto sena": "canales_contacto",
    }

    for text, expected in cases.items():
        entry = _match_general_info_entry(text)
        assert entry, f"No se encontró coincidencia para '{text}'"
        assert entry.get("id") == expected, f"Esperaba {expected} pero obtuve {entry.get('id')}"

    print("sena_info sanity checks passed")


if __name__ == "__main__":
    run_checks()
