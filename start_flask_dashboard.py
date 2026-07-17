#!/usr/bin/env python3
"""Flask Dashboard Wrapper - runs dashboard_web.py on port 5001.

Tracked in git so the deploy pipeline (which runs `git stash -u`) cannot stash
it away. The Flask venv lives OUTSIDE the repo (/opt/dashboard_venv) for the same
reason; the systemd unit cryptomaster-dashboard.service points ExecStart there.
"""
import sys
import os
import logging

logging.basicConfig(level=logging.INFO, format='[DASHBOARD] %(levelname)s: %(message)s')

sys.path.insert(0, '/opt/cryptomaster')
sys.path.insert(0, '/opt/cryptomaster/src')
os.chdir('/opt/cryptomaster')

from src.services.dashboard_web import app

if __name__ == '__main__':
    # Audit PR5 (P1.6): default bind is localhost (127.0.0.1), NOT 0.0.0.0.
    # Override via DASHBOARD_BIND_HOST / DASHBOARD_PORT only behind a VPN or an
    # authenticated HTTPS reverse proxy. Bearer-token auth is enforced by the
    # centralized middleware in dashboard_web (fail-closed without a token).
    host = os.getenv("DASHBOARD_BIND_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", "5001"))
    app.run(host=host, port=port, debug=False, use_reloader=False)
