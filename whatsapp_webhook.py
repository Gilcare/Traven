import os
import requests

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from aidex_connect.database_logic import fetch_stored_token

app = FastAPI()

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

GRAPH_API_URL = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"



# 1. Grab the secret key from the environment variables
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")

# 2. Add the secure endpoint that listens for AiDEX events
@app.post("/aidex-events")
async def aidex_events(request: Request):
    # Security check: Make sure the incoming request has the matching key
    if request.headers.get("X-API-Key") != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    payload = await request.json()
    
    # Trigger the instant WhatsApp confirmation when a user connects
    if payload.get("event") == "aidex_connected":
        wa_id = payload.get("wa_id")
        
        # TODO: Add your existing WhatsApp helper function below to message the user.
        # Example: send_whatsapp_message(wa_id, "✅ Your AiDEX account is successfully connected!")
        
    return {"ok": True}



# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "whatsapp-poc"}


# ─────────────────────────────────────────────
# Meta webhook verification
# ─────────────────────────────────────────────

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge)

    raise HTTPException(status_code=403, detail="Verification failed")



# ─────────────────────────────────────────────
# Receive WhatsApp messages (Clean Production)
# ─────────────────────────────────────────────

@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()
        
        # Safely pull out entries
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        # Log status updates silently, keep the log terminal clean
        if "statuses" in value:
            return {"status": "status_update_acknowledged"}
            
        messages = value.get("messages")
        if not messages:
            return {"status": "ignored_non_message_event"}
            
        message = messages[0]
        sender = message.get("from")
        
        # Route inbound workflows
        if message.get("type") == "text":
            text = message["text"]["body"]
            print(f"📥 Message from {sender}: '{text}'", flush=True)
            
            # Dynamic onboarding payload for ://cgm.com
            onboarding_url = f"https://://cgm.com/auth?whatsapp_id={sender}"
            
            reply = (
                f"Welcome to Travenhealth! 👋\n\n"
                f"To complete your setup, please securely connect your AiDEX CGM account via this link:\n"
                f"{onboarding_url}"
            )
            
            # Fire response via outbox channel
            send_whatsapp_message(sender, reply)
            print(f"📤 Sent onboarding link to {sender}.", flush=True)

    except Exception as e:
        print(f"⚠️ Webhook processing warning: {str(e)}", flush=True)

    # Always exit 200 OK so Meta leaves the pipeline active
    return {"status": "ok"}




# ─────────────────────────────────────────────
# Send WhatsApp message
# ─────────────────────────────────────────────

def send_whatsapp_message(to: str, text: str):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": text
        },
    }

    response = requests.post(
        GRAPH_API_URL,
        headers=headers,
        json=payload,
        timeout=10,
    )

    print("WhatsApp API response:")
    print(response.status_code)
    print(response.text)

    response.raise_for_status()
