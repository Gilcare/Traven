import os
import requests
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Router specifically for the Aidex connection endpoints
router = APIRouter(prefix="/aidex")

# Point Jinja2 to look directly inside aidex-connect directory for the HTML file
templates = Jinja2Templates(directory="aidex_connect")

# Base URL for the external AiDEX system API
AIDEX_BASE_URL = "https://microtechmd.com"

# Data models to process JSON payloads sent by your system
class TriggerOTPRequest(BaseModel):
    phone_number: str

class VerifyOTPRequest(BaseModel):
    phone_number: str
    otp_code: str
    whatsapp_id: str

# ─────────────────────────────────────────────────────────────
# 1. YOUR EXISTING FRONTEND & CALLBACK ROUTES
# ─────────────────────────────────────────────────────────────

# This creates the frontend webpage route: https://onrender.com{user_token}
@router.get("/connect/{user_token}", response_class=HTMLResponse)
async def serve_connect_page(request: Request, user_token: str):
    # Pass the user's phone token to the HTML template so the blue button can use it
    return templates.TemplateResponse("connect.html", {"request": request, "user_token": user_token})

# This creates your final landing/handshake route: https://onrender.com
@router.get("/callback")
async def aidex_callback(code: str, state: str):
    # 'state' contains the user_token you passed earlier.
    # 'code' is what you will swap for an access token to read their CGM metrics.
    return {"status": "Successfully connected your CGM to Travenhealth! You can close this screen."}


# ─────────────────────────────────────────────────────────────
# 2. NEW AIDEX HEADLESS API BRIDGE ROUTES
# ─────────────────────────────────────────────────────────────

# Step A: Mimic the official app request to trigger a real network SMS verification code
@router.post("/request-otp")
async def trigger_aidex_otp(payload: TriggerOTPRequest):
    try:
        response = requests.post(
            f"{AIDEX_BASE_URL}/auth/send-code",
            json={"phone": payload.phone_number, "type": "login"},
            timeout=10
        )
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="AiDEX rejected phone number validation")
        return {"success": True, "message": "OTP successfully requested from network"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Step B: Intercept the code the user received and exchanges it for a persistent token
@router.post("/verify-otp")
async def verify_aidex_otp(payload: VerifyOTPRequest):
    try:
        response = requests.post(
            f"{AIDEX_BASE_URL}/auth/login-by-code",
            json={"phone": payload.phone_number, "code": payload.otp_code},
            timeout=10
        )
        if response.status_code != 200:
            return {"success": False, "message": "Invalid or expired OTP code"}
            
        auth_data = response.json()
        access_token = auth_data.get("token")
        
        # TODO: Save the mapping of payload.whatsapp_id -> access_token in your database
        # save_token_to_db(payload.whatsapp_id, access_token)
        
        return {
            "success": True, 
            "message": "Account securely authorized",
            "connected_account": payload.phone_number
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
