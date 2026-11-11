"""Isolated reproduction of deploy_bot_files.sh's hash-check/install gap."""

import hashlib
import json


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


source = b"VALUE = 'reviewed'\n"
expected = digest(source)
assert digest(source) == expected  # script's initial EXPECTED_SHA256 check

stage = bytes(source)  # script's staging copy
exec(compile(stage, "stage.py", "exec"), {})  # staged import passes

source = b"VALUE = 'unreviewed'\n"  # changed during the open-position wait
installed = bytes(source)  # script installs from NEW, not stage

postimage_matches_source = digest(installed) == digest(source)
postimage_matches_expected = digest(installed) == expected
assert postimage_matches_source and not postimage_matches_expected
print(json.dumps({
    "preflight_source_sha256": expected,
    "installed_sha256": digest(installed),
    "postimage_matches_source": postimage_matches_source,
    "postimage_matches_expected": postimage_matches_expected,
}, sort_keys=True))
