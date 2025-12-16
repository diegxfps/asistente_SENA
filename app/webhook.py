import os
import json
import logging
import unicodedata
import re
from flask import Flask, request, jsonify
import requests
from sqlalchemy.orm import Session

# Capa de base de datos
from app.db import (
    ConsentEvent,
    get_or_create_session_state,
    get_or_create_user,
    get_session,
    init_db,
    log_interaction,
)

# Importa las funciones del core (v2/legacy compatibles)
from app.core import (
    generar_respuesta,
    ficha_por_codigo,
    ficha_por_codigo_y_ordinal,
    _parse_intent,
    _search_programs,
    route_general_response,
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

# Inicializar la base de datos (crea tablas si no existen)
init_db()

# ========================= ESTADO POR USUARIO =========================
# Guardamos lo mínimo por chat para paginar y seleccionar por índice
# STATE[user] = {
#   "last_query": "texto normalizado",
#   "page": 0,                          # página actual (0-based)
#   "items": [ (code, ordinal), ... ],  # lista completa para la última búsqueda
# }
STATE = {}

# ========================= ONBOARDING =========================
ONBOARDING_STATES = {
    "TERMS_PENDING": "TERMS_PENDING",
    "ASK_DOCUMENT": "ASK_DOCUMENT",
    "ASK_NAME": "ASK_NAME",
    "ASK_CITY": "ASK_CITY",
    "COMPLETED": "COMPLETED",
}


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


def send_and_log(session: Session, user_id: int | None, to: str, body: str, message_type: str = "text"):
    """Envia un mensaje de salida.

    Para reducir el tamaño de la base de datos no registramos los mensajes de salida por
    defecto. Si se necesita trazabilidad en un caso puntual puede agregarse un log
    explícito en el flujo correspondiente.
    """
    send_whatsapp_message(to=to, body=body)


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


def _handle_onboarding(session: Session, user, state_obj, text: str, text_norm: str) -> str | None:
    """Guía el flujo de consentimiento y datos mínimos."""
    state = state_obj.state
    data = state_obj.data or {}

    if state == ONBOARDING_STATES["TERMS_PENDING"]:
        if any(word in text_norm for word in {"acepto", "sí acepto", "si acepto", "aceptar"}):
            state_obj.state = ONBOARDING_STATES["ASK_DOCUMENT"]
            session.add(
                ConsentEvent(user_id=user.id, decision="accepted", metadata_json=text.strip())
            )
            log_interaction(
                session,
                user_id=user.id,
                direction="system",
                body="consent_accepted",
                message_type="consent",
                step="onboarding",
            )
            return (
                "¡Gracias! Para continuar necesitamos tus datos. "
                "¿Cuál es tu número de documento?"
            )
        return (
            "Antes de ayudarte necesito confirmar que aceptas el tratamiento de datos personales del SENA. "
            "Responde *ACEPTO* para continuar o *NO* si no deseas seguir."
        )

    if state == ONBOARDING_STATES["ASK_DOCUMENT"]:
        if not text_norm:
            return "Necesito tu número de documento para continuar."
        data["document_id"] = text.strip()
        user.document_id = text.strip()
        state_obj.data = data
        state_obj.state = ONBOARDING_STATES["ASK_NAME"]
        return "Gracias. ¿Cuál es tu nombre completo?"

    if state == ONBOARDING_STATES["ASK_NAME"]:
        if not text_norm:
            return "Por favor comparte tu nombre completo."
        data["name"] = text.strip()
        user.name = text.strip()
        state_obj.data = data
        state_obj.state = ONBOARDING_STATES["ASK_CITY"]
        return "¿En qué ciudad o municipio te encuentras?"

    if state == ONBOARDING_STATES["ASK_CITY"]:
        if not text_norm:
            return "Confírmame tu ciudad o municipio para finalizar."
        data["city"] = text.strip()
        user.city = text.strip()
        user.consent_accepted = True
        state_obj.data = data
        state_obj.state = ONBOARDING_STATES["COMPLETED"]
        return (
            "¡Listo! Ya guardé tus datos y puedes empezar a buscar programas del SENA. "
            "Cuéntame qué programa o municipio te interesa."
        )

    # Si ya completó, continuar con el flujo normal
    return None


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

        with get_session() as session:
            user = get_or_create_user(session, from_number)
            state_obj = get_or_create_session_state(session, user)
            if not user.consent_accepted or state_obj.state != ONBOARDING_STATES["COMPLETED"]:
                log_interaction(
                    session,
                    user_id=user.id,
                    direction="inbound",
                    body=text,
                    intent=_parse_intent(text_norm) if text_norm else None,
                    step="onboarding",
                    message_type=msg.get("type", "text"),
                    wa_message_id=msg.get("id"),
                )
                onboarding_reply = _handle_onboarding(session, user, state_obj, text, text_norm)
                if onboarding_reply:
                    send_and_log(session, user.id, from_number, onboarding_reply)
                return "ok", 200

            st = STATE.get(from_number, {"last_query": "", "page": 0, "items": []})

            intent = _parse_intent(text_norm) if text_norm else None

            # ============= Router para saludos / info general del SENA ==========
            routed = route_general_response(text)
            if routed:
                respuesta_routed, routed_intent = routed
                log_interaction(
                    session,
                    user_id=user.id,
                    direction="inbound",
                    body=text,
                    intent=routed_intent,
                    step="routed",
                    message_type=msg.get("type", "text"),
                    wa_message_id=msg.get("id"),
                )
                send_and_log(session, user.id, from_number, respuesta_routed)
                return "ok", 200

            # ============= 1) Selección directa "codigo-ordinal" =================
            m_code_idx = re.fullmatch(r"\s*(\d{5,7})-(\d{1,2})\s*", text_norm)
            if m_code_idx:
                code, ord_str = m_code_idx.groups()
                ord_n = int(ord_str)
                log_interaction(
                    session,
                    user_id=user.id,
                    direction="inbound",
                    body=text,
                    intent=intent,
                    program_code=code,
                    step="details",
                    message_type=msg.get("type", "text"),
                    wa_message_id=msg.get("id"),
                )
                respuesta = ficha_por_codigo_y_ordinal(code, ord_n)
                # mantener contexto en caso de que el usuario siga con "ver más"
                STATE[from_number] = {"last_query": f"{code}-{ord_n}", "page": 0, "items": []}
                send_and_log(session, user.id, from_number, respuesta)
                return "ok", 200

            # ============= 2) "ver más": misma búsqueda, siguiente página ========
            if text_norm in {"ver mas", "ver más", "vermas"}:
                log_interaction(
                    session,
                    user_id=user.id,
                    direction="inbound",
                    body=text,
                    intent=intent,
                    step="pagination",
                    message_type=msg.get("type", "text"),
                    wa_message_id=msg.get("id"),
                )
                if not st["last_query"]:
                    send_and_log(
                        session,
                        user.id,
                        from_number,
                        "No tengo una búsqueda previa. Escribe por ejemplo: *tecnólogos en Popayán* o *programas en La Casona*.",
                    )
                    return "ok", 200

                # Siguiente página
                st["page"] += 1
                # Volvemos a pedir la respuesta con show_all=True y la página nueva
                respuesta = generar_respuesta(st["last_query"], show_all=True, page=st["page"], page_size=10)
                STATE[from_number] = st
                send_and_log(session, user.id, from_number, respuesta)
                return "ok", 200

            # ============= 3) Selección por índice (1..10) en la página actual ===
            if re.fullmatch(r"[1-9]|10", text_norm) and st.get("items"):
                idx = int(text_norm) - 1
                page_items = _current_page_items(from_number, page_size=10)
                if 0 <= idx < len(page_items):
                    code, ord_n = page_items[idx]
                    log_interaction(
                        session,
                        user_id=user.id,
                        direction="inbound",
                        body=text,
                        intent=intent,
                        program_code=code,
                        step="details",
                        message_type=msg.get("type", "text"),
                        wa_message_id=msg.get("id"),
                    )
                    respuesta = ficha_por_codigo_y_ordinal(code, ord_n)
                    send_and_log(session, user.id, from_number, respuesta)
                    return "ok", 200
                # si no válido, sigue al flujo normal

            # ============= 4) Consulta normal ================================
            # Guardamos los items para poder seleccionar por índice y paginar
            intent = intent or _parse_intent(text_norm)
            items = _search_programs(intent)
            st = {"last_query": text_norm, "page": 0, "items": items}
            STATE[from_number] = st

            log_interaction(
                session,
                user_id=user.id,
                direction="inbound",
                body=text,
                intent=intent,
                step="search",
                message_type=msg.get("type", "text"),
                wa_message_id=msg.get("id"),
            )

            # Render principal (página 1)
            respuesta = generar_respuesta(text, show_all=False, page=0, page_size=10)
            send_and_log(session, user.id, from_number, respuesta)
            return "ok", 200

    except Exception as e:
        log.exception(f"Error procesando webhook: {e}")
        return "error", 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
