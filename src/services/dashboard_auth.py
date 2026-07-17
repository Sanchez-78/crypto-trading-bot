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

SHIP-DARK ROLLOUT (hotfix 2026-07-17): the whole security posture (localhost
bind + auth enforcement) is OFF by default and only activates when
DASHBOARD_SECURITY_ENABLED=1. This is required because the server autodeploys
`main` on a timer — landing PR5's fail-closed auth by default locked the Android
app out (503, no token). With the flag off the dashboard keeps its prior
behaviour (public bind, no auth); flip the flag ON only once the token is
provisioned and the app's token flow is ready.

Dev/test escape hatch: DASHBOARD_AUTH_DISABLED=1 — but it applies ONLY while
security is OFF. Once DASHBOARD_SECURITY_ENABLED=1, it is ignored (auth stays
enforced) so a hardened posture can never be silently bypassed (audit F4).
"""
import hmac
import logging
import os

log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}
DEFAULT_EXEMPT = ("/healthz",)


def security_enabled() -> bool:
    """Master switch for the dashboard security posture. Default OFF (ship-dark)."""
    return str(os.getenv("DASHBOARD_SECURITY_ENABLED", "")).strip().lower() in _TRUE


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
    if not security_enabled():
        # Ship-dark: with the master switch off the API is open exactly as it was
        # before PR5 — no 503, no lockout — until security is explicitly enabled.
        return True, 200, None
    if auth_disabled():
        # Audit F4: a hardened posture (security ON) must NOT be silently
        # bypassable. DASHBOARD_AUTH_DISABLED is a dev/test escape that applies
        # only while security is OFF; once security is ON it is IGNORED and
        # logged, so auth always stays enforced. (For an open dev dashboard,
        # leave DASHBOARD_SECURITY_ENABLED unset instead.)
        log.warning("[DASHBOARD_AUTH] DASHBOARD_AUTH_DISABLED ignored while "
                    "DASHBOARD_SECURITY_ENABLED=1 — auth stays enforced")
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
