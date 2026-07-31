import sqlite3
from pathlib import Path

from src.services import emergency_health_monitor as ehm
from src.services import paper_training_metrics as ptm


def test_hour_metrics_survive_process_restart(tmp_path, monkeypatch):
    db_path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE closed_trades ("
        "trade_id TEXT, entry_ts REAL, exit_ts REAL, learning_source TEXT)"
    )
    conn.executemany(
        "INSERT INTO closed_trades VALUES (?,?,?,?)",
        [
            ("fresh_learned", 9900.0, 9950.0, "paper_control"),
            ("fresh_unlearned", 9800.0, 9850.0, ""),
            ("old", 1000.0, 1100.0, "paper_control"),
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(ptm, "_cache_db_path", lambda: str(db_path))
    monkeypatch.setattr(ptm.time, "time", lambda: 10000.0)

    metrics = ptm.PaperTrainingMetrics().get_metrics()
    assert metrics["paper_entries_1h"] == 2
    assert metrics["paper_exits_1h"] == 2
    assert metrics["paper_learning_updates_1h"] == 1
    assert metrics["last_paper_entry_age_s"] == 100.0
    assert metrics["last_paper_exit_age_s"] == 50.0
    assert metrics["last_learning_update_age_s"] == 50.0


def test_dashboard_monitor_scans_full_window_and_counts_open_positions():
    now = 10000.0
    ehm._monitor_state["last_dashboard_metrics"] = {"timestamp": now - 999}
    logs = [
        "[V5_BRIDGE_DASHBOARD_METRICS] closed_today=0 "
        "paper_exits_1h=0 learning_updates=0 open=1 quota_state=normal"
    ] + [f"filler {i}" for i in range(100)]

    is_zero, reason = ehm.detect_dashboard_zero(logs, now)

    assert is_zero is False
    assert reason == "Dashboard metrics flowing"
    assert ehm._monitor_state["last_dashboard_metrics"]["open_positions"] == 1
    assert ehm._monitor_state["last_dashboard_metrics"]["timestamp"] == now


def test_close_is_excursion_enriched_before_authoritative_archive():
    source = Path("src/services/paper_trade_executor.py").read_text(
        encoding="utf-8"
    )
    close_body = source.split("def close_paper_position(", 1)[1].split(
        "def get_paper_open_positions", 1
    )[0]

    assert close_body.index("closed_trade.update(compute_excursion") < close_body.index(
        "_archive_paper_close(closed_trade)"
    )


def test_strict_canonical_close_reaches_adaptive_learning_hook():
    source = Path("src/services/paper_trade_executor.py").read_text(
        encoding="utf-8"
    )
    close_body = source.split("def close_paper_position(", 1)[1].split(
        "def get_paper_open_positions", 1
    )[0]

    candidate = close_body.index("canonical_learning_candidate =")
    strict = close_body.index('pos.get("strict_ev") is True', candidate)
    recorder = close_body.index(
        "_record_adaptive_learning_close(closed_trade, pos, pnl_data)",
        strict,
    )
    assert candidate < strict < recorder
