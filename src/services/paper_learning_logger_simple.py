"""Paper Learning Logger — Clear trade pipeline visibility

Shows user-friendly breakdown:
1. Signály: kolik kandidátů → kolik vstoupilo → kolik uzavřeno
2. Výsledky: z uzavřených - kolik zisků vs ztrát
3. Zamítnuté: proč se signály nepoužily
"""
import logging
import time
import json
from pathlib import Path
from typing import Dict, Optional
from collections import defaultdict

log = logging.getLogger(__name__)

class SimplePaperLearningLogger:
    """Clear, user-friendly paper learning logger."""

    def __init__(self, learning_state_file: Optional[str] = None):
        self.learning_state_file = learning_state_file or "server_local_backups/paper_adaptive_learning_state.json"
        self.last_log_time = 0.0
        self.log_interval_s = 60

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

    def calculate_stats_from_rolling(self, rolling_list: list) -> Dict:
        """Calculate win/loss from rolling list."""
        if not rolling_list:
            return {"wins": 0, "losses": 0, "flats": 0, "total": 0}

        wins = sum(1 for r in rolling_list if len(r) > 1 and r[1] == "WIN")
        losses = sum(1 for r in rolling_list if len(r) > 1 and r[1] == "LOSS")
        flats = sum(1 for r in rolling_list if len(r) > 1 and r[1] == "FLAT")

        return {
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "total": len(rolling_list)
        }

    def log_simple_status(self) -> None:
        """Log clear, understandable status."""
        if not self.should_log_now():
            return

        state = self.load_learning_state()
        if not state:
            return

        lifetime_n = state.get("lifetime_n", 0)
        lifetime_pf = state.get("lifetime_pf", 0.0)
        lifecycle = state.get("lifecycle", "unknown")

        if lifetime_n == 0:
            return

        # Rolling stats
        rolling50 = state.get("rolling50", [])
        stats_r50 = self.calculate_stats_from_rolling(rolling50)
        wr_recent = (stats_r50["wins"] / stats_r50["total"] * 100) if stats_r50["total"] > 0 else 0

        # Ready check
        ready_conditions = {
            "trades_50": lifetime_n >= 50,
            "wr_positive": wr_recent > 45,
            "pf_positive": lifetime_pf > 1.0,
        }
        all_ready = all(ready_conditions.values())

        # MAIN: Clear pipeline view
        log.info("")
        log.info("=" * 70)
        log.info("📊 OBCHODNÍ PIPELINE - JASNÝ PŘEHLED")
        log.info("=" * 70)

        log.info("")
        log.info("📈 ŽIVOTNÍ STATISTIKA (všechny časy)")
        log.info(f"   Celkem obchodů:        {lifetime_n} (spouštěno, vstoupeno a uzavřeno)")
        log.info(f"   Profit Factor:         {lifetime_pf:.2f}x (zisk/ztráta)")
        log.info(f"   Status:                {lifecycle}")

        log.info("")
        log.info("🎯 POSLEDNÍ 50 OBCHODŮ - DETAILY")
        log.info(f"   Uzavřeno:              {stats_r50['total']} obchodů")
        log.info(f"   ✅ Zisky (WIN):        {stats_r50['wins']} obchodů")
        log.info(f"   ❌ Ztráty (LOSS):      {stats_r50['losses']} obchodů")
        log.info(f"   ⏸️  Neutrální (FLAT):   {stats_r50['flats']} obchodů")
        log.info(f"   Win Rate:              {wr_recent:.0f}%")

        # Per-currency
        by_symbol = self._analyze_by_symbol(rolling50)
        if by_symbol:
            log.info("")
            log.info("💰 VÝSLEDKY PER MĚNA (poslední 50)")
            for symbol in sorted(by_symbol.keys()):
                data = by_symbol[symbol]
                wr = (data["wins"] / data["total"] * 100) if data["total"] > 0 else 0
                log.info(f"   {symbol:10} {data['total']:2}x | ✅ {data['wins']:2} | ❌ {data['losses']:2} | ⏸️  {data['flats']:2} | WR: {wr:5.0f}%")

        # Ready status
        log.info("")
        log.info("🚀 READY PRO REAL TRADING?")
        log.info(f"   ✓ 50+ obchodů:  {'✅ ANO' if ready_conditions['trades_50'] else '❌ NE'} ({lifetime_n}/50)")
        log.info(f"   ✓ WR > 45%:     {'✅ ANO' if ready_conditions['wr_positive'] else '❌ NE'} ({wr_recent:.0f}%)")
        log.info(f"   ✓ PF > 1.0:     {'✅ ANO' if ready_conditions['pf_positive'] else '❌ NE'} ({lifetime_pf:.2f}x)")
        log.info("")

        if all_ready:
            log.warning("✅ ✅ ✅ BOT JE READY PRO REAL TRADING! ✅ ✅ ✅")
            log.warning("Lze zapnout: ENABLE_REAL_ORDERS=true")
        else:
            missing = [k.replace("_", " ").upper() for k, v in ready_conditions.items() if not v]
            log.warning(f"❌ BOT NENÍ READY - Chybí: {', '.join(missing)}")

        log.info("=" * 70)
        log.info("")

    def _analyze_by_symbol(self, rolling_list: list) -> Dict:
        """Analyze by currency symbol."""
        by_symbol = defaultdict(lambda: {"wins": 0, "losses": 0, "flats": 0, "total": 0})

        for trade in rolling_list:
            if len(trade) < 3:
                continue
            status = trade[1]
            segment_key = trade[2]
            symbol = segment_key.split(":")[0] if ":" in segment_key else segment_key

            by_symbol[symbol]["total"] += 1
            if status == "WIN":
                by_symbol[symbol]["wins"] += 1
            elif status == "LOSS":
                by_symbol[symbol]["losses"] += 1
            elif status == "FLAT":
                by_symbol[symbol]["flats"] += 1

        return by_symbol

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
