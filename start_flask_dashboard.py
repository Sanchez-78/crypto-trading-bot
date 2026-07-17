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
    # Ship-dark (hotfix 2026-07-17): the secure localhost bind only becomes the
    # default once DASHBOARD_SECURITY_ENABLED=1; until then the bind stays
    # 0.0.0.0 (prior behaviour) so the autodeployed dashboard keeps serving the
    # Android app. DASHBOARD_BIND_HOST always overrides. See dashboard_auth.
    from src.services.dashboard_auth import security_enabled
    default_host = "127.0.0.1" if security_enabled() else "0.0.0.0"
    host = os.getenv("DASHBOARD_BIND_HOST", default_host)
    port = int(os.getenv("DASHBOARD_PORT", "5001"))
    app.run(host=host, port=port, debug=False, use_reloader=False)
