import os
import requests
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone

# Import the existing DB instance and encryption tool from your main file
from main import users_col, FERNET

# Create a router specifically for the Aidex connection endpoints
# Note: folder name updated to "aidex_connect" to match your GitHub directory
router = APIRouter(prefix="/aidex")
templates = Jinja2Templates(directory="aidex_connect")

AIDEX_BASE_URL = "https://microtechmd.com"

class TriggerOTPRequest(BaseModel):
    phone_number: str

class VerifyOTPRequest(BaseModel):
    phone_number: str
    otp_code: str
    whatsapp_id: str

# ─────────────────────────────────────────────────────────────
# 1. YOUR EXISTING FRONTEND & CALLBACK ROUTES
# ─────────────────────────────────────────────────────────────

@router.get("/connect/{user_token}", response_class=HTMLResponse)
async def serve_connect_page(request: Request, user_token: str):
    return templates.TemplateResponse("connect.html", {"request": request, "user_token": user_token})

@router.get("/callback")
async def aidex_callback(code: str, state: str):
    return {"status": "Successfully connected your CGM to Travenhealth! You can close this screen."}


# ─────────────────────────────────────────────────────────────
# 2. NEW AIDEX HEADLESS API BRIDGE ROUTES (With Database Logic)
# ─────────────────────────────────────────────────────────────

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
        
        if not access_token:
            return {"success": False, "message": "Authentication succeeded but no token returned"}

        # Calculate expiration window (Default to 24 hours if not provided by direct login API)
        expires_in_seconds = int(auth_data.get("expiresIn", 86400))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)

        # Encrypt the token using the existing Fernet system key from main.py
        encrypted_token = FERNET.encrypt(access_token.encode()).decode()

        # Securely upsert the user record matching your main data schema
        users_col.update_one(
            {"wa_id": payload.whatsapp_id},
            {"$set": {
                "access_token_enc":  encrypted_token,
                "token_expires_at":  expires_at,
                "connected_phone":   payload.phone_number,
                "updated_at":        datetime.now(timezone.utc)
            }},
            upsert=True,
        )
        
        return {
            "success": True, 
            "message": "Account securely authorized and saved to database",
            "connected_account": payload.phone_number
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
