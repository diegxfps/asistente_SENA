# app/webhook.py
import os
import json
import logging
import unicodedata
import re
from flask import Flask, request, jsonify
import requests


from app.core import generar_respuesta, top_codigos_para, ficha_por_codigo  # core sigue siendo la única fuente
  # solo usamos el core limpio

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

            # Guardar candidatos para 1..5 (si no hay código explícito en el texto)
            if not re.search(r"\b\d{5,7}\b", text_norm):
                try:
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