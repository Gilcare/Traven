"""
Traven <> AiDEX OAuth Connect Service  (PoC)
=============================================
Deploy on Render as a Web Service. Uses MongoDB (Atlas) for storage.

Flow:
  1. WhatsApp bot sends user:  https://<your-app>/connect?wa_id=<whatsapp_id>
  2. This app redirects to AiDEX login (state binds login to that wa_id, CSRF-safe)
  3. AiDEX redirects back to /callback?code=...&state=...   <-- REGISTER THIS URL
  4. We exchange code -> tokens (camelCase API), encrypt, store in MongoDB
  5. Success page with "Return to WhatsApp" (wa.me deep link) + webhook to bot backend

AiDEX endpoints (from docs):
  authorize : GET  {base}/v1/oauth2/authorize?clientId=..&responseType=code&state=..
  token     : POST {base}/v1/oauth2/token   (form: clientId, clientSecret, code, grantType=authorization_code)
  refresh   : POST {base}/v1/oauth2/token   (form: refreshToken, grantType=refresh_token)
  readings  : GET  {base}/v1/user/sensor-glucose?startTime=..&endDate=..
              header: authorization: {accessToken}   (raw token, no "Bearer" per docs)
NOTE: AiDEX auth codes expire in 1 min and are single-use.
      Refresh tokens are single-use too -> always save the NEW refreshToken.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from cryptography.fernet import Fernet
from pymongo import MongoClient, ASCENDING

# ------------------------------------------------------------------ config
AIDEX_BASE_URL  = os.environ.get("AIDEX_BASE_URL", "https://aidexapi.microtechmd.com")
AIDEX_AUTH_URL  = f"{AIDEX_BASE_URL}/v1/oauth2/authorize"
AIDEX_TOKEN_URL = f"{AIDEX_BASE_URL}/v1/oauth2/token"
AIDEX_GLUCOSE_URL = f"{AIDEX_BASE_URL}/v1/user/sensor-glucose"

CLIENT_ID     = os.environ["AIDEX_CLIENT_ID"]
CLIENT_SECRET = os.environ["AIDEX_CLIENT_SECRET"]

BASE_URL     = os.environ.get("BASE_URL", "http://localhost:8000")
REDIRECT_URI = f"{BASE_URL}/callback"          # <-- register EXACTLY this in AiDEX portal

MONGO_URI = os.environ["MONGO_URI"]            # e.g. mongodb+srv://user:pass@cluster0.x.mongodb.net/traven
DB_NAME   = os.environ.get("MONGO_DB", "traven")

TRAVEN_WEBHOOK_URL = os.environ.get("TRAVEN_WEBHOOK_URL", "")
INTERNAL_API_KEY   = os.environ.get("INTERNAL_API_KEY", secrets.token_hex(16))

_token_key = os.environ.get("TOKEN_KEY", "")
FERNET = Fernet(_token_key.encode() if _token_key else Fernet.generate_key())
# Generate a stable key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

STATE_TTL_MINUTES = 10

app = FastAPI(title="Traven AiDEX Connect (PoC)")

# ------------------------------------------------------------------ storage (MongoDB)
mongo = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
db = mongo[DB_NAME]
states_col = db["oauth_states"]
users_col  = db["users"]

states_col.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)  # TTL cleanup
users_col.create_index("wa_id", unique=True)

# ------------------------------------------------------------------ helpers
def now() -> datetime:
    return datetime.now(timezone.utc)

def new_state(wa_id: str) -> str:
    state = secrets.token_urlsafe(24)
    states_col.delete_many({"expires_at": {"$lt": now()}})          # lazy cleanup
    states_col.insert_one({
        "state": state,
        "wa_id": wa_id,
        "expires_at": now() + timedelta(minutes=STATE_TTL_MINUTES),
    })
    return state

def pop_state(state: str):
    """One-time-use state -> wa_id, or None if invalid/expired."""
    doc = states_col.find_one_and_delete({"state": state})
    if not doc or doc["expires_at"] < now():
        return None
    return doc["wa_id"]

def save_tokens(wa_id: str, token_resp: dict):
    expires_at = now() + timedelta(seconds=int(token_resp.get("expiresIn", 86400)))
    users_col.update_one(
        {"wa_id": wa_id},
        {"$set": {
            "access_token_enc":  FERNET.encrypt(token_resp["accessToken"].encode()).decode(),
            "token_expires_at":  expires_at,
            "updated_at":        now(),
            # refreshToken is single-use -> always overwrite with the newest one
            **({"refresh_token_enc": FERNET.encrypt(token_resp["refreshToken"].encode()).decode()}
               if token_resp.get("refreshToken") else {}),
        }},
        upsert=True,
    )

def get_user(wa_id: str):
    return users_col.find_one({"wa_id": wa_id})

def mark_disconnected(wa_id: str):
    users_col.delete_one({"wa_id": wa_id})

async def aidex_token_request(data: dict) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(AIDEX_TOKEN_URL, data=data,
                              headers={"Content-Type": "application/x-www-form-urlencoded",
                                       "cache-control": "no-cache"})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or "error" in body:
        raise HTTPException(status_code=502, detail=f"AiDEX token error: {body.get('error', r.text)}")
    return body

async def refresh_access_token(wa_id: str) -> str:
    """Return a valid access token, refreshing if needed. AiDEX style (see docs)."""
    user = get_user(wa_id)
    if not user:
        raise HTTPException(404, "User not connected")
    if user["token_expires_at"] > now() + timedelta(minutes=1):
        return FERNET.decrypt(user["access_token_enc"].encode()).decode()
    if not user.get("refresh_token_enc"):
        mark_disconnected(wa_id)
        raise HTTPException(401, "Token expired, no refresh token -> user must reconnect")
    rt = FERNET.decrypt(user["refresh_token_enc"].encode()).decode()
    try:
        # Per docs: refresh sends ONLY refreshToken + grantType (no client creds)
        resp = await aidex_token_request({"refreshToken": rt, "grantType": "refresh_token"})
    except HTTPException:
        mark_disconnected(wa_id)   # refreshToken revoked/used/expired -> re-auth via Step 1
        raise HTTPException(401, "Refresh failed (revoked or expired) -> user must reconnect")
    save_tokens(wa_id, resp)
    return resp["accessToken"]

async def notify_traven(wa_id: str, event: str, extra: dict | None = None):
    if not TRAVEN_WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(TRAVEN_WEBHOOK_URL,
                              json={"event": event, "wa_id": wa_id, **(extra or {})},
                              headers={"X-API-Key": INTERNAL_API_KEY})
    except Exception:
        pass  # never break the OAuth flow over a webhook hiccup

# ------------------------------------------------------------------ routes
@app.get("/health")
def health():
    mongo.admin.command("ping")
    return {"ok": True, "db": "mongodb", "aidex_base": AIDEX_BASE_URL}

@app.get("/connect")
def connect(wa_id: str):
    """WhatsApp bot links users here -> 302 to AiDEX login page."""
    if not wa_id:
        raise HTTPException(400, "Missing wa_id")
    state = new_state(wa_id)
    url = (f"{AIDEX_AUTH_URL}?clientId={CLIENT_ID}"
           f"&responseType=code&state={state}")
    return RedirectResponse(url)

@app.get("/callback")
async def callback(code: str | None = None, state: str | None = None,
                   error: str | None = None):
    """This IS the Redirect URL registered with AiDEX."""
    if error:
        return HTMLResponse(page("Authorization denied", f"AiDEX returned: {error}", ok=False))
    if not code or not state:
        raise HTTPException(400, "Missing code or state")

    wa_id = pop_state(state)
    if not wa_id:
        return HTMLResponse(page("Link expired",
                                 "Please go back to WhatsApp and tap the connect link again.",
                                 ok=False), status_code=400)

    token_resp = await aidex_token_request({
        "clientId": CLIENT_ID,
        "clientSecret": CLIENT_SECRET,
        "code": code,
        "grantType": "authorization_code",
    })
    save_tokens(wa_id, token_resp)
    await notify_traven(wa_id, "aidex_connected")

    back = f"https://wa.me/{wa_id.lstrip('+')}?text=Connected%20my%20AiDEX%20CGM%20%E2%9C%85"
    return HTMLResponse(page(
        "You're connected!",
        "Traven can now read your AiDEX glucose data. Tap below to return to WhatsApp.",
        ok=True, button_text="Return to WhatsApp", button_url=back))

@app.get("/readings/{wa_id}")
async def readings(wa_id: str, request: Request,
                   startTime: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$"),
                   endDate: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")):
    """INTERNAL (bot backend only): pull CGM readings. Auto-refreshes token. Format: 2026-09-09T13:00:00"""
    if request.headers.get("X-API-Key") != INTERNAL_API_KEY:
        raise HTTPException(401, "Unauthorized")
    token = await refresh_access_token(wa_id)
    if not endDate:
        endDate = now().strftime("%Y-%m-%dT%H:%M:%S")
    if not startTime:
        startTime = (now() - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(AIDEX_GLUCOSE_URL,
                             params={"startTime": startTime, "endDate": endDate},
                             headers={"authorization": token})   # raw token, per AiDEX docs
    if r.status_code == 401:
        raise HTTPException(401, "AiDEX access rejected -> ask user to reconnect")
    r.raise_for_status()
    return {"wa_id": wa_id, "window": {"startTime": startTime, "endDate": endDate},
            "aidex_response": r.json()}

@app.post("/disconnect/{wa_id}")
async def disconnect(wa_id: str, request: Request):
    """INTERNAL: drop a user's tokens (e.g. user asks Traven to disconnect)."""
    if request.headers.get("X-API-Key") != INTERNAL_API_KEY:
        raise HTTPException(401, "Unauthorized")
    mark_disconnected(wa_id)
    await notify_traven(wa_id, "aidex_disconnected")
    return {"ok": True}

# ------------------------------------------------------------------ page template
def page(title: str, body: str, ok: bool, button_text: str | None = None,
         button_url: str | None = None) -> str:
    color = "#22c55e" if ok else "#ef4444"
    btn = (f'<a href="{button_url}" style="display:inline-block;margin-top:24px;'
           f'padding:14px 28px;background:#22c55e;color:#fff;border-radius:10px;'
           f'text-decoration:none;font-weight:600;">{button_text}</a>') if button_url else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Traven</title></head>
<body style="margin:0;font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center;">
<div style="max-width:420px;padding:40px 24px;">
<div style="width:64px;height:64px;border-radius:50%;background:{color};margin:0 auto 20px;
display:flex;align-items:center;justify-content:center;font-size:32px;">{'✓' if ok else '✕'}</div>
<h1 style="font-size:24px;margin:0 0 10px;">{title}</h1>
<p style="color:#94a3b8;line-height:1.5;">{body}</p>{btn}
</div></body></html>"""
