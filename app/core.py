import os, json, re, unicodedata
from collections import defaultdict

# ========================= CARGA DE DATOS =========================
def _here(*parts):
    return os.path.join(os.path.dirname(__file__), *parts)


def _load_json_or_yaml(path: str):
    """Carga un archivo JSON o YAML según la extensión."""
    with open(path, "r", encoding="utf-8") as fh:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except ImportError as exc:
                raise RuntimeError("PyYAML es requerido para cargar configuraciones YAML") from exc
            return yaml.safe_load(fh)
        return json.load(fh)

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


# Base de conocimiento general del SENA
SENA_INFO_PATHS = [
    _here("data", "sena_info.json"),
    _here("..", "data", "sena_info.json"),
    "data/sena_info.json",
]


def _load_sena_info():
    for pth in SENA_INFO_PATHS:
        if os.path.exists(pth):
            with open(pth, "r", encoding="utf-8") as fh:
                data = json.load(fh) or []
            # Normalizamos tags para matching rápido
            for item in data:
                tags = item.get("tags") or []
                item["tags_norm"] = [_norm(t) for t in tags if _norm(t)]
            return data
    return []


SENA_INFO = _load_sena_info()


# ========================= CONFIGURACIÓN (alias / sinónimos) =========================

CONFIG_DIR = _here("config")
TOPIC_SYNONYM_PATHS = [
    os.path.join(CONFIG_DIR, "topic_synonyms.json"),
    os.path.join(CONFIG_DIR, "topic_synonyms.yaml"),
    os.path.join(CONFIG_DIR, "topic_synonyms.yml"),
]
LOCATION_ALIAS_PATHS = [
    os.path.join(CONFIG_DIR, "location_aliases.json"),
    os.path.join(CONFIG_DIR, "location_aliases.yaml"),
    os.path.join(CONFIG_DIR, "location_aliases.yml"),
]


def _first_existing(paths: list[str]) -> str:
    for pth in paths:
        if os.path.exists(pth):
            return pth
    raise FileNotFoundError(
        "No se encontró ningún archivo de configuración en: " + ", ".join(paths)
    )


def _normalize_mapping(raw: dict, label: str) -> dict:
    """Normaliza claves y valores con _norm y detecta duplicados."""
    normalized = {}
    seen = set()
    duplicates = []
    for canon, variants in (raw or {}).items():
        canon_norm = _norm(canon)
        if canon_norm in seen:
            duplicates.append(canon_norm)
            continue
        seen.add(canon_norm)
        vals = set()
        for v in (variants or []):
            v_norm = _norm(v)
            if v_norm:
                vals.add(v_norm)
        vals.add(canon_norm)
        normalized[canon_norm] = vals
    if duplicates:
        raise ValueError(f"Claves duplicadas en {label}: {', '.join(sorted(set(duplicates)))}")
    return normalized


def _load_topic_synonyms():
    path = _first_existing(TOPIC_SYNONYM_PATHS)
    data = _load_json_or_yaml(path) or {}
    if not isinstance(data, dict):
        raise ValueError("El archivo de sinónimos debe contener un objeto mapping")
    return _normalize_mapping(data, "topic_synonyms")


def _load_location_aliases():
    path = _first_existing(LOCATION_ALIAS_PATHS)
    data = _load_json_or_yaml(path) or {}
    if not isinstance(data, dict):
        raise ValueError("El archivo de alias debe contener un objeto mapping")
    sede_aliases_v2 = _normalize_mapping(data.get("sede_aliases_v2") or {}, "sede_aliases_v2")
    alias_municipio = _normalize_mapping(data.get("alias_municipio") or {}, "alias_municipio")
    alias_sede = _normalize_mapping(data.get("alias_sede") or {}, "alias_sede")
    return sede_aliases_v2, alias_municipio, alias_sede

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

# Alias y sinónimos desde configuración externa
_SEDE_ALIASES_V2_RAW, ALIAS_MUNICIPIO, ALIAS_SEDE = _load_location_aliases()
SEDE_ALIASES_V2 = _SEDE_ALIASES_V2_RAW
_TOPIC_SYNONYMS = _load_topic_synonyms()

# reverse lookup: variante -> canon (lo usa el parser)
SEDE_ALIAS_TO_CANON = {}
for canon, variants in SEDE_ALIASES_V2.items():
    for v in variants:
        SEDE_ALIAS_TO_CANON[_norm(v)] = _norm(canon)


# Expandir tokens de tema (sinónimos básicos; puedes añadir más)
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

# ==== TOPIC MATCH (v2) =======================================================

def _topic_match_codes(intent: dict) -> set:
    """
    Devuelve códigos candidatos por tema.
    - Coincidencia por frase ("contains") usando TITLE_PHRASES
    - Coincidencia por tokens con umbral mínimo
    """
    if DATA_FORMAT != "normalized_v2":
        # Fallback: usa NG_TITLE existente
        grams = set()
        for t in (intent.get("tema_tokens") or []):
            grams |= _grams(t)
        out = set()
        for g in grams:
            for c in NG_TITLE.get(g, []):
                out.add(c)
        return out

    tokens = set(intent.get("tema_tokens") or [])
    tail   = _norm(intent.get("tail_text") or "")

    codes = set()

    # 1) frase (si viene desde "sobre ...")
    if tail:
        for phrase, cs in TITLE_PHRASES.items():
            if tail in phrase or phrase in tail:
                codes |= cs

    # 2) tokens con umbral: exigimos al menos la mitad (redondeo hacia arriba) o 2, lo que sea menor pero ≥1
    if tokens:
        from math import ceil
        hit_counter = defaultdict(int)
        for t in tokens:
            for c in TITLE_TOKENS.get(_norm(t), ()):
                hit_counter[c] += 1

        need = max(1, min(2, ceil(len(tokens) / 2)))
        for c, hits in hit_counter.items():
            if hits >= need:
                codes.add(c)

    return codes


def _topic_match_score_v2(prog: dict, tema_tokens: set[str], tema_phrase: str) -> int:
    """
    Calcula un puntaje de match temático SOLO usando el programa base (v2).
    Evita falsos positivos premiando frase exacta y cobertura de tokens.
    """
    if not tema_tokens:
        return 0

    titulo = _norm(prog.get("programa") or prog.get("programa_norm") or "")
    titulo_toks = set(_tokens(titulo))
    kw = prog.get("palabras_clave") or []
    kw_norm = " ".join(_norm(k or "") for k in kw)
    kw_toks = set(_tokens(kw_norm))

    score = 0

    # 1) Frase exacta en el título
    if tema_phrase and tema_phrase in titulo:
        score += 100

    # 2) Todos los tokens del tema están en el título
    if tema_tokens and tema_tokens.issubset(titulo_toks):
        score += 60

    # 3) Cobertura por palabras_clave
    if tema_tokens:
        covered_kw = len(tema_tokens & kw_toks)
        score += covered_kw * 10

    return score


def _topic_scores_v2(tema_tokens: set[str], tema_phrase: str) -> list[tuple[str,int]]:
    """
    Devuelve [(code, score)] ordenado por score descendente para DATA_FORMAT == 'normalized_v2'.
    Aplica un umbral para filtrar ruido.
    """
    results = []
    for code, prog in BY_CODE.items():
        sc = _topic_match_score_v2(prog, tema_tokens, tema_phrase)
        if sc >= 20:
            results.append((code, sc))
    results.sort(key=lambda x: (-x[1], BY_CODE[x[0]]["programa_norm"]))
    return results

TITLE_TOKENS = defaultdict(set)   # token -> {code,...}
TITLE_PHRASES = defaultdict(set)  # frase (programa_norm/keyword completo) -> {code,...}

# ========================= RUTA v2 (programas_normalizado_v2.json) =========================
if DATA_FORMAT == "normalized_v2":
    # Limpia / reinicia índices v2
    BY_CODE.clear()
    BY_MUNICIPIO.clear()
    BY_SEDE.clear()
    NG_TITLE.clear()
    TITLE_TOKENS.clear()
    TITLE_PHRASES.clear()

    # --- helper interno: añade claves de sede/centro a BY_SEDE
    def _index_sede_keys(oferta, code, ord_n):
        # Tomamos sede_norm y centro_norm (algunas filas lo traen solo en 'centro_norm')
        raw_keys = [oferta.get("sede_norm"), oferta.get("centro_norm")]
        for raw in raw_keys:
            if not raw:
                continue
            k = _norm(raw)
            BY_SEDE[k].append((code, ord_n))
        # Si hay un canon definido para esta clave, también indexa bajo canon y sus alias
        for raw in raw_keys:
            if not raw:
                continue
            k = _norm(raw)
            canon = SEDE_ALIAS_TO_CANON.get(k)
            if canon:
                BY_SEDE[canon].append((code, ord_n))
                # Indexa además todas las variantes declaradas para ese canon
                for v in SEDE_ALIASES_V2.get(canon, set()):
                    BY_SEDE[_norm(v)].append((code, ord_n))

    # Indexación principal
    for prog in PROGRAMAS:
        code = str(prog.get("codigo") or "").strip()
        if not code:
            continue

        # 1) Código -> programa base
        BY_CODE[code] = prog

        # 2) Ubicaciones (se indexa por cada oferta)
        ofertas = prog.get("ofertas") or []
        for of in ofertas:
            ord_n = of.get("ordinal", 1)

            # Municipio: usar tanto el municipio_norm como el municipio_base_norm
            for key in (of.get("municipio_norm"), of.get("municipio_base_norm")):
                if key:
                    BY_MUNICIPIO[_norm(key)].append((code, ord_n))

            # Sede/centro + alias
            _index_sede_keys(of, code, ord_n)

        # 3) Título/tema:
        #    - NG_TITLE (n-gramas) para compatibilidad
        #    - TITLE_PHRASES (frases completas) para "contains"
        #    - TITLE_TOKENS (tokens) para matching por cobertura
        name_norm = _norm(prog.get("programa_norm") or prog.get("programa") or "")
        if name_norm:
            TITLE_PHRASES[name_norm].add(code)
            for g in _grams(name_norm):
                NG_TITLE[g].append(code)
            for tok in _tokens(name_norm):
                TITLE_TOKENS[tok].add(code)

        for kw in (prog.get("palabras_clave") or []):
            kw_norm = _norm(kw or "")
            if not kw_norm:
                continue
            TITLE_PHRASES[kw_norm].add(code)
            for g in _grams(kw_norm):
                NG_TITLE[g].append(code)
            for tok in _tokens(kw_norm):
                TITLE_TOKENS[tok].add(code)

    # 4) Expansión de alias de sedes (por si algún canon no se tocó arriba)
    if "SEDE_ALIASES_V2" in globals():
        for canon, variants in SEDE_ALIASES_V2.items():
            canon_key = _norm(canon)
            pairs = BY_SEDE.get(canon_key, [])
            if pairs:
                for v in variants:
                    BY_SEDE[_norm(v)].extend(pairs)

    # 5) Llaves conocidas (después de expandir alias)
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
            # Coincidencias por alias explícito
            for v, canon in SEDE_ALIAS_TO_CANON.items():
                if v in tail or tail in v:
                    sedes.add(canon)
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
    Scoring para DATA_FORMAT == 'normalized_v2'.
    Puntos:
      +5 si el nivel coincide exactamente.
      +3 si coincide municipio (municipio_norm o municipio_base_norm) en alguna oferta.
      +3 si coincide sede (sede_norm) en alguna oferta.
      +2 por cada token de tema en común (máx +10).
      +8 si la frase de la cola ('tail_text') está contenida en el nombre del programa.
    En formatos legacy retorna 0 (se ordena por nombre).
    """
    if DATA_FORMAT != "normalized_v2":
        return 0

    prog = BY_CODE.get(code)
    if not prog:
        return 0

    score = 0

    # Nivel exacto
    if intent.get("nivel") and intent["nivel"] == prog.get("nivel_norm"):
        score += 5

    # Ubicación (miramos todas las ofertas)
    loc = intent.get("location") or {}
    ofertas = prog.get("ofertas") or []

    if "municipio" in loc:
        muni_keys = { _norm(x) for x in loc["municipio"] if x }
        if any((of.get("municipio_norm") in muni_keys) or
               (of.get("municipio_base_norm") in muni_keys) for of in ofertas):
            score += 3

    if "sede" in loc:
        sede_keys = { _norm(x) for x in loc["sede"] if x }
        if any(of.get("sede_norm") in sede_keys for of in ofertas):
            score += 3

    # Afinidad por tema
    tema = set(intent.get("tema_tokens") or [])
    if tema:
        # bolsa de términos del programa: nombre + palabras_clave
        bag = set(_tokens(prog.get("programa_norm", "")))
        for kw in (prog.get("palabras_clave") or []):
            bag |= set(_tokens(kw))

        overlap = len(tema & bag)
        score += min(10, overlap * 2)  # hasta +10

        tail = _norm(intent.get("tail_text") or "")
        if tail and (tail in (prog.get("programa_norm", ""))):
            score += 8

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

    # 4) tema
    topic_codes = _topic_match_codes(intent)

    if topic_codes:
        if candidates:
            # si ya había ubicación, mantenemos sólo los que coinciden con el tema
            candidates = {pair for pair in candidates if pair[0] in topic_codes}
        else:
            # sin ubicación: añadimos la primera oferta de cada código
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
    parts = [f"📘 *{titulo}*", f"{nivel} · Código [{code}]"]

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
        comp_list = comp if isinstance(comp, list) else [str(comp)]
        for c in comp_list[:6]:
            if c:
                parts.append(f"• {c}")
        if len(comp_list) > 6:
            parts.append(f"   (+{len(comp_list)-6} más)")

    if cert:
        parts.append("\n*Certificación:*")
        parts.append(cert)

    # 💡 Hints sobre ubicaciones (siempre mostramos algo)
    offers = prog.get("ofertas") or []
    offer_count = len(offers)
    if offer_count > 1:
        parts.append(
            f"\n💡 Este programa tiene *{offer_count} ubicaciones*."
            f"\n   Escribe *{code}* para ver todas."
        )
    else:
        parts.append("\n🔸 Única ubicación disponible.")

    parts.append(
        "\nℹ️ Puedes escribir:  requisitos {code} · perfil {code} · competencias {code} · certificacion {code}"
        .format(code=code)
    )
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

def _offer_count_v2(prog_or_code) -> int:
    """
    Devuelve el número de ofertas reales (ordinales únicos) para un programa (v2).
    Acepta el dict del programa o un código.
    """
    if DATA_FORMAT != "normalized_v2":
        return 0
    prog = prog_or_code
    if not isinstance(prog_or_code, dict):
        prog = BY_CODE.get(str(prog_or_code).strip()) or {}
    ofertas = prog.get("ofertas") or []
    # contar ordinales únicos por seguridad
    seen = set()
    for of in ofertas:
        o = of.get("ordinal")
        if o:
            seen.add(o)
    return len(seen)


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
            # Render normal + el mismo aviso si detectamos más de una ubicación real (por si hay ofertas colapsadas)
            txt = _render_ficha_v2(prog, ofertas[0], code)
            total = _offer_count_v2(prog)
            if total > 1 and "Este programa tiene" not in txt:
                txt += f"\n\n💡 Este programa tiene *{total} ubicaciones*. Escribe *{code}* para ver todas."
            return txt

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
        if DATA_FORMAT == "normalized_v2":
            prog = BY_CODE.get(code)
            of = None
            if prog:
                for o in (prog.get("ofertas") or []):
                    if o.get("ordinal") == ord_n:
                        of = o
                        break

            # datos comunes
            offer_count = len((prog or {}).get("ofertas") or [])
            if offer_count > 1:
                hint = f"\n    💡 +{offer_count-1} ubic. más — escribe *{code}* para ver todas."
            else:
                hint = "\n    🔸 Única ubicación disponible."

            if prog and of:
                muni = of.get('municipio','')
                sede = of.get('sede_nombre','')
                hor  = of.get('horario','')
                lines.append(
                    f"{i}. {prog['programa']} ({prog.get('nivel','')}) — Código [{code}]"
                    f"\n    📍 {muni} — {sede}"
                    + (f"\n    🕒 {hor}" if hor else "")
                    + hint
                )
            elif prog:
                # Si por alguna razón no hallamos la oferta exacta, igual mostramos el hint
                lines.append(f"{i}. {prog['programa']} — Código [{code}]" + hint)
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
                    + (f"\n    🕒 {hor}" if hor else "")
                )
            else:
                lines.append(f"{i}. Código [{code}]")

    if len(items) > start + page_size:
        lines.append("\nEscribe *ver más* para ver más resultados.")
    return "\n".join(lines)
    
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

def _render_prog_fields(prog, fields):
    """Utilidad para armar bloques de requisitos/perfil/competencias/certificacion."""
    parts = []
    if "requisitos" in fields:
        parts.append("\n*Requisitos:*")
        parts.append(prog.get("requisitos") or "No disponible.")
    if "perfil" in fields:
        parts.append("\n*Perfil del egresado:*")
        parts.append(prog.get("perfil") or "No disponible.")
    if "competencias" in fields:
        parts.append("\n*Competencias:*")
        comps = prog.get("competencias") or []
        if comps:
            for c in comps[:6]:
                if c:
                    parts.append(f"• {c}")
            if len(comps) > 6:
                parts.append(f"   (+{len(comps)-6} más)")
        else:
            parts.append("No disponible.")
    if "certificacion" in fields or "certificación" in fields:
        parts.append("\n*Certificación:*")
        parts.append(prog.get("certificacion") or "No disponible.")
    return parts


def _handle_follow_query(texto: str) -> str or None:
    """
    Maneja consultas del tipo:
      - requisitos|perfil|competencias|certificacion|horario (+ código/ordinal opcional)
      - también combina con nivel/ubicación (p.ej. 'horario tecnólogo en popayán')
    Retorna un string de respuesta o None si no aplica FOLLOW.
    """
    qn = _norm(texto)
    FOLLOW = {"requisitos","requisito","req","duracion","duración","tiempo",
              "perfil","competencias","certificacion","certificación","horario","jornada"}
    if not any(w in qn for w in FOLLOW):
        return None

    # Qué campos pide
    asked = set()
    for w in FOLLOW:
        if w in qn:
            asked.add("horario" if w in {"horario","jornada"} else w)

    intent = _parse_intent(texto)

    # 1) Si viene código-ordinal: responde específico a esa oferta
    if intent.get("code") and intent.get("ordinal") and DATA_FORMAT == "normalized_v2":
        code, ord_n = intent["code"], intent["ordinal"]
        prog = BY_CODE.get(code)
        if not prog:
            return "No encontré información para ese código."
        oferta = None
        for of in (prog.get("ofertas") or []):
            if of.get("ordinal") == ord_n:
                oferta = of; break

        if not oferta:
            return "No encontré esa variante (revisa el *código-ordinal*)."

        parts = [f"📘 *{prog['programa']}* — Código [{code}-{ord_n}]",
                 f"📍 {oferta.get('municipio','')} — {oferta.get('sede_nombre','')}"]
        if "horario" in asked:
            parts.append("\n*Horario:*")
            parts.append(oferta.get("horario") or "No registrado.")
        # Campos de programa (generales)
        parts += _render_prog_fields(prog, asked - {"horario"})
        # Sugerencia
        all_offers = prog.get("ofertas") or []
        if len(all_offers) > 1:
            parts.append(f"\n💡 Este programa tiene *{len(all_offers)} ubicaciones*. Escribe *{code}* para ver todas.")
        return "\n".join([p for p in parts if p])

    # 2) Si viene código SIN ordinal
    if intent.get("code") and DATA_FORMAT == "normalized_v2":
        code = intent["code"]
        prog = BY_CODE.get(code)
        if not prog:
            return "No encontré información para ese código."

        ofertas = prog.get("ofertas") or []
        parts = [f"📘 *{prog['programa']}* — Código [{code}]"]

        # Horarios: listar por ubicación si hay varias ofertas
        if "horario" in asked:
            parts.append("\n*Horarios por ubicación:*")
            if ofertas:
                for of in ofertas[:10]:
                    muni = of.get("municipio",""); sede = of.get("sede_nombre","")
                    hor = of.get("horario") or "No registrado"
                    ord_n = of.get("ordinal")
                    parts.append(f"• {muni} — {sede}: {hor}   (elige con *{code}-{ord_n}*)")
                if len(ofertas) > 10:
                    parts.append("   (+ más ubicaciones; escribe el código para verlas todas)")
            else:
                parts.append("No hay horarios registrados.")
        # Campos generales del programa
        parts += _render_prog_fields(prog, asked - {"horario"})

        # Sugerencia de ubicaciones
        if len(ofertas) > 1:
            parts.append(f"\n💡 Este programa tiene *{len(ofertas)} ubicaciones*. Escribe *{code}* para listarlas.")
        return "\n".join([p for p in parts if p])

    # 3) Sin código: combinar con nivel/ubicación si la consulta los trae
    #    - horario: listamos horarios de los primeros matches (10)
    #    - demás campos: mostramos campos generales por programa (1 por código)
    items = _search_programs(intent)
    if not items:
        return "No encontré coincidencias para esa consulta."

    # Recorta a 10 ítems visibles
    items = items[:10]

    # Si pide HORARIO → mejor mostrar por oferta (code-ordinal) con ubicación
    if "horario" in asked and DATA_FORMAT == "normalized_v2":
        lines = ["*Horarios encontrados:*"]
        seen = set()
        for code, ord_n in items:
            prog = BY_CODE.get(code); oferta = None
            if not prog: continue
            for of in prog.get("ofertas") or []:
                if of.get("ordinal") == ord_n:
                    oferta = of; break
            if not oferta: continue
            key = (code, ord_n)
            if key in seen: continue
            seen.add(key)
            muni = oferta.get("municipio",""); sede = oferta.get("sede_nombre","")
            hor = oferta.get("horario") or "No registrado"
            lines.append(f"• {prog['programa']} — [{code}-{ord_n}]\n   📍 {muni} — {sede}\n   🕒 {hor}")
        return "\n".join(lines)

    # Para requisitos/perfil/competencias/certificacion: 1 bloque por programa (no por oferta)
    if DATA_FORMAT == "normalized_v2":
        lines = []
        seen_codes = set()
        for code, ord_n in items:
            if code in seen_codes: continue
            seen_codes.add(code)
            prog = BY_CODE.get(code)
            if not prog: continue
            lines.append(f"📘 *{prog['programa']}* — Código [{code}]")
            lines += _render_prog_fields(prog, asked)
            lines.append(f"💡 Escribe *{code}* para ver ubicaciones y horarios.")
            lines.append("")  # espaciado
        return "\n".join([ln for ln in lines if ln.strip()])

    # Legacy fallback: si no es v2, solo devolvemos un tip
    return "Para ver requisitos/horarios exactos, envía el *código* del programa (ej. 233104 o 233104-2)."


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


# ========================= GENERAR RESPUESTA =========================
# Estado global para manejar paginación
STATE = {
    "items": [],
    "intent": None,
    "page": 0,
    "header": "",
}

GREETING_KEYWORDS = {
    "hola",
    "holi",
    "holis",
    "buenos dias",
    "buen dia",
    "buenas",
    "buenas tardes",
    "buenas noches",
    "saludos",
    "hey",
    "ola",
    "gracias",
    "como estas",
    "cómo estas",
    "como estas?",
    "qué tal",
    "que tal",
}

GREETING_RESPONSES = [
    (
        "¡Hola! 👋 Soy el asistente del SENA. "
        "Puedo ayudarte a buscar programas de formación y responder dudas generales como "
        "‘qué es el SENA’ o ‘cómo inscribirme’. ¿Qué tienes en mente?"
    ),
    (
        "¡Hola! 🙌 Soy tu asistente del SENA. "
        "Dime si quieres saber sobre programas, horarios o cómo registrarte y te guío."
    ),
]


def _is_greeting(text_norm: str) -> bool:
    return text_norm in GREETING_KEYWORDS or any(
        text_norm.startswith(prefix) for prefix in GREETING_KEYWORDS
    )


def route_general_response(texto: str):
    """Responde saludos y preguntas generales sin pasar por el buscador."""

    if not texto:
        return None

    qn = _norm(texto)

    # --- Saludos / small-talk ---
    if _is_greeting(qn):
        idx = hash(qn) % len(GREETING_RESPONSES)
        return GREETING_RESPONSES[idx], "greeting"

    # --- Conocimiento general del SENA ---
    matched = _match_sena_info(qn)
    if matched:
        title = matched.get("title") or "Información SENA"
        answer = matched.get("answer") or ""
        return f"*{title}*\n{answer}", "general_info"

    return None


def _match_sena_info(text_norm: str) -> dict | None:
    """Busca la respuesta de conocimiento general por tags normalizados."""
    for item in SENA_INFO:
        for tag in item.get("tags_norm", []):
            if tag and tag in text_norm:
                return item
    return None

def generar_respuesta(texto: str, show_all: bool = False, page: int = 0, page_size: int = 10) -> str:
    """
    Motor principal del bot con soporte de paginación 'ver más'.
    """
    if not texto:
        return (
            "Escribe una consulta, por ejemplo:\n"
            "• *tecnólogo en Popayán*\n"
            "• *técnicos sobre sistemas*\n"
            "• *233104* o *233104-2*"
        )

    qn = _norm(texto)

    # --- Paginación: 'ver más' ---
    if qn in {"ver mas", "ver más", "vermas"} and STATE.get("items"):
        STATE["page"] += 1
        body = _format_list(STATE["items"], page=STATE["page"], page_size=page_size)
        if body.startswith("No encontré") or body.startswith("No hay más"):
            STATE["page"] -= 1
            return "No hay más resultados en esta lista."
        return (STATE.get("header") or f"Resultados (pág. {STATE['page']+1}):\n") + body

    # --- Saludos / small-talk ---
    if _is_greeting(qn):
        idx = hash(qn) % len(GREETING_RESPONSES)
        return GREETING_RESPONSES[idx]

    # --- Conocimiento general del SENA ---
    matched = _match_sena_info(qn)
    if matched:
        title = matched.get("title") or "Información SENA"
        answer = matched.get("answer") or ""
        return f"*{title}*\n{answer}"

    # --- Consultas puntuales (requisitos, perfil, horario, competencias, etc.) ---
    follow = _handle_follow_query(texto)
    if follow:
        return follow


    # --- Parseo de intención ---
    intent = _parse_intent(texto)

    # --- Consultas por código ---
    if intent.get("code") and intent.get("ordinal"):
        return ficha_por_codigo_y_ordinal(intent["code"], intent["ordinal"])

    if intent.get("code"):
        prog = BY_CODE.get(intent["code"]) if DATA_FORMAT == "normalized_v2" else None
        if prog and prog.get("ofertas"):
            items = [(intent["code"], of.get("ordinal", i+1)) for i, of in enumerate(prog.get("ofertas"))]
            STATE.update({
                "items": items,
                "intent": intent,
                "page": 0,
                "header": f"Ubicaciones para *{prog['programa']}* (pág. 1):\n"
            })
            return STATE["header"] + _format_list(items, page=0, page_size=page_size)
        return ficha_por_codigo(intent["code"])

    # --- Búsqueda general ---
    results = _search_programs(intent)
    if not results:
        return (
            "No estoy seguro de haber entendido. Puedo ayudarte a buscar programas de formación del SENA "
            "y responder dudas como ‘qué es el SENA’, ‘cómo inscribirme’ o ‘cómo continuar el proceso’. "
            "¿Me repites tu pregunta con otras palabras?"
        )

    # --- Encabezado ---
    if intent.get("location", {}).get("municipio"):
        mun_txt = next(iter(intent["location"]["municipio"]))
        header = f"Programas en *{mun_txt.title()}* (pág. 1):\n"
    elif intent.get("location", {}).get("sede"):
        sede_txt = next(iter(intent["location"]["sede"]))
        header = f"Programas en *{sede_txt.title()}* (pág. 1):\n"
    elif intent.get("nivel") and intent.get("tema_tokens"):
        tema_txt = " ".join(sorted(intent["tema_tokens"]))
        header = f"{intent['nivel'].title()} sobre *{tema_txt}* (pág. 1):\n"
    elif intent.get("tema_tokens"):
        tema_txt = " ".join(t for t in _tokens(qn) if t not in {"en", "de", "sobre"})
        header = f"Resultados para el tema *{tema_txt}* (pág. 1):\n"
    elif intent.get("nivel"):
        header = f"Programas del nivel *{intent['nivel']}* (pág. 1):\n"
    else:
        header = "Resultados (pág. 1):\n"

    # --- Guardar estado (para 'ver más') ---
    STATE.update({
        "items": results,
        "intent": intent,
        "page": 0,
        "header": header
    })

    # --- Página inicial ---
    body = _format_list(results, page=page, page_size=page_size)
    if body.startswith("No encontré"):
        return body

    return header + body
