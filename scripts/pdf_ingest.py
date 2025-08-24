# scripts/pdf_ingest.py
import json, re, unicodedata
from pathlib import Path

import fitz  # PyMuPDF

SRC = Path("storage_simple/programas_normalizado.json")   # fuente base
DST = Path("storage_simple/programas_enriquecido.json")   # salida con texto de PDF
PDF_DIR = Path("storage_pdfs")

def norm(s: str) -> str:
    if s is None: return ""
    s = str(s)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return " ".join(s.lower().strip().split())

def read_pdf_text(pdf_path: Path) -> str:
    try:
        doc = fitz.open(pdf_path)
        parts = [page.get_text("text") for page in doc]
        doc.close()
        raw = "\n".join(parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{2,}", "\n\n", raw)
        return raw.strip()
    except Exception:
        return ""

def guess_pdf_file(p: dict) -> Path | None:
    # 1) Recolecta candidatos “obvios” si existen
    candidates = []
    def add_num(val):
        v = str(val or "").strip()
        if not v:
            return
        candidates.extend([PDF_DIR / f"{v}.pdf", PDF_DIR / f"{v}.PDF"])

    # Campos más comunes (si existen en tu dataset)
    for key in ("codigo_ficha", "codigo_programa", "codigo", "no", "ficha", "id", "id_programa"):
        add_num(p.get(key))

    # 2) Escaneo genérico: busca números de 5–7 dígitos en cualquier campo de texto
    import re
    seen = set()
    for v in p.values():
        if not isinstance(v, (str, int, float)):
            continue
        s = str(v)
        for m in re.findall(r"\b(\d{5,7})\b", s):
            if m not in seen:
                seen.add(m)
                add_num(m)

    # 3) Fallback por nombre normalizado
    prog = p.get("programa", "")
    if prog:
        prog_s = re.sub(r"[^\w\-]+", "_", norm(prog))
        candidates.extend([PDF_DIR / f"{prog_s}.pdf", PDF_DIR / f"{prog_s}.PDF"])

    for c in candidates:
        if c.exists():
            return c
    return None

data = json.loads(SRC.read_text(encoding="utf-8"))
with_pdf, without_pdf = 0, 0
for p in data:
    pdf_file = guess_pdf_file(p)
    p["pdf_file"] = str(pdf_file) if pdf_file else ""
    if pdf_file:
        txt = read_pdf_text(pdf_file)
        p["pdf_text"] = txt
        p["_n_pdf_text"] = norm(txt)
        with_pdf += 1
    else:
        p.setdefault("pdf_text", "")
        p.setdefault("_n_pdf_text", "")
        without_pdf += 1

DST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✅ Guardado {DST} — con PDF: {with_pdf} | sin PDF: {without_pdf}")
