import time
import requests
from typing import Dict, Any, List
from pydantic import BaseModel
from aidex_connect.database_logic import AidexTokenProfile

# =====================================================================
# DOCUMENTED EXCEPTION EXTRACTION ENGINE
# =====================================================================
class AidexApiError(Exception):
    def __init__(self, error_code: str, description: str):
        self.error_code = error_code
        self.description = description
        super().__init__(f"[{error_code}] {description}")

class InvalidRequestError(AidexApiError): pass
class AccessDeniedError(AidexApiError): pass
class InvalidClientError(AidexApiError): pass
class InvalidGrantError(AidexApiError): pass

def raise_for_error_code(payload: Dict[str, Any]) -> None:
    """Matches the exact string error codes defined in the platform manual."""
    if "error" not in payload:
        return
    err_code = payload.get("error", "")
    desc = payload.get("error_description", "Missing vendor error context details.")
    
    mapping = {
        "InvalidRequest": InvalidRequestError,
        "AccessDenied": AccessDeniedError,
        "InvalidClient": InvalidClientError,
        "InvalidGrant": InvalidGrantError
    }
    raise mapping.get(err_code, AidexApiError)(err_code, desc)

# =====================================================================
# PROGRAMMATIC SERVICE CLIENT
# =====================================================================
class AidexSandboxClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str = "https://sandbox-accesslist.microtechmd.com"):
        self.clientId = client_id
        self.clientSecret = client_secret
        self.base_url = base_url.rstrip('/')

    def exchange_authorization_code(self, code: str) -> Dict[str, Any]:
        """Swaps codes for standard tokens. Enforces lowerCamelCase parameter keys."""
        url = f"{self.base_url}/v1/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"}
        payload = {
            "clientId": self.clientId,
            "clientSecret": self.clientSecret,
            "code": code,
            "grantType": "authorization_code"
        }
        res = requests.post(url, headers=headers, data=payload, timeout=10)
        data = res.json()
        raise_for_error_code(data)
        return data

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Renews session access via the single-use token rotation strategy."""
        url = f"{self.base_url}/v1/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"}
        payload = {
            "refreshToken": refresh_token,
            "grantType": "refresh_token"
        }
        res = requests.post(url, headers=headers, data=payload, timeout=10)
        data = res.json()
        raise_for_error_code(data)
        return data

    def fetch_glucose_telemetry(self, token_profile: AidexTokenProfile, start_iso: str, end_iso: str) -> Dict[str, Any]:
        """Pulls telemetry arrays directly into core app engine memory buffers."""
        url = f"{self.base_url}/v1/user/sensor-glucose"
        headers = {"authorization": token_profile.access_token}
        # Note parameter structure naming variance 'endDate' extracted from docs
        params = {"startTime": start_iso, "endDate": end_iso}
        
        res = requests.get(url, headers=headers, params=params, timeout=10)
        data = res.json()
        raise_for_error_code(data)
        return data
