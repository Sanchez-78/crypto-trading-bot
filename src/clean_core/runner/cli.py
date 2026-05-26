"""CLI for standalone forward PAPER runner."""

import argparse
import json
import logging
import sys
from pathlib import Path

from .forward_paper_runner import ForwardPaperRunner
from .simulated_futures_feed import SimulatedFuturesFeed


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_simulated_feed_data() -> tuple[dict, list[dict]]:
    """Create default simulated feed data for MVP validation."""
    snapshot = {
        "time": "2026-05-26T12:00:00Z",
        "price": 50000.0,
        "bid": 49999.5,
        "ask": 50000.5,
    }
    trades = [
        {"time": "2026-05-26T12:01:00Z", "price": 50050.0},
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
        {"time": "2026-05-26T12:16:00Z", "price": 50555.0},
    ]
    return snapshot, trades


def main():
    """CLI entry point for forward PAPER runner."""
    parser = argparse.ArgumentParser(
        description="Clean Core MVP forward PAPER runner (simulated or live public feed)"
    )
    parser.add_argument(
        "--mode",
        choices=["simulated", "live-public-paper"],
        default="simulated",
        help="Feed mode: simulated (default) or live-public-paper",
    )
    parser.add_argument(
        "--symbol",
        default="BTCUSDT",
        help="Trading symbol (default: BTCUSDT)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for journal and report (must exist, no defaults)",
    )

    args = parser.parse_args()

    try:
        # Validate output dir
        output_path = Path(args.output_dir)
        if not output_path.exists():
            print(f"ERROR: output_dir does not exist: {args.output_dir}", file=sys.stderr)
            sys.exit(1)
        if not output_path.is_absolute():
            print(f"ERROR: output_dir must be absolute: {args.output_dir}", file=sys.stderr)
            sys.exit(1)

        if args.mode == "simulated":
            logger.info("Starting simulated PAPER run")
            snapshot, trades = create_simulated_feed_data()
            feed = SimulatedFuturesFeed(snapshot, trades)
        else:
            logger.error("Live-public-paper mode not yet implemented in MVP")
            sys.exit(1)

        # Run forward PAPER runner
        runner = ForwardPaperRunner(
            feed=feed,
            symbol=args.symbol,
            output_dir=args.output_dir,
        )
        report = runner.run()

        # Print report
        print("\n" + "=" * 60)
        print("FORWARD PAPER RUN COMPLETE")
        print("=" * 60)
        print(f"Epoch ID: {report['epoch_id']}")
        print(f"Symbol: {report['symbol']}")
        print(f"Closed Trades: {report['closed_trades_count']}")
        if report['closed_trades_count'] > 0:
            print(f"Average Net PnL: {report['average_net_pnl_pct']:+.4f}%")
        print(f"Journal: {report['journal_path']}")
        print("=" * 60)

        # Write report JSON
        report_path = output_path / f"report_{report['epoch_id']}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Report saved: {report_path}\n")

    except Exception as e:
        logger.exception(f"Forward PAPER runner failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
