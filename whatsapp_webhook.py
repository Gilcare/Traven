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

# Grab the secret keys and endpoints from environment variables
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")
AIDEX_CONNECT_BACKEND_URL = os.environ.get("AIDEX_CONNECT_BACKEND_URL", "https://onrender.com")


# 1. Secure endpoint that listens for internal AiDEX backend login notifications
@app.post("/aidex-events")
async def aidex_events(request: Request):
    if request.headers.get("X-API-Key") != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    payload = await request.json()
    
    if payload.get("event") == "aidex_connected":
        wa_id = payload.get("wa_id")
        # Trigger the instant WhatsApp confirmation when a user connects via OAuth web flow
        send_whatsapp_message(wa_id, "✅ Your AiDEX account is successfully connected to Travenhealth!")
        
    return {"ok": True}


# ─────────────────────────────────────────────
# Health check & Meta verification
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "whatsapp-poc"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge"))
    raise HTTPException(status_code=403, detail="Verification failed")


# ─────────────────────────────────────────────
# Receive WhatsApp messages (Clean Production)
# ─────────────────────────────────────────────

@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()
        
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        if "statuses" in value:
            return {"status": "status_update_acknowledged"}
            
        messages = value.get("messages")
        if not messages:
            return {"status": "ignored_non_message_event"}
            
        message = messages[0]
        sender = message.get("from") # This is the user's WhatsApp ID
        
        if message.get("type") == "text":
            text = message["text"]["body"].strip()
            print(f"📥 Message from {sender}: '{text}'", flush=True)
            
            # WORKFLOW A: User is sending a 6-digit confirmation OTP code
            if text.isdigit() and len(text) == 6:
                print(f"🔄 Processing headless verification code for {sender}...", flush=True)
                
                # Forward the code to your backend's endpoint inside routes.py
                verify_response = requests.post(
                    f"{AIDEX_CONNECT_BACKEND_URL}/aidex/verify-otp",
                    json={
                        "phone_number": sender, # Or look up their linked mobile if distinct
                        "otp_code": text,
                        "whatsapp_id": sender
                    },
                    timeout=10
                )
                
                res_data = verify_response.json()
                if verify_response.status_code == 200 and res_data.get("success"):
                    send_whatsapp_message(sender, "✅ Success! Your AiDEX CGM account is now paired directly over WhatsApp.")
                else:
                    error_msg = res_data.get("message", "Invalid or expired code.")
                    send_whatsapp_message(sender, f"❌ Authentication failed: {error_msg}\nPlease try again.")
            
            # WORKFLOW B: User explicitly asks to link or initializes with standard greeting
            else:
                onboarding_url = f"{AIDEX_CONNECT_BACKEND_URL}/aidex/connect/{sender}"
                
                reply = (
                    f"Welcome to Travenhealth! 👋\n\n"
                    f"To complete your setup, please securely connect your AiDEX CGM account via this link:\n"
                    f"{onboarding_url}\n\n"
                    f"💡 *Alternative Headless Option:* If you prefer to log in directly over text, simply reply with your 6-digit verification code once requested."
                )
                send_whatsapp_message(sender, reply)
                print(f"📤 Sent onboarding instructions to {sender}.", flush=True)

    except Exception as e:
        print(f"⚠️ Webhook processing warning: {str(e)}", flush=True)

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
        "text": {"body": text},
    }
    response = requests.post(GRAPH_API_URL, headers=headers, json=payload, timeout=10)
    print(f"WhatsApp API Status: {response.status_code}", flush=True)
    response.raise_for_status()
