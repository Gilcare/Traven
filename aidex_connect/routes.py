from fastapi import APIRouter, Query, HTTPException, status
from aidex_connect.client import AidexSandboxClient, AidexApiError
from aidex_connect.database_logic import TokenRepository

router = APIRouter(prefix="/v1/oauth2")

# Initialize client using credentials loaded from your runtime configurations
sandbox_client = AidexSandboxClient(
    client_id="YOUR_ACTUAL_SANDBOX_CLIENT_ID", 
    client_secret="YOUR_ACTUAL_SANDBOX_CLIENT_SECRET"
)

@router.get("/callback")
async def process_oauth_callback(
    code: str = Query(..., description="Authorization code passed by the platform callback engine"),
    state: str = Query(..., description="The user identity context tracking key")
):
    """Intercepts authorization codes and updates credentials inside the user session cache."""
    try:
        # 1. Trigger network verification sequence
        raw_token_data = sandbox_client.exchange_authorization_code(code=code)
        
        # 2. Extract lowerCamelCase configuration data fields safely
        access_token = raw_token_data["accessToken"]
        refresh_token = raw_token_data["refreshToken"]
        expires_in = raw_token_data.get("expiresIn", 86400)
        
        # 3. Securely update tokens in our decoupled persistence layer
        profile = TokenRepository.save_tokens(
            user_id=state,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(expires_in)
        )
        
        return {
            "status": "success",
            "message": "AiDEX continuous streaming service successfully coupled.",
            "synchronized_until": profile.expires_at
        }
        
    except AidexApiError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": error.error_code, "msg": error.description}
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fatal exception handled inside internal processing operations: {str(e)}"
        )
