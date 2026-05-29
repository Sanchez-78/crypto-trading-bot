#!/usr/bin/env python3
"""
V5 Bot Status Analyzer
Shows trading and learning status with detailed metrics
Run on Hetzner: python3 bot_status_analyzer.py
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, Any, Optional

class BotStatusAnalyzer:
    def __init__(self, api_url: str = "http://localhost:5000"):
        self.api_url = api_url
        self.metrics = None
        self.learning = None

    def fetch_metrics(self) -> bool:
        """Fetch metrics from bot API"""
        try:
            with urllib.request.urlopen(f"{self.api_url}/metrics", timeout=5) as response:
                self.metrics = json.loads(response.read().decode())
            return True
        except Exception as e:
            print(f"✗ Failed to fetch metrics: {e}")
            return False

    def fetch_learning(self) -> bool:
        """Fetch learning history from bot API"""
        try:
            with urllib.request.urlopen(f"{self.api_url}/metrics/learning-history", timeout=5) as response:
                self.learning = json.loads(response.read().decode())
            return True
        except Exception as e:
            print(f"✗ Failed to fetch learning history: {e}")
            return False

    def print_status(self):
        """Print current bot status"""
        print("\n" + "="*60)
        print("V5 BOT TRADING & LEARNING STATUS")
        print("="*60)
        print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
        print()

        if not self.metrics:
            print("✗ Could not connect to bot API")
            return

        # Bot Status
        print("📊 BOT STATUS")
        print("-" * 60)
        running = self.metrics.get('running', False)
        status = "✓ RUNNING" if running else "✗ STOPPED"
        print(f"Status: {status}")
        print(f"Epoch: {self.metrics.get('epoch_id', 'N/A')}")
        print(f"Uptime: {self.metrics.get('uptime_seconds', 0)} seconds")
        print(f"Feed Connected: {'✓ Yes' if self.metrics.get('feed_connected') else '✗ No'}")
        print(f"Symbols with Data: {self.metrics.get('symbols_with_data', 0)}")
        print()

        # Trading Activity
        print("💹 TRADING ACTIVITY (CURRENT SESSION)")
        print("-" * 60)
        entries_attempted = self.metrics.get('entries_attempted', 0)
        entries_successful = self.metrics.get('entries_successful', 0)
        entries_rejected = self.metrics.get('entries_rejected_by_gate', 0)
        trades_closed = self.metrics.get('trades_closed', 0)

        print(f"Entries Attempted: {entries_attempted}")
        print(f"Entries Successful: {entries_successful}")
        print(f"Entries Rejected: {entries_rejected}")
        success_rate = (entries_successful / entries_attempted * 100) if entries_attempted > 0 else 0
        print(f"Entry Success Rate: {success_rate:.1f}%")
        print(f"Trades Closed: {trades_closed}")
        print()

        # Current Positions
        print("📈 CURRENT POSITIONS")
        print("-" * 60)
        open_positions = self.metrics.get('open_positions', 0)
        open_notional = self.metrics.get('open_notional_usd', 0)
        max_open = self.metrics.get('max_open_global', 3)
        print(f"Open Positions: {open_positions}/{max_open}")
        print(f"Open Notional: ${open_notional:.2f}")
        print()

        # Performance
        print("🎯 SESSION PERFORMANCE")
        print("-" * 60)
        total_pnl = self.metrics.get('total_net_pnl_usd', 0)
        pnl_pct = self.metrics.get('net_pnl_pct', 0)
        win_rate = self.metrics.get('win_rate', 0)
        profit_factor = self.metrics.get('profit_factor', 0)

        pnl_color = "✓" if total_pnl >= 0 else "✗"
        print(f"Total PnL: {pnl_color} ${total_pnl:.2f} ({pnl_pct:.2f}%)")
        print(f"Win Rate: {win_rate*100:.1f}%" if win_rate else "N/A")
        print(f"Profit Factor: {profit_factor:.2f}" if profit_factor else "N/A")
        print()

        # Firebase Quota
        print("🔥 FIREBASE QUOTA")
        print("-" * 60)
        quota_reads_used = self.metrics.get('quota_reads_used', 0)
        quota_reads_limit = self.metrics.get('quota_reads_limit', 20000)
        quota_writes_used = self.metrics.get('quota_writes_used', 0)
        quota_writes_limit = self.metrics.get('quota_writes_limit', 10000)
        quota_state = self.metrics.get('quota_state', 'UNKNOWN')

        reads_pct = (quota_reads_used / quota_reads_limit * 100) if quota_reads_limit > 0 else 0
        writes_pct = (quota_writes_used / quota_writes_limit * 100) if quota_writes_limit > 0 else 0

        state_emoji = "✓" if quota_state == "NORMAL" else "⚠" if quota_state == "WARNING" else "✗"
        print(f"State: {state_emoji} {quota_state}")
        print(f"Reads: {quota_reads_used}/{quota_reads_limit} ({reads_pct:.1f}%)")
        print(f"Writes: {quota_writes_used}/{quota_writes_limit} ({writes_pct:.1f}%)")
        print(f"Writes Today: {self.metrics.get('firebase_writes', 0)}")
        print(f"Write Failures: {self.metrics.get('firebase_failures', 0)}")
        print()

        # Current Signals
        print("📡 CURRENT SIGNALS")
        print("-" * 60)
        signals = self.metrics.get('signals', {})
        current_regime = self.metrics.get('current_regime', 'N/A')
        print(f"Regime: {current_regime}")
        for symbol, signal in sorted(signals.items()):
            emoji = "✓" if "ACCEPTED" in signal else "✗"
            print(f"  {emoji} {symbol}: {signal}")
        print()

        # Learning Status
        if self.learning:
            self.print_learning_status()

    def print_learning_status(self):
        """Print learning and success metrics"""
        print("🎓 LEARNING & SUCCESS METRICS")
        print("-" * 60)

        total_trades = self.learning.get('total_trades_closed', 0)
        total_wins = self.learning.get('total_wins', 0)
        total_losses = self.learning.get('total_losses', 0)
        total_flats = self.learning.get('total_flats', 0)
        win_rate = self.learning.get('win_rate', 0)
        total_pnl = self.learning.get('total_net_pnl_usd', 0)
        total_fees = self.learning.get('total_fees_usd', 0)
        avg_pnl = self.learning.get('avg_pnl_per_trade', 0)

        print(f"Total Trades (All Time): {total_trades}")
        print(f"  ✓ Wins: {total_wins}")
        print(f"  ✗ Losses: {total_losses}")
        print(f"  ○ Flats: {total_flats}")
        print(f"Win Rate: {win_rate*100:.1f}%" if win_rate else "N/A")
        print(f"Total Net PnL: ${total_pnl:.2f}")
        print(f"Total Fees Paid: ${total_fees:.2f}")
        print(f"Average PnL/Trade: ${avg_pnl:.2f}" if avg_pnl else "N/A")
        print()

        # Per-symbol summary
        per_symbol = self.learning.get('per_symbol_summary', {})
        if per_symbol:
            print("📍 PER-SYMBOL PERFORMANCE")
            print("-" * 60)
            for symbol, metrics in sorted(per_symbol.items()):
                trades = metrics.get('trades_closed', 0)
                wins = metrics.get('wins', 0)
                wr = metrics.get('win_rate', 0)
                pnl = metrics.get('total_pnl_usd', 0)
                pnl_emoji = "✓" if pnl >= 0 else "✗"
                print(f"{symbol}:")
                print(f"  Trades: {trades} | Wins: {wins} | Win Rate: {wr*100:.1f}%")
                print(f"  {pnl_emoji} PnL: ${pnl:.2f} | Best: ${metrics.get('best_trade_pnl_usd', 0):.2f} | Worst: ${metrics.get('worst_trade_pnl_usd', 0):.2f}")
            print()

        # Recent trades
        closed_trades = self.learning.get('closed_trades', [])
        if closed_trades:
            print("📋 RECENT TRADES (Last 5)")
            print("-" * 60)
            for trade in closed_trades[-5:]:
                symbol = trade.get('symbol', 'N/A')
                side = trade.get('entry_side', 'N/A')
                outcome = trade.get('outcome', 'FLAT')
                pnl = trade.get('net_pnl_usd', 0)
                duration = trade.get('hold_seconds', 0)
                entry_ts = trade.get('entry_timestamp', 'N/A')[:19]

                outcome_emoji = "✓" if outcome == "WIN" else "✗" if outcome == "LOSS" else "○"
                pnl_emoji = "+" if pnl >= 0 else ""
                print(f"{outcome_emoji} {symbol} {side}: {pnl_emoji}${pnl:.2f} ({duration}s) @ {entry_ts}")
            print()

    def run(self):
        """Run analyzer"""
        print("\nConnecting to bot API...")
        if not self.fetch_metrics():
            sys.exit(1)

        print("Fetching learning history...")
        self.fetch_learning()

        self.print_status()
        print("="*60)

if __name__ == "__main__":
    import sys
    api_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000"
    analyzer = BotStatusAnalyzer(api_url)
    analyzer.run()
