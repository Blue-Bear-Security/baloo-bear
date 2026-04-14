"""Basic auth dependency for the dashboard."""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from baloo.config.settings import get_settings

security = HTTPBasic()


def verify_credentials(
    credentials: HTTPBasicCredentials = Depends(security),
) -> str:
    """Verify basic-auth credentials against settings. Returns the username."""
    settings = get_settings()
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.dashboard_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.dashboard_password.encode("utf-8"),
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
