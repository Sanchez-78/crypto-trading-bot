"""Centralized Bearer-token auth for the dashboard API (audit PR5 / P1.6).

One middleware guards every route. The token is resolved, in order, from:
  1. a systemd credential  ($CREDENTIALS_DIRECTORY/dashboard_api_token)
  2. the DASHBOARD_API_TOKEN env var (development / tests only)

Security contract (audit 9.4 / 9.10):
  * constant-time comparison (hmac.compare_digest),
  * token never appears in logs, URLs, or error responses,
  * missing / wrong token -> 401,
  * fail-closed: if auth is not explicitly disabled AND no server token is
    configured, protected endpoints return 503 (never an open, unauthenticated
    public API),
  * the health endpoint is exempt and minimal (no strategy, no metrics),
  * X-Forwarded-For is never trusted for auth decisions.

Explicit escape hatch for local dev / tests: DASHBOARD_AUTH_DISABLED=1.
"""
import hmac
import logging
import os

log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}
DEFAULT_EXEMPT = ("/healthz",)


def auth_disabled() -> bool:
    return str(os.getenv("DASHBOARD_AUTH_DISABLED", "")).strip().lower() in _TRUE


def load_api_token() -> str | None:
    """Return the configured server token, or None if none is set.

    Never logs the token value.
    """
    cred_dir = os.getenv("CREDENTIALS_DIRECTORY")
    if cred_dir:
        cred_path = os.path.join(cred_dir, "dashboard_api_token")
        try:
            if os.path.exists(cred_path):
                with open(cred_path) as f:
                    tok = f.read().strip()
                if tok:
                    return tok
        except OSError:
            log.warning("dashboard_api_token credential present but unreadable")
    tok = os.getenv("DASHBOARD_API_TOKEN", "").strip()
    return tok or None


def _extract_bearer(authorization: str) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    tok = parts[1].strip()
    return tok or None


def evaluate(authorization_header: str) -> tuple[bool, int, str | None]:
    """Pure auth decision. Returns (allowed, http_status, error_code).

    error_code is a machine-readable string safe to expose (never the token).
    """
    if auth_disabled():
        return True, 200, None
    server_token = load_api_token()
    if not server_token:
        return False, 503, "auth_not_configured"
    provided = _extract_bearer(authorization_header or "")
    # Compare as bytes: hmac.compare_digest raises TypeError on a non-ASCII str,
    # which a hostile client could send to force a 500. Bytes compare is still
    # constant-time and degrades a bad token to a clean 401.
    if provided and hmac.compare_digest(provided.encode("utf-8"), server_token.encode("utf-8")):
        return True, 200, None
    return False, 401, "unauthorized"


def install_auth(app, exempt=DEFAULT_EXEMPT):
    """Register the single before_request auth gate on a Flask app."""
    from flask import jsonify, request

    exempt_set = set(exempt)

    @app.before_request
    def _require_bearer_token():
        if request.path in exempt_set:
            return None
        allowed, status, code = evaluate(request.headers.get("Authorization", ""))
        if allowed:
            return None
        # Body carries only a machine-readable code — never the token or a stack.
        return jsonify({"error": code, "degraded": True}), status

    return app
