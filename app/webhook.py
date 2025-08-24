# app/webhook.py
import os
import json
import logging
import unicodedata
from flask import Flask, request, jsonify
import requests

from app.core import generar_respuesta  # <- toda la lógica vive en core.py

# -----------------------------
# Config & logging
# -----------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "sena_token")

GRAPH_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

app = Flask(__name__)

# Memoria simple por usuario (última consulta)
STATE = {}  # { "57311...": {"last_query": "alto cauca"} }

# -----------------------------
# Helpers
# -----------------------------
def _norm_simple(s: str) -> str:
    if not s:
        return ""
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return " ".join(s.lower().strip().split())

def send_whatsapp_message(to: str, body: str):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        log.error("❌ Faltan credenciales de WhatsApp (TOKEN o PHONE_NUMBER_ID).")
        return

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body[:4096]},  # límite de seguridad
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(GRAPH_URL, headers=headers, json=payload, timeout=20)
        if r.status_code >= 400:
            log.error(f"Error enviando: {r.status_code} {r.text}")
        else:
            log.info(f"📤 Enviado a {to}")
    except Exception as e:
        log.exception(f"Error enviando mensaje: {e}")

# -----------------------------
# Health
# -----------------------------
@app.get("/health")
def health():
    return jsonify({"status": "ok"})

# -----------------------------
# Webhook verification (Meta)
# -----------------------------
@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        log.info("✅ Verificación de webhook exitosa.")
        return challenge, 200
    log.warning("❌ Verificación de webhook fallida.")
    return "forbidden", 403

# -----------------------------
# Incoming messages
# -----------------------------
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

        # extraer texto
        if mtype == "text":
            text = msg["text"]["body"]
        elif mtype == "interactive":
            inter = msg.get("interactive", {})
            text = (inter.get("button_reply", {}) or inter.get("list_reply", {})).get("title", "")
        else:
            text = "(mensaje no-texto)"

        text_norm = _norm_simple(text)

        # --- PAGINACIÓN "MÁS" ---
        if text_norm in {"mas", "más", "ver mas", "ver más", "mostrar mas", "mostrar más"}:
            st = STATE.get(from_number)
            if not st or not st.get("last_query"):
                respuesta = "No tengo una búsqueda previa. Escribe una consulta (ej.: 'alto cauca', 'tecnologo en sistemas')."
            else:
                respuesta = generar_respuesta(st["last_query"], show_all=True)

        # --- VER TODOS explícito ---
        elif text_norm in {"ver todos", "mostrar todos", "todo", "todos"}:
            st = STATE.get(from_number)
            if not st or not st.get("last_query"):
                respuesta = "No tengo una búsqueda previa. Escribe una consulta (ej.: 'alto cauca')."
            else:
                respuesta = generar_respuesta(st["last_query"], show_all=True)

        # --- NUEVA CONSULTA (saludos, ayuda, búsquedas, detalle, etc.) ---
        else:
            respuesta = generar_respuesta(text, show_all=False)
            # guarda última consulta (sirve para "más")
            STATE[from_number] = {"last_query": text_norm}

        # Enviar
        send_whatsapp_message(to=from_number, body=respuesta)

    except Exception as e:
        log.exception(f"Error procesando webhook: {e}")

    return "ok", 200

# -----------------------------
# Entrypoint (dev)
# -----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
