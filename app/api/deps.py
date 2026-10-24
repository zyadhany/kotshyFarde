"""
app/api/deps.py
───────────────
FastAPI dependencies for authentication, role verification, and session management.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.user import User

logger = logging.getLogger(__name__)


def _is_html_request(request: Request) -> bool:
    """Determine if the incoming request expects an HTML response.

    Any path starting with `/api/` is a REST API request (expects JSON 401).
    All other application endpoints are browser page views (redirect to /login).
    """
    return not request.url.path.startswith("/api/")


def get_optional_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> Optional[User]:
    """Retrieve the authenticated User if a valid JWT is present; otherwise None.

    Checks HttpOnly cookie ``access_token`` first, then falls back to Authorization header.
    """
    token: Optional[str] = request.cookies.get("access_token")

    if not token:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        return None

    try:
        user_id = int(user_id_raw)
    except (ValueError, TypeError):
        return None

    user = session.get(User, user_id)
    if not user or not user.is_active:
        return None

    return user


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    """Require an authenticated user.

    Redirects browser HTML requests to /login.
    Raises 401 Unauthorized for API/JSON endpoints.
    """
    user = get_optional_current_user(request=request, session=session)
    if not user:
        if _is_html_request(request):
            next_url = request.url.path
            login_url = f"/login?next={next_url}" if next_url and next_url != "/" else "/login"
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": login_url},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_coach(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require that the authenticated user has coach privileges.

    Raises 403 Forbidden if user is a student.
    """
    if not current_user.is_coach():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Coach privileges required to access this resource.",
        )
    return current_user
