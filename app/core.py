import os, json, re, unicodedata
from collections import defaultdict

# ========================= CARGA DE DATOS =========================
def _here(*parts):
    return os.path.join(os.path.dirname(__file__), *parts)

PROGRAMAS_PATH_CANDIDATES = [
    _here("programas_enriquecido.json"),                          # app/programas_enriquecido.json
    _here("..", "programas_enriquecido.json"),                    # /app/programas_enriquecido.json
    _here("..", "storage_simple", "programas_enriquecido.json"),  # /app/storage_simple/programas_enriquecido.json  👈
    _here("storage_simple", "programas_enriquecido.json"),        # app/storage_simple/programas_enriquecido.json   (por si acaso)
    "programas_enriquecido.json",                                 # raíz del repo (modo local)
]

PROGRAMAS = []
for pth in PROGRAMAS_PATH_CANDIDATES:
    if os.path.exists(pth):
        with open(pth, "r", encoding="utf-8") as fh:
            PROGRAMAS = json.load(fh)
        break
if not PROGRAMAS:
    PROGRAMAS = []  # evita crash si no encuentra archivo

# ========================= NORMALIZACIÓN =========================
def _norm(s: str) -> str:
    if not s:
        return ""
    s = "".join(ch for ch in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _tokens(s: str):
    return [t for t in re.split(r"[^\w]+", _norm(s)) if t]

# Campos “temáticos” para buscar por tema
def _fields_for_topic(p: dict) -> str:
    campos = [
        p.get("programa") or p.get("nombre") or "",
        p.get("perfil") or p.get("perfil_egresado") or "",
        p.get("competencias") or "",
        p.get("descripcion") or p.get("descripción") or "",
        p.get("requisitos") or "",
    ]
    return _norm(" ".join([str(x) for x in campos if x]))

# Mapa de niveles (clave = cómo lo escribe la gente, valor = forma canónica normalizada)
NIVEL_CANON = {
    "tecnico": "tecnico",
    "tecnicos": "tecnico", 
    "tec": "tecnico",

    "tecnologo": "tecnologo", 
    "tecnologos": "tecnologo",
    "tecnologia": "tecnologo", 

    "auxiliar": "auxiliar", 
    "auxiliares": "auxiliar",
    
    "operario": "operario", 
    "operarios": "operario",
}

# Expandir tokens de tema (sinónimos básicos; puedes añadir más)
_TOPIC_SYNONYMS = {
    # Negocios/finanzas
    "gestion empresarial": {
        "contabilidad", "contable", "cuentas", "costos", "finanzas",
        "tesoreria", "facturacion", "tributaria", "nomina"
    },
    "gestion empresarial": {"gestion", "empresarial", "gestion empresarial", "administracion"},
    "logistica": {"logistica", "logistico", "suministros"},

    # TIC
    "analisis y desarrollo de software": {
        "software", "programacion", "desarrollo", "sistemas",
        "computacion", "analisis y desarrollo", "ads", "adso", "analisis y desarrollo de software"
    },
    "redes": {"redes", "telecomunicaciones", "teleinformatica", "teleinformaticos", "cisco"},

    # Industria/ingenierias
    "automatizacion de sistemas mecatronicos": {"mecatronica", "automatizacion", "automatizacion industrial", "robotica", "sistemas mecatronicos"},
    "electricidad industrial": {"electricidad", "electrico", "electrica", "instalaciones electricas"},
    "construccion": {"construccion", "obra civil", "edificaciones", "albañileria"},

    # Salud
    "supervision en sistemas de agua y saneamiento": {
        "supervision", "agua", "sistemas de agua", "saneamiento"
    },

    # Deportes / actividad fisica
    "deporte": {"deporte", "actividad fisica", "entrenamiento", "fisiologia"},
}
def _expand_topic_tokens(tokens:set) -> set:
    base = set(tokens)
    for t in list(tokens):
        if t in _TOPIC_SYNONYMS:
            base |= _TOPIC_SYNONYMS[t]
    return base

# Patrón “nivel + (sobre|en|de) + tema/ubicación”
TOPIC_RE = re.compile(
    r"^(tecnico[s]?|tecnologo[s]?|auxiliar[es]?|operario[s]?)\s+(sobre|en|de)\s+(.+)$",
    re.I,
)


# ========================= HELPERS DE CÓDIGO/UBICACIÓN =========================
def _code_of(p):  # string
    return str(p.get("codigo") or p.get("codigo_ficha") or p.get("no") or "").strip()

def _nivel_of(p):  # normalizado
    return _norm(p.get("nivel", ""))

def _loc_fields(p):
    return (
        p.get("municipio") or p.get("ciudad") or p.get("lugar") or "",
        p.get("sede") or p.get("centro") or p.get("ambiente") or "",
        p.get("horario") or p.get("jornada") or p.get("dias") or p.get("días") or "",
    )

def _ordinal_for_variant(code: str, p_obj) -> int:
    lst = BY_CODE.get(str(code).strip(), [])
    for i, pi in enumerate(lst, start=1):
        if pi is p_obj:
            return i
    return 1

def _loc_text(p):
    c, s, h = _loc_fields(p)
    return _norm(" ".join([str(x) for x in (c, s, h) if x]))

def _fields_for_title(p):
    return _norm(p.get("programa") or p.get("nombre") or "")

# ========================= ÍNDICES =========================
BY_CODE = defaultdict(list)         # codigo -> [variant,...]
BY_MUNICIPIO = defaultdict(list)    # municipio_norm -> [p,...]
BY_SEDE = defaultdict(list)         # sede_norm -> [p,...]
NG_SEDE = defaultdict(list)         # ngram sede -> [p,...]
NG_TITLE = defaultdict(list)        # ngram titulo -> [p,...]

# ---- Alias (evita genéricos como "santander") ----
ALIAS_MUNICIPIO = {
    "popayan": {"popayan", "popa", "ppyn"},
    "popayan - vrd. el sendero": {"popayan - vrd. el sendero", "popayan - vereda el sendero", "vereda el sendero", "vrd. el sendero", "el sendero"},
    "santander de quilichao": {"santander de quilichao", "quilichao", "qilichao"},
    "guapi": {"guapi", "guapy", "guap"},
    "la sierra": {"la sierra", "sierra", "siera"},
    "mercaderes": {"mercaderes", "mercaderez"},
    "morales": {"morales", "moralez", "morale"},
    "puerto tejada": {"puerto tejada"},
    "silvia": {"silvia", "silv", "slv"},
    "timbio": {"timbio", "tmbio", "timbi"},
    "timbiqui": {"timbiqui"},
}
ALIAS_SEDE = {
    "la casona": {"la casona", "sede la casona", "casona"},
    "sena sede calle 5 con cra 14 esquina barrio valencia": {
        "calle 5", "sena sede calle 5", "sede calle 5", "barrio valencia", "ctpi barrio valencia"
    },
    "sede alto cauca": {"alto cauca", "sede alto cauca", "sede norte", "ctpi norte"},
    "sede la samaria": {"sede la samaria", "la samaria", "samaria"},
}

def _alias_lookup(bucket: dict, q_norm: str) -> set:
    for canon, variants in bucket.items():
        if q_norm in variants:
            return variants
    return {q_norm}

def _ngrams_for_text(s: str) -> set:
    s = _norm(s)
    toks = [t for t in _tokens(s) if t]
    grams = set()
    for t in toks:
        n = len(t)
        for k in (3, 4, 5, 6):
            if n >= k:
                for i in range(0, n - k + 1):
                    grams.add(t[i:i+k])
            else:
                grams.add(t)
    return grams

# --- Index keys para municipios: forma completa + base (antes de "-") ---
def _mun_index_keys(mun_raw: str) -> set:
    if not mun_raw:
        return set()
    m = _norm(mun_raw)
    keys = set()
    if m:
        keys.add(m)
    base = re.split(r"\s*[-–]\s*", m)[0].strip()
    if base:
        keys.add(base)
    m_exp = m.replace("vrd.", "vereda").replace("vrd", "vereda")
    if m_exp != m:
        keys.add(m_exp)
        base2 = re.split(r"\s*[-–]\s*", m_exp)[0].strip()
        if base2:
            keys.add(base2)
    return {k for k in keys if k}

# --- Ordinal real de una variante dentro de su código ---
def _ordinal_for_variant(code: str, p_obj) -> int:
    lst = BY_CODE.get(str(code).strip(), [])
    for i, pi in enumerate(lst, start=1):
        if pi is p_obj:
            return i
    return 1

# ---- Construcción de índices principales ----
if not BY_CODE:
    for p in PROGRAMAS:
        code = _code_of(p)
        if not code:
            continue
        BY_CODE[code].append(p)

        mun, sede, _hr = _loc_fields(p)

        # municipio: indexa por forma completa y base (incluye "popayan - vrd. el sendero" bajo "popayan")
        if mun:
            for key in _mun_index_keys(mun):
                BY_MUNICIPIO[key].append(p)

        # sede
        if sede:
            sede_n = _norm(sede)
            BY_SEDE[sede_n].append(p)
            for g in _ngrams_for_text(sede_n):
                NG_SEDE[g].append(p)

        # título / contenido para temas
        title = _fields_for_title(p)
        if title:
            for g in _ngrams_for_text(title):
                NG_TITLE[g].append(p)

# ---- Conjuntos de llaves conocidas (ahora SÍ pobladas) ----
KNOWN_MUNICIPIOS = set(BY_MUNICIPIO.keys())
KNOWN_SEDES = set(BY_SEDE.keys())

# ---- Vista normalizada por código (programa + ofertas) ----
PROGRAMAS_BY_CODE = {}
for p in PROGRAMAS:
    code = _code_of(p)
    if not code:
        continue
    base = PROGRAMAS_BY_CODE.setdefault(code, {
        "code": code,
        "nivel": p.get("nivel"),
        "programa": p.get("programa") or p.get("nombre") or "",
        "perfil": p.get("perfil") or p.get("perfil_egresado") or "",
        "competencias": p.get("competencias") or "",
        "certificacion": p.get("certificacion") or p.get("certificación") or "",
        "ofertas": [],
    })
    mun, sede, hor = _loc_fields(p)
    base["ofertas"].append({
        "ordinal": _ordinal_for_variant(code, p),  # ahora BY_CODE ya está lleno
        "municipio": mun,
        "sede": sede,
        "horario": hor,
    })
# ========================= PARSER DE INTENCIÓN =========================
def _parse_intent(q: str) -> dict:
    qn = _norm(q)
    m = re.fullmatch(r"\s*(\d{5,7})-(\d{1,2})\s*", qn or "")
    if m: return {"code": m.group(1), "ordinal": int(m.group(2))}
    m = re.fullmatch(r"\s*(\d{5,7})\s*", qn or "")
    if m: return {"code": m.group(1)}

    nivel = None
    for canon, nivel_txt in NIVEL_CANON.items():
        if re.search(rf"\b{re.escape(canon)}s?\b", qn):
            nivel = nivel_txt; break

    prep = ""; tail_txt = ""
    m_tail = re.search(r"(?:\b(en|de|sobre)\b)\s+(.+)$", qn)
    if m_tail:
        prep = m_tail.group(1); tail_txt = _norm(m_tail.group(2))
        if prep in {"en","de"}:
            mun_detect, sede_detect = set(), set()
            for k in BY_MUNICIPIO.keys():
                if re.search(rf"\b{re.escape(k)}\b", tail_txt): mun_detect.add(k)
            for canon, vars in ALIAS_MUNICIPIO.items():
                for v in vars:
                    if re.search(rf"\b{re.escape(v)}\b", tail_txt):
                        for vv in ALIAS_MUNICIPIO.get(canon,{canon}):
                            if vv in BY_MUNICIPIO: mun_detect.add(vv)
            for k in BY_SEDE.keys():
                if re.search(rf"\b{re.escape(k)}\b", tail_txt): sede_detect.add(k)
            for canon, vars in ALIAS_SEDE.items():
                for v in vars:
                    if re.search(rf"\b{re.escape(v)}\b", tail_txt): sede_detect.add(_norm(v))
            for g in _ngrams_for_text(tail_txt):
                if g in NG_SEDE:
                    for p in NG_SEDE[g]:
                        s = _norm(p.get("sede") or p.get("centro") or p.get("ambiente") or "")
                        if s: sede_detect.add(s)
            if mun_detect or sede_detect:
                return {"nivel": nivel, "location": {"municipio": mun_detect} if mun_detect else {"sede": sede_detect}, "tail_text": tail_txt}

        if prep == "sobre":
            tema_tokens = _expand_topic_tokens(set(_tokens(tail_txt)))
            return {"nivel": nivel, "tema_tokens": tema_tokens} if nivel else {"tema_tokens": tema_tokens}

    municipios_detectados, sedes_detectadas = set(), set()
    for k in BY_MUNICIPIO.keys():
        if re.search(rf"\b{re.escape(k)}\b", qn): municipios_detectados.add(k)
    for canon, vars in ALIAS_MUNICIPIO.items():
        for v in vars:
            if re.search(rf"\b{re.escape(v)}\b", qn):
                for vv in ALIAS_MUNICIPIO.get(canon,{canon}):
                    if vv in BY_MUNICIPIO: municipios_detectados.add(vv)
    for k in BY_SEDE.keys():
        if re.search(rf"\b{re.escape(k)}\b", qn): sedes_detectadas.add(k)
    for canon, vars in ALIAS_SEDE.items():
        for v in vars:
            if re.search(rf"\b{re.escape(v)}\b", qn): sedes_detectadas.add(_norm(v))
    for g in _ngrams_for_text(qn):
        if g in NG_SEDE:
            for p in NG_SEDE[g]:
                s = _norm(p.get("sede") or p.get("centro") or p.get("ambiente") or "")
                if s: sedes_detectadas.add(s)

    toks = set(_tokens(qn))
    tema_tokens = _expand_topic_tokens(toks - set(NIVEL_CANON.keys()) - {"en","de","sobre","la","el"})

    if nivel and (municipios_detectados or sedes_detectadas):
        return {"nivel": nivel, "location": {"municipio": municipios_detectados} if municipios_detectados else {"sede": sedes_detectadas}}
    if municipios_detectados: return {"location": {"municipio": municipios_detectados}}
    if sedes_detectadas: return {"location": {"sede": sedes_detectadas}}
    if nivel and tema_tokens: return {"nivel": nivel, "tema_tokens": tema_tokens}
    if tema_tokens: return {"tema_tokens": tema_tokens}
    if nivel: return {"nivel": nivel}
    return {}
# ========================= RANKING/BÚSQUEDA =========================
def _score_program(p, intent) -> int:
    score = 0
    # municipio exacto
    if "location" in intent and "municipio" in intent["location"]:
        cand = intent["location"]["municipio"]
        mun = _norm((p.get("municipio") or p.get("ciudad") or ""))
        if any(m == mun for m in cand):
            score += 100
    # sede exacta o por ngram
    if "location" in intent and "sede" in intent["location"]:
        cand = intent["location"]["sede"]
        sede = _norm((p.get("sede") or p.get("centro") or p.get("ambiente") or ""))
        if any(s == sede for s in cand):
            score += 80
        else:
            grams = _ngrams_for_text(sede)
            if any(g in grams for g in _ngrams_for_text(" ".join(cand))):
                score += 70
    # nivel
    if intent.get("nivel") and intent["nivel"] in _nivel_of(p):
        score += 40
    # tema
    if intent.get("tema_tokens"):
        title = _fields_for_title(p)
        fields_topic = _fields_for_topic(p)
        tt = intent["tema_tokens"]
        if any(t in title for t in tt): score += 30
        if any(t in fields_topic for t in tt): score += 15
    return score

def _search_programs(intent: dict) -> list:
    # code-ordinal directo
    if intent.get("code") and intent.get("ordinal"):
        return [(intent["code"], intent["ordinal"])]

    # code → todas sus variantes
    if intent.get("code"):
        code = intent["code"]
        variants = BY_CODE.get(code, [])
        return [(code, i + 1) for i in range(len(variants))]

    # candidatos
    candidates = set()
    had_location = bool(intent.get("location"))

    # ubicación: municipio
    if intent.get("location", {}).get("municipio"):
        for m in intent["location"]["municipio"]:
            for p in BY_MUNICIPIO.get(m, []):
                candidates.add(id(p))

    # ubicación: sede
    if intent.get("location", {}).get("sede"):
        for s in intent["location"]["sede"]:
            for p in BY_SEDE.get(_norm(s), []):
                candidates.add(id(p))
        grams = _ngrams_for_text(" ".join(intent["location"]["sede"]))
        for g in grams:
            for p in NG_SEDE.get(g, []):
                candidates.add(id(p))

    # tema (si ya hay ubicación, intersecta para más precisión)
    if intent.get("tema_tokens"):
        grams = set()
        for t in intent["tema_tokens"]:
            grams |= _ngrams_for_text(t)
        topic_ids = set()
        for g in grams:
            for p in NG_TITLE.get(g, []):
                topic_ids.add(id(p))
        candidates = (candidates & topic_ids) if candidates else (candidates | topic_ids)

    # construye id→programa (una sola vez)
    id2p = {id(p): p for p in PROGRAMAS}

    # filtro estricto por nivel si está presente
    if intent.get("nivel"):
        if candidates:
            candidates = {pid for pid in candidates if intent["nivel"] in _nivel_of(id2p[pid])}
        else:
            # solo si NO hubo ubicación/tema; si hubo, no rellenamos con todo
            if not had_location and not intent.get("tema_tokens"):
                for pid, p in id2p.items():
                    if intent["nivel"] in _nivel_of(p):
                        candidates.add(pid)

    # si sigue vacío, última opción
    if not candidates:
        if had_location or intent.get("tema_tokens"):
            return []  # no mezclar si pidió ubicación/tema explícito
        candidates = set(id2p.keys())

    # puntuar y ordenar
    scored = [(_score_program(id2p[pid], intent), id2p[pid]) for pid in candidates]
    scored.sort(
        key=lambda x: (
            -x[0],
            _norm(x[1].get("municipio") or x[1].get("ciudad") or ""),
            _fields_for_title(x[1]),
        )
    )

    # map a (code, ord) usando el ordinal real de esa variante
    seen, result = set(), []
    for _sc, p in scored:
        code = _code_of(p)
        if not code:
            continue
        ord_n = _ordinal_for_variant(code, p)
        key = (code, ord_n)
        if key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result
# ========================= RENDER FICHAS =========================
def _render_ficha(p, code: str):
    mun, sede, hor = _loc_fields(p)
    titulo = p.get("programa") or p.get("nombre") or "Programa"
    nivel = p.get("nivel") or ""
    dur = p.get("duracion") or p.get("duración") or ""
    req = p.get("requisitos") or ""
    perfil = p.get("perfil") or p.get("perfil_egresado") or ""
    comp = p.get("competencias") or ""
    cert = p.get("certificacion") or p.get("certificación") or ""

    parts = []
    parts.append(f"📘 *{titulo}*")
    parts.append(f"{nivel} · Código [{code}]")
    if mun or sede: parts.append(f"📍 {str(mun).strip()} · {str(sede).strip()}".strip(" ·"))
    if hor: parts.append(f"🕘 {hor}")

    if dur:
        parts.append("\n*Duración:*")
        parts.append(str(dur))
    if req:
        parts.append("\n*Requisitos:*")
        parts.append(str(req))
    if perfil:
        parts.append("\n*Perfil del egresado:*")
        parts.append(str(perfil))
    if comp:
        parts.append("\n*Competencias:*")
        parts.append(str(comp))
    if cert:
        parts.append("\n*Certificación:*")
        parts.append(str(cert))

    parts.append("\nℹ️ Pide un campo puntual con:  requisitos {code} · duracion {code} · perfil {code} · competencias {code} · certificacion {code}".format(code=code))
    return "\n".join(parts)

def ficha_por_codigo(code: str) -> str:
    p = _find_by_code(code)
    if not p:
        return (
                "No encontré un programa con ese código.\n\n"
                "Prueba revisando el código 😢."
        )
    return _render_ficha(p, code)

def ficha_por_codigo_y_ordinal(code: str, ord_n: int) -> str:
    p = _nth_by_code(code, ord_n)
    if not p:
        return "No encontré esa variante (revisa el *código-ordinal*)."
    return _render_ficha(p, code)

# ========================= API LEGADA: TOP CODIGOS =========================
def top_codigos_para(texto: str, limit: int = 5):
    intent = _parse_intent(texto)
    items = _search_programs(intent)
    # devolvemos solo códigos en orden, únicos
    seen, out = set(), []
    for code, _ord in items:
        if code in seen: continue
        seen.add(code)
        out.append(code)
        if len(out) >= limit: break
    return out

def _nth_by_code(code: str, n: int):
    """
    Devuelve la n-ésima variante (1-based) de un programa por código,
    según el orden en BY_CODE[code]. Si no existe, retorna None.
    """
    lst = BY_CODE.get(str(code).strip(), [])
    return lst[n - 1] if 1 <= n <= len(lst) else None

def _find_by_code(code: str):
    """
    Devuelve la primera variante para un código (o None si no existe).
    """
    lst = BY_CODE.get(str(code).strip(), [])
    return lst[0] if lst else None


# ========================= GENERAR RESPUESTA =========================
def generar_respuesta(texto: str, show_all: bool = False, page: int = 0, page_size: int = 10) -> str:
    if not texto:
        return "Escribe una consulta, por ejemplo: *técnico en sistemas Popayán* o el *código* del programa."

    q = _norm(texto)

    # 1) Saludos / Ayuda
    SALUDOS = {"hola","buenos dias","buenas tardes","buenas noches","buen dia","buen día","buenas","menu","menú","ayuda","start","hi","hello"}
    if any(s in q for s in SALUDOS):
        return (
            "¡Hola! Soy tu asistente SENA 👋\n\n"
            "Puedes enviarme:\n"
            "• Un *código* (ej. *228118*).\n"
            "• *nivel + sede/ciudad* (ej. *tecnólogos en Popayán*, *técnicos sede norte*).\n"
            "• *nivel + tema* (ej. *tecnólogos sobre software *).\n"
            "• Una *búsqueda* por palabra clave (ej. *software*, *Popayán técnico*).\n\n"
            "También: *requisitos técnico*, *duración tecnólogo*, *perfil auxiliar*, etc.\n"
            "Si lo deseas puedes pedir escribir *ayuda* para más información."
        )

    # 2) Requisitos/Duración/Perfil (general por nivel)
    FOLLOW = {"requisitos","requisito","req","duracion","duración","tiempo","perfil","competencias","certificacion","certificación"}
    if any(w in q for w in FOLLOW) and not re.search(r"\b\d{5,7}\b", q):
        nivel_detectado = None
        for canon, nivel_txt in NIVEL_CANON.items():
            if canon in q:
                nivel_detectado = nivel_txt
                break
        ocurrencias = { "requisitos": set(), "duración": set(), "perfil": set(), "competencias": set(), "certificación": set() }
        for p in PROGRAMAS:
            if nivel_detectado and (nivel_detectado not in _nivel_of(p)): continue
            if p.get("requisitos"): ocurrencias["requisitos"].add(_norm(str(p["requisitos"]))[:400])
            if p.get("duracion") or p.get("duración"): ocurrencias["duración"].add(_norm(str(p.get("duracion") or p.get("duración")))[:150])
            if p.get("perfil"): ocurrencias["perfil"].add(_norm(str(p["perfil"]))[:400])
            if p.get("competencias"): ocurrencias["competencias"].add(_norm(str(p["competencias"]))[:400])
            if p.get("certificacion") or p.get("certificación"): ocurrencias["certificación"].add(_norm(str(p.get("certificacion") or p.get("certificación")))[:250])
        etiquetas = ["requisitos","duración","perfil","competencias","certificación"]
        partes, titulo_nivel = [], (f" {nivel_detectado}" if nivel_detectado else "")
        for etq in etiquetas:
            if ocurrencias[etq]:
                ejemplos = list(ocurrencias[etq])[:2]
                bullets = "\n".join(f"- {ej[:500]}{'…' if len(ej)>=500 else ''}" for ej in ejemplos)
                partes.append(f"*{etq.title()}{titulo_nivel}:*\n{bullets}")
        if partes:
            partes.append("\nSi quieres ver un programa específico, envía su *código* (ej. 228118) o escribe un tema más concreto.")
            return "\n\n".join(partes)

    # 3) Intent y caminos
    intent = _parse_intent(q)

    # code-ordinal
    if intent.get("code") and intent.get("ordinal"):
        return ficha_por_codigo_y_ordinal(intent["code"], intent["ordinal"])

    # code con desambiguación
    if intent.get("code"):
        code = intent["code"]
        variants = BY_CODE.get(code, [])
        if not variants:
            return (
                    "No encontré un programa con ese código.\n\n"
                    "Prueba con otra combinación o escribiendo *ayuda* 😢."
            )
        if len(variants) == 1:
            return ficha_por_codigo(code)
        items = [(code, i+1) for i in range(len(variants))]
        header = f"El código *{code}* tiene *{len(items)}* ubicaciones (pág. {page+1}):"
    else:
        items = _search_programs(intent)
        if not items:
            return (
                    "No encontré resultados para tu búsqueda.\n\n"
                    "Prueba con otra combinación o escribiendo *ayuda* 😢."
            )
        # encabezados informativos
        if intent.get("location", {}).get("municipio"):
            mun_txt = next(iter(intent["location"]["municipio"]))
            header = f"Programas en *{mun_txt.title()}* (pág. {page+1}):"
        elif intent.get("location", {}).get("sede"):
            sede_txt = next(iter(intent["location"]["sede"]))
            header = f"Programas en *{sede_txt.title()}* (pág. {page+1}):"
        elif intent.get("nivel") and intent.get("tema_tokens"):
            tema_txt = " ".join(sorted(intent["tema_tokens"]))
            header = f"{intent['nivel'].title()} sobre *{tema_txt}* (pág. {page+1}):"
        elif intent.get("tema_tokens"):
            tema_txt = " ".join(t for t in _tokens(q) if t not in {"en","de","sobre"})
            header = f"Resultados para el tema *{tema_txt}* (pág. {page+1}):"
        elif intent.get("nivel"):
            header = f"Programas del nivel *{intent['nivel']}* (pág. {page+1}):"
        else:
            header = f"Resultados (pág. {page+1}):"

    # 4) Render listado 10×10 con ubicación visible
    start, end = page*page_size, (page+1)*page_size
    page_items = items[start:end]
    if not page_items:
        return "No hay más resultados en esta lista."

    lines = [header]
    for i, (code, ord_n) in enumerate(page_items, start=1):
        p = _nth_by_code(code, ord_n) or _find_by_code(code)
        if not p: 
            continue
        titulo = p.get("programa") or p.get("nombre") or "Programa"
        mun, sede, hor = _loc_fields(p)
        loc_line = " · ".join([s for s in [str(mun).strip(), str(sede).strip()] if s]) or "Ubicación no especificada"
        extra = f"\n   🕘 {hor}" if hor else ""
        lines.append(
            f"{i}) *{titulo}*\n"
            f"   📍 {loc_line}{extra}\n"
            f"   🆔 Código [{code}] — responde: {code}-{ord_n}\n"
        )

    if end < len(items):
        lines.append("\nEscribe *ver más* para ver los siguientes 10.")
    return "\n".join(lines)
