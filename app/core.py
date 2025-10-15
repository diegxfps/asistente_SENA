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

# Requisitos por nivel (agregados y deduplicados)
def _build_reqs_por_nivel() -> Dict[str, List[str]]:
    levels = {"tecnologo": [], "tecnico": [], "operario": [], "auxiliar": []}
    seen = {k: set() for k in levels}
    for p in PROGRAMAS:
        nivel = _norm(p.get("nivel",""))
        reqs = p.get("requisitos") or []
        for k in levels:
            if k in nivel:
                for r in reqs:
                    rn = _norm(r)
                    if rn and rn not in seen[k]:
                        seen[k].add(rn)
                        levels[k].append(str(r).strip())
    return levels

REQS_POR_NIVEL = _build_reqs_por_nivel()


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
# Búsqueda por "nivel + sobre/en/de + tema"
# ---------------------------------------------------------------------
TOPIC_SYNONYMS = {
    "mecanica": ["mecanica","mecánica","automotor","motocic","mecatronica","mantenimiento","vehiculo","vehículos","moto","motos"],
    "sistemas": ["sistemas","software","programacion","programación","redes","teleinformatica","telecomunicaciones"],
    "electricidad": ["electricidad","electrico","eléctrico","fotovoltaica","domot","industrial"],
    "construccion": ["construccion","construcción","arquitectonica","topografia","infraestructura","concreto","edificacion"],
    "ambiental": ["ambiental","saneamiento","agua","residuos","medio ambiente"],
    "dibujo": ["dibujo","modelado","arquitectonica","cad"],
    "metalmecanica": ["metalmec","soldadura","fabricacion","soldadura","mecanizado"],
    "cocina": ["cocina","gastronomia","gastronomía","culinaria","chef","alimentos","alimentación"],
}


NIVEL_CANON = {
    "tecnico":"tecnico","tecnicos":"tecnico",
    "tecnologo":"tecnologo","tecnologos":"tecnologo",
    "auxiliar":"auxiliar","auxiliares":"auxiliar",
    "operario":"operario","operarios":"operario",
}

def _fields_for_topic(p: Dict[str,Any]) -> str:
    """Texto unificado y normalizado para 'tema' (programa + perfil + competencias)."""
    base = [p.get("_n_programa","")]
    perfil = _norm(p.get("perfil_egresado",""))
    comps = " ".join(_norm(x) for x in (p.get("competencias") or []))
    base.extend([perfil, comps])
    return " ".join(base)

def _expand_topic_tokens(topic_tokens: List[str]) -> List[str]:
    out = set(topic_tokens)
    for t in list(topic_tokens):
        for k, syns in TOPIC_SYNONYMS.items():
            if t.startswith(k) or k.startswith(t):
                out.update(syns)
    return list(out)

TOPIC_RE = re.compile(r"^\s*(tecnico[s]?|tecnologo[s]?|auxiliar[es]?|operario[s]?)\s+(sobre|en|de)\s+(.+)$", re.I)

def _buscar_por_nivel_y_tema(texto_norm: str, limit: int = 5) -> Optional[str]:
    m = TOPIC_RE.match(texto_norm)
    if not m:
        return None
    nivel_raw, _, tema = m.groups()
    nivel = NIVEL_CANON.get(_norm(nivel_raw), None)
    if not nivel:
        return None
    # 🚫 Si el "tema" parece una ubicación (municipio/sede), no aplicar modo nivel+tema
    tema_n = _norm(tema)
    # 1) match directo por cadena
    if any(
        (tema_n and (tema_n in p.get("_n_municipio","") or tema_n in p.get("_n_sede","")))
        for p in PROGRAMAS
    ):
        return None
    # 2) o por tokens (ej. "la casona", "alto cauca")
    tema_toks = set(_tokens(tema_n))
    if tema_toks:
        for p in PROGRAMAS:
            loc_toks = set(_tokens(p.get("_n_municipio",""))) | set(_tokens(p.get("_n_sede","")))
            if tema_toks & loc_toks:
                return None

    tema_norm = _norm(tema)
    topic_tokens = _expand_topic_tokens(_tokens(tema_norm))

    # 1) Intento estricto: nivel + tema
    en_nivel = []
    for p in PROGRAMAS:
        if nivel not in _norm(p.get("nivel","")):
            continue
        hay = _fields_for_topic(p)
        if any(tok in hay for tok in topic_tokens):
            en_nivel.append(p)

    # 1.a) Hay resultados en el nivel pedido → mostrar normal
    if en_nivel:
        seen, unicos = set(), []
        for p in en_nivel:
            ident = "|".join([
                p.get('programa',''),
                str(p.get('codigo') or p.get('codigo_ficha') or p.get('no') or ''),
                _norm(p.get('municipio','')),
                _norm(p.get('sede','')),
                _norm(p.get('horario','')),
            ])
            if ident not in seen:
                seen.add(ident); unicos.append(p)
        mostrados = unicos[:limit]

        # 🔢 numerado para que se vean 2..5 claramente
        tarjetas = []
        for i, p in enumerate(mostrados, 1):
            tarjetas.append(f"{i}. " + _card_header(p).lstrip("• ").strip())

        r = "ℹ️ Pide detalle con el **código** o responde **1–5** para elegir.\n"
        r += "📌 Programas encontrados (por nivel y tema):\n\n"
        r += "\n\n".join(tarjetas) + "\n\n"
        if len(unicos) > limit:
            r += "Escribe *más* o *ver todos* para ver más resultados."
        return r


    
    # 2) Sin resultados en el nivel → buscar el mismo tema en otros niveles
    otros_niveles = []
    for p in PROGRAMAS:
        # ignora nivel para ver si el tema existe en la base
        hay = _fields_for_topic(p)
        if any(tok in hay for tok in topic_tokens):
            otros_niveles.append(p)

    if otros_niveles:
        # Mostrar microcopy claro + sugerencias de otros niveles
        seen, unicos = set(), []
        for p in otros_niveles:
            ident = "|".join([
                p.get('programa',''),
                str(p.get('codigo') or p.get('codigo_ficha') or p.get('no') or ''),
                _norm(p.get('municipio','')),
                _norm(p.get('sede','')),
                _norm(p.get('horario','')),
            ])
            if ident not in seen:
                seen.add(ident); unicos.append(p)
        mostrados = unicos[:limit]

        # 🔢 numerado para que se vean 2..5 claramente
        tarjetas = []
        for i, p in enumerate(mostrados, 1):
            tarjetas.append(f"{i}. " + _card_header(p).lstrip("• ").strip())
        
        nl = nivel.upper()
        r = (f"❕ No tengo programas **{nl}** sobre **{tema_norm}** en este momento.\n"
             f"Pero encontré opciones en **otros niveles**:\n\n")
        r += "\n\n".join(_card_header(p) for p in mostrados) + "\n\n"
        r += "ℹ️ Si quieres, pide por **nivel** (técnico/tecnólogo/auxiliar/operario) o por **municipio**.\n"
        return r

    # 3) No existe ese tema en la base → microcopy específico (sin ruido)
    temas_sugeridos = "mecánica, sistemas, electricidad, construcción, ambiental, dibujo, metalmecánica"
    nl = nivel.upper()
    return (f"❌ No encuentro programas **{nl}** sobre **{tema_norm}** en la base.\n"
            f"Temas frecuentes: {temas_sugeridos}.\n"
            f"También puedes buscar por municipio o sede (ej.: *popayán {nivel}*).")


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
    # Stopwords simples para queries conversacionales
    stop = {"sobre","de","en","del","la","el","los","las","para","y","o","un","una","unos","unas"}
    toks = [t for t in _tokens(m_norm) if t not in stop]

    # Detección robusta de nivel por tokens (soporta sing/plural)
    nivel_map = {
        "tecnico": "tecnico", "tecnicos": "tecnico",
        "tecnologo": "tecnologo", "tecnologos": "tecnologo",
        "operario": "operario", "operarios": "operario",
        "auxiliar": "auxiliar", "auxiliares": "auxiliar",
    }
    desired_level = None
    for t in list(toks):
        if t in nivel_map:
            desired_level = nivel_map[t]
            toks.remove(t)  # el nivel no debe participar en el AND de campos
            break


    # Filtros por nivel y horario (conversacionales)
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

    # Filtro AND por tokens + filtros conversacionales
    resultados = []
    for p in PROGRAMAS:
        if not _match_program_all_tokens(p, toks):
            continue
        if desired_level and desired_level not in _norm(p.get('nivel','')):
            continue
        if desired_horario_tokens:
            h = _norm(p.get('horario',''))
            if not all(tk in h for tk in desired_horario_tokens):
                continue
        resultados.append(p)

    # Fallback: si no hubo matches por tokens pero sí hay un nivel pedido → listar por nivel
    if not resultados and desired_level:
        for p in PROGRAMAS:
            if desired_level in _norm(p.get('nivel','')):
                hay = " ".join([p.get("_n_programa",""), p.get("_n_municipio",""), p.get("_n_sede",""), p.get("_n_codigo","")])
                if all(t in hay for t in toks):
                    resultados.append(p)

    # Sin resultados: microcopy honesto (sin sugerencias ruidosas)
    if not resultados:
        ejemplos = "\n".join(
            [f"• {p.get('programa','(sin nombre)')} ({p.get('nivel','N/A')})"
             for p in PROGRAMAS[:3]]
        )
        return (
            f"❌ No encontré coincidencias para “{mensaje}”.\n\n"
            "Prueba así:\n"
            "• nombre del programa  ·  nivel (técnico/tecnólogo/auxiliar/operario)\n"
            "• municipio o sede  ·  duracion 134104\n"
            "• requisitos 134104\n\n"
            f"Algunos ejemplos:\n{ejemplos}"
        )

    # Unicidad por código+nombre
    seen = set()
    unicos: List[Dict[str, Any]] = []
    for p in resultados:
        ident = "|".join([
            p.get('programa',''),
            str(p.get('codigo') or p.get('codigo_ficha') or p.get('no') or ''),
            _norm(p.get('municipio','')),
            _norm(p.get('sede','')),
            _norm(p.get('horario','')),
        ])
        if ident not in seen:
            seen.add(ident)
            unicos.append(p)

    mostrados = unicos if show_all else unicos[:limit]

    # Encabezado + tarjetas enumeradas (1..N)
    tarjetas = []
    for i, p in enumerate(mostrados, 1):
        tarjetas.append(f"{i}. " + _card_header(p).lstrip("• ").strip())
    
    r = "ℹ️ Pide detalle con el **código**. Ejemplos:\n"
    r += "   Requisitos [código]  ·  Duración [código]  ·  Perfil [código]\n"
    r += "·  Si deseas toda la información del programa puedes escribir el código\n\n"
    
    r += "📌 Programas encontrados:\n\n" + "\n\n".join(tarjetas) + "\n\n"

    # Pie con guía

    if not show_all and len(unicos) > limit:
        r += "¿Te interesa alguno en particular?\n"
        r += "💡 Escribe *más* o *ver todos* para ver más resultados."
    else:
        r += "¿Te interesa alguno en particular?"

    return r[:4096]

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

def responder_requisitos_unificados(m_norm: str) -> Optional[str]:
    # Si el usuario pide requisitos SIN código → devolvemos por nivel
    if "requisit" not in m_norm or re.search(r"\b\d{5,7}\b", m_norm):
        return None
    # nivel opcional
    niveles = [("TECNÓLOGO","tecnologo"), ("TÉCNICO","tecnico"), ("OPERARIO","operario"), ("AUXILIAR","auxiliar")]
    target = None
    for etiqueta, key in niveles:
        if key in m_norm:
            target = (etiqueta, key)
            break

    def bloque(etiqueta: str, key: str) -> str:
        vals = REQS_POR_NIVEL.get(key, [])
        cuerpo = "• " + "\n• ".join(vals) if vals else "(No tengo ese dato en este momento)."
        # recorte defensivo
        if len(cuerpo) > 900:  # para no exceder 4096 sumando 4 bloques
            cuerpo = cuerpo[:900].rstrip() + "…"
        return f"◾ *{etiqueta}:*\n{cuerpo}\n"

    if target:
        etiqueta, key = target
        return f"**Requisitos por nivel — {etiqueta}**\n\n{bloque(etiqueta, key)}".strip()[:4096]

    # Todos los niveles
    partes = ["**Requisitos por nivel**\n"]
    for etiqueta, key in niveles:
        partes.append(bloque(etiqueta, key))
    out = "\n".join(partes).strip()
    return out[:4096]


# ---------------------------------------------------------------------
# Generador principal
# ---------------------------------------------------------------------
def generar_respuesta(texto: str, show_all: bool = False, page: int = 0, page_size: int = 10) -> str:
    """
    Flujo de respuesta:
      1) Saludos/Ayuda (ampliado)
      2) Requisitos/Duración/Perfil... por NIVEL (general; sin código)
      3) Código + ordinal
      4) Código puro
      5) Consulta por TEMA (con/sin NIVEL)  -> lista paginada 10×10
      6) NIVEL SOLO (técnico/tecnólogo/auxiliar/operario) -> lista paginada 10×10
      7) Búsqueda genérica -> lista paginada 10×10
    """
    if not texto:
        return "Escribe una consulta, por ejemplo: *técnico en sistemas Popayán* o el *código* del programa."

    q = _norm(texto)
    toks = set(_tokens(q))

    # 1) Saludos / Ayuda (ampliado)
    SALUDOS = {
        "hola","buenos dias","buenas tardes","buenas noches",
        "buen dia","buen día","buenas","menu","menú","ayuda","start","hi","hello"
    }
    if any(sal in q for sal in SALUDOS):
        return (
            "¡Hola! Soy tu asistente SENA 👋\n\n"
            "Puedes enviarme:\n"
            "• Un *código* (ej. 228118)\n"
            "• Un *nivel + tema* (ej. *técnico sobre contabilidad*)\n"
            "• Una *búsqueda* por ciudad o palabra clave (ej. *Popayán técnico*)\n\n"
            "También: *requisitos técnico*, *duración tecnólogo*, *perfil auxiliar*, etc."
        )

    # 2) Requisitos/Duración/Perfil... por NIVEL (general)
    FOLLOW = {"requisitos","requisito","req","duracion","duración","tiempo","perfil","competencias","certificacion","certificación"}
    NIVEL_TOKENS = set(NIVEL_CANON.keys())
    if any(w in q for w in FOLLOW) and not re.search(r"\b\d{5,7}\b", q):
        nivel_detectado = None
        for canon, nivel_txt in NIVEL_CANON.items():
            if canon in q:
                nivel_detectado = nivel_txt
                break
        ocurrencias = { "requisitos": set(), "duración": set(), "perfil": set(), "competencias": set(), "certificación": set() }
        for p in PROGRAMAS:
            if nivel_detectado and (nivel_detectado not in _norm(p.get("nivel",""))):
                continue
            if p.get("requisitos"): ocurrencias["requisitos"].add(_norm(str(p["requisitos"]))[:400])
            if p.get("duracion") or p.get("duración"): ocurrencias["duración"].add(_norm(str(p.get("duracion") or p.get("duración")))[:150])
            if p.get("perfil"): ocurrencias["perfil"].add(_norm(str(p["perfil"]))[:400])
            if p.get("competencias"): ocurrencias["competencias"].add(_norm(str(p["competencias"]))[:400])
            if p.get("certificacion") or p.get("certificación"): ocurrencias["certificación"].add(_norm(str(p.get("certificacion") or p.get("certificación")))[:250])
        etiquetas_orden = ["requisitos","duración","perfil","competencias","certificación"]
        partes = []
        titulo_nivel = f" {nivel_detectado}" if nivel_detectado else ""
        for etq in etiquetas_orden:
            if ocurrencias[etq]:
                ejemplos = list(ocurrencias[etq])[:2]  # 2 para que suene general
                bullets = "\n".join(f"- {ej[:500]}{'…' if len(ej)>=500 else ''}" for ej in ejemplos)
                partes.append(f"*{etq.title()}{titulo_nivel}:*\n{bullets}")
        if partes:
            partes.append("\nSi quieres ver un programa específico, envía su *código* (ej. 228118) o escribe un tema más concreto.")
            return "\n\n".join(partes)

    # 3) Código + ordinal
    m_code_idx = re.fullmatch(r"\s*(\d{5,7})-(\d{1,2})\s*", q or "")
    if m_code_idx:
        base, ord_str = m_code_idx.groups()
        return ficha_por_codigo_y_ordinal(base, int(ord_str))

    # 4) Código puro
    m_code = re.fullmatch(r"\s*(\d{5,7})\s*", q or "")
    if m_code:
        return ficha_por_codigo(m_code.group(1))

    # Sinónimos de tema
    TOPIC_SYNONYMS = {
        "contabilidad": {"contabilidad","contable","cuentas","costos","finanzas","tributaria","nomina","nómina"},
        "salud": {"salud","enfermeria","enfermería","hospitalario","clínico","clinico"},
        "software": {"software","programacion","programación","desarrollo","sistemas"},
        "datos": {"datos","data","analitica","analítica","bi","inteligencia de negocios"},
    }
    def expand_topic_tokens_local(tokens):
        base = set(tokens)
        for t in list(tokens):
            if t in TOPIC_SYNONYMS:
                base |= TOPIC_SYNONYMS[t]
        return _expand_topic_tokens(base)

    # 5.a) nivel + (sobre|en|de) + tema  -> lista paginada
    m_topic = TOPIC_RE.match(q)
    if m_topic:
        nivel_raw, _, tema = m_topic.groups()
        nivel = NIVEL_CANON.get(_norm(nivel_raw), None)
        if nivel:
            topic_tokens = expand_topic_tokens_local(_tokens(_norm(tema)))
            encontrados = []
            for p in PROGRAMAS:
                if nivel not in _norm(p.get("nivel", "")):
                    continue
                hay = _fields_for_topic(p)
                if any(tok in hay for tok in topic_tokens):
                    cod = str(p.get("codigo") or p.get("codigo_ficha") or p.get("no") or "").strip()
                    if cod:
                        encontrados.append(cod)
            lista = list(dict.fromkeys(encontrados))
            if not lista:
                return "No encontré resultados con ese tema."
            start, end = page*page_size, (page+1)*page_size
            page_items = lista[start:end]
            header = f"Resultados para *{nivel.lower()}* sobre *{tema}* (pág. {page+1}):"
            per_code_count, body_lines = {}, []
            for i, cod in enumerate(page_items, start=1):
                f = _find_by_code(cod)
                if not f: continue
                per_code_count[cod] = per_code_count.get(cod, 0) + 1
                ord_n = per_code_count[cod]
                titulo = f.get('programa') or f.get('nombre') or "Programa"
                body_lines.append(f"{i}. {titulo}  —  Código [{cod}]  (respuesta: {cod}-{ord_n})")
            footer = ""
            if end < len(lista):
                footer = "\nEscribe *ver más* para ver los siguientes 10."
            if not body_lines:
                return "No hay más resultados en esta lista."
            return f"{header}\n" + "\n".join(body_lines) + footer

    # 5.b) tema solo  -> lista paginada
    if not (toks & NIVEL_TOKENS) and len(toks) <= 3:
        topic_tokens = expand_topic_tokens_local(toks)
        encontrados = []
        for p in PROGRAMAS:
            hay = _fields_for_topic(p)
            if any(tok in hay for tok in topic_tokens):
                cod = str(p.get("codigo") or p.get("codigo_ficha") or p.get("no") or "").strip()
                if cod:
                    encontrados.append(cod)
        lista = list(dict.fromkeys(encontrados))
        if not lista:
            return "No encontré resultados con ese tema."
        start, end = page*page_size, (page+1)*page_size
        page_items = lista[start:end]
        header = f"Resultados para el tema *{texto.strip()}* (pág. {page+1}):"
        per_code_count, body_lines = {}, []
        for i, cod in enumerate(page_items, start=1):
            f = _find_by_code(cod)
            if not f: continue
            per_code_count[cod] = per_code_count.get(cod, 0) + 1
            ord_n = per_code_count[cod]
            titulo = f.get('programa') or f.get('nombre') or "Programa"
            body_lines.append(f"{i}. {titulo}  —  Código [{cod}]  (respuesta: {cod}-{ord_n})")
        footer = ""
        if end < len(lista):
            footer = "\nEscribe *ver más* para ver los siguientes 10."
        if not body_lines:
            return "No hay más resultados en esta lista."
        return f"{header}\n" + "\n".join(body_lines) + footer

    # 6) nivel SOLO -> lista paginada
    SOLO_NIVEL = None
    for canon, nivel_txt in NIVEL_CANON.items():
        if re.fullmatch(rf"\s*{canon}s?\s*", q or ""):
            SOLO_NIVEL = nivel_txt
            break
    if SOLO_NIVEL:
        cods = []
        for p in PROGRAMAS:
            if SOLO_NIVEL in _norm(p.get("nivel","")):
                cod = str(p.get("codigo") or p.get("codigo_ficha") or p.get("no") or "").strip()
                if cod: cods.append(cod)
        lista = list(dict.fromkeys(cods))
        if not lista:
            return f"No encontré programas para el nivel *{SOLO_NIVEL}*."
        start, end = page*page_size, (page+1)*page_size
        page_items = lista[start:end]
        header = f"Programas del nivel *{SOLO_NIVEL}* (pág. {page+1}):"
        per_code_count, body_lines = {}, []
        for i, cod in enumerate(page_items, start=1):
            f = _find_by_code(cod)
            if not f: continue
            per_code_count[cod] = per_code_count.get(cod, 0) + 1
            ord_n = per_code_count[cod]
            titulo = f.get('programa') or f.get('nombre') or "Programa"
            body_lines.append(f"{i}. {titulo}  —  Código [{cod}]  (respuesta: {cod}-{ord_n})")
        footer = ""
        if end < len(lista):
            footer = "\nEscribe *ver más* para ver los siguientes 10."
        return f"{header}\n" + "\n".join(body_lines) + footer

    # 7) búsqueda genérica -> usa tu ranker, pero pagina
    cods = top_codigos_para(q, limit=9999 if show_all else 1000)  # grande para paginar local
    if not cods:
        return (
            "No encontré coincidencias. Prueba con:\n"
            "• Una ciudad o sede + nivel (ej. *Popayán técnico*)\n"
            "• Un *tema* (ej. *contabilidad*, *software*, *salud*)\n"
            "• El *código* del programa (ej. 228118)"
        )
    start, end = page*page_size, (page+1)*page_size
    page_items = cods[start:end]
    header = ("Resultados:" if page == 0 else f"Resultados (pág. {page+1}):")
    per_code_count, body_lines = {}, []
    for i, cod in enumerate(page_items, start=1):
        f = _find_by_code(cod)
        if not f: continue
        per_code_count[cod] = per_code_count.get(cod, 0) + 1
        ord_n = per_code_count[cod]
        titulo = f.get('programa') or f.get('nombre') or "Programa"
        body_lines.append(f"{i}. {titulo}  —  Código [{cod}]  (respuesta: {cod}-{ord_n})")
    footer = ""
    if end < len(cods):
        footer = "\nEscribe *ver más* para ver los siguientes 10."
    return f"{header}\n" + "\n".join(body_lines) + footer

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
        ident = "|".join([
            p.get('programa',''),
            str(p.get('codigo') or p.get('codigo_ficha') or p.get('no') or ''),
            _norm(p.get('municipio','')),
            _norm(p.get('sede','')),
            _norm(p.get('horario','')),
        ])
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
def ficha_por_codigo_y_ordinal(codigo: str, ordinal: int) -> str:
    """Devuelve la ficha de la 'ordinal'-ésima ocurrencia de 'codigo' en PROGRAMAS."""
    codigo_n = _norm(codigo)
    count = 0
    for p in PROGRAMAS:
        code_p = _norm(p.get("codigo") or p.get("codigo_ficha") or p.get("no") or "")
        if code_p == codigo_n:
            count += 1
            if count == ordinal:
                return _ficha_completa(p)
    return f"❌ No encontré la variante {codigo}-{ordinal}."
