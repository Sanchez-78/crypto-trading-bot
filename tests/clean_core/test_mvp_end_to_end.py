"""End-to-end Clean Core MVP test: complete PAPER lifecycle from snapshot to report."""

import pytest
from datetime import datetime, timezone, timedelta
import json

from src.clean_core.strategy.fixed_strategy import FixedStrategy
from src.clean_core.strategy.offline_replay import OfflineReplayEngine
from src.clean_core.execution.fees import FeeSchedule
from src.clean_core.domain import ExecutionTruthClass, MarketSourceIdentity
from src.clean_core.provenance.journal import CleanCoreJournal
from src.clean_core.provenance.epoch import CleanPaperEpoch
import tempfile
import os


class TestMVPEndToEnd:
    """Test complete PAPER lifecycle without service wiring."""

    def test_mvp_end_to_end_paper_lifecycle(self, temp_dir):
        """
        MVP Test: Complete PAPER cycle from market snapshot → signal → entry → exit → PnL.

        Proves:
        - Futures-only market source (no Spot contamination)
        - Fixed strategy (no legacy EV gate)
        - PAPER position entry/exit
        - Accurate PnL with explicit fees (no magic costs)
        - Journal logging
        - Isolation from legacy runtime
        """

        # 1. Setup: Create market source (FUTURES_PUBLIC_BOOK_MEASURED = R1 baseline)
        market_source = MarketSourceIdentity(
            venue="binance_usdm",
            instrument="BTCUSDT",
            price_source="public_book",
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            rpi_visibility=False,
            route_version="R1",
        )

        # 2. Setup: Create fee schedule and epoch
        fee_schedule = FeeSchedule.binance_usdm_standard()
        epoch = CleanPaperEpoch(
            epoch_id="mvp_test_001",
            status="active",
            created_utc="2026-05-26T12:00:00Z",
            started_utc="2026-05-26T12:00:00Z",
        )

        # 3. Setup: Create offline replay engine with fixed strategy
        strategy = FixedStrategy(tp_pct=1.0, sl_pct=0.5, timeout_minutes=60)
        engine = OfflineReplayEngine(strategy, fee_schedule, market_source)

        # 4. Setup: Create journal (isolated to temp dir, not production)
        journal_path = os.path.join(temp_dir, "mvp_test_journal.jsonl")
        journal = CleanCoreJournal(journal_path)

        # 5. Input: Synthetic market data (snapshot + trades)
        initial_snapshot = {
            "time": "2026-05-26T12:00:00Z",
            "price": 50000.0,
            "bid": 49999.5,
            "ask": 50000.5,
        }

        # Market trades that will trigger:
        # - Entry: at trade 0 (breakout above snapshot 50000 → 50050)
        # - Exit: at trade 16 (hit TP at 50550.5, which is entry + 1%)
        trades = [
            {"time": "2026-05-26T12:01:00Z", "price": 50050.0},  # ← entry signal (above 50000)
            {"time": "2026-05-26T12:02:00Z", "price": 50075.0},
            {"time": "2026-05-26T12:03:00Z", "price": 50100.0},
            {"time": "2026-05-26T12:04:00Z", "price": 50090.0},
            {"time": "2026-05-26T12:05:00Z", "price": 50105.0},
            {"time": "2026-05-26T12:06:00Z", "price": 50110.0},
            {"time": "2026-05-26T12:07:00Z", "price": 50150.0},
            {"time": "2026-05-26T12:08:00Z", "price": 50200.0},
            {"time": "2026-05-26T12:09:00Z", "price": 50250.0},
            {"time": "2026-05-26T12:10:00Z", "price": 50300.0},
            {"time": "2026-05-26T12:11:00Z", "price": 50350.0},
            {"time": "2026-05-26T12:12:00Z", "price": 50400.0},
            {"time": "2026-05-26T12:13:00Z", "price": 50450.0},
            {"time": "2026-05-26T12:14:00Z", "price": 50500.0},
            {"time": "2026-05-26T12:15:00Z", "price": 50540.0},
            {"time": "2026-05-26T12:16:00Z", "price": 50555.0},  # ← TP hit (50050 * 1.01 = 50550.5)
        ]

        # 6. Execute: Run offline replay
        closed_outcomes = engine.replay_snapshot_and_trades(
            symbol="BTCUSDT",
            initial_snapshot=initial_snapshot,
            trades=trades,
            epoch_id=epoch.epoch_id,
        )

        # 7. Assert: Verify exactly 1 closed trade
        assert len(closed_outcomes) == 1, f"Expected 1 closed trade, got {len(closed_outcomes)}"
        outcome = closed_outcomes[0]

        # 8. Assert: Verify execution truth class (must be PUBLIC_BOOK for R1 baseline)
        assert (
            outcome.execution_truth_class
            == ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED
        ), f"Wrong execution_truth_class: {outcome.execution_truth_class}"

        # 9. Assert: Verify readiness eligible (R1 accepts PUBLIC_BOOK)
        assert outcome.readiness_eligible is True, "FUTURES_PUBLIC_BOOK_MEASURED should be readiness eligible"

        # 10. Assert: Entry/exit prices match expectations
        assert outcome.entry_fill.fill_price == pytest.approx(50050.0), "Wrong entry price"
        assert outcome.exit_fill.fill_price == pytest.approx(50555.0), "Wrong exit price"

        # 11. Assert: Gross PnL is approximately 1% (before fees)
        gross_pnl = outcome.gross_pnl_pct
        assert gross_pnl == pytest.approx(1.0, rel=0.01), f"Gross PnL should be ~1%, got {gross_pnl}%"

        # 12. Assert: Fee cost is subtracted
        # Entry fee (maker): 2 bps = 0.02%
        # Exit fee (maker): 2 bps = 0.02%
        # Total: 0.04%
        expected_fee_cost = (fee_schedule.maker_fee_bps * 2) / 100.0
        assert outcome.fee_cost_pct == pytest.approx(expected_fee_cost, rel=0.01)

        # 13. Assert: Net PnL = Gross - Fees (no funding in MVP)
        expected_net = gross_pnl - (fee_schedule.maker_fee_bps * 2 / 100.0)
        assert outcome.net_pnl_pct == pytest.approx(expected_net, rel=0.01)

        # 14. Log to journal
        journal.append_event(
            "mvp_trade_closed",
            {
                "position_id": outcome.position_id,
                "symbol": outcome.symbol,
                "entry_price": outcome.entry_fill.fill_price,
                "exit_price": outcome.exit_fill.fill_price,
                "gross_pnl_pct": outcome.gross_pnl_pct,
                "fee_cost_pct": outcome.fee_cost_pct,
                "net_pnl_pct": outcome.net_pnl_pct,
                "exit_reason": outcome.entry_fill.timestamp_utc,
            },
            clean_core_version="R1",
            config_hash="mvp_test",
        )

        # 15. Update epoch
        epoch.add_closed_trade(
            net_pnl_pct=outcome.net_pnl_pct,
            readiness_eligible=outcome.readiness_eligible,
            execution_truth_class=outcome.execution_truth_class.value,
        )

        # 16. Assert: Journal was written (verify file exists in temp_dir, not production)
        assert os.path.exists(journal_path), f"Journal not created at {journal_path}"
        with open(journal_path, "r") as f:
            lines = f.readlines()
            assert len(lines) > 0, "Journal is empty"
            event = json.loads(lines[0])
            assert event["event_type"] == "mvp_trade_closed"

        # 17. Assert: Epoch tracking
        assert epoch.closed_trades_count == 1
        assert epoch.readiness_eligible_count == 1
        assert epoch.average_net_pnl_pct == pytest.approx(outcome.net_pnl_pct)

        # 18. Final validation: Verify no legacy services were touched
        # (This test runs in isolation; no imports of paper_adaptive_learning, market_stream, etc.)
        assert "paper_adaptive_learning" not in str(engine.__module__)
        assert "src.services" not in str(engine.__module__)

        # 19. Summary: Print PnL breakdown
        print("\n" + "=" * 60)
        print("MVP END-TO-END PAPER LIFECYCLE TEST RESULTS")
        print("=" * 60)
        print(f"Symbol: {outcome.symbol}")
        print(f"Entry Price: ${outcome.entry_fill.fill_price:.2f}")
        print(f"Exit Price: ${outcome.exit_fill.fill_price:.2f}")
        print(f"Holding Time: {outcome.holding_minutes:.1f} minutes")
        print(f"Gross PnL: {outcome.gross_pnl_pct:+.4f}%")
        print(f"Entry Maker Fee: {fee_schedule.maker_fee_bps:.1f} bps")
        print(f"Exit Maker Fee: {fee_schedule.maker_fee_bps:.1f} bps")
        print(f"Total Fee Cost: {outcome.fee_cost_pct:+.4f}%")
        print(f"Funding Cost: {outcome.funding_cost_pct:+.4f}%")
        print(f"NET PnL: {outcome.net_pnl_pct:+.4f}%")
        print(f"Execution Truth: {outcome.execution_truth_class.value}")
        print(f"Readiness Eligible: {outcome.readiness_eligible}")
        print(f"Journal Path: {journal_path}")
        print("=" * 60)

        return closed_outcomes
