# app/core.py
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Fuente única de la verdad: JSON ENRIQUECIDO
# ---------------------------------------------------------------------
DATA_ENR = Path("storage_simple/programas_enriquecido.json")

def _norm(s: Any) -> str:
    """minúsculas, sin tildes, espacios compactos."""
    if s is None:
        return ""
    s = str(s)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return " ".join(s.lower().strip().split())

def _tokens(s: str) -> List[str]:
    return [t for t in re.split(r"\s+", _norm(s)) if t]

def _load_data() -> List[Dict[str, Any]]:
    try:
        data = json.loads(DATA_ENR.read_text(encoding="utf-8"))
        for p in data:
            # claves normalizadas para búsquedas
            p["_n_programa"]  = _norm(p.get("programa", ""))
            p["_n_nivel"]     = _norm(p.get("nivel", ""))
            p["_n_municipio"] = _norm(p.get("municipio", ""))
            p["_n_sede"]      = _norm(p.get("sede", ""))
            p["_n_codigo"]    = _norm(p.get("codigo") or p.get("codigo_ficha") or p.get("no") or "")
        log.info(f"✅ Cargado {DATA_ENR.name}: {len(data)} programas")
        return data
    except Exception as e:
        log.error(f"❌ No pude cargar {DATA_ENR}: {e}")
        return []

PROGRAMAS: List[Dict[str, Any]] = _load_data()

# ---------------------------------------------------------------------
# Intenciones y helpers
# ---------------------------------------------------------------------
DETALLES_KEYS = {
    "duracion": "duracion",
    "requisitos": "requisitos",
    "perfil": "perfil_egresado",
    "competencias": "competencias",
    "certificacion": "certificacion",
}
_INTENT_DICT = [
    ("duracion", ["duracion", "duración", "tiempo", "intensidad", "horas", "meses", "cuanto dura", "cuánto dura", "dura", "durara"]),
    ("requisitos", ["requisito", "requisitos", "documentos", "ingreso", "necesito", "piden", "edad minima", "edad mínima"]),
    ("perfil", ["perfil", "egresado", "ocupacional", "salidas ocupacionales", "que aprende", "qué aprende", "que voy a aprender"]),
    ("competencias", ["competencia", "competencias", "resultados de aprendizaje"]),
    ("certificacion", ["titulo", "título", "certificado", "certificacion", "certificación", "que titulo dan", "qué título dan"]),
]


def _detect_intent(m_norm: str) -> Optional[str]:
    for key, kws in _INTENT_DICT:
        if any(kw in m_norm for kw in kws):
            return key
    return None

def _extract_code(m_norm: str) -> Optional[str]:
    m = re.search(r"\b(\d{5,7})\b", m_norm)
    return m.group(1) if m else None

def _find_by_code(code: str) -> Optional[Dict[str, Any]]:
    if not code:
        return None
    code = _norm(code)
    for p in PROGRAMAS:
        if _norm(p.get("codigo") or p.get("codigo_ficha") or p.get("no")) == code:
            return p
    return None

def _score_match(p: Dict[str, Any], toks: List[str]) -> Tuple[int, int]:
    """Score para elegir mejor programa por texto (coincidencias + campos)."""
    hay = " ".join([p.get("_n_programa",""), p.get("_n_nivel",""),
                    p.get("_n_municipio",""), p.get("_n_sede",""),
                    p.get("_n_codigo","")])
    hits = sum(1 for t in toks if t in hay)
    # pequeño bonus si aparece en nombre de programa
    hits_prog = sum(1 for t in toks if t in p.get("_n_programa",""))
    return (hits, hits_prog)

def _best_program_by_text(m_norm: str) -> Optional[Dict[str, Any]]:
    toks = _tokens(m_norm)
    if not toks:
        return None
    scored: List[Tuple[Tuple[int,int], Dict[str,Any]]] = []
    for p in PROGRAMAS:
        s = _score_match(p, toks)
        if s[0] > 0:
            scored.append((s, p))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0][0], x[0][1]), reverse=True)
    return scored[0][1]

# ---------------------------------------------------------------------
# Búsquedas de lista
# ---------------------------------------------------------------------

def _match_program_all_tokens(p: Dict[str, Any], toks: List[str]) -> bool:
    if not toks:
        return False
    hay = " ".join([p.get("_n_programa",""), p.get("_n_nivel",""),
                    p.get("_n_municipio",""), p.get("_n_sede",""),
                    p.get("_n_codigo","")])
    return all(t in hay for t in toks)

def buscar_programas_json(mensaje: str, show_all: bool = False, limit: int = 5) -> str:
    """Lista de resultados más legible (solo formato)."""
    if not PROGRAMAS:
        return "⚠️ Base de datos no disponible en este momento."

    m_norm = _norm(mensaje)
    toks = _tokens(m_norm)

    # Filtros por nivel y horario (conversacionales)
    nivel_keys = {"tecnico": "tecnico", "tecnologo": "tecnologo", "operario": "operario", "auxiliar": "auxiliar"}
    desired_level = None
    for k in nivel_keys:
        if k in m_norm:
            desired_level = nivel_keys[k]  # <-- ya normalizado
            break

    horario_terms = {
        "noche":  ["noche","nocturna","nocturno"],
        "mañana": ["mañana","manana","matutina"],
        "tarde":  ["tarde","vespertina"],
        "sabado": ["sábado","sabado","fin de semana","sábado y domingo","sabados"],
    }
    desired_horario_tokens = [w for arr in horario_terms.values() for w in arr if w in m_norm]

    # Filtro AND por tokens (igual que antes)
    resultados = []
    for p in PROGRAMAS:
        if not _match_program_all_tokens(p, toks):
            continue
        if desired_level and desired_level.lower() not in _norm(p.get('nivel','')):
            continue
        if desired_horario_tokens:
            h = _norm(p.get('horario',''))
            if not all(tk in h for tk in desired_horario_tokens):
                continue
        resultados.append(p)

        # --- Fallback por NIVEL si no hubo matches por tokens ---
    if not resultados and desired_level:
        for p in PROGRAMAS:
            if desired_level in _norm(p.get('nivel','')):
                resultados.append(p)

    if not resultados:
        # mismos sinónimos básicos
        sinonimos = {
            "informatica": ["software", "programacion", "sistemas", "tic", "computacion"],
            "tecnologo": ["tecnologo", "tecnologia", "tecnologico", "tecnico"],
            "administracion": ["gestion", "empresarial", "administrativo"],
            "alimentos": ["cocina", "gastronomia", "culinaria"],
            "alto cauca": ["alto", "cauca"],
        }
        for clave, lista in sinonimos.items():
            if clave in m_norm:
                for p in PROGRAMAS:
                    if any(w in p.get("_n_programa","") for w in lista):
                        resultados.append(p)
                break

    if not resultados:
        ejemplos = "\n".join(
            [f"• {p.get('programa','(sin nombre)')} ({p.get('nivel','N/A')})"
             for p in PROGRAMAS[:3]]
        )
        return (
            f"❌ No encontré resultados para “{mensaje}”.\n\n"
            "🔎 Prueba así:\n"
            "• popayán técnico / tecnólogo\n"
            "• alto cauca  \n"
            "• requisitos 134104  \n\n"
            f"Algunos ejemplos:\n{ejemplos}"
        )

    # Unicidad por código+nombre (igual)
    seen = set()
    unicos: List[Dict[str, Any]] = []
    for p in resultados:
        ident = f"{p.get('programa','')}|{p.get('codigo') or p.get('codigo_ficha') or p.get('no')}"
        if ident not in seen:
            seen.add(ident)
            unicos.append(p)

    mostrados = unicos if show_all else unicos[:limit]

    # Encabezado de la lista
    r = "📌 Programas encontrados:\n\n"
    for p in mostrados:
        r += _card_header(p) + "\n\n"

    # Pie con guía
    r += "ℹ️ Pide detalle con el **código**. Ejemplos:\n"
    r += "   Requisitos 134104  ·  Duración 134104  ·  Perfil 134104\n"
    r += "·  Si deseas toda la información del programa puedes escribir el código\n\n"

    if not show_all and len(unicos) > limit:
        r += "¿Te interesa alguno en particular?\n"
        r += "💡 Escribe *más* o *ver todos* para ver más resultados."
    else:
        r += "¿Te interesa alguno en particular?"
    return r

# ---------------------------------------------------------------------
# Respuestas de detalle (siempre del JSON enriquecido)
# ---------------------------------------------------------------------
def _fmt_list(values: Any) -> str:
    """Listas con bullets limpias."""
    if isinstance(values, list):
        vals = [str(x).strip() for x in values if str(x).strip()]
        if not vals:
            return ""
        # • item  (una por línea)
        return "• " + "\n• ".join(vals)
    return str(values or "").strip()

def _fmt_bullets(values: Any) -> str:
    if isinstance(values, list):
        vals = [str(x).strip() for x in values if str(x).strip()]
        if not vals:
            return "—"
        return "• " + "\n• ".join(vals)
    return str(values or "—").strip()

def _ficha_completa(prog: Dict[str, Any]) -> str:
    """Construye la ficha completa desde el JSON para enviar por WhatsApp."""
    # Campos base
    codigo = str(prog.get("codigo") or prog.get("codigo_ficha") or prog.get("no") or "").strip()
    titulo = prog.get("programa", "Programa")
    nivel  = prog.get("nivel", "—")
    muni   = prog.get("municipio", "—")
    sede   = prog.get("sede", "—")
    horario = prog.get("horario", "—")
    dur   = prog.get("duracion", "—")
    req   = _fmt_bullets(prog.get("requisitos"))
    perfil = str(prog.get("perfil_egresado") or "—").strip()
    comp  = _fmt_bullets(prog.get("competencias"))
    cert  = str(prog.get("certificacion") or "—").strip()

    # Encabezado + metadatos
    partes = []
    partes.append(f"📘 **{titulo}**")
    partes.append(f"   {nivel}  ·  Código [{codigo}]" if codigo else f"   {nivel}")
    if prog.get("municipio"): partes.append(f"🏙️ {muni}")
    if prog.get("sede"):      partes.append(f"🏫 {sede}")
    if prog.get("horario"):   partes.append(f"🕒 {horario}")

    # Secciones
    secciones = [
        ("Duración", dur),
        ("Requisitos", req),
        ("Perfil del egresado", perfil),
        ("Competencias", comp),
        ("Certificación", cert),
    ]

    cuerpo = "\n".join(partes) + "\n\n"
    for titulo_sec, contenido in secciones:
        # recorte defensivo por límite de WhatsApp (4096 chars); margen por encabezado:
        contenido_str = (contenido or "—").strip()
        if len(contenido_str) > 1500:
            contenido_str = contenido_str[:1500].rstrip() + "…"
        cuerpo += f"◾ *{titulo_sec}:*\n{contenido_str}\n\n"

    # Cierre con guía
    cuerpo += "ℹ️ Pide un campo puntual con:  requisitos {c} · duracion {c} · perfil {c} · competencias {c} · certificacion {c}".format(c=codigo or "<código>")
    return cuerpo[:4096]  # seguridad dura para WhatsApp

def _card_header(p: Dict[str, Any]) -> str:
    """Encabezado compacto y legible para un programa."""
    titulo = p.get("programa", "Programa")
    nivel  = p.get("nivel", "N/A")
    codigo = str(p.get("codigo") or p.get("codigo_ficha") or p.get("no") or "").strip()
    muni   = p.get("municipio", "")
    sede   = p.get("sede", "")
    hor    = p.get("horario", "")
    line1 = f"• {titulo}\n   {nivel}  ·  Código [{codigo}]" if codigo else f"• {titulo}\n   {nivel}"
    line2 = ""
    if muni: line2 += f"\n   🏙️ {muni}"
    if sede: line2 += f"\n   🏫 {sede}"
    if hor:  line2 += f"\n   🕒 {hor}"
    return line1 + line2

def responder_detalle(intent: str, mensaje: str) -> str:
    """Detalle más amigable (solo formato)."""
    if not PROGRAMAS:
        return "⚠️ Base de datos no disponible en este momento."

    m_norm = _norm(mensaje)

    # 1) Código exacto
    code = _extract_code(m_norm)
    prog = _find_by_code(code) if code else None
    # 2) Mejor match por texto si no hay código
    if not prog:
        prog = _best_program_by_text(m_norm)

    if not prog:
        return ("❌ No pude identificar el programa.\n"
                "Pide así: “requisitos 134104”, “requisitos nombre_del_programa” o por código.")

    campo = DETALLES_KEYS[intent]
    val = prog.get(campo)

    # Encabezado consistente
    titulo = prog.get("programa","")
    codigo = str(prog.get("codigo") or prog.get("codigo_ficha") or prog.get("no") or "").strip()
    nivel  = prog.get("nivel","N/A")
    encabezado = f"**{titulo}** — {nivel}  ·  código {codigo}" if codigo else f"**{titulo}** — {nivel}"

    etiqueta = intent.capitalize()
    if not val or (isinstance(val, list) and not val):
        return f"{encabezado}\n\n{etiqueta}:\n(No tengo ese dato en este momento)."

    # Cuerpo según tipo de campo
    if intent in {"requisitos", "competencias"}:
        cuerpo = _fmt_list(val)
    else:
        cuerpo = str(val).strip()

    # Contexto (municipio/sede/horario) opcional en una línea
    extras = []
    if prog.get("municipio"): extras.append(f"🏙️ {prog['municipio']}")
    if prog.get("sede"):      extras.append(f"🏫 {prog['sede']}")
    if prog.get("horario"):   extras.append(f"🕒 {prog['horario']}")
    meta = "  ·  ".join(extras)

    # Límite seguro para WhatsApp
    if len(cuerpo) > 1500:
        cuerpo = cuerpo[:1500].rstrip() + "…"

    out = f"{encabezado}\n"
    if meta:
        out += f"{meta}\n"
    out += f"\n{etiqueta}:\n{cuerpo}"
    return out

# ---------------------------------------------------------------------
# Generador principal
# ---------------------------------------------------------------------
def generar_respuesta(mensaje: str, show_all: bool = False) -> str:
    if not mensaje:
        return "No entendí el mensaje. ¿Podrías repetirlo? 😊"

    m_norm = _norm(mensaje)

    # Saludos con guía corta
    if any(p in m_norm for p in ["hola", "buenos dias", "buenas tardes", "saludos", "hi", "hello","hla","bnas", "Buenas"]):
        return (
            "👋 ¡Hola! Soy tu asistente SENA.\n\n"
            "🔎 ¿Qué deseas buscar?\n"
            "• Puedo darte brindarte información sobre tecnicos, tecnologos, operarios y/o auxiliares.\n"
            "• Detalles por código de programa: 'requisitos [código]', 'duración [código]'.\n"
            "• Si deseas la información completa de un programa puedes escribir el código del programa.\n\n"
            "💡 Tips: si ves muchos resultados escribe *más* o *ver todos*.\n\n"
            "• Para saber más sobre cómo preguntar escribe 'ayuda'"
        )

    # Ayuda
    if any(p in m_norm for p in ["ayuda", "que puedes hacer", "opciones", "funcionas", "como buscar"]):
        return (
            "Puedo buscar por nombre, nivel, municipio o sede y darte detalles por **código**.\n"
            "Ejemplos:\n"
            "• 'tecnologo en sistemas'\n"
            "• 'programas en popayan'\n"
            "• 'requisitos 134104', 'duracion 134104'\n"
        )

    # 1) Si el usuario envía SOLO un código de 5-7 dígitos → ficha completa
    m_code_only = re.fullmatch(r"\s*(\d{5,7})\s*", mensaje or "")
    if m_code_only:
        code = m_code_only.group(1)
        prog = _find_by_code(code)
        if not prog:
            return f"❌ No encontré el código {code} en la base."
        return _ficha_completa(prog)


    # Intención de detalle
    intent = _detect_intent(m_norm)
    if intent:
        return responder_detalle(intent, m_norm)

    # Lista de programas
    return buscar_programas_json(m_norm, show_all=show_all, limit=5)

def top_codigos_para(mensaje: str, limit: int = 5) -> List[str]:
    """Devuelve códigos de los top resultados (en el mismo orden que la lista)."""
    if not PROGRAMAS:
        return []
    m_norm = _norm(mensaje)
    toks = _tokens(m_norm)

    nivel_keys = {"tecnico": "tecnico", "tecnologo": "tecnologo", "operario": "operario", "auxiliar": "auxiliar"}
    desired_level = None
    for k in nivel_keys:
        if k in m_norm:
            desired_level = nivel_keys[k]
            break

    horario_terms = {
        "noche":  ["noche","nocturna","nocturno"],
        "mañana": ["mañana","manana","matutina"],
        "tarde":  ["tarde","vespertina"],
        "sabado": ["sábado","sabado","fin de semana","sábado y domingo","sabados"],
    }
    desired_horario_tokens = [w for arr in horario_terms.values() for w in arr if w in m_norm]

    candidatos = []
    for p in PROGRAMAS:
        if not _match_program_all_tokens(p, toks):
            continue
        if desired_level and desired_level not in _norm(p.get('nivel','')):
            continue
        if desired_horario_tokens:
            h = _norm(p.get('horario',''))
            if not all(tk in h for tk in desired_horario_tokens):
                continue
        candidatos.append(p)

    if not candidatos and desired_level:
        for p in PROGRAMAS:
            if desired_level in _norm(p.get('nivel','')):
                candidatos.append(p)

    seen, unicos = set(), []
    for p in candidatos:
        ident = f"{p.get('programa','')}|{p.get('codigo') or p.get('codigo_ficha') or p.get('no')}"
        if ident not in seen:
            seen.add(ident); unicos.append(p)

    codes = []
    for p in unicos[:limit]:
        codes.append(str(p.get('codigo') or p.get('codigo_ficha') or p.get('no') or '').strip())
    return codes

def ficha_por_codigo(codigo: str) -> str:
    p = _find_by_code(codigo)
    if not p:
        return f"❌ No encontré el código {codigo} en la base."
    return _ficha_completa(p)
