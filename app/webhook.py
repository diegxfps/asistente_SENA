# app/webhook.py
import os
import json
import logging
import unicodedata
import re
from flask import Flask, request, jsonify
import requests


from app.core import (
    generar_respuesta, top_codigos_para, ficha_por_codigo, _find_by_code, TOPIC_RE,
    PROGRAMAS, _norm, _tokens, _fields_for_topic, NIVEL_CANON, _expand_topic_tokens
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "sena_token")

GRAPH_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

app = Flask(__name__)

# memoria simple por usuario para "más"
STATE = {}  # {"5731...": {"last_query": "...", "last_code": "233104", "candidates": ["233104","233108",...]}}

def _norm_simple(s: str) -> str:
    if not s:
        return ""
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return " ".join(s.lower().strip().split())

def send_whatsapp_message(to: str, body: str):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        log.error("❌ Faltan credenciales de WhatsApp.")
        return
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body[:4096]},
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    r = requests.post(GRAPH_URL, headers=headers, json=payload, timeout=20)
    if r.status_code >= 400:
        log.error(f"Error enviando: {r.status_code} {r.text}")

# ------------------ Health ------------------
@app.get("/health")
def health():
    return jsonify({"status": "ok"})

# ------------- Meta verification -------------
@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        log.info("✅ Verificación OK")
        return challenge, 200
    return "forbidden", 403

# --------------- Incoming msgs ---------------
@app.post("/webhook")
def incoming():
    data = request.get_json(silent=True) or {}
    log.info(f"Incoming: {json.dumps(data, ensure_ascii=False)}")

    try:
        entry = data.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})
        msgs = value.get("messages", [])
        if not msgs:
            return "no messages", 200

        msg = msgs[0]
        from_number = msg.get("from")
        mtype = msg.get("type")

        # texto o interacción de lista/botón
        if mtype == "text":
            text = msg["text"]["body"]
        elif mtype == "interactive":
            inter = msg.get("interactive", {})
            text = (inter.get("button_reply", {}) or inter.get("list_reply", {})).get("title", "")
        else:
            text = "(mensaje no-texto)"

        text_norm = _norm_simple(text)
        st = STATE.get(from_number, {})

        # ----------------- Selección por "<codigo>-<n>" (variante enumerada) -----------------
        m_code_idx = re.fullmatch(r"\s*(\d{5,7})-(\d{1,2})\s*", text_norm or "")
        if m_code_idx and st.get("candidates_ext"):  # candidates_ext: lista de dicts con {"code","ord"}
            base, ord_str = m_code_idx.groups()
            ord_n = int(ord_str)
            # busca en el último listado una entrada que coincida code+ordinal
            for item in st["candidates_ext"]:
                if item.get("code") == base and item.get("ord") == ord_n:
                    code = item.get("code")
                    st["last_code"] = code
                    STATE[from_number] = st
                    respuesta = ficha_por_codigo(code)
                    send_whatsapp_message(to=from_number, body=respuesta)
                    return "ok", 200
            # si no encuentra match exacto, ignora y sigue flujo normal

        
        # ----------------- Selección numerada (1..5) tras lista ambigua -----------------
        if re.fullmatch(r"[1-5]", text_norm or "") and st.get("candidates"):
            idx = int(text_norm) - 1
            codes = st["candidates"]
            if 0 <= idx < len(codes):
                code = codes[idx]
                st["last_code"] = code
                STATE[from_number] = st
                respuesta = ficha_por_codigo(code)
                send_whatsapp_message(to=from_number, body=respuesta)
                return "ok", 200

        # ----------------- Follow-up: "requisitos?" usando el último código -----------------
        FOLLOW = {"requisitos","requisito","req","duracion","duración","tiempo","perfil","competencias","certificacion","certificación"}
        if any(w in text_norm for w in FOLLOW) and re.search(r"\b\d{5,7}\b", text_norm) is None and st.get("last_code"):
            text = f"{text_norm} {st['last_code']}"

        # ----------------- Paginación: "más" / "ver todos" -----------------
        if text_norm in {"mas", "más", "ver mas", "ver más", "mostrar mas", "mostrar más", "ver todos", "mostrar todos"}:
            if not st or not st.get("last_query"):
                respuesta = "No tengo una búsqueda previa. Escribe una consulta (ej.: 'popayan tecnico', 'alto cauca')."
            else:
                respuesta = generar_respuesta(st["last_query"], show_all=True)

        # ----------------- Nueva consulta normal -----------------
        else:
            respuesta = generar_respuesta(text, show_all=False)

            # Guardar contexto mínimo
            STATE[from_number] = {"last_query": text_norm}
            
            # --- Extraer candidatos en el mismo orden mostrado (hasta 5) ---
            # Buscamos líneas enumeradas "1. " ... "5. " y extraemos el código que aparece entre "Código [XXXXX]"
            candidates_ext = []
            lines = (respuesta or "").splitlines()
            per_code_count = {}  # para ordinal por código: { "134104": 1, ... }
            for ln in lines:
                m_item = re.match(r"\s*(\d+)\.\s+(.+)", ln)  # línea de ítem "1. ..."
                if not m_item:
                    continue
                # intenta extraer código dentro del encabezado
                m_code = re.search(r"C[oó]digo\s*\[(\d{5,7})\]", ln, flags=re.I)
                if not m_code:
                    continue
                code = m_code.group(1)
                per_code_count[code] = per_code_count.get(code, 0) + 1
                candidates_ext.append({"code": code, "ord": per_code_count[code]})
                if len(candidates_ext) >= 5:
                    break
            if candidates_ext:
                STATE[from_number]["candidates_ext"] = candidates_ext

                      # --- Si la consulta es "nivel + (sobre|en|de) + tema", guardamos candidates específicos ---
            m_topic = TOPIC_RE.match(text_norm)
            if m_topic:
                nivel_raw, _, tema = m_topic.groups()
                nivel = NIVEL_CANON.get(_norm(nivel_raw), None)
                if nivel:
                    topic_tokens = _expand_topic_tokens(_tokens(_norm(tema)))
                    # selecciona programas por nivel + presencia del tema en (programa+perfil+competencias)
                    encontrados = []
                    for p in PROGRAMAS:
                        if nivel not in _norm(p.get("nivel","")):
                            continue
                        hay = _fields_for_topic(p)
                        if any(tok in hay for tok in topic_tokens):
                            cod = str(p.get("codigo") or p.get("codigo_ficha") or p.get("no") or "").strip()
                            if cod:
                                encontrados.append(cod)
                    if encontrados:
                        STATE[from_number]["candidates"] = encontrados[:5]
                        STATE[from_number]["page"] = 0


                       # --- Si NO es "nivel + tema", usa el mecanismo genérico ---
            if not re.search(r"\b\d{5,7}\b", text_norm):
                try:
                    # si hubo nivel+tema, este overwrite no debe ejecutarse (ya habrá candidates);
                    # si quieres ser 100% explícito, envuelve en `if "candidates" not in STATE[from_number]:`
                    if "candidates" not in STATE[from_number]:
                        STATE[from_number]["candidates"] = top_codigos_para(text_norm, limit=5)
                except Exception:
                    pass

            # Si el usuario envió un código puro, recordar como last_code
            m_code = re.fullmatch(r"\s*(\d{5,7})\s*", text or "")
            if m_code:
                STATE[from_number]["last_code"] = m_code.group(1)

        # ----------------- Envío de respuesta -----------------
        send_whatsapp_message(to=from_number, body=respuesta)

    except Exception as e:
        log.exception(f"Error procesando webhook: {e}")

    return "ok", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
