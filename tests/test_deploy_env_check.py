"""deploy_env_check: effective env in the order the running bot sees it (review 77, P1)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "research_eval"))
import deploy_env_check as dec  # noqa: E402

FLAG = "PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED"
BASE = "TRADING_MODE=paper_train ENABLE_REAL_ORDERS=false LIVE_TRADING_CONFIRMED=false"


def _files(tmp_path, text, ignore="no"):
    path = tmp_path / "unit.env"
    path.write_text(text, encoding="utf-8")
    return f"{path} (ignore_errors={ignore})"


def environ(**kv):
    return "\0".join(f"{k}={v}" for k, v in kv.items()).encode() + b"\0"


def test_planned_value_accepted_without_overrides():
    env = dec.preflight(BASE, "", f"{FLAG}=true", "PAPER_TP_ZONE_BPS=35\n")
    assert env[FLAG] == "true" and env["PAPER_TP_ZONE_BPS"] == "35"


def test_new_managed_dropin_beats_older_environment_value():
    # deploy_bot_files.sh guarantees the managed drop-in sorts last, so it replaces earlier
    # Environment= values (including its own previous version) of the same key.
    env = dec.preflight(f"{BASE} {FLAG}=false", "", f"{FLAG}=true", "")
    assert env[FLAG] == "true"


def test_environment_file_false_overrides_planned_true_is_refused(tmp_path):
    with pytest.raises(dec.Refused, match="EnvironmentFile also sets"):
        dec.preflight(BASE, _files(tmp_path, f"{FLAG}=false\n"), f"{FLAG}=true")


@pytest.mark.parametrize("text", [f"{FLAG}=false\n", f"{FLAG}=ture\n", f"export {FLAG}=true\n"])
def test_dotenv_setting_the_planned_key_is_refused(text):
    with pytest.raises(dec.Refused, match="dotenv"):
        dec.preflight(BASE, "", f"{FLAG}=true", text)


def test_environment_file_overrides_environment_for_invariants(tmp_path):
    with pytest.raises(dec.Refused, match="TRADING_MODE"):
        dec.preflight(BASE, _files(tmp_path, "TRADING_MODE=live\n"), f"{FLAG}=true")


def test_dotenv_only_fills_missing_keys():
    env = dec.preflight(BASE, "", "", "TRADING_MODE=live\nENABLE_REAL_ORDERS=true\nX=1\n")
    assert env["TRADING_MODE"] == "paper_train" and env["ENABLE_REAL_ORDERS"] == "false" and env["X"] == "1"
    filled = dec.preflight("ENABLE_REAL_ORDERS=false", "", "", "TRADING_MODE=paper_train\n")
    assert filled["TRADING_MODE"] == "paper_train"


@pytest.mark.parametrize("value", ["True", "1", "yes", "on", ""])
def test_flag_must_be_literal_true_or_false(value):
    with pytest.raises(dec.Refused, match="true or false"):
        dec.preflight(BASE, "", f"{FLAG}={value}" if value else f"{FLAG}=", "")


def test_real_trading_flags_refused():
    with pytest.raises(dec.Refused, match="ENABLE_REAL_ORDERS"):
        dec.preflight("TRADING_MODE=paper_train ENABLE_REAL_ORDERS=true", "", "", "")


def test_env_files_parsing(tmp_path):
    missing = tmp_path / "missing.env"
    assert dec.preflight(BASE, f"{missing} (ignore_errors=yes)", "", "")
    with pytest.raises(dec.Refused, match="missing"):
        dec.preflight(BASE, f"{missing} (ignore_errors=no)", "", "")
    with pytest.raises(dec.Refused, match="parse"):
        dec.preflight(BASE, "garbage-without-flags", "", "")
    # review 78 R2: a recognised item followed by an unparsed remainder is refused too
    with pytest.raises(dec.Refused, match="parse"):
        dec.env_files(f"{missing} (ignore_errors=yes) GARBAGE")
    two = dec.env_files(f"{missing} (ignore_errors=yes) {missing}.b (ignore_errors=no)")
    assert [flag for _, flag in two] == [True, False]


def test_postcheck_reads_the_real_process_environment():
    good = environ(TRADING_MODE="paper_train", ENABLE_REAL_ORDERS="false", LIVE_TRADING_CONFIRMED="false",
                   **{FLAG: "true"})
    assert dec.postcheck(good, f"{FLAG}=true")[FLAG] == "true"
    stale = environ(TRADING_MODE="paper_train", **{FLAG: "false"})
    with pytest.raises(dec.Refused, match="running process"):
        dec.postcheck(stale, f"{FLAG}=true")
    with pytest.raises(dec.Refused, match="running process"):
        dec.postcheck(environ(TRADING_MODE="paper_train"), f"{FLAG}=true")


def test_postcheck_invariants_with_dotenv_fill():
    proc = environ(**{FLAG: "true"})
    assert dec.postcheck(proc, f"{FLAG}=true", "TRADING_MODE=paper_train\n")
    with pytest.raises(dec.Refused, match="LIVE_TRADING_CONFIRMED"):
        dec.postcheck(environ(TRADING_MODE="paper_train", LIVE_TRADING_CONFIRMED="true", **{FLAG: "true"}),
                      f"{FLAG}=true")


CHECK_DIR = Path(__file__).resolve().parents[1] / "deploy" / "research_eval"
MOD = "src/services/candidate.py"
SRC = b"VALUE = 'pinned'\n"


def _tree(tmp_path, content=SRC):
    services = tmp_path / "tree" / "src" / "services"
    services.mkdir(parents=True)
    (tmp_path / "tree" / "src" / "__init__.py").write_bytes(b"")
    (services / "__init__.py").write_bytes(b"")
    (tmp_path / "tree" / MOD).write_bytes(content)
    (tmp_path / "pycache").mkdir()
    return tmp_path / "tree", tmp_path / "pycache"


def _run_optimized(tree, prefix, pinned_hash, *, extra_path=None, use_prefix=True):
    """Run verify_staged_import under -O and PYTHONOPTIMIZE=2 (asserts stripped)."""
    import os
    import subprocess
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])\n"
        + ("sys.path.insert(0, sys.argv[5])\n" if extra_path else "")
        + "import deploy_env_check as d\n"
        "try:\n"
        "    d.verify_staged_import(sys.argv[2], [sys.argv[3]], {sys.argv[3]: sys.argv[4]}, sys.argv[6])\n"
        "except d.Refused as e:\n"
        "    print('REFUSED', e); sys.exit(2)\n"
        "print('OK')\n")
    args = [sys.executable, "-O", "-B"]
    if use_prefix:
        args += ["-X", f"pycache_prefix={prefix}"]
    args += ["-c", code, str(CHECK_DIR), str(tree), MOD, pinned_hash, str(extra_path or ""), str(prefix)]
    env = {**os.environ, "PYTHONOPTIMIZE": "2"}
    env.pop("PYTHONPYCACHEPREFIX", None)
    return subprocess.run(args, capture_output=True, text=True, env=env)


def test_staged_import_accepts_pinned_source_even_when_optimized(tmp_path):
    import hashlib
    tree, prefix = _tree(tmp_path)
    out = _run_optimized(tree, prefix, hashlib.sha256(SRC).hexdigest())
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout + out.stderr


def test_staged_import_refuses_wrong_hash_when_optimized(tmp_path):
    tree, prefix = _tree(tmp_path)
    out = _run_optimized(tree, prefix, "0" * 64)
    assert out.returncode == 2 and "tree bytes differ" in out.stdout


def test_staged_import_refuses_module_loaded_elsewhere_when_optimized(tmp_path):
    import hashlib
    tree, prefix = _tree(tmp_path)
    shadow = tmp_path / "shadow" / "src" / "services"
    shadow.mkdir(parents=True)
    (tmp_path / "shadow" / "src" / "__init__.py").write_bytes(b"")
    (shadow / "__init__.py").write_bytes(b"")
    (shadow / "candidate.py").write_bytes(b"VALUE = 'shadow'\n")
    out = _run_optimized(tree, prefix, hashlib.sha256(SRC).hexdigest(), extra_path=tmp_path / "shadow")
    assert out.returncode == 2 and "imported elsewhere" in out.stdout


def test_staged_import_refuses_without_dedicated_pycache_prefix(tmp_path):
    import hashlib
    tree, prefix = _tree(tmp_path)
    out = _run_optimized(tree, prefix, hashlib.sha256(SRC).hexdigest(), use_prefix=False)
    assert out.returncode == 2 and "pycache prefix" in out.stdout


def test_validator_has_no_asserts_and_runs_isolated():
    import ast
    import re
    script = (CHECK_DIR / "deploy_bot_files.sh").read_text(encoding="utf-8")
    heredoc = re.search(r"<<'PY'\n(.*?)\nPY\n", script, re.S).group(1)
    assert not [n for n in ast.walk(ast.parse(heredoc)) if isinstance(n, ast.Assert)]
    module = ast.parse((CHECK_DIR / "deploy_env_check.py").read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(module) if isinstance(n, ast.Assert)]
    assert '/usr/bin/python3 -I -B -X pycache_prefix="$SCRATCH/pycache" -' in script


def test_cli_exit_codes(tmp_path, capsys):
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{FLAG}=false\n", encoding="utf-8")
    assert dec.main(["pre", "--environment", BASE, "--env-files", "", "--vars", f"{FLAG}=true",
                     "--dotenv", str(dotenv)]) == 2
    proc = tmp_path / "environ"
    proc.write_bytes(environ(TRADING_MODE="paper_train", **{FLAG: "true"}))
    assert dec.main(["post", "--environ", str(proc), "--vars", f"{FLAG}=true",
                     "--dotenv", str(tmp_path / "absent")]) == 0
