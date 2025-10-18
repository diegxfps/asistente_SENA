import os
import json
import logging
import unicodedata
import re
from flask import Flask, request, jsonify
import requests

# Importa las funciones del core (v2/legacy compatibles)
from app.core import (
    generar_respuesta,
    ficha_por_codigo,
    ficha_por_codigo_y_ordinal,
    _parse_intent,
    _search_programs,
)

# ========================= LOGGING =========================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook")

# ========================= ENV VARS =========================
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "sena_token")

GRAPH_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

# ========================= APP =========================
app = Flask(__name__)

# ========================= ESTADO POR USUARIO =========================
# Guardamos lo mínimo por chat para paginar y seleccionar por índice
# STATE[user] = {
#   "last_query": "texto normalizado",
#   "page": 0,                          # página actual (0-based)
#   "items": [ (code, ordinal), ... ],  # lista completa para la última búsqueda
# }
STATE = {}

# ========================= HELPERS =========================
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
    try:
        r = requests.post(GRAPH_URL, headers=headers, json=payload, timeout=20)
        if r.status_code >= 400:
            log.error(f"Error enviando: {r.status_code} {r.text}")
    except Exception as e:
        log.exception(f"Error al llamar al Graph API: {e}")

def _extract_text(msg: dict) -> str:
    """Soporta 'text' y 'interactive' (botón/lista)."""
    mtype = msg.get("type")
    if mtype == "text":
        return msg.get("text", {}).get("body", "")
    if mtype == "interactive":
        inter = msg.get("interactive", {})
        # button_reply o list_reply devuelven title
        br = inter.get("button_reply", {})
        lr = inter.get("list_reply", {})
        return br.get("title") or lr.get("title") or ""
    return ""

def _current_page_items(user_id: str, page_size: int = 10):
    st = STATE.get(user_id, {})
    items = st.get("items", [])
    page = st.get("page", 0)
    start = page * page_size
    end = start + page_size
    return items[start:end]

# ========================= HEALTH & VERIFY =========================
@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        log.info("✅ Verificación OK")
        return challenge, 200
    return "forbidden", 403

# ========================= INCOMING =========================
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
        text = _extract_text(msg) or ""
        text_norm = _norm_simple(text)
        st = STATE.get(from_number, {"last_query": "", "page": 0, "items": []})

        # ============= 1) Selección directa "codigo-ordinal" =================
        m_code_idx = re.fullmatch(r"\s*(\d{5,7})-(\d{1,2})\s*", text_norm)
        if m_code_idx:
            code, ord_str = m_code_idx.groups()
            ord_n = int(ord_str)
            respuesta = ficha_por_codigo_y_ordinal(code, ord_n)
            # mantener contexto en caso de que el usuario siga con "ver más"
            STATE[from_number] = {"last_query": f"{code}-{ord_n}", "page": 0, "items": []}
            send_whatsapp_message(to=from_number, body=respuesta)
            return "ok", 200

        # ============= 2) "ver más": misma búsqueda, siguiente página ========
        if text_norm in {"ver mas", "ver más", "vermas"}:
            if not st["last_query"]:
                send_whatsapp_message(
                    to=from_number,
                    body="No tengo una búsqueda previa. Escribe por ejemplo: *tecnólogos en Popayán* o *programas en La Casona*."
                )
                return "ok", 200

            # Siguiente página
            st["page"] += 1
            # Volvemos a pedir la respuesta con show_all=True y la página nueva
            respuesta = generar_respuesta(st["last_query"], show_all=True, page=st["page"], page_size=10)
            STATE[from_number] = st
            send_whatsapp_message(to=from_number, body=respuesta)
            return "ok", 200

        # ============= 3) Selección por índice (1..10) en la página actual ===
        if re.fullmatch(r"[1-9]|10", text_norm) and st.get("items"):
            idx = int(text_norm) - 1
            page_items = _current_page_items(from_number, page_size=10)
            if 0 <= idx < len(page_items):
                code, ord_n = page_items[idx]
                respuesta = ficha_por_codigo_y_ordinal(code, ord_n)
                send_whatsapp_message(to=from_number, body=respuesta)
                return "ok", 200
            # si no válido, sigue al flujo normal

        # ============= 4) Consulta normal ================================
        # Guardamos los items para poder seleccionar por índice y paginar
        intent = _parse_intent(text_norm)
        items = _search_programs(intent)
        st = {"last_query": text_norm, "page": 0, "items": items}
        STATE[from_number] = st

        # Render principal (página 1)
        respuesta = generar_respuesta(text, show_all=False, page=0, page_size=10)
        send_whatsapp_message(to=from_number, body=respuesta)
        return "ok", 200

    except Exception as e:
        log.exception(f"Error procesando webhook: {e}")
        return "error", 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
