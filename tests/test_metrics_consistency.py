from src.services.exit_attribution import (
    build_exit_ctx,
    render_exit_attribution_summary,
    reset_exit_stats,
    update_exit_attribution,
)
from src.services.metrics_engine import MetricsEngine


def test_canonical_stats_read_top_level_profit_from_firestore_history():
    stats = MetricsEngine().compute_canonical_trade_stats([
        {
            "symbol": "BTCUSDT",
            "regime": "RANGING",
            "close_reason": "TP",
            "profit": 0.0025,
        },
        {
            "symbol": "ETHUSDT",
            "regime": "RANGING",
            "close_reason": "SL",
            "profit": -0.0015,
        },
    ])

    assert stats["trades_total"] == 2
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["flats"] == 0
    assert round(stats["net_pnl"], 7) == 0.001
    assert stats["per_symbol"]["BTCUSDT"]["wins"] == 1
    assert stats["per_exit_type"]["TP"]["wins"] == 1


def test_canonical_stats_still_support_nested_evaluation_profit():
    stats = MetricsEngine().compute_canonical_trade_stats([
        {
            "symbol": "SOLUSDT",
            "regime": "HIGH_VOL",
            "close_reason": "SCRATCH_EXIT",
            "evaluation": {"profit": -0.0003},
        }
    ])

    assert stats["trades_total"] == 1
    assert stats["losses"] == 1
    assert stats["net_pnl"] == -0.0003


def test_exit_attribution_summary_uses_session_scope_and_abs_share():
    reset_exit_stats()

    update_exit_attribution(
        build_exit_ctx(
            sym="BTCUSDT",
            regime="RANGING",
            side="BUY",
            entry_price=100.0,
            exit_price=100.2,
            size=1.0,
            hold_seconds=60,
            gross_pnl=0.0010,
            fee_cost=0.0,
            slippage_cost=0.0,
            net_pnl=0.0010,
            mfe=0.0020,
            mae=-0.0005,
            final_exit_type="PARTIAL_TP_25",
            was_winner=True,
        )
    )
    update_exit_attribution(
        build_exit_ctx(
            sym="ETHUSDT",
            regime="RANGING",
            side="BUY",
            entry_price=100.0,
            exit_price=99.6,
            size=1.0,
            hold_seconds=120,
            gross_pnl=-0.0030,
            fee_cost=0.0,
            slippage_cost=0.0,
            net_pnl=-0.0030,
            mfe=0.0005,
            mae=-0.0035,
            final_exit_type="SCRATCH_EXIT",
            was_winner=False,
        )
    )

    summary = render_exit_attribution_summary()

    assert "Session exits: 2" in summary
    assert "Session Net PnL: -0.00200000" in summary
    assert "share_abs=" in summary
    assert "pct=" not in summary
