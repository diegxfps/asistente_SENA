# scripts/build_index.py
import json, re, unicodedata
from pathlib import Path

from sentence_transformers import SentenceTransformer
import numpy as np
import faiss

DATA = Path("storage_simple/programas_normalizado.json")
if not DATA.exists():
    DATA = Path("storage_simple/programas.json")

IDX  = Path("storage_simple/faiss.index")
META = Path("storage_simple/faiss_meta.json")
DOCS = Path("storage_simple/faiss_docs.json")

def norm(s: str) -> str:
    if s is None: return ""
    s = str(s)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return " ".join(s.lower().strip().split())

def chunk_paragraphs(text: str) -> list[str]:
    # parte por párrafos y filtra tamaños razonables
    chunks = []
    for para in (text or "").split("\n\n"):
        para = para.strip()
        if 200 <= len(para) <= 1200:
            chunks.append(para)
    return chunks

# ---- carga de datos ----
data = json.loads(DATA.read_text(encoding="utf-8"))

# aseguramos campos normalizados y base textual aunque no haya PDF
for p in data:
    p["_n_programa"]  = p.get("_n_programa")  or norm(p.get("programa",""))
    p["_n_nivel"]     = p.get("_n_nivel")     or norm(p.get("nivel",""))
    p["_n_municipio"] = p.get("_n_municipio") or norm(p.get("municipio",""))
    p["_n_sede"]      = p.get("_n_sede")      or norm(p.get("sede",""))
    p["_n_horario"]   = p.get("_n_horario")   or norm(p.get("horario",""))
    p["_n_pdf_text"]  = p.get("_n_pdf_text")  or norm(p.get("pdf_text",""))

docs = []
metas = []

for i, p in enumerate(data):
    pid = p.get("codigo_ficha") or p.get("no") or i
    # base corta con campos clave
    base = " — ".join(filter(None, [
        p.get("programa",""),
        p.get("nivel",""),
        p.get("sede",""),
        p.get("municipio",""),
        p.get("horario",""),
    ])).strip()

    # si hay PDF, hacemos chunks; si no, usamos solo la base
    pdf_chunks = chunk_paragraphs(p.get("pdf_text",""))
    if not pdf_chunks:
        pdf_chunks = []

    texts = [base] + pdf_chunks
    for t in texts:
        docs.append(t)
        metas.append({
            "pid": str(pid),
            "programa": p.get("programa",""),
            "programa_n": p["_n_programa"],
        })

# ---- embeddings + FAISS ----
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
emb = model.encode(docs, batch_size=64, convert_to_numpy=True, normalize_embeddings=True)

index = faiss.IndexFlatIP(emb.shape[1])
index.add(emb)

faiss.write_index(index, str(IDX))
META.write_text(json.dumps({"metas": metas}, ensure_ascii=False, indent=2), encoding="utf-8")
DOCS.write_text(json.dumps({"docs": docs}, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"✅ FAISS listo: {len(docs)} chunks | {IDX.name}, {META.name}, {DOCS.name}")
