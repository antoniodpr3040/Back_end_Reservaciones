import base64
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from config import (
    get_backend_public_url,
    get_env,
    get_frontend_url,
    is_https_url,
    origin_from_url,
)
from security import create_access_token
from services import get_or_create_user, update_user_microsoft_tokens

router = APIRouter()


MICROSOFT_SCOPES = "openid profile email offline_access Calendars.ReadWrite"

oauth_state_store: dict[str, dict[str, str]] = {}


def _resolve_frontend_url(
    request: Request, frontend_url: str | None = None
) -> str:
    for candidate in (
        frontend_url,
        request.headers.get("origin"),
        request.headers.get("referer"),
        get_frontend_url(),
    ):
        resolved_origin = origin_from_url(candidate)
        if resolved_origin:
            return resolved_origin

    return ""


def _normalize_redirect_path(path: str | None) -> str:
    cleaned_path = (path or "").strip()
    if not cleaned_path:
        return "/dashboard"

    if cleaned_path.startswith(("http://", "https://", "//")):
        return "/dashboard"

    return f"/{cleaned_path.lstrip('/')}"


def _get_auth_settings() -> dict[str, str]:
    tenant_id = get_env("MICROSOFT_TENANT_ID", "common") or "common"
    redirect_uri = get_env("MICROSOFT_REDIRECT_URI") or ""
    frontend_url = get_frontend_url()
    backend_public_url = get_backend_public_url(redirect_uri)
    auth_base = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0"
    )

    return {
        "client_id": get_env("MICROSOFT_CLIENT_ID") or "",
        "client_secret": get_env("MICROSOFT_CLIENT_SECRET") or "",
        "redirect_uri": redirect_uri,
        "frontend_url": frontend_url,
        "backend_public_url": backend_public_url,
        "authorize_url": f"{auth_base}/authorize",
        "token_url": f"{auth_base}/token",
    }


@router.get("/login/microsoft")
def login_microsoft(
    request: Request,
    frontend_url: str | None = Query(default=None),
    redirect_path: str = Query(default="/dashboard"),
):
    settings = _get_auth_settings()

    if not settings["client_id"] or not settings["redirect_uri"]:
        raise HTTPException(
            status_code=500,
            detail="Faltan variables de entorno de Microsoft",
        )

    state = secrets.token_urlsafe(32)
    oauth_state_store[state] = {
        "frontend_url": _resolve_frontend_url(request, frontend_url),
        "redirect_path": _normalize_redirect_path(redirect_path),
    }

    params = {
        "client_id": settings["client_id"],
        "response_type": "code",
        "redirect_uri": settings["redirect_uri"],
        "response_mode": "query",
        "scope": MICROSOFT_SCOPES,
        "state": state,
    }

    auth_url = f"{settings['authorize_url']}?{urlencode(params)}"
    return RedirectResponse(url=auth_url)


@router.get("/auth/callback")
async def auth_callback(
    code: str = Query(...),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
):
    settings = _get_auth_settings()

    if error:
        raise HTTPException(
            status_code=400,
            detail=f"Microsoft devolvio error: {error} - {error_description}",
        )

    if not state or state not in oauth_state_store:
        raise HTTPException(status_code=400, detail="State invalido o ausente")

    state_context = oauth_state_store.pop(state)

    if (
        not settings["client_id"]
        or not settings["client_secret"]
        or not settings["redirect_uri"]
    ):
        raise HTTPException(
            status_code=500,
            detail="Faltan variables de entorno de Microsoft",
        )

    token_payload = {
        "client_id": settings["client_id"],
        "client_secret": settings["client_secret"],
        "code": code,
        "redirect_uri": settings["redirect_uri"],
        "grant_type": "authorization_code",
        "scope": MICROSOFT_SCOPES,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_response = await client.post(
            settings["token_url"],
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if token_response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No se pudo intercambiar el code por tokens",
                "microsoft_response": token_response.text,
            },
        )

    token_data = token_response.json()

    id_token = token_data.get("id_token")
    microsoft_access_token = token_data.get("access_token")
    microsoft_refresh_token = token_data.get("refresh_token")

    if not id_token or not microsoft_access_token:
        raise HTTPException(
            status_code=400,
            detail="Microsoft no devolvio tokens esperados",
        )

    try:
        parts = id_token.split(".")
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="No se pudo leer el id_token",
        ) from exc

    email = (
        claims.get("email")
        or claims.get("preferred_username")
        or claims.get("upn")
    )
    name = claims.get("name", "Usuario")

    if not email:
        raise HTTPException(
            status_code=400,
            detail="No vino email en los claims del usuario",
        )

    user_data = get_or_create_user(
        name=name,
        email=email,
        provider="microsoft",
    )
    expires_in = int(token_data.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    user_data = update_user_microsoft_tokens(
        user_data["id"],
        access_token=microsoft_access_token,
        refresh_token=microsoft_refresh_token,
        expires_at=expires_at.isoformat(),
        scope=token_data.get("scope", MICROSOFT_SCOPES),
    ) or user_data

    internal_access_token = create_access_token(
        {
            "sub": str(user_data["id"]),
            "email": user_data["email"],
            "role": user_data["role"],
        }
    )

    resolved_frontend_url = (
        state_context.get("frontend_url") or settings["frontend_url"]
    )
    redirect_path = _normalize_redirect_path(
        state_context.get("redirect_path")
    )

    frontend_origin = origin_from_url(resolved_frontend_url)
    backend_origin = origin_from_url(settings["backend_public_url"])
    is_cross_site = bool(
        frontend_origin and backend_origin and frontend_origin != backend_origin
    )
    cookie_secure = is_https_url(settings["backend_public_url"])
    cookie_samesite = "none" if is_cross_site else "lax"

    if cookie_samesite == "none" and not cookie_secure:
        raise HTTPException(
            status_code=500,
            detail=(
                "La cookie requiere HTTPS cuando el frontend y backend "
                "estan en origenes distintos. Configura BACKEND_PUBLIC_URL "
                "o MICROSOFT_REDIRECT_URI con https."
            ),
        )

    frontend_redirect_url = (
        f"{resolved_frontend_url}{redirect_path}"
        f"#access_token={quote(internal_access_token, safe='')}"
    )
    response = RedirectResponse(url=frontend_redirect_url)
    response.set_cookie(
        key="access_token",
        value=internal_access_token,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        max_age=60 * 60,
        path="/",
    )

    return response


@router.post("/logout")
def logout():
    response = JSONResponse(content={"message": "Sesion cerrada"})
    response.delete_cookie(key="access_token", path="/")
    return response
