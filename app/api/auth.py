"""
app/api/auth.py
───────────────
Authentication routes: login page, API login, and logout.
Handles cookie lifecycle and role-based redirects.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_optional_current_user
from app.core.config import settings
from app.core.database import get_session
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.user import LoginRequest, LoginResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _resolve_redirect_url(user: User, next_url: Optional[str] = None) -> str:
    """Determine where to send the user after successful authentication."""
    if user.is_coach():
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return next_url
        return "/"

    # For students: only redirect to permitted student destinations; default to /my-profile
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        is_student_page = (
            next_url == "/my-profile"
            or next_url.startswith("/tasks/")
            or next_url.startswith("/tasks-page/")
            or next_url == f"/students/{user.id}"
            or next_url == f"/students-page/{user.id}"
        )
        if is_student_page:
            return next_url

    return "/my-profile"


# ── GET /login: Render login page ──────────────────────────────
@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: Optional[str] = None,
    session: Session = Depends(get_session),
) -> Response:
    """Render the clean Kotchy login view or redirect if already authenticated."""
    current_user = get_optional_current_user(request=request, session=session)
    if current_user:
        target = _resolve_redirect_url(current_user, next)
        return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)

    context = {
        "request": request,
        "next": next or "",
    }
    return templates.TemplateResponse(request=request, name="login.html", context=context)


# ── POST /api/auth/login: Authenticate & set HttpOnly cookie ───
@router.post("/api/auth/login", response_model=LoginResponse)
async def api_login(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> LoginResponse:
    """Authenticate user with username or email, set access_token cookie."""
    # Support both JSON payload and form-urlencoded data
    content_type = request.headers.get("content-type", "")
    username_or_email = ""
    password = ""
    next_url: Optional[str] = None

    if "application/json" in content_type:
        try:
            body = await request.json()
            username_or_email = str(body.get("username_or_email") or body.get("username") or "").strip()
            password = str(body.get("password") or "")
            next_url = body.get("next")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload.",
            )
    else:
        form_data = await request.form()
        username_or_email = str(form_data.get("username_or_email") or form_data.get("username") or "").strip()
        password = str(form_data.get("password") or "")
        next_url = form_data.get("next")  # type: ignore[assignment]

    if not username_or_email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username/email and password are required.",
        )

    # Locate user by username or email
    user = session.exec(
        select(User).where(
            (User.username == username_or_email) | (User.email == username_or_email)
        )
    ).first()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid credentials. Please verify your username/email and password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Please contact your coach.",
        )

    # Generate JWT token
    token = create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "role": user.role,
        }
    )

    redirect_url = _resolve_redirect_url(user, next_url)

    # Set HttpOnly, SameSite="lax" cookie
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )

    return LoginResponse(
        success=True,
        username=user.username,
        role=user.role,
        redirect_url=redirect_url,
        access_token=token,
    )


# ── GET /logout & POST /logout: Clear cookie & redirect to /login
@router.get("/logout")
@router.post("/logout")
def logout(response: Response) -> Response:
    """Clear the access_token cookie and redirect to the login screen."""
    redirect = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    redirect.delete_cookie(key="access_token", path="/")
    return redirect
