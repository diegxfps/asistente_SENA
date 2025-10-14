import os
import time
import json
import logging
from typing import Tuple, Dict, Any, Optional

import requests

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GRAPH_API_VER = os.getenv("GRAPH_API_VER", "v20.0")

def _build_graph_url() -> str:
    """Construye la URL de envío para la versión y phone number id actuales."""
    if not PHONE_NUMBER_ID:
        raise RuntimeError("Falta WHATSAPP_PHONE_NUMBER_ID en variables de entorno")
    return f"https://graph.facebook.com/{GRAPH_API_VER}/{PHONE_NUMBER_ID}/messages"

def _auth_headers() -> Dict[str, str]:
    if not WHATSAPP_TOKEN:
        raise RuntimeError("Falta WHATSAPP_TOKEN en variables de entorno")
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

def _mask_phone(num: str) -> str:
    num = num or ""
    return num[:-4] + "****" if len(num) >= 4 else "****"

def send_whatsapp_message(to: str, body: str, timeout: int = 15, max_retries: int = 2) -> Tuple[bool, Dict[str, Any]]:
    """
    Envía un mensaje de texto por WhatsApp Cloud API.

    Retorna:
      (True, {"message_id": "wamid...","status_code": 200}) en éxito
      (False, {"status_code": <int>, "error": <str>, "response": <dict|str>}) en error
    """
    try:
        url = _build_graph_url()
        headers = _auth_headers()
    except Exception as e:
        log.error(f"[send] Config inválida: {e}")
        return False, {"status_code": 0, "error": str(e)}

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": (body or "")[:4000]},
    }

    # Retries simples para 5xx
    attempt = 0
    last_err: Optional[Dict[str, Any]] = None
    while attempt <= max_retries:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            sc = resp.status_code

            if sc < 300:
                try:
                    data = resp.json()
                except Exception:
                    data = {}
                # WhatsApp suele devolver message IDs en entry/changes o en "messages"
                message_id = None
                try:
                    message_id = data["messages"][0]["id"]
                except Exception:
                    pass
                if not message_id:
                    # intenta extraer de la respuesta cruda si cambia el shape
                    try:
                        entry = data["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
                        message_id = entry
                    except Exception:
                        message_id = None

                log.info(f"[send] OK -> {_mask_phone(to)} id={message_id or 'n/a'}")
                return True, {"message_id": message_id, "status_code": sc, "raw": data}

            # Error HTTP
            txt = None
            try:
                txt = resp.text
                j = resp.json() if "application/json" in resp.headers.get("Content-Type","") else None
            except Exception:
                j = None

            err = {"status_code": sc, "error": "http_error", "response": j or txt}
            last_err = err

            if 500 <= sc < 600 and attempt < max_retries:
                wait = (attempt + 1) * 0.75
                log.warning(f"[send] 5xx {sc}, retry {attempt+1}/{max_retries} en {wait:.2f}s …")
                time.sleep(wait)
                attempt += 1
                continue

            log.error(f"[send] Error {sc} -> {_mask_phone(to)} | resp={txt[:300] if isinstance(txt,str) else str(j)[:300]}")
            return False, err

        except requests.Timeout:
            err = {"status_code": 0, "error": "timeout"}
            last_err = err
            if attempt < max_retries:
                wait = (attempt + 1) * 0.75
                log.warning(f"[send] Timeout, retry {attempt+1}/{max_retries} en {wait:.2f}s …")
                time.sleep(wait)
                attempt += 1
                continue
            log.error("[send] Timeout definitivo")
            return False, err
        except Exception as e:
            err = {"status_code": 0, "error": f"exception: {e.__class__.__name__}", "detail": str(e)}
            last_err = err
            log.exception("[send] Excepción enviando")
            return False, err

    # si salimos del bucle por alguna razón, devuelve último error conocido
    return False, (last_err or {"status_code": 0, "error": "unknown"})
