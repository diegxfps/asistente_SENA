# scripts/normaliza_json.py
import json, unicodedata
from pathlib import Path

SRC = Path("storage_simple/programas.json")
DST = Path("storage_simple/programas_normalizado.json")

def norm(s):
    if s is None: return ""
    s = str(s)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return " ".join(s.lower().strip().split())

data = json.loads(SRC.read_text(encoding="utf-8"))
for p in data:
    p["_n_programa"]  = norm(p.get("programa",""))
    p["_n_nivel"]     = norm(p.get("nivel",""))
    p["_n_municipio"] = norm(p.get("municipio",""))
    p["_n_sede"]      = norm(p.get("sede",""))
    p["_n_horario"]   = norm(p.get("horario",""))
DST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✅ Escrito: {DST} ({len(data)} registros)")
