import os
import json
import secrets
import requests

from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

VERIFY_TOKEN     = os.getenv("WHATSAPP_VERIFY_TOKEN")
ACCESS_TOKEN     = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID  = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
APP_BASE_URL     = os.getenv("APP_BASE_URL")  # e.g. https://aia-api.onrender.com

if not APP_BASE_URL:
    raise ValueError("APP_BASE_URL environment variable is required")

GRAPH_API_URL = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"

# ─────────────────────────────────────────────
# PoC Storage (JSON files)
# NOTE: Render free tier has an ephemeral filesystem.
# Files persist between requests but are wiped on deploy/restart.
# For production, swap this for MongoDB/Postgres.
# ─────────────────────────────────────────────

USERS_FILE  = "users.json"
TOKENS_FILE = "oauth_tokens.json"

for f in [USERS_FILE, TOKENS_FILE]:
    if not os.path.exists(f):
        with open(f, "w") as fh:
            json.dump({}, fh)

def _load(path: str):
    with open(path, "r") as fh:
        return json.load(fh)

def _save(path: str, data: dict):
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2, default=str)

# ─────────────────────────────────────────────
# WhatsApp Send Helpers
# ─────────────────────────────────────────────

def send_text(to: str, text: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    _post_whatsapp(payload)

def send_buttons(to: str, text: str, buttons: list):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons
                ]
            },
        },
    }
    _post_whatsapp(payload)

def send_list(to: str, text: str, button_text: str, sections: list):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": button_text,
                "sections": sections,
            },
        },
    }
    _post_whatsapp(payload)

def _post_whatsapp(payload: dict):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(GRAPH_API_URL, headers=headers, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"WhatsApp send error: {e}")

# ─────────────────────────────────────────────
# User & Token Storage
# ─────────────────────────────────────────────

def get_or_create_user(whatsapp_id: str):
    users = _load(USERS_FILE)

    if whatsapp_id not in users:
        users[whatsapp_id] = {
            "whatsapp_id": whatsapp_id,
            "phone": whatsapp_id,
            "name": None,
            "step": "welcome",
            "role": None,
            "patient_phone": None,
            "diabetes_type": None,
            "sensor": None,
            "consent": False,
            "created_at": datetime.utcnow().isoformat(),
        }
        _save(USERS_FILE, users)

        send_buttons(
            whatsapp_id,
            "Welcome to Traven 🌿\n\nI help you understand your blood sugar over time — across any sensor you use.",
            [{"id": "get_started", "title": "Get Started"}],
        )
        users[whatsapp_id]["step"] = "awaiting_consent"
        _save(USERS_FILE, users)

    return users[whatsapp_id]

def update_user(whatsapp_id: str, updates: dict):
    users = _load(USERS_FILE)
    if whatsapp_id in users:
        users[whatsapp_id].update(updates)
        _save(USERS_FILE, users)

def store_oauth_state(whatsapp_id: str) -> str:
    state = secrets.token_urlsafe(16)
    tokens = _load(TOKENS_FILE)
    tokens[state] = {
        "whatsapp_id": whatsapp_id,
        "expires": (datetime.utcnow() + timedelta(minutes=10)).isoformat(),
    }
    _save(TOKENS_FILE, tokens)
    return state

def consume_oauth_state(state: str) -> dict | None:
    tokens = _load(TOKENS_FILE)
    data = tokens.get(state)
    if not data:
        return None

    expires = datetime.fromisoformat(data["expires"])
    if datetime.utcnow() > expires:
        return None

    del tokens[state]
    _save(TOKENS_FILE, tokens)
    return data

# ─────────────────────────────────────────────
# Onboarding Prompts
# ─────────────────────────────────────────────

def ask_diabetes_type(phone: str):
    send_list(
        phone,
        "What type of diabetes do you have?",
        "Select",
        [{
            "title": "Diabetes Type",
            "rows": [
                {"id": "type_1", "title": "Type 1"},
                {"id": "type_2", "title": "Type 2"},
                {"id": "prediabetes", "title": "Prediabetes / Gestational"},
                {"id": "not_sure", "title": "Not Sure"},
            ]
        }]
    )

def ask_sensor_type(phone: str):
    send_list(
        phone,
        "What sensor are you currently using?",
        "Select",
        [{
            "title": "CGM Sensor",
            "rows": [
                {"id": "aidex", "title": "Aidex (LinX)"},
                {"id": "sinocare", "title": "Sinocare iCare"},
                {"id": "freestyle", "title": "FreeStyle Libre"},
                {"id": "other", "title": "Other"},
                {"id": "none_yet", "title": "None Yet"},
            ]
        }]
    )

def send_aidex_oauth_link(phone: str):
    state = store_oauth_state(phone)
    link = f"{APP_BASE_URL}/static/connect-aidex.html?t={state}"

    send_buttons(
        phone,
        "Let's connect your Aidex sensor.\n\n🔐 This is secure. You will use your existing Aidex login.\n\nTap below — it opens your browser for 30 seconds, then come back here.",
        [{"id": "connect_aidex", "title": "🔗 Connect Aidex"}],
    )
    send_text(phone, f"Or use this link: {link}")

# ─────────────────────────────────────────────
# Onboarding State Machine
# ─────────────────────────────────────────────

def handle_onboarding(user: dict, reply_id: str, text_body: str):
    phone = user["whatsapp_id"]
    step = user.get("step", "welcome")

    if step == "awaiting_consent":
        if reply_id == "get_started":
            send_buttons(
                phone,
                "Before we begin:\n\n🔒 Your data belongs to you. Delete it anytime.\n📋 I provide insights, not medical advice.\n🌍 Stored securely.",
                [
                    {"id": "agree", "title": "✅ I Agree"},
                    {"id": "read_policy", "title": "📖 Privacy Policy"},
                ],
            )
            update_user(phone, {"step": "awaiting_role"})
        else:
            send_text(phone, "Please tap *Get Started* above to begin.")

    elif step == "awaiting_role":
        if reply_id == "agree":
            send_buttons(
                phone,
                "Is this your own phone, or are you helping someone set up Aia?",
                [
                    {"id": "my_phone", "title": "📱 My Phone"},
                    {"id": "helping_family", "title": "👨‍👩‍👧 Helping Family"},
                ],
            )
            update_user(phone, {"step": "awaiting_role_select"})
        else:
            send_text(phone, "Please tap *I Agree* to continue. This keeps your data safe.")

    elif step == "awaiting_role_select":
        if reply_id == "my_phone":
            update_user(phone, {"role": "patient", "step": "awaiting_diabetes"})
            ask_diabetes_type(phone)

        elif reply_id == "helping_family":
            update_user(phone, {"role": "helper", "step": "awaiting_helper_phone"})
            send_text(phone, "What is the patient's phone number? (Include country code, e.g. 2348012345678)")

        else:
            send_text(phone, "Please select an option above.")

    elif step == "awaiting_helper_phone":
        if text_body:
            update_user(phone, {"patient_phone": text_body, "step": "awaiting_diabetes"})
            ask_diabetes_type(phone)
        else:
            send_text(phone, "Please type the patient's phone number with country code.")

    elif step == "awaiting_diabetes":
        if reply_id in ("type_1", "type_2", "prediabetes", "not_sure"):
            update_user(phone, {"diabetes_type": reply_id, "step": "awaiting_sensor"})
            ask_sensor_type(phone)
        else:
            send_text(phone, "Please select your diabetes type from the list above.")

    elif step == "awaiting_sensor":
        if reply_id in ("aidex", "sinocare", "freestyle", "other", "none_yet"):
            update_user(phone, {"sensor": reply_id})

            if reply_id == "aidex":
                send_aidex_oauth_link(phone)
                update_user(phone, {"step": "oauth_pending"})
            else:
                send_text(
                    phone,
                    "No problem. I'll help you track manually until you get a sensor. Send me photos of your meals anytime! 📸"
                )
                update_user(phone, {"step": "onboarded"})
        else:
            send_text(phone, "Please select your current sensor from the list above.")

    elif step == "oauth_pending":
        if text_body and "help" in text_body.lower():
            send_aidex_oauth_link(phone)
        else:
            send_text(phone, "I'm waiting for your Aidex connection. Type HELP to resend the link.")

    elif step == "onboarded":
        if text_body:
            send_text(
                phone,
                f"You said: {text_body}\n\nI'm learning more about you every day. "
                "Your daily glucose summary will arrive at 8 AM. 🌅"
            )

# ─────────────────────────────────────────────
# FastAPI Routes
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "aia-whatsapp-poc"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()
    print("Incoming webhook:")
    print(data)

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        messages = value.get("messages")

        if not messages:
            return {"status": "ignored"}

        message = messages[0]
        sender = message["from"]
        message_type = message["type"]

        reply_id = ""
        text_body = ""

        if message_type == "text":
            text_body = message["text"]["body"]

        elif message_type == "interactive":
            interactive = message["interactive"]
            if "button_reply" in interactive:
                reply_id = interactive["button_reply"]["id"]
            elif "list_reply" in interactive:
                reply_id = interactive["list_reply"]["id"]

        elif message_type == "image":
            send_text(sender, "📸 Photo received! I'll analyze this once my AI vision is online. For now, I've saved it to your log.")
            return {"status": "ok"}

        else:
            return {"status": "ignored", "reason": f"unhandled type: {message_type}"}

        print(f"From {sender} | step: {get_or_create_user(sender).get('step')} | reply_id: {reply_id} | text: {text_body}")

        user = get_or_create_user(sender)
        handle_onboarding(user, reply_id, text_body)

    except (KeyError, IndexError, TypeError) as e:
        print(f"Could not parse webhook: {e}")

    return {"status": "ok"}

@app.post("/api/oauth/aidex/callback")
async def aidex_callback(request: Request):
    data = await request.json()
    code = data.get("code")
    state = data.get("state")

    token_data = consume_oauth_state(state)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired session")

    whatsapp_id = token_data["whatsapp_id"]
    print(f"Aidex callback for {whatsapp_id} with code: {code}")

    update_user(whatsapp_id, {
        "step": "onboarded",
        "aidex_connected_at": datetime.utcnow().isoformat(),
    })

    send_text(
        whatsapp_id,
        "✅ Your Aidex sensor is connected!\n\n"
        "I'll send you a summary every morning at 8 AM. "
        "You can also send me photos of your meals — just attach them like any WhatsApp photo."
    )

    return {"success": True}

# ─────────────────────────────────────────────
# Static files (PWA pages for OAuth bridge)
# ─────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")


