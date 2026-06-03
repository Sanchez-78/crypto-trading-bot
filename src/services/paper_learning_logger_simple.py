"""Paper Learning Logger — Simple Czech version for anyone to understand

Shows clearly in logs:
  - Kolik obchodů je otevřeno teď
  - Kolik obchodů bylo uzavřeno dnes
  - Jak se učí (kolik učíciích updatů)
  - Jaký je progres do READY statusu
  - Kterou měnu obchoduje nejlépe
  - Jednoduše, srozumitelně, s grafikou
"""
import logging
import time
import json
from pathlib import Path
from typing import Dict, Optional
from collections import defaultdict

log = logging.getLogger(__name__)

class SimplePaperLearningLogger:
    """Simple, human-friendly paper learning logger."""

    def __init__(self, learning_state_file: Optional[str] = None):
        self.learning_state_file = learning_state_file or "server_local_backups/paper_adaptive_learning_state.json"
        self.last_log_time = 0.0
        self.log_interval_s = 600  # Every 10 minutes

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

    def log_simple_status(self) -> None:
        """Log in simple, layman-friendly format."""
        if not self.should_log_now():
            return

        state = self.load_learning_state()
        if not state:
            return

        # Parse segments
        segments = {}
        for key, data in state.items():
            if not isinstance(data, dict) or data.get("n", 0) == 0:
                continue
            segments[key] = data

        if not segments:
            return

        # Calculate all metrics
        total_trades = sum(s.get("n", 0) for s in segments.values())
        ready_segments = sum(1 for s in segments.values() if s.get("n", 0) >= 20)
        total_segments = len(segments)

        # Top 3 symbols
        by_symbol = defaultdict(lambda: {"trades": 0, "pf": 0, "count": 0})
        for segment_key, data in segments.items():
            parts = segment_key.split(":")
            if len(parts) >= 1:
                symbol = parts[0]
                by_symbol[symbol]["trades"] += data.get("n", 0)
                by_symbol[symbol]["pf"] += data.get("rolling50_pf", 1.0)
                by_symbol[symbol]["count"] += 1

        for symbol in by_symbol:
            by_symbol[symbol]["pf"] /= by_symbol[symbol]["count"]

        top_symbols = sorted(by_symbol.items(), key=lambda x: x[1]["trades"], reverse=True)[:3]

        # Learning updates (approximation - each closed trade = 1 learning update)
        learning_updates = total_trades

        # Status
        progress_bar = self.get_progress_bar(total_trades, 50)
        if total_trades >= 50:
            progress_text = "✅ HOTOVO - Systém se naučil!"
        elif total_trades >= 30:
            progress_text = f"🟡 NA DOBRÉ CESTĚ - zbývá {50 - total_trades} obchodů"
        else:
            progress_text = f"🔄 SBÍRÁNÍ DAT - {total_trades} z 50 obchodů"

        # Log main status (every 10 min)
        log.info(
            f"[📚 UČENÍ] {progress_bar} {progress_text} | "
            f"Obchodů: {total_trades} | Učících update: {learning_updates} | "
            f"Segmentů s daty: {total_segments}"
        )

        # Top symbol breakdown
        symbols_str = " | ".join(
            f"{sym}({data['trades']} obchodů, PF={data['pf']:.2f})"
            for sym, data in top_symbols
        )
        log.info(f"[💰 NEJLEPŠÍ MĚNY] {symbols_str}")

        # Detailed log (every hour)
        if int(time.time()) % 3600 < self.log_interval_s:
            self._log_detailed(segments, total_trades, ready_segments, total_symbols)

    def _log_detailed(self, segments: Dict, total_trades: int, ready_segments: int, top_symbols: list) -> None:
        """Detailed human-friendly status every hour."""
        log.info("╔═══════════════════════════════════════════════════════════════╗")
        log.info("║               📊 STAV UČENÍ - DETAILNÍ PŘEHLED                 ║")
        log.info("╚═══════════════════════════════════════════════════════════════╝")

        log.info("")
        log.info("📈 SHRNUTÍ")
        log.info(f"   Celkem obchodů učení:    {total_trades}")
        log.info(f"   Potřeba k hotovosti:     50")
        log.info(f"   Zbývá ještě:             {max(0, 50 - total_trades)}")
        log.info(f"   Procento hotovosti:      {min(100, total_trades * 2)}%")
        log.info("")

        # Status in plain Czech
        if total_trades >= 50:
            log.info("   ✅ UČENÍ HOTOVO!")
            log.info("      Robot se naučil ze svých obchodů.")
            log.info("      Příští krok: zapnout učení (feedback na příští obchody)")
        elif total_trades >= 30:
            log.info(f"   🟡 UČENÍ POKRAČUJE")
            log.info(f"      Robot se učí z obchodů ({total_trades}/50)")
            log.info(f"      Potřebuje ještě {50 - total_trades} obchodů")
        else:
            log.info("   🔄 RANÁ FÁZE")
            log.info("      Robot teď sbírá údaje z obchodů")
            log.info("      Počkej na více obchodů...")
        log.info("")

        # Which pairs work best
        log.info("🏆 NEJLEPŠÍ OBCHODNÍ PÁRY")
        by_pf = sorted(segments.items(), key=lambda x: x[1].get("rolling50_pf", 0), reverse=True)
        for i, (key, data) in enumerate(by_pf[:3], 1):
            n = data.get("n", 0)
            pf = data.get("rolling50_pf", 0)
            wr = (data.get("wins", 0) / n * 100) if n > 0 else 0
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
            log.info(f"   {emoji} {key}")
            log.info(f"      Obchodů: {n}, Úspěšnost: {wr:.0f}%, Profit faktor: {pf:.2f}x")
        log.info("")

        # What robot learned
        log.info("📚 CO SE ROBOT NAUČIL")
        log.info(f"   Počet segmentů s daty:   {len(segments)}")
        log.info(f"   Segmentů už hotových:    {ready_segments} (mají 20+ obchodů)")
        if ready_segments > 0:
            log.info("   ✅ Lze už zapnout inteligentní výběr obchodů!")
        log.info("")

        log.info("💡 PŘÍŠTÍ KROKY")
        if total_trades >= 50:
            log.info("   1. Zkontrolovat která měna je nejlepší")
            log.info("   2. Zapnout inteligentní výběr (robot bude upřednostňovat dobré páry)")
            log.info("   3. Měřit zlepšení výsledků")
        elif total_trades >= 30:
            log.info("   1. Počkat na více obchodů")
            log.info(f"   2. Zbylo {50 - total_trades} obchodů")
            log.info("   3. Pak se bude moct automatika zapnout")
        else:
            log.info("   1. Nechej robot obchodovat")
            log.info("   2. Robot se učí z každého obchodu")
            log.info("   3. Až bude dost obchodů, objeví se lepší strategie")
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
