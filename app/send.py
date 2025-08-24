import os
import requests
import logging

log = logging.getLogger(__name__)
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GRAPH_URL = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"

def send_whatsapp_message(to: str, body: str):
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body[:4000]}
    }
    r = requests.post(GRAPH_URL, headers=headers, json=payload, timeout=15)
    if r.status_code >= 300:
        log.error(f"Error enviando: {r.status_code} {r.text}")
    else:
        log.info(f"Mensaje enviado a {to}")
