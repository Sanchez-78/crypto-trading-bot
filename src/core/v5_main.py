"""
V5 PRODUCTION MAIN LOOP

Unified integration of:
  - Market data → Feature builder
  - Decision engine (Bayesian + EV + Regime)
  - RL Agent (DQN exploration/exploitation)
  - Calibration guard (drift detection)
  - Risk engine (portfolio protection)
  - Execution engine
  - Learning loop (reward + training)
  - Self-healing (mutation + recovery)

Architecture:
  Market Data
    ↓
  Feature Builder (State Vector)
    ↓
  Decision Engine (Bayesian + EV + Regime)
    ↓
  Calibration Guard (Drift Check)
    ↓
  RL Agent (Policy Override / Exploration)
    ↓
  Risk Engine (Portfolio Protection)
    ↓
  Execution Engine
    ↓
  Learning Loop (Auditor + Reward)
    ↓
  Self-Healing + Genetic Evolution
"""

import logging
import time
import numpy as np
from typing import Dict, Any, Optional, Tuple

# Core modules
from src.core.state_builder import StateBuilder
from src.core.ev import compute_ev, is_positive_ev
from src.core.regime import detect_regime, regime_adjustment
from src.core.calibration_guard import CalibrationGuard
from src.core.genetic_optimizer import GeneticOptimizer, mutate
from src.core.reward_engine import RewardEngine

# Services
from src.services.self_healing import EnhancedSelfHealing
from src.optimized.orchestrator import TradeOrchestrator
from src.optimized.bot_types import TradeSignal, Direction

# ML Models
try:
    from src.core.rl_agent import DQNAgent
except ImportError:
    from src.services.dqn_agent import DQNAgent

logger = logging.getLogger(__name__)


class V5ProductionSystem:
    """
    Elite V5 production trading system.
    
    One autonomous trading organism with:
    - Bayesian signal calibration
    - RL-driven policy adaptation
    - Self-healing mutation
    - Risk-first architecture
    """
    
    def __init__(
        self,
        agent_state_size: int = 8,
        agent_action_size: int = 3,
        capital: float = 10_000,
    ):
        """
        Initialize V5 production system.
        
        Args:
            agent_state_size: RL state vector size (default 8)
            agent_action_size: Number of actions: HOLD=0, LONG=1, SHORT=2
            capital: Trading capital
        """
        logger.info("🚀 Initializing V5 Production System...")
        
        # Components
        self.state_builder = StateBuilder()
        self.dqn_agent = DQNAgent(agent_state_size, agent_action_size)
        self.calibration_guard = CalibrationGuard()
        self.genetic_optimizer = GeneticOptimizer()
        self.reward_engine = RewardEngine()
        self.self_healing = EnhancedSelfHealing()
        
        # Orchestrator
        self.orchestrator = TradeOrchestrator(capital=capital)
        
        # State tracking
        self.prev_state = None
        self.prev_action = None
        self.prev_action_id = None
        self.current_regime = "UNCERTAIN"
        self.capital = capital
        
        # Trading metrics
        self.trades_executed = 0
        self.total_reward = 0.0
        self.session_start = time.time()
        
        logger.info(f"✅ V5 System initialized with capital {capital}")
    
    # ─────────────────────────────────────────────────────────────────────
    # DECISION PIPELINE
    # ─────────────────────────────────────────────────────────────────────
    
    def evaluate_signal(
        self,
        signal: Dict[str, Any],
        market_data: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Full decision pipeline: signal → calibration → gating → validation.
        
        Args:
            signal: Raw MKTKiRA signal (symbol, entry_price, sl, tp, probability)
            market_data: Market indicators (rsi, adx, macd, etc.)
            
        Returns:
            Tuple[should_trade, decision_meta]
            
        Pipeline:
            1. Regime detection (TREND/RANGE/UNCERTAIN)
            2. EV computation & gating
            3. Calibration drift check
            4. Risk validation
            5. RL policy override/confirmation
        """
        # ─1. Regime Detection────────────────────────────────────
        adx = market_data.get("adx", 25)
        ema_slope = market_data.get("ema_slope", 0)
        self.current_regime = detect_regime(adx, ema_slope)
        
        # ─2. Compute Expected Value──────────────────────────────
        p = signal.get("probability", 0.5)
        rr = signal.get("rr_ratio", 1.5)
        atr = market_data.get("atr", 0.01)
        
        raw_ev = compute_ev(p, rr, atr)
        regime_ev = regime_adjustment(raw_ev, self.current_regime)
        
        # ─3. Calibration Drift Check─────────────────────────────
        reliability_mult = self.calibration_guard.get_reliability_multiplier()
        final_ev = regime_ev * reliability_mult
        
        ev_gated = is_positive_ev(p, rr, atr)
        cal_broken = self.calibration_guard.is_broken()
        
        logger.debug(
            f"Signal Eval | EV={final_ev:.4f} | Regime={self.current_regime} | "
            f"Calibration={self.calibration_guard.get_calibration_quality():.2f}"
        )
        
        # ─4. Gate: Only proceed if EV positive and calibration OK─
        if not ev_gated:
            logger.info(f"❌ EV Gate FAILED: {final_ev:.4f} <= 0")
            return False, {"reason": "EV_GATE_FAILED"}
        
        if cal_broken:
            logger.warning(f"⚠️  Calibration BROKEN, reducing signal strength")
        
        # ─5. Risk Validation─────────────────────────────────────
        portfolio = {"drawdown": 0.05, "exposure": 0.3}  # Placeholder
        risk_valid = self.validate_trade_risk(signal, portfolio)
        
        if not risk_valid:
            return False, {"reason": "RISK_VALIDATION_FAILED"}
        
        # ─6. RL Policy Confirmation──────────────────────────────
        # Build state vector from market data
        state = self.state_builder.build(market_data)
        
        # Get RL agent decision
        action_id = self.dqn_agent.act(state)
        action = self._action_from_id(action_id)
        
        # RL override: if agent says HOLD, don't trade
        if action == "HOLD":
            logger.info(f"RL Agent says HOLD, skipping trade")
            return False, {"reason": "RL_OVERRIDE"}
        
        # Success: signal passes all gates
        decision_meta = {
            "regime": self.current_regime,
            "ev": final_ev,
            "calibration_quality": self.calibration_guard.get_calibration_quality(),
            "rl_action": action,
            "state": state,
            "action_id": action_id,
        }
        
        return True, decision_meta
    
    # ─────────────────────────────────────────────────────────────────────
    # EXECUTION
    # ─────────────────────────────────────────────────────────────────────
    
    def execute_trade(
        self,
        signal: Dict[str, Any],
        decision_meta: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Execute validated trade through orchestrator.
        
        Args:
            signal: Trade signal
            decision_meta: Decision metadata
            
        Returns:
            Execution result or None if rejected
        """
        # Convert to TradeSignal object (if needed by orchestrator)
        trade_signal = TradeSignal(
            symbol=signal.get("symbol", "ETHUSDT"),
            direction=Direction.LONG if signal.get("direction", "LONG") == "LONG" else Direction.SHORT,
            entry_price=float(signal.get("entry_price", 0)),
            sl_price=float(signal.get("sl_price", 0)),
            tp_price=float(signal.get("tp_price", 0)),
            probability=signal.get("probability", 0.5),
            obi=signal.get("obi", 0),
            atr=signal.get("atr", 0.01),
        )
        
        # Execute through orchestrator
        decision, meta = self.orchestrator.on_signal(trade_signal, {})
        
        if decision not in ("ENTER", "ENTER_REDUCED"):
            logger.info(f"Orchestrator rejected: {decision} - {meta}")
            return None
        
        self.trades_executed += 1
        
        execution_result = {
            "trade_id": self.orchestrator.active.id if self.orchestrator.active else None,
            "decision": decision,
            "meta": meta,
        }
        
        logger.info(f"✅ Trade executed #{self.trades_executed}")
        return execution_result
    
    # ─────────────────────────────────────────────────────────────────────
    # LEARNING & REWARD
    # ─────────────────────────────────────────────────────────────────────
    
    def process_trade_outcome(self, trade: Dict[str, Any]):
        """
        Process closed trade for learning.
        
        Args:
            trade: Closed trade dict with pnl, exit_reason, etc.
        """
        # Compute reward
        reward = self.reward_engine.compute(trade)
        self.total_reward += reward
        
        # Update loss streak
        self.self_healing.update_trade(trade)
        
        # Update calibration guard
        actual_outcome = 1 if trade.get("pnl", 0) >= 0 else 0
        predicted_p = trade.get("probability", 0.5)
        self.calibration_guard.update(predicted_p, actual_outcome)
        
        # Replay in RL agent
        if self.prev_state is not None and self.prev_action_id is not None:
            state = self.prev_state
            action = self.prev_action_id
            next_state = np.zeros_like(state)  # Terminal state
            done = True
            
            self.dqn_agent.remember(state, action, reward, next_state, done)
            self.dqn_agent.replay()
        
        logger.debug(f"Trade outcome | Reward={reward:.6f} | Status={trade.get('exit_reason')}")
    
    # ─────────────────────────────────────────────────────────────────────
    # SELF-HEALING & MUTATION
    # ─────────────────────────────────────────────────────────────────────
    
    def check_self_healing(self):
        """Check if system needs healing/mutation."""
        metrics = {
            "health": {"status": "OK"},
            "learning": {"state": "NORMAL"},
            "equity": {"drawdown": 0.05},
        }
        
        should_mutate = self.self_healing.should_mutate()
        
        if should_mutate:
            logger.warning(f"🧬 GENETIC MUTATION TRIGGERED")
            # Placeholder: actual strategy mutation would happen here
            self.self_healing.loss_streak = 0
        
        # Update healing state
        update_result = self.self_healing.update(metrics, None)
        
        if update_result.get("heal"):
            logger.warning(f"🔧 Self-healing: {update_result['heal']}")
    
    # ─────────────────────────────────────────────────────────────────────
    # UTILITIES
    # ─────────────────────────────────────────────────────────────────────
    
    def validate_trade_risk(
        self,
        signal: Dict[str, Any],
        portfolio: Dict[str, Any]
    ) -> bool:
        """
        Validate trade against portfolio risk constraints.
        
        Args:
            signal: Trade signal
            portfolio: Portfolio state
            
        Returns:
            True if trade passes risk checks
        """
        # Basic risk checks
        if portfolio.get("drawdown", 0) > 0.2:
            logger.warning(f"Drawdown check failed: {portfolio['drawdown']:.2%}")
            return False
        
        if portfolio.get("exposure", 0) > 0.8:
            logger.warning(f"Exposure check failed: {portfolio['exposure']:.2%}")
            return False
        
        return True
    
    def _action_from_id(self, action_id: int) -> str:
        """Convert action ID to string."""
        actions = {0: "HOLD", 1: "LONG", 2: "SHORT"}
        return actions.get(action_id, "HOLD")
    
    def get_status(self) -> Dict[str, Any]:
        """Get system status."""
        elapsed = time.time() - self.session_start
        
        return {
            "regime": self.current_regime,
            "trades_executed": self.trades_executed,
            "total_reward": self.total_reward,
            "elapsed_seconds": elapsed,
            "loss_streak": self.self_healing.loss_streak,
            "calibration_quality": self.calibration_guard.get_calibration_quality(),
            "healing_mode": self.self_healing.mode,
            "rl_epsilon": getattr(self.dqn_agent, 'epsilon', 0.5),
        }


# ─────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────

def main_loop(system: V5ProductionSystem, market_stream_iterator):
    """
    Main trading loop.

    Args:
        system: V5ProductionSystem instance
        market_stream_iterator: Iterator yielding market data + signals
    """
    logger.info("🚀 Starting V5 Production Loop...")

    # V10.13u+18d: Emit startup marker for diagnostic hook
    try:
        from src.services.realtime_decision_engine import emit_econ_bad_diag_hook_marker
        emit_econ_bad_diag_hook_marker()
    except Exception:
        pass

    # V10.13u+18d: Track ticks for periodic diagnostic heartbeat
    _tick_count = 0
    _last_diag_heartbeat_tick = 0

    for market_tick in market_stream_iterator:
        _tick_count += 1
        try:
            # Extract data
            signal = market_tick.get("signal")
            market_data = market_tick.get("market_data")
            closed_trade = market_tick.get("closed_trade")
            
            # Process closed trade (if any)
            if closed_trade:
                system.process_trade_outcome(closed_trade)
                system.check_self_healing()
            
            # New signal: evaluate → execute → learn
            if signal and market_data:
                should_trade, decision_meta = system.evaluate_signal(signal, market_data)
                
                if should_trade:
                    system.execute_trade(signal, decision_meta)
            
            # Log status every 100 ticks
            if system.trades_executed % 100 == 0:
                status = system.get_status()
                logger.info(f"📊 Status: {status}")

            # V10.13u+18d: Emit ECON BAD diagnostic heartbeat every ~100 ticks (~10s)
            if _tick_count - _last_diag_heartbeat_tick >= 100:
                try:
                    from src.services.realtime_decision_engine import maybe_emit_econ_bad_diag_heartbeat
                    maybe_emit_econ_bad_diag_heartbeat(source="main_loop")
                except Exception:
                    pass
                _last_diag_heartbeat_tick = _tick_count

        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)


if __name__ == "__main__":
    # Initialize logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Initialize system
    system = V5ProductionSystem()
    
    # Mock market stream for testing
    def mock_market_stream():
        """Generate mock market data for testing."""
        for i in range(100):
            yield {
                "signal": {
                    "symbol": "ETHUSDT",
                    "entry_price": 2000.0 + i * 0.1,
                    "sl_price": 1950.0 + i * 0.1,
                    "tp_price": 2050.0 + i * 0.1,
                    "probability": 0.55 + np.random.random() * 0.1,
                    "rr_ratio": 1.5,
                    "direction": "LONG",
                    "atr": 0.01,
                    "obi": 0.5,
                },
                "market_data": {
                    "rsi": 50 + np.random.random() * 20,
                    "adx": 25 + np.random.random() * 10,
                    "macd": np.random.random() * 0.01,
                    "ema_fast": 2000.0 + np.random.random() * 10,
                    "ema_slow": 1995.0 + np.random.random() * 10,
                    "ema_slope": np.random.random() * 0.01,
                    "bb_width": 0.05,
                    "atr": 0.01,
                },
                "closed_trade": {
                    "pnl": np.random.random() * 0.02 - 0.01,
                    "exit_reason": np.random.choice(["tp", "sl", "timeout"]),
                    "duration_seconds": 300 + np.random.random() * 600,
                    "bars_held": np.random.randint(1, 20),
                    "probability": 0.55,
                } if i % 10 == 0 else None,
            }
    
    # Run main loop
    main_loop(system, mock_market_stream())
