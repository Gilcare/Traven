import httpx
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException

def now() -> datetime:
    return datetime.now(timezone.utc)

def fetch_stored_token(wa_id: str, users_col, fernet, aidex_base_url: str) -> str:
    """
    Safely retrieves, decrypts, and automatically auto-refreshes 
    the active token for a user from MongoDB.
    """
    user = users_col.find_one({"wa_id": wa_id})
    if not user:
        raise HTTPException(status_code=404, detail="User account not linked to Travenhealth.")

    # Token is still fresh (giving a 1-minute buffer window)
    if user["token_expires_at"] > now() + timedelta(minutes=1):
        return fernet.decrypt(user["access_token_enc"].encode()).decode()

    # Token is expired. Determine if we can refresh it or if they must re-auth
    if user.get("auth_method") == "headless_sms" or not user.get("refresh_token_enc"):
        # Headless API logins typically do not supply an OAuth refresh token.
        raise HTTPException(
            status_code=401, 
            detail="Session expired. Please send 'login' to get a new WhatsApp verification code."
        )

    # If it's an OAuth2 user, execute the secure token rotation
    return execute_oauth_refresh(wa_id, user, users_col, fernet, aidex_base_url)


def execute_oauth_refresh(wa_id: str, user: dict, users_col, fernet, aidex_base_url: str) -> str:
    """Performs the single-use OAuth2 refresh token exchange."""
    old_refresh_token = fernet.decrypt(user["refresh_token_enc"].encode()).decode()
    
    try:
        # Requesting a fresh token set from AiDEX network
        response = httpx.post(
            f"{aidex_base_url}/v1/oauth2/token",
            data={"refreshToken": old_refresh_token, "grantType": "refresh_token"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15
        )
        
        if response.status_code != 200:
            # Refresh token was likely single-use and already consumed or revoked
            users_col.delete_one({"wa_id": wa_id})
            raise HTTPException(status_code=401, detail="Session revoked. Please reconnect your account.")

        token_data = response.json()
        new_access_token = token_data["accessToken"]
        new_refresh_token = token_data.get("refreshToken")
        expires_at = now() + timedelta(seconds=int(token_data.get("expiresIn", 86400)))

        # Update MongoDB atomically
        update_payload = {
            "access_token_enc": fernet.encrypt(new_access_token.encode()).decode(),
            "token_expires_at": expires_at,
            "updated_at": now()
        }
        if new_refresh_token:
            update_payload["refresh_token_enc"] = fernet.encrypt(new_refresh_token.encode()).decode()

        users_col.update_one({"wa_id": wa_id}, {"$set": update_payload})
        return new_access_token

    except Exception:
        users_col.delete_one({"wa_id": wa_id})
        raise HTTPException(status_code=401, detail="Network authorization handshake dropped. Re-authentication required.")
