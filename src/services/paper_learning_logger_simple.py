"""Paper Learning Logger — Extended Czech version with detailed metrics

Shows:
  - Kolik obchodů se naučilo + win rate
  - Detaily pro jednotlivé měny
  - Kdy bude bot READY pro REAL trading
  - Jaké podmínky musí být splněny
"""
import logging
import time
import json
from pathlib import Path
from typing import Dict, Optional
from collections import defaultdict

log = logging.getLogger(__name__)

class SimplePaperLearningLogger:
    """Simple, human-friendly paper learning logger with detailed metrics."""

    def __init__(self, learning_state_file: Optional[str] = None):
        self.learning_state_file = learning_state_file or "server_local_backups/paper_adaptive_learning_state.json"
        self.last_log_time = 0.0
        self.log_interval_s = 60  # Every minute (but called every 5 min with METRICS_INTERVAL)

    def load_learning_state(self) -> Dict:
        """Load learning state."""
        try:
            path = Path(self.learning_state_file)
            if not path.exists():
                return {}
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}

    def should_log_now(self) -> bool:
        """Check if enough time has passed."""
        now = time.time()
        if now - self.last_log_time >= self.log_interval_s:
            self.last_log_time = now
            return True
        return False

    def get_progress_bar(self, current: int, target: int, width: int = 15) -> str:
        """Create simple progress bar."""
        if target == 0:
            return "░" * width
        filled = int(current / target * width)
        filled = min(filled, width)
        empty = width - filled
        return "█" * filled + "░" * empty

    def calculate_stats_from_rolling(self, rolling_list: list) -> Dict:
        """Calculate win rate and other stats from rolling list."""
        if not rolling_list:
            return {"wins": 0, "losses": 0, "flats": 0, "wr": 0, "pnl": 0}

        wins = sum(1 for r in rolling_list if len(r) > 1 and r[1] == "WIN")
        losses = sum(1 for r in rolling_list if len(r) > 1 and r[1] == "LOSS")
        flats = sum(1 for r in rolling_list if len(r) > 1 and r[1] == "FLAT")
        total = len(rolling_list)
        wr = (wins / total * 100) if total > 0 else 0
        pnl = sum(float(r[0]) for r in rolling_list if len(r) > 0)

        return {
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "wr": wr,
            "pnl": pnl,
            "total": total
        }

    def analyze_by_symbol(self, rolling_list: list) -> Dict:
        """Analyze performance by currency symbol."""
        by_symbol = defaultdict(lambda: {"wins": 0, "losses": 0, "flats": 0, "count": 0, "pnl": 0})

        for trade in rolling_list:
            if len(trade) < 3:
                continue
            pnl = float(trade[0])
            status = trade[1]  # WIN, LOSS, FLAT
            segment_key = trade[2]  # BTCUSDT:BULL_TREND:BUY

            symbol = segment_key.split(":")[0] if ":" in segment_key else segment_key

            by_symbol[symbol]["pnl"] += pnl
            by_symbol[symbol]["count"] += 1
            if status == "WIN":
                by_symbol[symbol]["wins"] += 1
            elif status == "LOSS":
                by_symbol[symbol]["losses"] += 1
            elif status == "FLAT":
                by_symbol[symbol]["flats"] += 1

        return by_symbol

    def log_simple_status(self) -> None:
        """Log in simple, layman-friendly format."""
        if not self.should_log_now():
            return

        state = self.load_learning_state()
        if not state:
            return

        # Get lifetime metrics
        lifetime_n = state.get("lifetime_n", 0)
        lifetime_pf = state.get("lifetime_pf", 0.0)
        lifecycle = state.get("lifecycle", "unknown")

        if lifetime_n == 0:
            return

        # Get rolling metrics for win rate
        rolling50 = state.get("rolling50", [])
        stats_r50 = self.calculate_stats_from_rolling(rolling50)
        wr_recent = stats_r50.get("wr", 0)

        # Get segment weights
        segment_weights = state.get("segment_weights", {})

        # Calculate readiness
        ready_conditions = {
            "trades_50": lifetime_n >= 50,
            "wr_positive": wr_recent > 45,
            "pf_positive": lifetime_pf > 1.0,
        }

        all_ready = all(ready_conditions.values())

        # Status
        progress_bar = self.get_progress_bar(lifetime_n, 50)
        if all_ready:
            progress_text = "✅ HOTOVO - Bot je READY!"
        elif lifetime_n >= 50:
            progress_text = f"🟡 MÁLO DAT - WR je nízká ({wr_recent:.0f}%)"
        elif lifetime_n >= 30:
            progress_text = f"🟡 NA DOBRÉ CESTĚ - zbývá {50 - lifetime_n} obchodů"
        else:
            progress_text = f"🔄 SBÍRÁNÍ DAT - {lifetime_n} z 50 obchodů"

        # Main status log
        log.info(
            f"[📚 UČENÍ] {progress_bar} {progress_text} | "
            f"Obchodů: {lifetime_n} | WR: {wr_recent:.0f}% | PF: {lifetime_pf:.2f} | "
            f"Status: {lifecycle}"
        )

        # Per-currency breakdown
        by_symbol = self.analyze_by_symbol(rolling50)
        if by_symbol:
            symbols_info = []
            for symbol in sorted(by_symbol.keys()):
                data = by_symbol[symbol]
                count = data["count"]
                wr = (data["wins"] / count * 100) if count > 0 else 0
                pnl = data["pnl"]
                symbols_info.append(f"{symbol}({count}x,WR={wr:.0f}%,PnL={pnl:+.5f})")

            symbols_str = " | ".join(symbols_info)
            log.info(f"[💰 PO MĚNÁCH] {symbols_str}")

        # Detailed log (hourly)
        if int(time.time()) % 3600 < 60:
            self._log_detailed(lifetime_n, lifetime_pf, lifecycle, segment_weights,
                             wr_recent, by_symbol, ready_conditions)

    def _log_detailed(self, lifetime_n: int, lifetime_pf: float, lifecycle: str,
                     segments: Dict, wr_recent: float, by_symbol: Dict,
                     ready_conditions: Dict) -> None:
        """Detailed human-friendly status every hour."""
        log.info("╔═══════════════════════════════════════════════════════════════╗")
        log.info("║               📊 DETAILNÍ STAV UČENÍ - PŘEHLED                 ║")
        log.info("╚═══════════════════════════════════════════════════════════════╝")

        log.info("")
        log.info("📈 ZÁKLADNÍ METRIKY")
        log.info(f"   Celkem obchodů:          {lifetime_n}")
        log.info(f"   Profit Factor (lifetime): {lifetime_pf:.2f}x")
        log.info(f"   Win Rate (poslédních 50): {wr_recent:.0f}%")
        log.info(f"   Status:                  {lifecycle}")
        log.info(f"   Potřeba k READY:         50 obchodů")
        log.info("")

        log.info("💹 DETAILY PER MĚNA")
        for symbol in sorted(by_symbol.keys()):
            data = by_symbol[symbol]
            count = data["count"]
            wr = (data["wins"] / count * 100) if count > 0 else 0
            pnl = data["pnl"]
            log.info(f"   {symbol:10} Obchodů: {count:3} | WR: {wr:5.1f}% | PnL: {pnl:+.6f}")
        log.info("")

        log.info("✅ PODMÍNKY PRO REAL TRADING")
        log.info(f"   ✓ 50+ obchodů:  {'✅ ANO' if ready_conditions['trades_50'] else '❌ NE'} ({lifetime_n}/50)")
        log.info(f"   ✓ WR > 45%:     {'✅ ANO' if ready_conditions['wr_positive'] else '❌ NE'} ({wr_recent:.0f}%)")
        log.info(f"   ✓ PF > 1.0:     {'✅ ANO' if ready_conditions['pf_positive'] else '❌ NE'} ({lifetime_pf:.2f}x)")
        log.info("")

        if all(ready_conditions.values()):
            log.info("   ✅ VŠECHNY PODMÍNKY SPLNĚNY - BOT JE READY PRO REAL TRADING!")
            log.info("      Lze zapnout ENABLE_REAL_ORDERS=true a začít obchodovat")
        else:
            missing = [k for k, v in ready_conditions.items() if not v]
            log.info(f"   ❌ CHYBÍ: {', '.join(missing)}")
            log.info("      Pokračuj v sbírání dat, bot zatím není ready")
        log.info("")

        log.info("💡 PŘÍŠTÍ KROKY")
        if all(ready_conditions.values()):
            log.info("   1. Zapnout ENABLE_REAL_ORDERS=true")
            log.info("   2. Monitorovat live obchodování")
            log.info("   3. Měřit zlepšení výsledků v reálném obchodování")
        else:
            log.info("   1. Pokračovat v papírovém obchodování")
            log.info(f"   2. Čekat na more data ({50-lifetime_n} obchodů zbývá)")
            log.info("   3. Zlepšit win rate a profit factor")
        log.info("")

        log.info("╚═══════════════════════════════════════════════════════════════╝")

# Global singleton
_logger = None

def get_simple_paper_learning_logger() -> SimplePaperLearningLogger:
    """Get or create the global logger."""
    global _logger
    if _logger is None:
        _logger = SimplePaperLearningLogger()
    return _logger

def log_simple_paper_learning_status() -> None:
    """Log simple paper learning status."""
    get_simple_paper_learning_logger().log_simple_status()
