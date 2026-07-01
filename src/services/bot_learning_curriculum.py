"""
CryptoMaster Bot Learning Curriculum V1

Vnitřní učebnice - všechny strategie, podmínky, self-tuning.
Bot se sám učí co funguje a automaticky se přizpůsobuje.

Structure:
1. Entry Strategies (4 modes)
2. Exit Strategies (9 levels + adaptive)
3. Risk Management
4. Market Adaptation Engine
5. Parameter Auto-Tuning
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json
import os

# ═══════════════════════════════════════════════════════════════════════════════
# 1. ENTRY STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EntryStrategy:
    """Co vlezít do pozice a kdy"""
    name: str
    regime: str  # BULL_TREND, BEAR_TREND, RANGING, etc
    conditions: Dict  # entry conditions
    confidence_min: float  # 0.0-1.0, min confidence to enter
    vol_band: str  # low_vol, mid_vol, high_vol
    success_rate: float = 0.0  # učení - kolik WR má tato strategie
    sample_count: int = 0  # kolik trades pro WR kalkulaci


ENTRY_STRATEGIES = {
    "BULL_TREND_PULLBACK": EntryStrategy(
        name="Bull Trend Pullback",
        regime="BULL_TREND",
        conditions={
            "ema_fast_above_slow": True,
            "price_at_or_below_ema50": True,
            "rsi_threshold": (30, 50),  # RSI oversoldo, ale ne extrém
            "macd_positive": True,
        },
        confidence_min=0.6,
        vol_band="mid_vol",
    ),
    "BEAR_TREND_RALLY": EntryStrategy(
        name="Bear Trend Rally",
        regime="BEAR_TREND",
        conditions={
            "ema_fast_below_slow": True,
            "price_at_or_above_ema50": True,
            "rsi_threshold": (50, 70),  # RSI overbought, ale ne extrém
            "macd_negative": True,
        },
        confidence_min=0.6,
        vol_band="mid_vol",
    ),
    "RANGE_MEAN_REVERSION": EntryStrategy(
        name="Range Mean Reversion",
        regime="RANGING",
        conditions={
            "price_near_bb_lower": True,  # cena blízko dolní Bollinger
            "rsi_oversold": True,  # RSI < 30
        },
        confidence_min=0.5,
        vol_band="low_vol",
    ),
    "QUIET_RANGE_SCALP": EntryStrategy(
        name="Quiet Range Scalp",
        regime="QUIET_RANGE",
        conditions={
            "volatility_very_low": True,
            "price_stable": True,
        },
        confidence_min=0.4,
        vol_band="low_vol",
    ),
}

# ═══════════════════════════════════════════════════════════════════════════════
# 2. EXIT STRATEGIES (9 Levels)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExitStrategy:
    """Kdy a jak vylézt z pozice"""
    level: int  # 1-9, priority
    name: str
    condition: str
    threshold: float
    min_age_seconds: int = 0
    success_rate: float = 0.0  # jak často to skutečně profituje
    sample_count: int = 0


EXIT_STRATEGIES = [
    ExitStrategy(level=1, name="MICRO_TP", condition="pnl_pct >= threshold", threshold=0.0010, success_rate=0.0),
    ExitStrategy(level=2, name="BREAKEVEN_STOP", condition="pnl_pct >= 0.05% AND MFE > 0.05%", threshold=0.0005, success_rate=0.0),
    ExitStrategy(level=3, name="PARTIAL_TP_25", condition="progress >= 25% to TP", threshold=0.25, success_rate=0.0),
    ExitStrategy(level=4, name="PARTIAL_TP_50", condition="progress >= 50% to TP", threshold=0.50, success_rate=0.0),
    ExitStrategy(level=5, name="PARTIAL_TP_75", condition="progress >= 75% to TP", threshold=0.75, success_rate=0.0),
    ExitStrategy(level=6, name="EARLY_STOP", condition="loss >= 60% of SL", threshold=0.60, success_rate=0.0),
    ExitStrategy(level=7, name="TRAILING_STOP", condition="retrace >= 50% from peak", threshold=0.50, success_rate=0.0),
    ExitStrategy(level=8, name="SCRATCH_EXIT", condition="age >= 90s AND |pnl| < 0.15%", threshold=0.0015, min_age_seconds=90, success_rate=0.0),
    ExitStrategy(level=9, name="STAGNATION_EXIT", condition="age >= 110s AND |pnl| < 0.05%", threshold=0.0005, min_age_seconds=110, success_rate=0.0),
]

EXIT_STRATEGIES_BY_NAME = {s.name: s for s in EXIT_STRATEGIES}

# ═══════════════════════════════════════════════════════════════════════════════
# 3. RISK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RiskProfile:
    """Jak riskovat pozice - Kelly sizing, position caps, daily limits"""
    account_size_usd: float = 5000
    max_daily_loss_pct: float = 0.02  # 2% = $100
    kelly_safety_factor: float = 0.25  # 25% Kelly
    min_position_usd: float = 10
    max_position_usd: float = 100
    max_concurrent_positions: int = 25


# ═══════════════════════════════════════════════════════════════════════════════
# 4. MARKET ADAPTATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MarketAdaptation:
    """Jak se bot přizpůsobuje trhu"""
    regime: str
    volatility: str  # low, mid, high
    trend_strength: float  # 0-1
    liquidity: float  # 0-1
    timestamp: datetime

    # Adaptive thresholds
    tp_zone_bps_adaptive: int = 35
    sl_zone_bps_adaptive: int = 40
    entry_quality_gate_pct: float = 0.0015  # min price move to enter
    timeout_seconds_adaptive: int = 300


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PARAMETER AUTO-TUNING
# ═══════════════════════════════════════════════════════════════════════════════

class BotLearningEngine:
    """Srdce učebnice - bot se učí a sám se nastavuje"""

    def __init__(self, persistence_file: str = "/opt/cryptomaster/server_local_backups/bot_curriculum.json"):
        self.persistence_file = persistence_file
        self.entry_strategies = ENTRY_STRATEGIES.copy()
        self.exit_strategies = {s.name: s for s in EXIT_STRATEGIES}
        self.risk_profile = RiskProfile()
        self.market_state = None
        self.load_state()

    def load_state(self):
        """Načti učenost z minulých trades"""
        if os.path.exists(self.persistence_file):
            try:
                with open(self.persistence_file, 'r') as f:
                    data = json.load(f)
                    # Obnov success rates z databáze
                    for strategy_name, metrics in data.get("entry_success_rates", {}).items():
                        if strategy_name in self.entry_strategies:
                            self.entry_strategies[strategy_name].success_rate = metrics.get("wr", 0.0)
                            self.entry_strategies[strategy_name].sample_count = metrics.get("n", 0)
                    for exit_name, metrics in data.get("exit_success_rates", {}).items():
                        if exit_name in self.exit_strategies:
                            self.exit_strategies[exit_name].success_rate = metrics.get("success_rate", 0.0)
                            self.exit_strategies[exit_name].sample_count = metrics.get("n", 0)
            except Exception as e:
                print(f"[CURRICULUM] Load failed: {e}")

    def save_state(self):
        """Ulož učenost pro příště"""
        try:
            data = {
                "timestamp": datetime.now().isoformat(),
                "entry_success_rates": {
                    name: {"wr": s.success_rate, "n": s.sample_count}
                    for name, s in self.entry_strategies.items()
                },
                "exit_success_rates": {
                    name: {"success_rate": s.success_rate, "n": s.sample_count}
                    for name, s in self.exit_strategies.items()
                },
            }
            os.makedirs(os.path.dirname(self.persistence_file), exist_ok=True)
            with open(self.persistence_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[CURRICULUM] Save failed: {e}")

    def update_entry_success(self, strategy_name: str, won: bool):
        """Aktualizuj WR pro entry strategii po uzavření trade"""
        if strategy_name in self.entry_strategies:
            s = self.entry_strategies[strategy_name]
            old_wr = s.success_rate if s.sample_count > 0 else 0.5
            s.sample_count += 1
            s.success_rate = (old_wr * (s.sample_count - 1) + (1.0 if won else 0.0)) / s.sample_count
            self.save_state()

    def update_exit_success(self, exit_name: str, profit_pct: float):
        """Aktualizuj success rate pro exit strategii"""
        if exit_name in self.exit_strategies:
            s = self.exit_strategies[exit_name]
            s.sample_count += 1
            was_profitable = 1.0 if profit_pct > 0 else 0.0
            s.success_rate = ((s.success_rate * (s.sample_count - 1)) + was_profitable) / s.sample_count
            self.save_state()

    def get_best_entry_strategy(self, regime: str) -> Optional[EntryStrategy]:
        """Vrať nejlepší entry strategii pro režim podle historického WR"""
        candidates = [s for s in self.entry_strategies.values() if s.regime == regime and s.sample_count >= 5]
        if not candidates:
            candidates = [s for s in self.entry_strategies.values() if s.regime == regime]
        return max(candidates, key=lambda s: s.success_rate) if candidates else None

    def get_best_exit_strategies(self) -> List[ExitStrategy]:
        """Vrať exit strategie seřazené podle success rate (učení)"""
        return sorted(self.exit_strategies.values(), key=lambda s: s.success_rate, reverse=True)

    def recommend_tp_sl(self, regime: str, volatility: str) -> tuple:
        """Doporuč TP/SL na základě režimu a volatility"""
        base_tp, base_sl = 35, 40  # baseline

        # Adaptuj podle volatility
        if volatility == "high_vol":
            base_tp, base_sl = 50, 50  # širší banda
        elif volatility == "low_vol":
            base_tp, base_sl = 25, 35  # užší banda

        # Adaptuj podle režimu
        if regime == "BULL_TREND":
            base_tp *= 1.1  # optimističtější v trendu
        elif regime == "RANGING":
            base_tp *= 0.8  # pesimističtější v range

        return int(base_tp), int(base_sl)

    def report_curriculum(self) -> str:
        """Sestav zprávu o tom, co se bot naučil"""
        lines = []
        lines.append("=" * 80)
        lines.append("🤖 BOT LEARNING CURRICULUM REPORT")
        lines.append("=" * 80)

        lines.append("\n📍 ENTRY STRATEGIES (Učenost po režimech):")
        for regime in ["BULL_TREND", "BEAR_TREND", "RANGING", "QUIET_RANGE"]:
            strats = [s for s in self.entry_strategies.values() if s.regime == regime]
            for s in sorted(strats, key=lambda x: x.success_rate, reverse=True):
                lines.append(f"  {regime:15} > {s.name:30} WR={s.success_rate*100:5.1f}% (n={s.sample_count})")

        lines.append("\n🚪 EXIT STRATEGIES (Učenost dle úspěšnosti):")
        for s in sorted(self.exit_strategies.values(), key=lambda x: x.success_rate, reverse=True):
            lines.append(f"  L{s.level} {s.name:25} Success={s.success_rate*100:5.1f}% (n={s.sample_count})")

        lines.append("\n📊 RISK PROFILE:")
        lines.append(f"  Account: ${self.risk_profile.account_size_usd}")
        lines.append(f"  Max Daily Loss: {self.risk_profile.max_daily_loss_pct*100:.1f}%")
        lines.append(f"  Kelly Factor: {self.risk_profile.kelly_safety_factor*100:.0f}%")

        lines.append("\n" + "=" * 80)
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    engine = BotLearningEngine()
    print(engine.report_curriculum())
