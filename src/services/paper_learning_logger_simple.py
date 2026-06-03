"""Paper Learning Logger — Simple Czech version for anyone to understand

Shows clearly in logs:
  - Kolik obchodů se naučilo (lifetime trades)
  - Jaký je profit factor (lifetime PF)
  - Jaký je status (PAPER_COLLECTING, etc.)
  - Které měny se obchodují nejlépe (segment weights)
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

        # Get lifetime metrics
        lifetime_n = state.get("lifetime_n", 0)
        lifetime_pf = state.get("lifetime_pf", 0.0)
        lifecycle = state.get("lifecycle", "unknown")

        if lifetime_n == 0:
            return

        # Get segment weights (top performers)
        segment_weights = state.get("segment_weights", {})
        top_segments = sorted(segment_weights.items(), key=lambda x: x[1], reverse=True)[:3]

        # Status
        progress_bar = self.get_progress_bar(lifetime_n, 50)
        if lifetime_n >= 50:
            progress_text = "✅ HOTOVO - Systém se naučil!"
        elif lifetime_n >= 30:
            progress_text = f"🟡 NA DOBRÉ CESTĚ - zbývá {50 - lifetime_n} obchodů"
        else:
            progress_text = f"🔄 SBÍRÁNÍ DAT - {lifetime_n} z 50 obchodů"

        # Log main status (every 10 min)
        log.info(
            f"[📚 UČENÍ] {progress_bar} {progress_text} | "
            f"Obchodů: {lifetime_n} | Profit factor: {lifetime_pf:.2f} | "
            f"Status: {lifecycle}"
        )

        # Top segment breakdown
        if top_segments:
            symbols_str = " | ".join(
                f"{seg[0].split(':')[0]}(váha={seg[1]:.1%})"
                for seg in top_segments
            )
            log.info(f"[💰 NEJLEPŠÍ MĚNY] {symbols_str}")

        # Detailed log (every hour)
        if int(time.time()) % 3600 < self.log_interval_s:
            self._log_detailed(lifetime_n, lifetime_pf, lifecycle, segment_weights)

    def _log_detailed(self, lifetime_n: int, lifetime_pf: float, lifecycle: str, segments: Dict) -> None:
        """Detailed human-friendly status every hour."""
        log.info("╔═══════════════════════════════════════════════════════════════╗")
        log.info("║               📊 STAV UČENÍ - DETAILNÍ PŘEHLED                 ║")
        log.info("╚═══════════════════════════════════════════════════════════════╝")

        log.info("")
        log.info("📈 SHRNUTÍ")
        log.info(f"   Celkem obchodů učení:    {lifetime_n}")
        log.info(f"   Potřeba k hotovosti:     50")
        log.info(f"   Zbývá ještě:             {max(0, 50 - lifetime_n)}")
        log.info(f"   Procento hotovosti:      {min(100, lifetime_n * 2)}%")
        log.info(f"   Profit Factor:           {lifetime_pf:.2f}x")
        log.info(f"   Status:                  {lifecycle}")
        log.info("")

        # Status in plain Czech
        if lifetime_n >= 50:
            log.info("   ✅ UČENÍ HOTOVO!")
            log.info("      Robot se naučil ze svých obchodů.")
            log.info("      Příští krok: zapnout učení (feedback na příští obchody)")
        elif lifetime_n >= 30:
            log.info(f"   🟡 UČENÍ POKRAČUJE")
            log.info(f"      Robot se učí z obchodů ({lifetime_n}/50)")
            log.info(f"      Potřebuje ještě {50 - lifetime_n} obchodů")
        else:
            log.info("   🔄 RANÁ FÁZE")
            log.info("      Robot teď sbírá údaje z obchodů")
            log.info("      Počkej na více obchodů...")
        log.info("")

        # Which pairs work best
        if segments:
            log.info("🏆 NEJLEPŠÍ OBCHODNÍ PÁRY")
            top_by_weight = sorted(segments.items(), key=lambda x: x[1], reverse=True)[:3]
            for i, (key, weight) in enumerate(top_by_weight, 1):
                emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                symbol = key.split(":")[0] if ":" in key else key
                log.info(f"   {emoji} {symbol}")
                log.info(f"      Důvěra: {weight:.1%}")
            log.info("")

        log.info("💡 PŘÍŠTÍ KROKY")
        if lifetime_n >= 50:
            log.info("   1. Zkontrolovat která měna je nejlepší")
            log.info("   2. Zapnout inteligentní výběr (robot bude upřednostňovat dobré páry)")
            log.info("   3. Měřit zlepšení výsledků")
        elif lifetime_n >= 30:
            log.info("   1. Počkat na více obchodů")
            log.info(f"   2. Zbylo {50 - lifetime_n} obchodů")
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
