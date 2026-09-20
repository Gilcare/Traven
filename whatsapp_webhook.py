import os
import requests
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from pymongo import MongoClient
from huggingface_hub import InferenceClient

app = FastAPI()

# ─────────────────────────────────────────────────────────────
# CONFIGURATION & CONNECTIONS
# ─────────────────────────────────────────────────────────────
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
#GRAPH_API_URL = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
GRAPH_API_URL = f"https://graph.facebook.com/v25.0/1322440827617778/messages"


INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")
AIDEX_CONNECT_BACKEND_URL = os.environ.get("AIDEX_CONNECT_BACKEND_URL")
STREAMLIT_DASHBOARD_URL = os.environ.get("STREAMLIT_DASHBOARD_URL")

# MongoDB Connections
MONGO_URI = os.environ["MONGO_URI"]
DB_NAME = os.environ.get("MONGO_DB", "traven")
mongo_client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
db = mongo_client[DB_NAME]
users_col = db["users"]

# Initialize Hugging Face Serverless Client
# Make sure 'HF_TOKEN' is set in your Render environment variables panel
hf_client = InferenceClient(api_key=os.environ["HF_TOKEN"])

# Qwen instruction tailored exactly to append the link anchor
ROUTER_SYSTEM_INSTRUCTION = (
    "You are the Travenhealth WhatsApp Router. Your single mission is to stop intensive health chats on WhatsApp to save API costs. "
    "The user is ALREADY successfully onboarded. Acknowledge what they are asking about in exactly ONE friendly sentence "
    "(e.g., 'I can definitely help you look at that sudden glucose trend!'). "
    "Then, strictly append the dynamic tag '[STREAMLIT_LINK]' right after it. Do not answer their health or data questions here."
)

# ─────────────────────────────────────────────────────────────
# META VERIFICATION & SYSTEM HANDSHAKES
# ─────────────────────────────────────────────────────────────
@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok", "service": "whatsapp-poc"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge"))
    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/aidex-events")
async def aidex_events(request: Request):
    if request.headers.get("X-API-Key") != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    payload = await request.json()
    if payload.get("event") == "aidex_connected":
        wa_id = payload.get("wa_id")
        send_whatsapp_message(wa_id, "✅ Your AiDEX account is successfully connected to Travenhealth!")
        
    return {"ok": True}

# ─────────────────────────────────────────────────────────────
# THE INTELLIGENT WEBHOOK ROUTER (Qwen Powered)
# ─────────────────────────────────────────────────────────────
@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        if "statuses" in value: 
            return {"status": "ok"}
        messages = value.get("messages")
        if not messages: 
            return {"status": "ignored"}
            
        message = messages[0]
        sender = message.get("from")
        
        if message.get("type") == "text":
            text = message["text"]["body"].strip()
            existing_user = users_col.find_one({"wa_id": sender})
            
            # PATHWAY 1: Capturing the 6-Digit OTP code
            if text.isdigit() and len(text) == 6:
                verify_response = requests.post(
                    f"{AIDEX_CONNECT_BACKEND_URL}/aidex/verify-otp",
                    json={"phone_number": sender, "otp_code": text, "whatsapp_id": sender},
                    timeout=10
                )
                res_data = verify_response.json()
                if verify_response.status_code == 200 and res_data.get("success"):
                    send_whatsapp_message(sender, "✅ Success! Your AiDEX CGM account is now paired directly over WhatsApp.")
                else:
                    error_msg = res_data.get("message", "Invalid or expired code.")
                    send_whatsapp_message(sender, f"❌ Authentication failed: {error_msg}\nPlease try again.")
            
            # PATHWAY 2: The Initial Greeting / Onboarding Trigger
            elif text.lower() in ["hi", "hello", "hey"]:
                if existing_user:
                    reply = "Welcome back to Travenhealth! 👋\nYour AiDEX CGM sync is live. How can I help you check your health metrics today?"
                    send_whatsapp_message(sender, reply)
                else:
                    # NEW USER ONBOARDING WORKFLOW (Bypassing Template Mismatch)
                    print(f"✨ New user {sender} detected. Sending plain text onboarding instructions...", flush=True)
                    
                    onboarding_url = f"{AIDEX_CONNECT_BACKEND_URL}/aidex/connect/{sender}"
                    
                    reply = (
                        f"Welcome to Travenhealth! 👋🏼\n\n"
                        f"Great! To sync your glucose numbers to your phone, please securely pair your AiDEX CGM account via this button link:\n\n"
                        f"👉 {onboarding_url}"
                    )
                    
                    send_whatsapp_message(sender, reply)
                    #send_whatsapp_message(sender, "Welcome to Travenhealth! 👋🏼")
                    #send_whatsapp_approved_template(sender, template_name="connect_aidex_cgm")
            
            # PATHWAY 3: Conversational Offloading to Streamlit (Qwen Cloud Engine)
            else:
                if existing_user:
                    print(f"🧠 Routing intensive conversation from {sender} via Qwen Hub API...", flush=True)
                    
                    # Generate response payload matching Qwen instruction format
                    response = hf_client.chat.completions.create(
                        model="Qwen/Qwen2.5-0.5B-Instruct",
                        messages=[
                            {"role": "system", "content": ROUTER_SYSTEM_INSTRUCTION},
                            {"role": "user", "content": text}
                        ],
                        max_tokens=150,
                        temperature=0.3
                    )
                    
                    ai_response_text = response.choices[0].message.content or ""
                    
                    # Create the auto-login tracking link
                    personal_link = f"{STREAMLIT_DASHBOARD_URL}?wa_id={sender}"
                    
                    # Replace the anchor block with the real hyperlinked text card
                    final_reply = ai_response_text.replace(
                        "[STREAMLIT_LINK]", 
                        f"\n\n👉 Click here to continue our chat for free and view your live interactive glucose charts:\n{personal_link}"
                    )
                    
                    send_whatsapp_message(sender, final_reply)
                else:
                    send_whatsapp_message(sender, "To begin tracking your health data, type 'Hi' to start your setup process.")

    except Exception as e:
        print(f"⚠️ Webhook error: {str(e)}", flush=True)

    return {"status": "ok"}




def send_whatsapp_message(to: str, text: str):
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    response = requests.post(GRAPH_API_URL, json=payload, headers=headers, timeout=10)
    response.raise_for_status()

def send_whatsapp_approved_template(to: str, template_name: str):
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {"name": template_name, "language": {"code": "en_US"}}
    }
    response = requests.post(GRAPH_API_URL, json=payload, headers=headers, timeout=10)
    response.raise_for_status()



# ─────────────────────────────────────────────────────────────
# OUTBOX CHANNELS (WhatsApp Utilities)
# ─────────────────────────────────────────────────────────────
