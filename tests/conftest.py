"""pytest configuration for CryptoMaster test suite."""
import os
import sys
import tempfile
from pathlib import Path

# Add project root to path so 'src' module can be imported
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# ── Test-write sink separation (2026-09-14) ─────────────────────────────────
# local_persistent_cache resolves its storage dir from this env var, defaulting
# to the CWD-relative "local_learning_storage". pytest runs from the repo root,
# so before this redirect every test that closed a paper position wrote into
# the SAME cache.sqlite the dashboard reads and every WR analysis is computed
# from. Phase 0 forensics found that had already contaminated 116 of 472 rows
# (24.6%) with fake-clock, TEST/MANUAL and SYM* rows -- and TEST/MANUAL rows
# are 100% wins, so they inflated every reported win rate.
#
# This must run at conftest IMPORT time, before any test module imports
# local_persistent_cache, because that module reads the env var at its own
# import. local_persistent_cache._assert_not_production_sink() is the
# fail-closed backstop if this is ever bypassed.
#
# Set CRYPTOMASTER_LEARNING_STORAGE_DIR yourself to inspect the test sink;
# otherwise each session gets a throwaway temp directory.
if not os.environ.get("CRYPTOMASTER_LEARNING_STORAGE_DIR", "").strip():
    os.environ["CRYPTOMASTER_LEARNING_STORAGE_DIR"] = tempfile.mkdtemp(
        prefix="cryptomaster_test_sink_"
    )
