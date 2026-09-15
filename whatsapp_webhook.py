import os
import requests

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

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
# Receive WhatsApp messages
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# Receive WhatsApp messages (Diagnostic Version)
# ─────────────────────────────────────────────

@app.post("/webhook")
async def receive_webhook(request: Request):
    # FORCE LOGGING: Print to standard output instantly before any parsing
    print("!!! WEBHOOK INSTANTLY TRIGGERED !!!", flush=True)
    
    # Capture the raw text body to prevent silent framework errors
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8")
    print(f"RAW BODY RECEIVED: {body_text}", flush=True)

    try:
        data = await request.json()
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        messages = value.get("messages")

        if not messages:
            print("Status: Ignored (Not a message event)", flush=True)
            return {"status": "ignored"}

        message = messages[0]
        sender = message["from"]
        message_type = message["type"]

        if message_type != "text":
            print(f"Status: Ignored (Message type is {message_type})", flush=True)
            return {"status": "ignored", "reason": "not a text message"}

        text = message["text"]["body"]
        print(f"Parsed Message from {sender}: {text}", flush=True)

        # Send response back
        reply = f"You said: {text}"
        send_whatsapp_message(sender, reply)

    except Exception as e:
        # Catch absolutely every parsing error so the request returns a 200 to Meta
        print(f"!!! CRITICAL PARSING ERROR !!!: {str(e)}", flush=True)

    # Always return a 200 OK so Meta doesn't pause your webhook
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
