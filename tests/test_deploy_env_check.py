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


def test_cli_exit_codes(tmp_path, capsys):
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{FLAG}=false\n", encoding="utf-8")
    assert dec.main(["pre", "--environment", BASE, "--env-files", "", "--vars", f"{FLAG}=true",
                     "--dotenv", str(dotenv)]) == 2
    proc = tmp_path / "environ"
    proc.write_bytes(environ(TRADING_MODE="paper_train", **{FLAG: "true"}))
    assert dec.main(["post", "--environ", str(proc), "--vars", f"{FLAG}=true",
                     "--dotenv", str(tmp_path / "absent")]) == 0
