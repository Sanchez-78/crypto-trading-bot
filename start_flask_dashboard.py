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
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
