import json# app/core.py
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

# ---------------------------
# Rutas de datos / índices
# ---------------------------
DATA_ENR  = Path("storage_simple/programas_enriquecido.json")
DATA_NORM = Path("storage_simple/programas_normalizado.json")
DATA_RAW  = Path("storage_simple/programas.json")

FAISS_IDX  = Path("storage_simple/faiss.index")
FAISS_META = Path("storage_simple/faiss_meta.json")
FAISS_DOCS = Path("storage_simple/faiss_docs.json")

# ---------------------------
# Normalización / utilidades
# ---------------------------
def _norm(s: str) -> str:
    """Minúsculas + sin tildes + espacios compactos."""
    if s is None:
        return ""
    s = str(s)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return " ".join(s.lower().strip().split())

def _tokens(s: str) -> List[str]:
    return [t for t in re.split(r"\s+", _norm(s)) if t]

# ---------------------------
# Carga de programas
# ---------------------------
def _load_data() -> List[Dict[str, Any]]:
    if DATA_ENR.exists():
        path = DATA_ENR
    elif DATA_NORM.exists():
        path = DATA_NORM
    else:
        path = DATA_RAW

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for p in data:
            p.setdefault("_n_programa",  _norm(p.get("programa", "")))
            p.setdefault("_n_nivel",     _norm(p.get("nivel", "")))
            p.setdefault("_n_municipio", _norm(p.get("municipio", "")))
            p.setdefault("_n_sede",      _norm(p.get("sede", "")))
            p.setdefault("_n_horario",   _norm(p.get("horario", "")))
            p.setdefault("_n_pdf_text",  _norm(p.get("pdf_text", "")))
        log.info(f"✅ Cargado {path.name}: {len(data)} programas")
        return data
    except Exception as e:
        log.error(f"❌ Error cargando {path}: {e}")
        return []

PROGRAMAS: List[Dict[str, Any]] = _load_data()

# ---------------------------
# Embeddings + FAISS (lazy)
# ---------------------------
_vec_model: SentenceTransformer | None = None
_vec_index: faiss.Index | None = None
_vec_meta: List[Dict[str, Any]] | None = None
_vec_docs: List[str] | None = None

def _load_vector_search():
    """Carga perezosa del modelo y el índice."""
    global _vec_model, _vec_index, _vec_meta, _vec_docs
    if _vec_model is None:
        _vec_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    if _vec_index is None and FAISS_IDX.exists():
        _vec_index = faiss.read_index(str(FAISS_IDX))
    if _vec_meta is None and FAISS_META.exists():
        _vec_meta = json.loads(FAISS_META.read_text(encoding="utf-8"))["metas"]
    if _vec_docs is None and FAISS_DOCS.exists():
        _vec_docs = json.loads(FAISS_DOCS.read_text(encoding="utf-8"))["docs"]

def _embed_query(q: str) -> np.ndarray:
    v = _vec_model.encode([q], convert_to_numpy=True, normalize_embeddings=True)
    return v.astype("float32")

def retrieve_chunks(query: str, k: int = 5) -> List[Dict[str, Any]]:
    """Devuelve lista [{pid, programa, programa_n, text, score, rank}]"""
    _load_vector_search()
    if _vec_index is None or _vec_model is None or _vec_meta is None or _vec_docs is None:
        return []
    q = _embed_query(query)
    D, I = _vec_index.search(q, k)
    out = []
    for rank, (idx, score) in enumerate(zip(I[0], D[0])):
        if idx == -1:
            continue
        m = _vec_meta[idx]
        text = _vec_docs[idx]
        out.append(
            {
                "pid": m["pid"],
                "programa": m["programa"],
                "programa_n": m["programa_n"],
                "text": text,
                "score": float(score),
                "rank": rank + 1,
            }
        )
    return out

def _find_program_by_pid_or_name(pid: str, programa_n: str) -> Dict[str, Any] | None:
    """Mapea el hit del índice al dict del programa original."""
    for p in PROGRAMAS:
        if str(p.get("codigo_ficha", "")) == pid or str(p.get("no", "")) == pid:
            return p
    for p in PROGRAMAS:
        if _norm(p.get("programa", "")) == programa_n:
            return p
    return None

# ---------------------------
# Detección de intención
# ---------------------------
DETALLES_JSON_KEYS = {
    "duracion": "duracion",
    "requisitos": "requisitos",
    "perfil": "perfil_egresado",
    "competencias": "competencias",
    "certificacion": "certificacion",
}
DETALLES_PDF_KEYS = {"duracion", "requisitos", "perfil", "competencias", "certificacion"}

def _detect_intent(m_norm: str) -> str | None:
    pairs = [
        ("duracion", ["duracion", "duración", "tiempo", "intensidad"]),
        ("requisitos", ["requisito", "requisitos", "documentos", "ingreso"]),
        ("perfil", ["perfil", "egresado", "ocupacional", "salidas ocupacionales"]),
        ("competencias", ["competencia", "competencias", "resultados de aprendizaje"]),
        ("certificacion", ["titulo", "título", "certificado", "certificacion", "certificación"]),
    ]
    for key, kws in pairs:
        if any(kw in m_norm for kw in kws):
            return key
    return None

# ---------------------------
# Búsqueda por JSON (lista)
# ---------------------------
def _match_program(p: Dict[str, Any], m_norm: str) -> bool:
    """Coincidencia si TODOS los tokens aparecen en alguno de los campos."""
    if not m_norm:
        return False
    toks = _tokens(m_norm)
    haystack = " ".join([
        p.get("_n_programa", ""),
        p.get("_n_nivel", ""),
        p.get("_n_municipio", ""),
        p.get("_n_sede", ""),
        str(p.get("codigo_ficha", "")),
        str(p.get("no", "")),
    ])
    return all(t in haystack for t in toks)
def buscar_programas_json(mensaje: str, show_all: bool = False, limit: int = 5) -> str:
    if not PROGRAMAS:
        return "⚠️ Base de datos no disponible en este momento."

    m_norm = _norm(mensaje)
    resultados = [p for p in PROGRAMAS if _match_program(p, m_norm)]

    # Si nada coincide, intenta sinónimos simples
    if not resultados:
        sinonimos = {
            "informatica": ["software", "programacion", "sistemas", "tic", "computacion"],
            "tecnologo": ["tecnologo", "tecnologia", "tecnologico", "tecnico"],
            "administracion": ["gestion", "empresarial", "administrativo"],
            "alimentos": ["cocina", "gastronomia", "culinaria"],
            "alto cauca": ["alto", "cauca"],  # ayuda a 'alto cauca'
        }
        for clave, lista in sinonimos.items():
            if clave in m_norm:
                for p in PROGRAMAS:
                    nombre = p.get("_n_programa", "")
                    if any(w in nombre for w in lista):
                        resultados.append(p)
                break

    if not resultados:
        ejemplos = "\n".join(
            [f"• {p.get('programa','(sin nombre)')} ({p.get('nivel','N/A')})" for p in PROGRAMAS[:3]]
        )
        return f"❌ No encontré resultados para '{mensaje}'.\n\nAlgunos ejemplos:\n{ejemplos}\n\nPrueba con: técnico, tecnólogo, nombre del programa, municipio o sede."

    total = len(resultados)
    vistos = set()
    unicos = []
    for p in resultados:
        ident = f"{p.get('programa','')}|{p.get('no','')}"
        if ident not in vistos:
            vistos.add(ident)
            unicos.append(p)

    mostrados = unicos if show_all else unicos[:limit]
    r = "🎓 Programas encontrados:\n\n"
    for p in mostrados:
        cod = str(p.get("codigo_ficha") or p.get("no") or "").strip()
        nombre = p.get('programa','Programa')
        # Título con código (si existe)
        titulo = f"• [{cod}] {nombre}" if cod else f"• {nombre}"
        r += titulo + "\n"
        if p.get('nivel'):      r += f"  📍 Nivel: {p['nivel']}\n"
        if p.get('municipio'):  r += f"  🏙️ Municipio: {p['municipio']}\n"
        if p.get('sede'):       r += f"  🏫 Sede: {p['sede']}\n"
        if p.get('horario'):    r += f"  ⏰ Horario: {p['horario']}\n"
        r += "\n"

    # Pie con guía para pedir detalle
    r += "ℹ️ Para ver detalles usa el código. Ejemplos:\n"
    r += "   requisitos 134104   ·   duracion 134104   ·   perfil 134104\n\n"

    if not show_all and len(unicos) > limit:
        r += f"… y {len(unicos) - limit} más. Escribe **más** para verlos todos."
    else:
        r += "¿Te interesa alguno en particular?"
    return r


def _extract_code(m_norm: str) -> str | None:
    """Busca un código de 5 a 7 dígitos en el mensaje normalizado."""
    m = re.search(r"\b(\d{5,7})\b", m_norm)
    return m.group(1) if m else None

def _find_program_by_code(code: str) -> dict | None:
    if not code:
        return None
    for p in PROGRAMAS:
        if str(p.get("codigo_ficha","")) == code or str(p.get("no","")) == code:
            return p
    return None


# ---------------------------
# Respuesta de detalle
# ---------------------------
def responder_detalle(intent: str, mensaje: str) -> str:
    if not PROGRAMAS:
        return "⚠️ Base de datos no disponible en este momento."

    m_norm = _norm(mensaje)

    # 0) Si viene un código, úsalo como primera opción (match exacto)
    code = _extract_code(m_norm)
    prog = _find_program_by_code(code) if code else None

    # 1) Si no vino código o no hubo match, usa búsqueda por nombre/nivel/municipio/sede
    if not prog:
        candidatos = [p for p in PROGRAMAS if _match_program(p, m_norm)]
        prog = candidatos[0] if candidatos else None

    # 2) Si hay programa y el campo existe en JSON enriquecido → úsalo
    if prog and intent in DETALLES_JSON_KEYS:
        campo = DETALLES_JSON_KEYS[intent]
        val = prog.get(campo)
        if isinstance(val, list):
            val = "\n- " + "\n- ".join([str(x) for x in val if str(x).strip()])
        if val and str(val).strip():
            cod = str(prog.get("codigo_ficha") or prog.get("no") or "").strip()
            titulo = f"[{cod}] {prog.get('programa','')}" if cod else prog.get('programa','')
            return f"{intent.capitalize()} — {titulo}:\n{val}"

    # 3) Retrieval semántico (FAISS) como fallback
    hits = retrieve_chunks(m_norm, k=5)
    if hits:
        top = hits[0]
        p_guess = _find_program_by_pid_or_name(top["pid"], top["programa_n"])
        titulo = p_guess.get("programa") if p_guess else top["programa"]
        cod = str((p_guess or {}).get("codigo_ficha") or (p_guess or {}).get("no") or "").strip()
        if cod:
            titulo = f"[{cod}] {titulo}"
        snippet = top["text"]
        if len(snippet) > 400:
            snippet = snippet[:400].rstrip() + "…"
        etiqueta = intent.capitalize()
        return f"{etiqueta} — {titulo} (del PDF):\n{snippet}"

    # 4) Último intento: primer párrafo del PDF del programa localizado
    if prog:
        snippet = prog.get("pdf_text", "")
        if snippet:
            snippet_nice = snippet[:400].rstrip() + ("…" if len(snippet) > 400 else "")
            cod = str(prog.get("codigo_ficha") or prog.get("no") or "").strip()
            titulo = f"[{cod}] {prog.get('programa','')}" if cod else prog.get('programa','')
            return f"{intent.capitalize()} — {titulo} (del PDF):\n{snippet_nice}"

    return f"❌ No encontré información sobre {intent} para esa búsqueda."

# ---------------------------
# Generador de respuestas
# ---------------------------
def generar_respuesta(mensaje: str, show_all: bool = False) -> str:
    """Router principal: saludos/ayuda → detalle → lista."""
    if not mensaje:
        return "No entendí el mensaje. ¿Podrías repetirlo? 😊"

    m_norm = _norm(mensaje)

    # Saludos
    if any(p in m_norm for p in ["hola", "buenos dias", "buenas tardes", "saludos", "hi", "hello"]):
        return "¡Hola! 😊 Soy tu asistente. Dime qué programa buscas (técnico/tecnólogo, área, sede, municipio)."

    # Ayuda
    if any(p in m_norm for p in ["ayuda", "que puedes hacer", "opciones", "funcionas", "como buscar"]):
        return (
            "Puedo buscar por nombre, nivel, municipio o sede (soporto tildes y variantes). "
            "Ejemplos: 'tecnologo en sistemas', 'programas en popayan', 'alto cauca', 'cocina'.\n"
            "También puedo darte detalles: 'requisitos cocina', 'duracion sistemas', 'perfil egresado ADS'."
        )
    # “más” para ver todo (tu webhook puede detectar esto y pasar show_all=True)
    if m_norm.strip() in {"mas", "más", "ver mas", "ver más"}:
        return "Para ver más, envíame tu última búsqueda junto a la palabra 'más'. Ej: 'cocina más'."

    # Intención de detalle
    intent = _detect_intent(m_norm)
    if intent:
        return responder_detalle(intent, m_norm)

    # Lista de programas (con límite y opción de “más”)
    return buscar_programas_json(m_norm, show_all=show_all, limit=5)
