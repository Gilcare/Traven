import time
from typing import Optional, Dict, Any
from pydantic import BaseModel

class AidexTokenProfile(BaseModel):
    """Encapsulates active tokens along with absolute local token expiration."""
    access_token: str
    refresh_token: str
    expires_at: float

    def is_expired(self) -> bool:
        # 60-second safety window to shield against network propagation delays
        return time.time() >= (self.expires_at - 60)

# Thread-safe global state cache mimicking a database table
# Easily swappable for Supabase client calls later
_VOLATILE_RAM_STORE: Dict[str, Dict[str, Any]] = {}

class TokenRepository:
    @staticmethod
    def save_tokens(user_id: str, access_token: str, refresh_token: str, expires_in: int) -> AidexTokenProfile:
        """Saves or rotates an active token profile state."""
        profile = AidexTokenProfile(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + float(expires_in)
        )
        _VOLATILE_RAM_STORE[user_id] = profile.model_dump()
        return profile

    @staticmethod
    def get_tokens(user_id: str) -> Optional[AidexTokenProfile]:
        """Fetches active user token snapshots."""
        raw_data = _VOLATILE_RAM_STORE.get(user_id)
        if not raw_data:
            return None
        return AidexTokenProfile(**raw_data)
