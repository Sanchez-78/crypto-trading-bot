"""
Parameter Tuner V10.15m - Automatically adjust trading parameters based on learning

Implements feedback loop:
  Database Analysis → Detect Problems → Adjust Parameters → Monitor Impact → Learn

Key adaptations:
1. TP/SL zone sizing: increase if too many TOUTCALLOWs
2. Position sizing: reduce if PF < 0.7
3. Symbol filtering: disable poorly-performing symbols
4. Regime filtering: disable entry in poor regimes
"""

import os
import logging
from typing import Dict, Tuple
from src.services.learning_optimizer import get_optimizer

log = logging.getLogger(__name__)


class ParameterTuner:
    """Adaptively tune parameters based on trading results"""

    def __init__(self):
        self.env_file = '/opt/cryptomaster/.env'
        self.optimizer = get_optimizer()
        self.MIN_TRADES_FOR_TUNING = 5  # Need this many trades to make adjustment

    def run_tuning_cycle(self) -> Dict:
        """Run complete tuning cycle and return changes made"""
        analysis = self.optimizer.analyze_and_optimize()

        if not analysis:
            log.info("[PARAMETER_TUNER] No trades to analyze yet.")
            return {}

        overall = analysis.get('overall', {})
        per_symbol = analysis.get('per_symbol', {})
        recommendations = analysis.get('recommendations', [])

        changes = {}

        # 1. Check for critical issues (CYCLE 23: Skip auto TP/SL adjustment — manual override.conf controls bands)
        if overall.get('timeout_exits_pct', 0) > 80:
            log.warning("[PARAMETER_TUNER] Too many TIMEOUT exits (but TP/SL bands controlled manually via override.conf, skipping auto-adjust).")

        # 2. Check win rate
        if overall.get('win_rate_pct', 0) == 0.0 and overall.get('total_trades', 0) >= self.MIN_TRADES_FOR_TUNING:
            log.warning("[PARAMETER_TUNER] Zero win rate. Reducing position size by 50%.")
            changes['position_size_reduction'] = self._reduce_position_size(0.5)

        # 3. Check profit factor
        if overall.get('profit_factor', 0) < 0.7 and overall.get('total_trades', 0) >= self.MIN_TRADES_FOR_TUNING:
            log.warning("[PARAMETER_TUNER] Low PF. Reducing position size by 25%.")
            changes['position_size_reduction'] = self._reduce_position_size(0.25)

        # 4. Blacklist bad symbols
        for symbol, metrics in per_symbol.items():
            if metrics['trades'] >= 3 and metrics['profit_factor'] < 0.3:
                log.warning(f"[PARAMETER_TUNER] Blacklisting {symbol} (PF={metrics['profit_factor']:.2f}x)")
                changes[f'blacklist_{symbol}'] = self._add_to_disabled_symbols(symbol)

        # 5. Log recommendations
        for rec in recommendations:
            log.info(f"[LEARNING_RECOMMENDATION] {rec}")

        # 6. Log tuning cycle
        log.info(f"""
[PARAMETER_TUNING_CYCLE]
  Trades analyzed: {overall.get('total_trades', 0)}
  Win Rate: {overall.get('win_rate_pct', 0):.1f}%
  Profit Factor: {overall.get('profit_factor', 0):.2f}x
  Timeout %: {overall.get('timeout_exits_pct', 0):.1f}%
  Changes made: {len(changes)}
""")

        return changes

    def _increase_tp_sl_zones(self) -> bool:
        """Increase TP and SL zone BPS"""
        try:
            # Read current env
            config = self._read_env_file()

            # Increase zones
            tp_bps = int(config.get('PAPER_TP_ZONE_BPS', '100'))
            sl_bps = int(config.get('PAPER_SL_ZONE_BPS', '50'))

            new_tp_bps = int(tp_bps * 1.5)  # Increase by 50%
            new_sl_bps = int(sl_bps * 1.5)

            # Update env file
            self._update_env('PAPER_TP_ZONE_BPS', str(new_tp_bps))
            self._update_env('PAPER_SL_ZONE_BPS', str(new_sl_bps))

            log.info(f"[PARAMETER_TUNER] TP/SL zones increased: TP {tp_bps}→{new_tp_bps} bps, SL {sl_bps}→{new_sl_bps} bps")
            return True
        except Exception as e:
            log.error(f"[PARAMETER_TUNER_ERROR] Failed to increase TP/SL zones: {e}")
            return False

    def _reduce_position_size(self, reduction_factor: float) -> bool:
        """Reduce position size by given factor (0.5 = 50%, 0.25 = 25%)"""
        try:
            config = self._read_env_file()
            size_usd = float(config.get('PAPER_POSITION_SIZE_USD', '25'))

            new_size = size_usd * (1 - reduction_factor)
            self._update_env('PAPER_POSITION_SIZE_USD', str(int(new_size)))

            log.info(f"[PARAMETER_TUNER] Position size reduced: ${size_usd}→${new_size:.0f}")
            return True
        except Exception as e:
            log.error(f"[PARAMETER_TUNER_ERROR] Failed to reduce position size: {e}")
            return False

    def _add_to_disabled_symbols(self, symbol: str) -> bool:
        """Add symbol to disabled list"""
        try:
            config = self._read_env_file()
            disabled = config.get('PAPER_DISABLED_SYMBOLS', '').strip()

            if symbol in disabled:
                return True  # Already disabled

            if disabled:
                disabled = f"{disabled},{symbol}"
            else:
                disabled = symbol

            self._update_env('PAPER_DISABLED_SYMBOLS', disabled)
            log.info(f"[PARAMETER_TUNER] Symbol disabled: {symbol}")
            return True
        except Exception as e:
            log.error(f"[PARAMETER_TUNER_ERROR] Failed to disable symbol: {e}")
            return False

    def _read_env_file(self) -> Dict[str, str]:
        """Read .env file into dictionary"""
        config = {}
        try:
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
        except Exception as e:
            log.error(f"[PARAMETER_TUNER_ERROR] Failed to read {self.env_file}: {e}")
        return config

    def _update_env(self, key: str, value: str) -> bool:
        """Update specific .env variable"""
        try:
            config = self._read_env_file()
            config[key] = value

            # Write back
            with open(self.env_file, 'w') as f:
                for k, v in sorted(config.items()):
                    f.write(f"{k}={v}\n")

            return True
        except Exception as e:
            log.error(f"[PARAMETER_TUNER_ERROR] Failed to update {key}: {e}")
            return False


# Singleton
_tuner = None

def get_tuner() -> ParameterTuner:
    """Get global tuner instance"""
    global _tuner
    if _tuner is None:
        _tuner = ParameterTuner()
    return _tuner


def run_tuning():
    """Run parameter tuning cycle"""
    tuner = get_tuner()
    return tuner.run_tuning_cycle()
