import os, json, re, unicodedata
from collections import defaultdict

# ========================= CARGA DE DATOS =========================
def _here(*parts):
    return os.path.join(os.path.dirname(__file__), *parts)

# Prioridad: v2 (normalizado mejorado) > v1 (normalizado) > crudo (enriquecido)
PROGRAMAS_PATH_CANDIDATES = [
    # ---- v2 ----
    _here("..", "storage_simple", "programas_normalizado_v2.json"),  # /app/storage_simple/programas_normalizado_v2.json
    _here("storage_simple", "programas_normalizado_v2.json"),        # app/storage_simple/programas_normalizado_v2.json
    "storage_simple/programas_normalizado_v2.json",                  # raíz del repo (modo local)

    # ---- v1 ----
    _here("..", "storage_simple", "programas_normalizado.json"),
    _here("storage_simple", "programas_normalizado.json"),
    "storage_simple/programas_normalizado.json",

    # ---- crudo/enriquecido (fallback) ----
    _here("..", "storage_simple", "programas_enriquecido.json"),
    _here("storage_simple", "programas_enriquecido.json"),
    _here("programas_enriquecido.json"),
    "programas_enriquecido.json",
]

PROGRAMAS = []
DATA_FORMAT = "unknown"  # "normalized_v2" | "normalized" | "raw"
for pth in PROGRAMAS_PATH_CANDIDATES:
    if os.path.exists(pth):
        with open(pth, "r", encoding="utf-8") as fh:
            PROGRAMAS = json.load(fh)
        if pth.endswith("programas_normalizado_v2.json"):
            DATA_FORMAT = "normalized_v2"
        elif pth.endswith("programas_normalizado.json"):
            DATA_FORMAT = "normalized"
        else:
            DATA_FORMAT = "raw"
        break

if not PROGRAMAS:
    PROGRAMAS = []  # evita crash si no encuentra archivo
    DATA_FORMAT = "raw"
# ========================= NORMALIZACIÓN =========================

def _strip(s):
    if s is None: return ""
    return " ".join(str(s).strip().split())

def _norm(s: str) -> str:
    s = _strip(s).lower()
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s\-]", " ", s)
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
    "tecnico":"tecnico","tecnicos":"tecnico",
    "tecnologo":"tecnologo","tecnologos":"tecnologo",
    "auxiliar":"auxiliar","auxiliares":"auxiliar",
    "operario":"operario","operarios":"operario",
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
from collections import defaultdict

# Estructuras comunes (se rellenan según el formato de datos detectado)
BY_CODE = {}                          # v2: "228118" -> programa base (con ofertas)
BY_MUNICIPIO = defaultdict(list)      # v2: "popayan" / "popayan - vrd el sendero" -> [(code, ordinal), ...]
BY_SEDE = defaultdict(list)           # v2: "calle 5" / "alto cauca" / "la casona" -> [(code, ordinal), ...]
NG_TITLE = defaultdict(list)          # v2: n-gram (programa_norm + palabras_clave) -> [code, ...]

# --- Helpers genéricos ---
def _grams(s: str) -> set:
    s = _norm(s)
    out = set()
    for tok in s.split():
        n = len(tok)
        for k in (3, 4, 5):
            if n >= k:
                for i in range(n - k + 1):
                    out.add(tok[i:i+k])
            else:
                out.add(tok)
    return out

# ========================= RUTA v2 (programas_normalizado_v2.json) =========================
if DATA_FORMAT == "normalized_v2":
    # Construcción de índices específicos para v2
    BY_CODE.clear(); BY_MUNICIPIO.clear(); BY_SEDE.clear(); NG_TITLE.clear()

    for prog in PROGRAMAS:
        code = str(prog.get("codigo") or "").strip()
        if not code:
            continue
        BY_CODE[code] = prog  # guardamos el objeto programa completo

        # Index por ubicación (por cada oferta del programa)
        for of in prog.get("ofertas", []):
            # municipio: indexa tanto el municipio completo como el "base"
            for key in (of.get("municipio_norm"), of.get("municipio_base_norm")):
                if key:
                    BY_MUNICIPIO[_norm(key)].append((code, of.get("ordinal", 1)))
            # sede
            sede_key = of.get("sede_norm")
            if sede_key:
                BY_SEDE[_norm(sede_key)].append((code, of.get("ordinal", 1)))

        # Index temático (SOLO sobre programa_norm + palabras_clave del programa)
        bag = [prog.get("programa_norm", "")] + (prog.get("palabras_clave") or [])
        for token in bag:
            for g in _grams(token):
                NG_TITLE[g].append(code)

    # Conjuntos de llaves conocidas (útiles para validaciones rápidas)
    KNOWN_MUNICIPIOS = set(BY_MUNICIPIO.keys())
    KNOWN_SEDES = set(BY_SEDE.keys())

# ========================= Fallback: formatos anteriores =========================
else:
    # Mantiene tu lógica previa (para programas_enriquecido.json o normalizado v1),
    # usando los helpers que ya tienes definidos: _code_of, _loc_fields, _fields_for_title, etc.
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

    # ---- Construcción de índices principales (formato previo) ----
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

    # ---- Conjuntos de llaves conocidas (ahora sí pobladas) ----
    KNOWN_MUNICIPIOS = set(BY_MUNICIPIO.keys())
    KNOWN_SEDES = set(BY_SEDE.keys())

    # ---- Vista normalizada por código (programa + ofertas) (formato previo) ----
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
            "ordinal": _ordinal_for_variant(code, p),
            "municipio": mun,
            "sede": sede,
            "horario": hor,
        })
# ========================= PARSER DE INTENCIÓN =========================
def _parse_intent(q: str) -> dict:
    """
    Parser de intención compatible con:
      - DATA_FORMAT == "normalized_v2": usa KNOWN_MUNICIPIOS / KNOWN_SEDES y n-gramas de título (NG_TITLE)
      - Formatos previos: usa alias y NG_SEDE si existen
    Retorna un dict con posibles llaves: code, ordinal, nivel, location{municipio[], sede[]}, tema_tokens
    """
    qn = _norm(q or "")

    # 1) código-ordinal: 233104-2
    m = re.fullmatch(r"\s*(\d{5,7})-(\d{1,2})\s*", qn)
    if m:
        return {"code": m.group(1), "ordinal": int(m.group(2))}

    # 2) código puro
    m = re.fullmatch(r"\s*(\d{5,7})\s*", qn)
    if m:
        return {"code": m.group(1)}

    # 3) nivel
    nivel = None
    for canon, nivel_txt in NIVEL_CANON.items():
        if re.search(rf"\b{re.escape(canon)}s?\b", qn):
            nivel = nivel_txt
            break

    # Helpers locales
    def _collect_loc_matches(text_tail: str):
        """Devuelve (municipios_detectados, sedes_detectadas) según DATA_FORMAT."""
        tail = _norm(text_tail)
        munis, sedes = set(), set()

        if DATA_FORMAT == "normalized_v2":
            # Busca por contains tanto en municipio_norm como base_norm
            for k in KNOWN_MUNICIPIOS:
                if k in tail or tail in k:
                    munis.add(k)
            for k in KNOWN_SEDES:
                if k in tail or tail in k:
                    sedes.add(k)
        else:
            # Formato previo (mantiene tu lógica antigua si existen esas estructuras)
            for k in BY_MUNICIPIO.keys():
                if re.search(rf"\b{re.escape(k)}\b", tail):
                    munis.add(k)
            ALIAS_M = globals().get("ALIAS_MUNICIPIO", {})
            for canon, variants in ALIAS_M.items():
                for v in variants:
                    if re.search(rf"\b{re.escape(v)}\b", tail):
                        # agrega todas las variantes que estén indexadas
                        for vv in ALIAS_M.get(canon, {canon}):
                            if vv in BY_MUNICIPIO:
                                munis.add(vv)

            for k in BY_SEDE.keys():
                if re.search(rf"\b{re.escape(k)}\b", tail):
                    sedes.add(k)
            ALIAS_S = globals().get("ALIAS_SEDE", {})
            for canon, variants in ALIAS_S.items():
                for v in variants:
                    if re.search(rf"\b{re.escape(v)}\b", tail):
                        sedes.add(_norm(v))

            # NG_SEDE (si existe)
            if "NG_SEDE" in globals():
                for g in _ngrams_for_text(tail):
                    if g in NG_SEDE:
                        for p in NG_SEDE[g]:
                            s = _norm(p.get("sede") or p.get("centro") or p.get("ambiente") or "")
                            if s:
                                sedes.add(s)

        return munis, sedes

    # 4) “en / de / sobre …” (cola de la oración)
    prep = ""
    tail_txt = ""
    m_tail = re.search(r"(?:\b(en|de|sobre)\b)\s+(.+)$", qn)
    if m_tail:
        prep = m_tail.group(1)
        tail_txt = _strip(m_tail.group(2))

        if prep in {"en", "de"}:
            mun_detect, sede_detect = _collect_loc_matches(tail_txt)
            if mun_detect or sede_detect:
                loc = {"municipio": list(mun_detect)} if mun_detect else {"sede": list(sede_detect)}
                return {"nivel": nivel, "location": loc, "tail_text": _norm(tail_txt)}

        if prep == "sobre":
            # Tema explícito
            tema_tokens = _tokens(_norm(tail_txt))
            # Expand solo si tienes sinónimos configurados; si no, deja tokens directos
            expand = globals().get("_expand_topic_tokens")
            tema_tokens = expand(set(tema_tokens)) if expand else set(tema_tokens)
            return {"nivel": nivel, "tema_tokens": tema_tokens} if nivel else {"tema_tokens": tema_tokens}

    # 5) Si no hubo prep explícita, intenta detectar ubicación en toda la frase
    mun_all, sed_all = _collect_loc_matches(qn)

    # 6) Tema implícito (palabras restantes)
    toks = set(_tokens(qn))
    tema_tokens = toks - set(NIVEL_CANON.keys()) - {"en", "de", "sobre", "la", "el", "los", "las"}

    # 7) Reglas de retorno (prioriza señales fuertes)
    if nivel and (mun_all or sed_all):
        return {"nivel": nivel, "location": {"municipio": list(mun_all)} if mun_all else {"sede": list(sed_all)}}
    if mun_all:
        return {"location": {"municipio": list(mun_all)}}
    if sed_all:
        return {"location": {"sede": list(sed_all)}}
    if nivel and tema_tokens:
        return {"nivel": nivel, "tema_tokens": tema_tokens}
    if tema_tokens:
        return {"tema_tokens": tema_tokens}
    if nivel:
        return {"nivel": nivel}
    return {}
# ========================= RANKING/BÚSQUEDA =========================

def _score_code(code: str, intent: dict) -> int:
    """
    Scoring para DATA_FORMAT == 'normalized_v2' (programas_normalizado_v2.json).
    Puntuamos por:
      +5 si el nivel coincide exactamente (e.g., 'tecnologo').
      +3 si hay match de municipio (municipio_norm o municipio_base_norm) en alguna oferta.
      +3 si hay match de sede (sede_norm) en alguna oferta.
    """
    prog = BY_CODE.get(code)
    if not prog:
        return 0

    score = 0

    # nivel exacto
    if intent.get("nivel") and intent["nivel"] == prog.get("nivel_norm"):
        score += 5

    # ubicación (miramos todas las ofertas del programa)
    loc = intent.get("location") or {}
    ofertas = prog.get("ofertas") or []

    if "municipio" in loc:
        muni_keys = { _norm(x) for x in loc["municipio"] if x }
        if any(
            (of.get("municipio_norm") in muni_keys) or
            (of.get("municipio_base_norm") in muni_keys)
            for of in ofertas
        ):
            score += 3

    if "sede" in loc:
        sede_keys = { _norm(x) for x in loc["sede"] if x }
        if any(of.get("sede_norm") in sede_keys for of in ofertas):
            score += 3

    return score


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

def _search_programs(intent: dict) -> list[tuple]:
    # 1) código-ordinal directo
    if intent.get("code") and intent.get("ordinal"):
        return [(intent["code"], intent["ordinal"])]

    # 2) código → todas sus ofertas
    if intent.get("code"):
        prog = BY_CODE.get(intent["code"])
        if not prog: return []
        return [(intent["code"], of.get("ordinal", i+1)) for i, of in enumerate(prog.get("ofertas", []))]

    candidates = set()

    # 3) ubicación primero (si viene)
    had_loc = False
    for muni in intent.get("location", {}).get("municipio", []):
        had_loc = True
        key = _norm(muni)
        # intentamos match por beginswith (soporte "popayan - vrd")
        for k in list(BY_MUNICIPIO.keys()):
            if key in k or k in key:
                for pair in BY_MUNICIPIO[k]:
                    candidates.add(pair)
    for sede in intent.get("location", {}).get("sede", []):
        had_loc = True
        key = _norm(sede)
        for k in list(BY_SEDE.keys()):
            if key in k or k in key:
                for pair in BY_SEDE[k]:
                    candidates.add(pair)

    # 4) tema (sobre/de). Usamos NG_TITLE → devuelve códigos (no ofertas).
    topic_codes = set()
    grams = set()
    for t in intent.get("tema_tokens") or []:
        grams |= _grams(t)
    for g in grams:
        for c in NG_TITLE.get(g, []):
            topic_codes.add(c)

    # intersecta si ya había ubicación; si no, añade
    if topic_codes:
        if candidates:
            # quedarnos con ofertas cuyo code esté en topic_codes
            candidates = {pair for pair in candidates if pair[0] in topic_codes}
        else:
            # sin ubicación: agregamos (code, ordinal 1) y luego expandimos
            for code in topic_codes:
                prog = BY_CODE.get(code)
                if prog and prog.get("ofertas"):
                    candidates.add((code, prog["ofertas"][0]["ordinal"]))

    # 5) filtro por nivel (si viene)
    if intent.get("nivel"):
        level = intent["nivel"]
        if candidates:
            candidates = {pair for pair in candidates if BY_CODE.get(pair[0], {}).get("nivel_norm") == level}
        else:
            # sin candidatos aún: buscar por nivel
            for code, prog in BY_CODE.items():
                if prog.get("nivel_norm") == level and prog.get("ofertas"):
                    candidates.add((code, prog["ofertas"][0]["ordinal"]))

    # 6) si no hay nada y no pidió ubicación/tema, ofrece todo (top por nombre)
    if not candidates and not had_loc and not intent.get("tema_tokens"):
        for code, prog in BY_CODE.items():
            if prog.get("ofertas"):
                candidates.add((code, prog["ofertas"][0]["ordinal"]))

    # ranking: por score (nivel), luego por nombre
    ranked = []
    for code, ord_n in candidates:
        ranked.append((_score_code(code, intent), code, ord_n))
    ranked.sort(key=lambda x: (-x[0], BY_CODE[x[1]]["programa_norm"], x[2]))
    # dedup por (code, ord)
    seen, out = set(), []
    for _, code, ord_n in ranked:
        key = (code, ord_n)
        if key in seen: 
            continue
        seen.add(key); out.append(key)
    return out
# ========================= RENDER FICHAS =========================

def _render_ficha_legacy(p, code: str) -> str:
    """Render para formato antiguo (crudo / normalizado v1)."""
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
    if mun or sede:
        parts.append(f"📍 {str(mun).strip()} · {str(sede).strip()}".strip(" ·"))
    if hor:
        parts.append(f"🕘 {hor}")

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

    parts.append(
        "\nℹ️ Pide un campo puntual con:  requisitos {code} · duracion {code} · perfil {code} · competencias {code} · certificacion {code}"
        .format(code=code)
    )
    return "\n".join(parts)


def _render_ficha_v2(prog: dict, of: dict | None, code: str) -> str:
    """Render para formato normalized_v2 (programa base + oferta específica)."""
    titulo = prog.get("programa") or "Programa"
    nivel = prog.get("nivel") or ""
    parts = [f"📘 *{titulo}*",
             f"{nivel} · Código [{code}]"]

    if of:
        # Mostrar ubicación concreta (oferta elegida)
        loc = f"📍 {of.get('municipio') or ''} — {of.get('sede_nombre') or ''}".strip(" —")
        if loc and loc != "📍":
            parts.append(loc)
        if of.get("ambiente"):
            parts.append(f"🏫 Ambiente: {of['ambiente']}")
        if of.get("horario"):
            parts.append(f"🕒 Horario: {of['horario']}")

    # Campos del programa
    perfil = (prog.get("perfil") or "").strip()
    comp = prog.get("competencias") or []
    cert = (prog.get("certificacion") or "").strip()

    if perfil:
        parts.append("\n*Perfil del egresado:*")
        parts.append(perfil)

    if comp:
        parts.append("\n*Competencias:*")
        # Asegura lista y recorta a 6 bullets para WhatsApp
        comp_list = comp if isinstance(comp, list) else [str(comp)]
        for c in comp_list[:6]:
            if c:
                parts.append(f"• {c}")
        if len(comp_list) > 6:
            parts.append(f"   (+{len(comp_list)-6} más)")

    if cert:
        parts.append("\n*Certificación:*")
        parts.append(cert)

    parts.append("\nℹ️ Puedes escribir:  requisitos {code} · perfil {code} · competencias {code} · certificacion {code}".format(code=code))
    return "\n".join(parts)


def _get_offer_v2(code: str, ordinal: int):
    """Devuelve (programa, oferta) para normalized_v2, o (None, None) si no existe."""
    prog = BY_CODE.get(code)
    if not prog:
        return None, None
    for of in prog.get("ofertas", []):
        if of.get("ordinal") == ordinal:
            return prog, of
    return prog, None


def ficha_por_codigo_y_ordinal(code: str, ord_n: int) -> str:
    """
    Si hay dataset v2: muestra la ubicación específica (municipio+sede+horario) del ordinal dado.
    Si no, cae al render legacy usando la n-ésima variante.
    """
    code = str(code).strip()

    if DATA_FORMAT == "normalized_v2":
        prog, of = _get_offer_v2(code, ord_n)
        if not prog:
            return "No encontré ese programa."
        if not of:
            # Si no existe ese ordinal, muestra listado de ubicaciones para que el usuario elija
            return ficha_por_codigo(code)
        return _render_ficha_v2(prog, of, code)

    # Fallback legacy
    p = _nth_by_code(code, ord_n)
    if not p:
        return "No encontré esa variante (revisa el *código-ordinal*)."
    return _render_ficha_legacy(p, code)


def ficha_por_codigo(code: str) -> str:
    """
    Si hay dataset v2:
      - Si el programa tiene varias ofertas: lista las ubicaciones (10 primeras) con su ordinal.
      - Si tiene una sola: muestra la ficha completa de esa oferta.
    Si no hay v2, renderiza con el formato legacy.
    """
    code = str(code).strip()

    if DATA_FORMAT == "normalized_v2":
        prog = BY_CODE.get(code)
        if not prog:
            return "No encontré un programa con ese código.\n\nPrueba revisando el código 😢."
        ofertas = prog.get("ofertas") or []
        if len(ofertas) == 0:
            return "No encontré secciones para ese código."
        if len(ofertas) == 1:
            return _render_ficha_v2(prog, ofertas[0], code)

        # Varias ubicaciones → listado con ordinal para elegir
        lines = [
            f"*{prog['programa']}* ({prog.get('nivel','')}) — Código [{code}]",
            "Este programa tiene varias ubicaciones. Elige una escribiendo *'codigo-ordinal'*:"
        ]
        for of in ofertas[:10]:
            ord_n = of.get("ordinal")
            muni = of.get("municipio") or ""
            sede = of.get("sede_nombre") or ""
            hor = of.get("horario") or ""
            lines.append(f" {ord_n}. {muni} — {sede}" + (f"  •  {hor}" if hor else ""))
        if len(ofertas) > 10:
            lines.append("\nEscribe *'ver más'* para ver otras ubicaciones.")
        return "\n".join(lines)

    # Fallback legacy
    p = _find_by_code(code)
    if not p:
        return "No encontré un programa con ese código.\n\nPrueba revisando el código 😢."
    return _render_ficha_legacy(p, code)

# ========================= LISTADOS =========================
def _format_list(items: list[tuple], page: int = 0, page_size: int = 10) -> str:
    """
    items: lista de (code, ordinal) ya ordenada.
    Muestra 10 por página con ubicación (si disponible) y guía para 'ver más'.
    """
    if not items:
        return "No encontré coincidencias."

    start = page * page_size
    chunk = items[start:start + page_size]

    lines = []
    for i, (code, ord_n) in enumerate(chunk, start=1):
        # Usa la oferta específica si estamos en v2
        if DATA_FORMAT == "normalized_v2":
            prog = BY_CODE.get(code)
            of = None
            if prog:
                for o in (prog.get("ofertas") or []):
                    if o.get("ordinal") == ord_n:
                        of = o
                        break
            if prog and of:
                lines.append(
                    f"{i}. {prog['programa']} ({prog.get('nivel','')}) — Código [{code}]"
                    f"\n    📍 {of.get('municipio','')} — {of.get('sede_nombre','')}"
                    + (f"  •  🕒 {of.get('horario','')}" if of.get('horario') else "")
                )
            elif prog:
                lines.append(f"{i}. {prog['programa']} — Código [{code}]")
            else:
                lines.append(f"{i}. Código [{code}]")
        else:
            # Legacy: sin ofertas estructuradas
            p = _nth_by_code(code, ord_n) or _find_by_code(code)
            if p:
                mun, sede, hor = _loc_fields(p)
                titulo = p.get("programa") or p.get("nombre") or "Programa"
                lines.append(
                    f"{i}. {titulo} ({p.get('nivel','')}) — Código [{code}]"
                    + (f"\n    📍 {str(mun).strip()} · {str(sede).strip()}" if (mun or sede) else "")
                    + (f"  •  🕒 {hor}" if hor else "")
                )
            else:
                lines.append(f"{i}. Código [{code}]")

    more = ""
    if len(items) > start + page_size:
        more = "\n\nEscribe *'ver más'* para ver más resultados."

    return "\n".join(lines) + more


# ========================= API LEGADA: TOP CODIGOS =========================

def _nth_by_code(code: str, n: int):
    """
    Legacy ONLY.
    Devuelve la n-ésima variante (1-based) de un programa por código usando BY_CODE=list.
    En normalized_v2 no aplica y retorna None.
    """
    if DATA_FORMAT == "normalized_v2":
        return None
    lst = BY_CODE.get(str(code).strip(), [])
    return lst[n - 1] if 1 <= n <= len(lst) else None


def _find_by_code(code: str):
    """
    Legacy ONLY.
    Devuelve la primera variante para un código usando BY_CODE=list.
    En normalized_v2 no aplica y retorna None (ficha_por_codigo usa BY_CODE[code] v2 directamente).
    """
    if DATA_FORMAT == "normalized_v2":
        return None
    lst = BY_CODE.get(str(code).strip(), [])
    return lst[0] if lst else None

# ========================= BÚSQUEDA RÁPIDA Y RESPUESTA =========================

def top_codigos_para(texto: str, limit: int = 10) -> list[str]:
    """
    Devuelve hasta 'limit' códigos (sin repetir) para la consulta dada.
    Se usa para poblar STATE['candidates'] y permitir selección numérica.
    """
    intent = _parse_intent(texto)
    found = _search_programs(intent)
    out, seen = [], set()
    for code, _ord in found:
        if code not in seen:
            out.append(code)
            seen.add(code)
        if len(out) >= limit:
            break
    return out


def generar_respuesta(texto: str, show_all: bool = False, page: int = 0, page_size: int = 10) -> str:
    """
    Motor principal de respuesta del bot.
    - Saludos/ayuda
    - código y código-ordinal
    - búsquedas por ubicación (“en …”), por tema (“sobre …”) y por nivel
    - listado paginado de 10 en 10 cuando show_all=True (usa 'page' y 'page_size')
    """
    if not texto:
        return ("Escribe una consulta, por ejemplo:\n"
                "• *tecnólogo en Popayán*\n"
                "• *técnicos sobre sistemas*\n"
                "• *233104* o *233104-2*")

    qn = _norm(texto)

    # ---- Saludos / Ayuda ----
    GREETINGS = {
        "hola", "buenos dias", "buen dia", "buenas", "buenas tardes", "buenas noches",
        "hola sena", "hola, sena", "menu", "menú", "ayuda", "start", "hi", "hello"
    }
    if qn in GREETINGS:
        return (
            "¡Hola! Soy el asistente del SENA Cauca 👋\n"
            "Puedes preguntar por:\n"
            "• Nivel: *técnico*, *tecnólogo*, *auxiliar*, *operario*\n"
            "• Ubicación: *programas en Popayán*, *en La Casona*\n"
            "• Tema: *tecnólogos sobre contabilidad*, *técnicos sobre sistemas*\n"
            "• Código: *233104* o *233104-2*\n\n"
            "Tip: escribe *ver más* para paginar cuando haya muchos resultados."
        )

    # ---- Parseo de intención ----
    intent = _parse_intent(texto)

    # ---- Accesos directos por código ----
    if intent.get("code") and intent.get("ordinal"):
        return ficha_por_codigo_y_ordinal(intent["code"], intent["ordinal"])
    if intent.get("code"):
        return ficha_por_codigo(intent["code"])

    # ---- Búsqueda general ----
    results = _search_programs(intent)
    if not results:
        tips = [
            "• *tecnólogos sobre sistemas*",
            "• *programas en La Casona*",
            "• *233104-2*",
        ]
        if intent.get("nivel"):
            tips.insert(0, f"• *{intent['nivel']} en Popayán*")
        return "No encontré coincidencias. Prueba con:\n" + "\n".join(tips)

    # ---- Encabezado informativo (opcional, antes del listado) ----
    if intent.get("location", {}).get("municipio"):
        mun_txt = next(iter(intent["location"]["municipio"]))
        header = f"Programas en *{mun_txt.title()}* (pág. {page+1}):\n"
    elif intent.get("location", {}).get("sede"):
        sede_txt = next(iter(intent["location"]["sede"]))
        header = f"Programas en *{sede_txt.title()}* (pág. {page+1}):\n"
    elif intent.get("nivel") and intent.get("tema_tokens"):
        tema_txt = " ".join(sorted(intent["tema_tokens"]))
        header = f"{intent['nivel'].title()} sobre *{tema_txt}* (pág. {page+1}):\n"
    elif intent.get("tema_tokens"):
        tema_txt = " ".join(t for t in _tokens(qn) if t not in {"en","de","sobre"})
        header = f"Resultados para el tema *{tema_txt}* (pág. {page+1}):\n"
    elif intent.get("nivel"):
        header = f"Programas del nivel *{intent['nivel']}* (pág. {page+1}):\n"
    else:
        header = f"Resultados (pág. {page+1}):\n"

    # ---- Listado 10×10 con ubicación visible ----
    if show_all:
        body = _format_list(results, page=page, page_size=page_size)
    else:
        body = _format_list(results, page=0, page_size=page_size)

    # Evita duplicar encabezado si _format_list ya muestra “No encontré…”
    if body.startswith("No encontré"):
        return body
    return header + body
