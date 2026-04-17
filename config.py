import os
from urllib.parse import urlparse

from dotenv import load_dotenv

DEFAULT_FRONTEND_URL = "http://localhost:3000"


def _load_env() -> None:
    load_dotenv(override=True)


def get_env(name: str, default: str | None = None) -> str | None:
    _load_env()
    value = os.getenv(name, default)
    if value is None:
        return None
    return value.strip()


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    return url.strip().rstrip("/")


def origin_from_url(url: str | None) -> str:
    normalized = normalize_url(url)
    if not normalized:
        return ""

    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return ""

    return f"{parsed.scheme}://{parsed.netloc}".lower()


def is_https_url(url: str | None) -> bool:
    normalized = normalize_url(url)
    if not normalized:
        return False

    parsed = urlparse(normalized)
    return parsed.scheme.lower() == "https"


def get_frontend_url() -> str:
    return normalize_url(get_env("FRONTEND_URL", DEFAULT_FRONTEND_URL))


def get_backend_public_url(redirect_uri: str | None = None) -> str:
    resolved_redirect_uri = redirect_uri or get_env("MICROSOFT_REDIRECT_URI")
    return normalize_url(
        get_env("BACKEND_PUBLIC_URL") or origin_from_url(resolved_redirect_uri)
    )


def get_cors_origins() -> list[str]:
    configured = get_env("CORS_ALLOWED_ORIGINS")
    if configured:
        origins = {
            origin_from_url(origin)
            for origin in configured.split(",")
            if origin.strip()
        }
        return [origin for origin in origins if origin]

    origins = {
        origin_from_url(DEFAULT_FRONTEND_URL),
        origin_from_url(get_frontend_url()),
    }
    return [origin for origin in origins if origin]
