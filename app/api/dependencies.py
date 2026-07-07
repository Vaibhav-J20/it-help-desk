"""
API key authentication dependency.
Uses constant-time comparison to prevent timing attacks.
"""
import secrets
from fastapi import Header, HTTPException, status
from app.core.config import get_settings


async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    """
    Validate the X-API-Key header against the configured secret.
    Raises HTTP 401 if the key is missing or incorrect.
    """
    settings = get_settings()
    if not settings.api_key_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API_KEY_SECRET is not configured on the server.",
        )
    if not secrets.compare_digest(x_api_key.encode(), settings.api_key_secret.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
