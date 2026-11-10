from __future__ import annotations

import os
import logging
from contextvars import ContextVar

_identity: ContextVar[dict] = ContextVar(
    "repofix_identity", default={"uid": "local-dev", "email": "local@repofix.dev"}
)


def auth_mode() -> str:
    return os.getenv("REPOFIX_AUTH_MODE", "local").strip().lower()


def firebase_config() -> dict:
    mapping = {"apiKey": "FIREBASE_API_KEY", "authDomain": "FIREBASE_AUTH_DOMAIN",
               "projectId": "FIREBASE_PROJECT_ID", "appId": "FIREBASE_APP_ID"}
    config = {key: os.getenv(variable, "") for key, variable in mapping.items()}
    enabled = auth_mode() == "firebase" and all(config.values())
    return {"enabled": enabled, "mode": "firebase" if enabled else "local",
            "config": config if enabled else {}}


def verify_bearer(authorization: str | None) -> dict:
    if auth_mode() != "firebase":
        return {"uid": "local-dev", "email": "local@repofix.dev", "name": "Local developer"}
    if not authorization or not authorization.startswith("Bearer "):
        raise ValueError("Authentication required")
    try:
        import firebase_admin
        from firebase_admin import auth
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        return auth.verify_id_token(authorization[7:], check_revoked=True)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Firebase ID token verification failed (%s): %s", type(exc).__name__, exc
        )
        raise ValueError("Invalid or expired authentication token") from exc


def set_identity(value: dict):
    return _identity.set(value)


def reset_identity(token) -> None:
    _identity.reset(token)


def current_identity() -> dict:
    return _identity.get()
