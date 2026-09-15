"""Production-linked RED gate for the Phase 4/5 denominator reconciliation.

Phase 0 evidence (local `cache.sqlite`, 472 closed rows, read-only):

    exit_reason=TIMEOUT_NO_PRICE   n=106   exit_price=0.0   pnl_pct=0.0   win=0

Those rows are positions the executor closed WITHOUT ever obtaining a market
price.  The trading code already treats them as non-trades everywhere it
matters -- `paper_trade_executor` stamps `learning_skipped=True`, skips
`record_close`, and `canonical_learning_eligibility()` rejects them with the
explicit reason `timeout_no_price_invalid`.

The dashboard, however, reads the same rows out of `closed_trades` and books
each one as a LOSS (`pnl_pct=0.0` is not `> 0`).  So two denominators in one
system disagree about what counts as a trade.

Phase 4 requires "raw input count == the sum of all mutually-exclusive
buckets" and Phase 5 requires the qualified cohort be shown SEPARATELY from
the all-source headline.  These tests assert exactly that, and -- critically --
that the all-source headline is NOT quietly redefined to raise the number.

PAPER-only: builds a throwaway SQLite file in tmp_path; touches no runtime or
production database.
"""

import sqlite3

import pytest

from src.services import dashboard_web


def _make_cache(tmp_path, rows, with_outcome=True):
    """Create a minimal closed_trades cache with the columns the reader uses.

    `with_outcome=False` reproduces a legacy cache.sqlite predating the
    `outcome` column, so the reader's fallback path stays covered.
    """
    db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(db))
    outcome_col = ", outcome TEXT" if with_outcome else ""
    conn.execute(
        "CREATE TABLE closed_trades ("
        "id INTEGER PRIMARY KEY, exit_ts REAL, pnl_usd REAL, pnl_pct REAL, "
        f"exit_reason TEXT, source TEXT{outcome_col})"
    )
    if with_outcome:
        conn.executemany(
            "INSERT INTO closed_trades "
            "(id, exit_ts, pnl_usd, pnl_pct, exit_reason, source, outcome) "
            "VALUES (?,?,?,?,?,?,?)",
            [r + (("VOID" if r[4] == "TIMEOUT_NO_PRICE" else None),) for r in rows],
        )
    else:
        conn.executemany(
            "INSERT INTO closed_trades "
            "(id, exit_ts, pnl_usd, pnl_pct, exit_reason, source) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
    conn.commit()
    conn.close()
    return str(db)


# 3 real wins, 2 real losses, 5 TIMEOUT_NO_PRICE non-trades.
_ROWS = (
    [(i, 1000.0 + i, 1.0, 0.5, "TP", "rde_take") for i in range(1, 4)]
    + [(i, 1000.0 + i, -1.0, -0.5, "TIMEOUT", "rde_take") for i in range(4, 6)]
    + [(i, 1000.0 + i, 0.0, 0.0, "TIMEOUT_NO_PRICE", "rde_take") for i in range(6, 11)]
)


def test_qualified_window_metrics_reconciles_exactly(tmp_path):
    """RED-1: raw == qualified + excluded, with the excluded reason named."""
    assert hasattr(dashboard_web, "_qualified_window_metrics"), \
        "_qualified_window_metrics() is not defined"

    cache = _make_cache(tmp_path, _ROWS)
    m = dashboard_web._qualified_window_metrics(cache, 100)
    assert m is not None

    assert m["raw_n"] == 10
    assert m["excluded_n"] == 5
    assert m["qualified_n"] == 5
    # The Phase 4 invariant, asserted literally.
    assert m["raw_n"] == m["qualified_n"] + m["excluded_n"]
    assert m["excluded_by_reason"] == {"timeout_no_price_invalid": 5}


def test_qualified_win_rate_uses_only_the_qualified_denominator(tmp_path):
    """RED-2: 3 wins of 5 real trades = 60%, not 3 of 10 = 30%."""
    cache = _make_cache(tmp_path, _ROWS)
    m = dashboard_web._qualified_window_metrics(cache, 100)

    assert m["qualified_wins"] == 3
    assert m["qualified_win_rate_pct"] == pytest.approx(60.0)


def test_all_source_headline_is_not_redefined(tmp_path):
    """RED-3: the raw all-source WR must still count non-trades as losses.

    This is the anti-gaming assertion.  Exposing a qualified cohort is only
    legitimate while the unfiltered headline stays exactly as it was -- 3 wins
    out of all 10 rows = 30%.  If this ever starts reporting 60%, the headline
    denominator has been silently narrowed to hit the WR target.
    """
    cache = _make_cache(tmp_path, _ROWS)
    raw = dashboard_web._rolling_window_metrics(cache, 100)

    assert raw["n"] == 10
    assert raw["wins"] == 3
    assert raw["win_rate_pct"] == pytest.approx(30.0)


def test_excluded_rows_are_never_silently_dropped(tmp_path):
    """RED-4: a cohort of nothing but non-trades reports 0 qualified, not None."""
    cache = _make_cache(
        tmp_path,
        [(i, 1000.0 + i, 0.0, 0.0, "TIMEOUT_NO_PRICE", "rde_take") for i in range(1, 4)],
    )
    m = dashboard_web._qualified_window_metrics(cache, 100)

    assert m["raw_n"] == 3
    assert m["qualified_n"] == 0
    assert m["excluded_n"] == 3
    # No qualified rows means no defensible win rate -- report None, not 0.0,
    # so the dashboard cannot render an invented "0%" as if it were measured.
    assert m["qualified_win_rate_pct"] is None


def test_legacy_cache_without_outcome_column_still_reconciles(tmp_path):
    """A cache.sqlite predating the `outcome` column must not blank the metric.

    The reader classifies on exit_reason alone there; returning None instead
    would take the whole qualified cohort off the dashboard.
    """
    cache = _make_cache(tmp_path, _ROWS, with_outcome=False)
    m = dashboard_web._qualified_window_metrics(cache, 100)

    assert m is not None, "legacy schema blanked the qualified metric"
    assert m["raw_n"] == 10
    assert m["qualified_n"] == 5
    assert m["excluded_n"] == 5
    assert m["excluded_by_reason"] == {"timeout_no_price_invalid": 5}


def test_void_outcome_is_excluded_even_with_an_unmapped_exit_reason(tmp_path):
    """outcome=VOID alone is enough to keep a row out of the qualified cohort."""
    rows = [
        (1, 1001.0, 1.0, 0.5, "TP", "rde_take"),
        (2, 1002.0, 0.0, 0.0, "SOME_FUTURE_REASON", "rde_take"),
    ]
    db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE closed_trades ("
        "id INTEGER PRIMARY KEY, exit_ts REAL, pnl_usd REAL, pnl_pct REAL, "
        "exit_reason TEXT, source TEXT, outcome TEXT)"
    )
    conn.executemany(
        "INSERT INTO closed_trades "
        "(id, exit_ts, pnl_usd, pnl_pct, exit_reason, source, outcome) "
        "VALUES (?,?,?,?,?,?,?)",
        [rows[0] + (None,), rows[1] + ("VOID",)],
    )
    conn.commit()
    conn.close()

    m = dashboard_web._qualified_window_metrics(str(db), 100)
    assert m["raw_n"] == 2
    assert m["qualified_n"] == 1
    assert m["excluded_by_reason"] == {"void_no_fill_price": 1}


# ── Mixed old/new semantics + client-field stability (audit 2026-09-15) ──────

def test_mixed_void_and_legacy_timeout_no_price_in_one_window(tmp_path):
    """A single window holding BOTH marker generations must reconcile.

    The VOID fix only affects closes written after it shipped. Every row that
    already existed keeps the legacy shape -- `exit_reason=TIMEOUT_NO_PRICE`
    with `win=0` and no VOID outcome (verified on the real cohort: all 106
    historical rows are still legacy, deliberately not backfilled). So for the
    entire lifetime of this database a recent window will straddle BOTH
    semantics.

    Earlier evidence only covered each generation in isolation, which is
    exactly where a reconciliation bug hides: double-counting a row matched by
    both rules, or missing one matched by neither.
    """
    rows = [
        # 2 genuine wins and 1 genuine loss -- the real trades.
        (1, 1001.0, 1.0, 0.5, "TP", "rde_take", "WIN"),
        (2, 1002.0, 1.0, 0.5, "TP", "rde_take", "WIN"),
        (3, 1003.0, -1.0, -0.5, "TIMEOUT", "rde_take", "LOSS"),
        # LEGACY pre-fix non-trades: exit_reason marker only, booked win=0.
        (4, 1004.0, 0.0, 0.0, "TIMEOUT_NO_PRICE", "rde_take", None),
        (5, 1005.0, 0.0, 0.0, "TIMEOUT_NO_PRICE", "rde_take", "FLAT"),
        # NEW post-fix non-trades: explicit VOID outcome.
        (6, 1006.0, None, None, "TIMEOUT_NO_PRICE", "rde_take", "VOID"),
        (7, 1007.0, None, None, "SOME_FUTURE_REASON", "rde_take", "VOID"),
    ]
    db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE closed_trades ("
        "id INTEGER PRIMARY KEY, exit_ts REAL, pnl_usd REAL, pnl_pct REAL, "
        "exit_reason TEXT, source TEXT, outcome TEXT)"
    )
    conn.executemany(
        "INSERT INTO closed_trades "
        "(id, exit_ts, pnl_usd, pnl_pct, exit_reason, source, outcome) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()

    m = dashboard_web._qualified_window_metrics(str(db), 100)

    assert m["raw_n"] == 7
    # 4 excluded: 2 legacy + 2 VOID. A row matched by BOTH rules (id 6, which
    # carries the legacy exit_reason AND outcome=VOID) must be counted once.
    assert m["excluded_n"] == 4
    assert m["qualified_n"] == 3
    assert m["raw_n"] == m["qualified_n"] + m["excluded_n"]

    # Each generation is attributed to its own reason, and they sum to the total.
    assert m["excluded_by_reason"] == {
        "timeout_no_price_invalid": 3,   # ids 4, 5, 6 (exit_reason matched first)
        "void_no_fill_price": 1,         # id 7 (VOID with an unmapped reason)
    }
    assert sum(m["excluded_by_reason"].values()) == m["excluded_n"]

    # 2 wins out of the 3 real trades.
    assert m["qualified_wins"] == 2
    assert m["qualified_win_rate_pct"] == pytest.approx(66.67, abs=0.01)


def test_headline_win_rate_field_name_is_structurally_pinned():
    """Guard against a client silently reading a different WR field.

    Three win-rate families are published side by side -- the all-source
    headline, `canonical_*`, and `qualified_*`. They legitimately differ (48%
    vs 64% on the real cohort), so a client that quietly switched which one it
    renders would change the reported number without any calculation changing.
    That is the exact failure mode the anti-gaming rules exist to prevent, and
    it would not show up as a test failure anywhere else.

    This is structural rather than a value assertion: it reads the shipped
    dashboard source and pins BOTH the emitted key set and the key the client
    actually renders. Adding, renaming or re-pointing a field then requires a
    deliberate edit here.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).parents[1] / "src/services/dashboard_web.py").read_text(
        encoding="utf-8"
    )

    emitted = set(re.findall(r"""['"]([a-z_]*win_rate[a-z_]*)['"]\s*:""", src))
    assert emitted == {
        "win_rate_pct",
        "win_rate_window",
        "win_rate_basis",
        "win_rate_scope",
        "win_rate_denominator",
        "canonical_win_rate_pct",
        "canonical_win_rate_window",
        "qualified_win_rate_pct",
        "qualified_win_rate_denominator",
    }, f"win-rate field set changed: {sorted(emitted)}"

    # The browser client must render the all-source headline and nothing else.
    client_reads = set(re.findall(r"data\.([a-z_]*win_rate[a-z_]*)", src))
    assert client_reads == {"win_rate_pct"}, (
        "the dashboard client reads a non-canonical win-rate field: "
        f"{sorted(client_reads)}"
    )
