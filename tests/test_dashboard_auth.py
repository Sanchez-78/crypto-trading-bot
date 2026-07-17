"""Audit PR5 (P1.6 / 9.10) — dashboard Bearer-token auth + hardening checks."""
from pathlib import Path

import pytest

import src.services.dashboard_auth as da

REPO = Path(__file__).resolve().parents[1]
TOKEN = "s3cr3t-token-value-not-in-repo"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("DASHBOARD_API_TOKEN", "DASHBOARD_AUTH_DISABLED", "CREDENTIALS_DIRECTORY"):
        monkeypatch.delenv(k, raising=False)
    # Most tests exercise the ENFORCED posture; enable the master switch here.
    # The ship-dark default (flag off) has its own dedicated tests that clear it.
    monkeypatch.setenv("DASHBOARD_SECURITY_ENABLED", "1")
    yield


# ── ship-dark master switch (default OFF = open, pre-PR5 behaviour) ────────────

def test_security_disabled_by_default_is_open(monkeypatch):
    monkeypatch.delenv("DASHBOARD_SECURITY_ENABLED", raising=False)
    assert da.security_enabled() is False
    # no token, no header -> still allowed (no 503, no lockout)
    allowed, status, code = da.evaluate("")
    assert allowed is True and status == 200 and code is None


def test_master_switch_gates_enforcement(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    monkeypatch.delenv("DASHBOARD_SECURITY_ENABLED", raising=False)
    assert da.evaluate("")[0] is True            # off -> open
    monkeypatch.setenv("DASHBOARD_SECURITY_ENABLED", "1")
    assert da.evaluate("")[0] is False           # on -> enforced


# ── pure decision (evaluate) ──────────────────────────────────────────────────

def test_no_token_configured_fails_closed(monkeypatch):
    allowed, status, code = da.evaluate("Bearer whatever")
    assert allowed is False and status == 503 and code == "auth_not_configured"


def test_missing_authorization_header_401(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    allowed, status, code = da.evaluate("")
    assert allowed is False and status == 401 and code == "unauthorized"


def test_wrong_token_401(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    allowed, status, code = da.evaluate("Bearer not-the-token")
    assert allowed is False and status == 401 and code == "unauthorized"


def test_correct_token_200(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    allowed, status, code = da.evaluate(f"Bearer {TOKEN}")
    assert allowed is True and status == 200 and code is None


def test_auth_disabled_allows(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_DISABLED", "1")
    allowed, status, _ = da.evaluate("")
    assert allowed is True and status == 200


def test_malformed_authorization_header(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    for hdr in ("Basic abc", "Bearer", "Bearer  ", TOKEN, f"bearer {TOKEN}x"):
        allowed, status, _ = da.evaluate(hdr)
        assert allowed is False, hdr
    # case-insensitive scheme, exact token still works
    allowed, _, _ = da.evaluate(f"bearer {TOKEN}")
    assert allowed is True


def test_non_ascii_token_denied_not_crashed(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    # A non-ASCII bearer token must degrade to 401, never raise (would be a 500).
    allowed, status, code = da.evaluate("Bearer tökén-ünïcödé-☠")
    assert allowed is False and status == 401 and code == "unauthorized"


def test_credential_file_preferred(monkeypatch, tmp_path):
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    (tmp_path / "dashboard_api_token").write_text(TOKEN + "\n")
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "env-token-should-lose")
    assert da.load_api_token() == TOKEN  # credential wins over env


def test_uses_constant_time_comparison():
    src = (REPO / "src/services/dashboard_auth.py").read_text()
    assert "hmac.compare_digest" in src
    assert "==" not in src.split("def evaluate")[1].split("def ")[0].replace("!=", "")


# ── Flask integration ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from src.services.dashboard_web import app
    app.config["TESTING"] = True
    return app.test_client()


def test_healthz_open_and_minimal(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)  # auth on, but /healthz exempt
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.get_json()
    assert body == {"status": "ok"}  # no strategy, no metrics leaked


def test_protected_endpoint_requires_token(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    assert client.get("/api/dashboard/metrics").status_code == 401
    assert client.get("/api/trades/recent").status_code == 401


def test_protected_endpoint_bad_token_401(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    r = client.get("/api/dashboard/metrics", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_protected_endpoint_good_token_200(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    r = client.get("/api/dashboard/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


def test_token_never_in_error_body(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    r = client.get("/api/dashboard/metrics", headers={"Authorization": f"Bearer {TOKEN}-wrong"})
    assert r.status_code == 401
    assert TOKEN not in r.get_data(as_text=True)  # neither the server nor the sent token echoed


def test_endpoints_open_when_security_disabled(client, monkeypatch):
    # ship-dark default: with the master switch off the API serves the app as
    # before PR5 — no 503, no token needed.
    monkeypatch.delenv("DASHBOARD_SECURITY_ENABLED", raising=False)
    assert client.get("/api/dashboard/metrics").status_code == 200
    assert client.get("/api/trades/recent").status_code == 200


def test_unconfigured_server_fails_closed_503(client, monkeypatch):
    # no token, auth not disabled -> protected endpoints refuse (never open API)
    r = client.get("/api/dashboard/metrics")
    assert r.status_code == 503
    assert r.get_json().get("error") == "auth_not_configured"


# ── static hardening / bind checks ────────────────────────────────────────────

def test_systemd_service_non_root_and_hardened():
    svc = (REPO / "systemd/cryptomaster-dashboard.service").read_text()
    assert "User=root" not in svc
    assert "User=cryptomaster-dashboard" in svc
    for directive in ("NoNewPrivileges=true", "ProtectSystem=strict", "PrivateTmp=true",
                      "ProtectHome=true", "CapabilityBoundingSet=", "RestrictSUIDSGID=true",
                      "LoadCredential=dashboard_api_token"):
        assert directive in svc, directive
    # preserves the CLAUDE.md permanent fix (direct python, no gunicorn wrapper)
    execstart = next(ln for ln in svc.splitlines() if ln.startswith("ExecStart="))
    assert "start_flask_dashboard.py" in execstart
    assert "gunicorn" not in execstart.lower()


def _binding_lines(src):
    return [ln for ln in src.splitlines() if "app.run(" in ln]


def test_bind_is_security_gated():
    # Ship-dark: the binding is configurable and its DEFAULT is gated on
    # security_enabled() — 127.0.0.1 when security is on, 0.0.0.0 (prior
    # behaviour) when off. The app.run call must use a variable, never a literal.
    for f in ("start_flask_dashboard.py", "src/services/dashboard_web.py"):
        src = (REPO / f).read_text()
        assert "security_enabled()" in src, f"{f} bind not gated on security flag"
        assert '"127.0.0.1"' in src and '"0.0.0.0"' in src
        assert "DASHBOARD_BIND_HOST" in src
        for ln in _binding_lines(src):
            assert "host=host" in ln or "host=_host" in ln, f"{f} bind not configurable: {ln}"
            assert "0.0.0.0" not in ln and "127.0.0.1" not in ln  # no hardcoded host on the call


def test_firewall_workflow_is_manual_and_not_auto():
    wf = (REPO / ".github/workflows/hetzner-dashboard-firewall.yml").read_text()
    import yaml
    doc = yaml.safe_load(wf)
    on = doc.get("on") or doc.get(True)
    assert "workflow_dispatch" in on and "push" not in on
    assert "APPLY_FIREWALL" in wf and "STATUS" in wf
