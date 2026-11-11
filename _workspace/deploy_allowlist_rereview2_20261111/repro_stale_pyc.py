"""Check whether python -B can import copied stale bytecode instead of staged source."""

import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
root = Path(tempfile.mkdtemp(prefix="repro-pyc-", dir=HERE)).resolve()
assert root.is_relative_to(HERE) and root.name.startswith("repro-pyc-")
try:
    services = root / "src" / "services"
    services.mkdir(parents=True)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (services / "__init__.py").write_text("", encoding="utf-8")
    source = services / "candidate.py"
    old = "VALUE = 'old'\n"
    new = "VALUE = 'new'\n"
    assert len(old) == len(new)
    source.write_text(old, encoding="utf-8")
    fixed_mtime = 1_700_000_000
    os.utime(source, (fixed_mtime, fixed_mtime))
    py_compile.compile(str(source), doraise=True)

    # A staged overlay with the same timestamp (integer seconds) and size as the old source.
    source.write_text(new, encoding="utf-8")
    os.utime(source, (fixed_mtime, fixed_mtime))
    code = "import sys; sys.path.insert(0,sys.argv[1]); from src.services import candidate; print(candidate.VALUE)"
    result = subprocess.run([sys.executable, "-B", "-c", code, str(root)],
                            cwd=root, capture_output=True, text=True, check=True)
    timestamp_observed = result.stdout.strip()
    assert timestamp_observed == "old", timestamp_observed

    # Unchecked-hash bytecode stays valid even if the new source has a different size/mtime.
    source.write_text(old, encoding="utf-8")
    py_compile.compile(str(source), doraise=True,
                       invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    source.write_text("VALUE = 'new_source_with_different_size'\n", encoding="utf-8")
    result = subprocess.run([sys.executable, "-B", "-c", code, str(root)],
                            cwd=root, capture_output=True, text=True, check=True)
    unchecked_hash_observed = result.stdout.strip()
    assert unchecked_hash_observed == "old", unchecked_hash_observed
    print(json.dumps({"timestamp_cache_imported": timestamp_observed,
                      "unchecked_hash_cache_imported": unchecked_hash_observed,
                      "staged_source": "new"}, sort_keys=True))
finally:
    assert root.resolve().is_relative_to(HERE.resolve()) and root.name.startswith("repro-pyc-")
    shutil.rmtree(root)
