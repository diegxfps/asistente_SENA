# scripts/pdf_to_json.py
import re, json, unicodedata
from pathlib import Path
import fitz  # PyMuPDF

PDF_DIR = Path("storage_pdfs")
CAT_IN  = Path("storage_simple/programas_normalizado.json")   # tu base
CAT_OUT = Path("storage_simple/programas_enriquecido.json")   # salida con campos del PDF

# -------- utilidades ----------
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
        txt = "\n".join(parts)
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\n{2,}", "\n\n", txt)
        return txt.strip()
    except Exception:
        return ""

# -------- extracción por regex (ajusta a tu formato) ----------
# Toma líneas siguientes hasta un separador en blanco o el inicio de otra sección
def extract_block(text: str, header_patterns: list[str]) -> str:
    # Une alternativas y permite acentos/variantes
    pat = r"(?is)\b(" + "|".join(header_patterns) + r")\b[:\-]?\s*(.+?)(?=\n\s*\n|^\s*[A-ZÁÉÍÓÚÑ][^\n]{0,60}\n)"
    m = re.search(pat, text)
    if m:
        return m.group(2).strip()
    return ""

SECTION_PATS = {
    "duracion": [
        r"duraci[oó]n", r"intensidad horaria"
    ],
    "requisitos": [
        r"requisitos(?:\s+de\s+ingreso)?", r"documentaci[oó]n requerida"
    ],
    "perfil_egresado": [
        r"perfil(?:\s+del)?\s+egresad[oa]", r"campo ocupacional"
    ],
    "competencias": [
        r"competencias?(?:\s+del\s+programa)?", r"resultados de aprendizaje"
    ],
    "certificacion": [
        r"t[ií]tulo a otorgar", r"certificaci[oó]n"
    ],
}

# -------- emparejar PDF ↔ programa ----------
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

# -------- main ----------
def main():
    cat = json.loads(CAT_IN.read_text(encoding="utf-8"))
    ok, miss = 0, 0
    for p in cat:
        pdf = guess_pdf_file(p)
        p["pdf_file"] = str(pdf) if pdf else ""
        if not pdf:
            miss += 1
            continue

        raw = read_pdf_text(pdf)
        raw_n = norm(raw)

        # extrae campos
        extra = {}
        for k, pats in SECTION_PATS.items():
            val = extract_block(raw, pats)
            # limpiezas comunes
            val = re.sub(r"\n+", " ", val).strip()
            extra[k] = val

        # guarda campos y texto
        p.update(extra)
        p["pdf_text"] = raw
        p["_n_pdf_text"] = raw_n
        ok += 1

    CAT_OUT.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Enriquecido: {CAT_OUT} — con PDF: {ok} | sin PDF: {miss}")

if __name__ == "__main__":
    main()
