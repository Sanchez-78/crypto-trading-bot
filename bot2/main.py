import threading, time

# ────────────────────────────────────────────────────────────────────────────
# V10.12i: Safe idle computation helper
# ────────────────────────────────────────────────────────────────────────────
def log_bootstrap_status():
    """
    V10.13b: Log comprehensive hydration status after all bootstrap steps complete.
    Helps diagnose if learning state is properly loaded from Firebase/Redis.
    """
    print("\n[V10.13b] ── Bootstrap Hydration Status ────────────────────────────")

    # Learning Monitor status
    try:
        from src.services.learning_monitor import _hydration_source as lm_source, lm_count
        lm_status = f"source={lm_source} pairs={len(lm_count)}"
        print(f"  Learning Monitor: {lm_status}")
    except Exception as e:
        print(f"  Learning Monitor: error → {e}")

    # Metrics status
    try:
        from src.services.learning_event import _hydration_source as metrics_source, METRICS
        metrics_status = f"source={metrics_source} trades={METRICS.get('trades', 0)}"
        print(f"  Metrics:          {metrics_status}")
    except Exception as e:
        print(f"  Metrics:          error → {e}")

    # RDE state status
    try:
        from src.services.realtime_decision_engine import _last_restore_source, _last_restore_ts
        rde_status = f"source={_last_restore_source} ts={_last_restore_ts}"
        print(f"  RDE State:        {rde_status}")
    except Exception as e:
        print(f"  RDE State:        (not tracked)")

    print("─" * 70 + "\n")


def safe_idle_seconds(last_trade_ts, now=None):
    """
    Compute idle seconds safely, preventing unix-time-sized values.

    V10.12i: Validates timestamps and clamps unrealistic values to 0.0
    to prevent false STALL/self-heal triggers from invalid timestamps.

    Args:
        last_trade_ts: float or int timestamp of last trade, or None
        now: current time (defaults to time.time())

    Returns:
        float: idle seconds (0.0 if invalid, otherwise max(0, now - last_trade_ts))
    """
    if now is None:
        now = time.time()

    # Invalid timestamp → 0 idle
    if not last_trade_ts:
        return 0.0

    try:
        ts = float(last_trade_ts)
    except (ValueError, TypeError):
        return 0.0

    # Zero or negative timestamp → 0 idle
    if ts <= 0:
        return 0.0

    # Future timestamp → 0 idle
    if ts > now:
        return 0.0

    idle = max(0.0, now - ts)

    # BUG FIX: Only clamp unix-timestamp-sized corrupted values (>10 years)
    # Do NOT clamp legitimate long idles (24+ hour market close, weekend)
    if idle > 315360000:  # ~10 years in seconds
        return 0.0

    return idle


from src.services.market_stream import start
from src.services.firebase_client import init_firebase, daily_budget_report, load_history, save_metrics_full
from src.services.learning_event import get_metrics, bootstrap_from_history
from src.services.trade_executor import get_open_positions
from src.services.signal_generator import warmup
from src.services.dashboard_live import dashboard_loop
from src.services.metrics_engine import MetricsEngine
from bot2.auditor import run_audit

# ────────────────────────────────────────────────────────────────────────────
# PATCH: Self-Healing System (Autonomous Failure Detection & Recovery)
# ────────────────────────────────────────────────────────────────────────────
try:
    from src.core.anomaly import AnomalyDetector
    from src.core.self_heal import (
        handle_anomaly,
        apply_safe_mode,
        apply_position_floor,
        apply_position_cap,
        failsafe_halt,
    )
    from src.core.state_history import StateHistory
except ImportError as e:
    import logging
    logging.warning(f"Self-healing imports failed: {e} - continuing without self-healing")
    AnomalyDetector = None
    StateHistory = None

# ────────────────────────────────────────────────────────────────────────────
# PATCH: V4 Self-Evolving Strategy (Genetic Algorithm)
# ────────────────────────────────────────────────────────────────────────────
try:
    from src.core.genetic_pool import GeneticPool
    from src.core.strategy_selector import StrategySelector
    from src.core.strategy_executor import StrategyExecutor
except ImportError as e:
    import logging
    logging.warning(f"Genetic algorithm imports failed: {e} - continuing without genetic pool")
    GeneticPool = None
    StrategySelector = None
    StrategyExecutor = None

# ────────────────────────────────────────────────────────────────────────────
# PATCH: V5.1 Reinforcement Learning (RL Agent)
# ────────────────────────────────────────────────────────────────────────────
# V5.1: Using RLAgent from src.services (not DQNAgent from src.core)
try:
    from src.services.rl_agent import RLAgent
    rl_agent_instance = RLAgent()
except Exception as e:
    import logging
    logging.warning(f"RL Agent import error: {e} - continuing without RL")
    rl_agent_instance = None

# Legacy imports (commented out for V5.1 compatibility)
# from src.core.rl_agent import DQNAgent
# from src.core.state_builder import StateBuilder, ACTIONS, action_to_name
# from src.core.reward_engine import RewardEngine

import src.services.signal_generator
import src.services.signal_engine
import src.services.trade_executor
import src.services.audit_worker

# V10.13s.1: Canonical state oracle for unified trade count / maturity
try:
    from src.services.canonical_state import (
        invalidate_cache,
        print_canonical_state,
    )
except ImportError:
    def invalidate_cache(): pass
    def print_canonical_state(): pass

# ────────────────────────────────────────────────────────────────────────────
# PATCH: Event Bus Integration (Zero Bug V2 Migration Phase 1)
# ────────────────────────────────────────────────────────────────────────────
try:
    from src.core.event_bus_v2 import get_event_bus
except ImportError:
    import logging
    logging.warning("Event bus import failed - using no-op implementation")
    def get_event_bus():
        class NoOpBus:
            def subscribe(self, *args, **kwargs): pass
            def emit(self, *args, **kwargs): pass
        return NoOpBus()

def _init_event_handlers():
    """Set up event handlers for LOG_OUTPUT events (replaces print)."""
    bus = get_event_bus()
    
    # Handler for LOG_OUTPUT events → print to console
    def log_handler(payload):
        if payload and isinstance(payload, dict):
            msg = payload.get("message", str(payload))
            timestamp = payload.get("timestamp", "")
            if timestamp:
                print(f"[{timestamp}] {msg}")
            else:
                print(msg)
        elif payload:
            print(payload)
    
    bus.subscribe("LOG_OUTPUT", log_handler, priority=100)

_last_audit      = 0
_last_metrics    = 0
_last_pre_audit  = 0

# ════════════════════════════════════════════════════════════════════════════════
# V10.13a: Per-symbol block reason tracking for observability
# ════════════════════════════════════════════════════════════════════════════════
_symbol_block_reasons = {}  # sym → (reason_code, reason_str, timestamp)
_cycle_stats = {
    "symbols_evaluated": 0,
    "candidates_generated": 0,
    "candidates_passed": 0,
    "candidates_executed": 0,
    "block_reasons": {},  # reason → count
}

# ════════════════════════════════════════════════════════════════════════════
# INTERVAL CONSTANTS — Control audit and metrics frequency
# ════════════════════════════════════════════════════════════════════════════
AUDIT_INTERVAL      = 120      # Run audit every 2 minutes
METRICS_INTERVAL    = 300      # Save metrics every 5 minutes (reduced from 30s to prevent quota exhaustion)
PRE_AUDIT_INTERVAL  = 60       # Run pre_live_audit every minute

# ────────────────────────────────────────────────────────────────────────────
# PATCH 3.1: Renderer Lock — Atomic rendering with deduplication
# ────────────────────────────────────────────────────────────────────────────
_render_lock = threading.Lock()
_last_snapshot_hash = [None]  # Use list for mutability

def atomic_render(snapshot_data, component_name=""):
    """PATCH 3.1 + ZERO BUG V2: Thread-safe render with deduplication.
    
    Prevents duplicate dashboard output by comparing hash of current snapshot
    to last rendered snapshot. Only renders if content changed.
    
    Uses event_bus.emit() instead of direct print() calls (Zero Bug Migration).
    
    Args:
        snapshot_data: dict or str to render (metrics, dashboard, learning monitor)
        component_name: Optional label for the component being rendered
    """
    with _render_lock:
        # BUG FIX: Exclude 'cycle_time' from hash to prevent false diffs
        # cycle_time always changes but doesn't affect content meaningfully
        hashable = {k: v for k, v in (snapshot_data.items() if isinstance(snapshot_data, dict) else {})} if isinstance(snapshot_data, dict) else snapshot_data
        if isinstance(hashable, dict):
            hashable = {k: v for k, v in hashable.items() if k != "cycle_time"}
        current_hash = hash(str(hashable))

        # Skip if identical to last render
        if current_hash == _last_snapshot_hash[0]:
            return

        _last_snapshot_hash[0] = current_hash
        
        # Render via event_bus (PATCH: Zero Bug V2 Migration)
        if snapshot_data:
            bus = get_event_bus()
            
            if component_name:
                msg = f"\n  ── {component_name} ────────────────────────────────────────"
                bus.emit("LOG_OUTPUT", {"message": msg}, time.time())
            
            if isinstance(snapshot_data, dict):
                import json
                msg = json.dumps(snapshot_data, indent=2, default=str)
            else:
                msg = str(snapshot_data)
            
            bus.emit("LOG_OUTPUT", {"message": msg}, time.time())

# ────────────────────────────────────────────────────────────────────────────
# PATCH 5 & 6: Watchdog + Last Trade Tracking
# ────────────────────────────────────────────────────────────────────────────
last_trade_ts = [time.time()]  # V10.12i: Initialize to current time, not 0.0


def watchdog(now, agent=None):
    """PATCH 5 & ZERO BUG V2: Watchdog — boost exploration if no trades in 600 seconds.

    Monitors trade frequency and increases exploration rate if system is idle.
    This maintains signal flow during market downturns or poor conditions.

    V10.12i: Use safe idle computation to prevent unix-time-sized STALL values.

    Uses event_bus.emit() instead of direct print() calls (Zero Bug Migration).
    """
    bus = get_event_bus()

    # V10.12i: Use safe idle computation instead of raw timestamp arithmetic
    idle_sec = safe_idle_seconds(last_trade_ts[0], now)

    if idle_sec > 600:
        msg = "[WATCHDOG] No trades for 600s → boosting exploration"
        bus.emit("LOG_OUTPUT", {"message": msg}, now)

        if agent and hasattr(agent, 'exploration_rate'):
            agent.exploration_rate = min(1.0, agent.exploration_rate + 0.2)
        else:
            # Direct exploration rate boost in decision engine
            try:
                import src.services.realtime_decision_engine as rde
                if hasattr(rde, '_exploration_boost'):
                    rde._exploration_boost = min(1.0, rde._exploration_boost + 0.2)
            except Exception:
                pass

    # ────────────────────────────────────────────────────────────────────────
    # PATCH 3.4 + ZERO BUG V2: Watchdog micro-trades — Allow small trades when idle
    # ────────────────────────────────────────────────────────────────────────
    if idle_sec > 900:  # 15 minutes idle
        msg = "[WATCHDOG] Critical idle (15min) → enabling micro-trades"
        bus.emit("LOG_OUTPUT", {"message": msg}, now)

        try:
            import src.services.trade_executor as te
            # Flag to allow smaller, exploratory positions
            if not hasattr(te, '_allow_micro_trade'):
                te._allow_micro_trade = False
            te._allow_micro_trade = True
        except Exception:
            pass


# ────────────────────────────────────────────────────────────────────────────
# PATCH: V4 Self-Evolving Strategy System (Genetic Algorithm)
# ────────────────────────────────────────────────────────────────────────────
_genetic_pool = None
_strategy_selector = None
_current_strategy = None
_strategy_trade_count = [0]  # Use list for mutability
_evolution_interval = 50  # Run evolution every N trades

# ────────────────────────────────────────────────────────────────────────────
# PATCH: V5 Reinforcement Learning (DQN Agent)
# ────────────────────────────────────────────────────────────────────────────
_rl_agent = None
_state_builder = None
_reward_engine = None
_prev_state = None
_prev_action = None
_episode_reward = [0.0]  # Use list for mutability
_rl_training_interval = 10  # Train every 10 transitions


# ── FX rate cache (USD/CZK) ───────────────────────────────────────────────────
_fx_usd_czk:      float = 0.0
_fx_last_fetch:   float = 0.0
_FX_REFRESH_SECS: int   = 3600   # refresh once per hour

def _refresh_fx_rate() -> None:
    """Fetch USD/CZK from Frankfurter API; silently keeps old value on error."""
    global _fx_usd_czk, _fx_last_fetch
    try:
        import urllib.request, json as _json
        with urllib.request.urlopen(
            "https://api.frankfurter.app/latest?from=USD&to=CZK", timeout=5
        ) as r:
            rate = _json.loads(r.read()).get("rates", {}).get("CZK", 0.0)
            if rate > 0:
                _fx_usd_czk    = float(rate)
                _fx_last_fetch = time.time()
    except Exception:
        pass  # keep stale value — better than 0


# ────────────────────────────────────────────────────────────────────────────
# PATCH: V4 Strategy Evolution Cycle (Genetic Algorithm)
# ────────────────────────────────────────────────────────────────────────────

def update_strategy_fitness(trade):
    """
    Update current strategy fitness when a trade closes.
    
    Called after every trade close to record outcomes and trigger evolution if needed.
    
    Args:
        trade: Trade object with pnl, net_pnl_pct, result, etc.
    """
    global _current_strategy, _strategy_trade_count, _genetic_pool, _strategy_selector
    
    if _current_strategy is None or _genetic_pool is None:
        return
    
    try:
        # Record trade in strategy
        _current_strategy.record_trade(trade)
        _strategy_trade_count[0] += 1
        
        # Log updates every 10 trades
        if _strategy_trade_count[0] % 10 == 0:
            bus = get_event_bus()
            msg = f"STRATEGY: {_current_strategy} | Pool avg fitness: {_genetic_pool.get_stats()['avg_fitness']:.3f}"
            bus.emit("LOG_OUTPUT", {"message": msg}, time.time())
        
        # Evolution trigger: every N trades
        if _strategy_trade_count[0] % _evolution_interval == 0:
            bus = get_event_bus()
            msg = f"🧬 EVOLVE: Running evolution cycle (trade #{_strategy_trade_count[0]})"
            bus.emit("LOG_OUTPUT", {"message": msg}, time.time())
            
            # Run evolution
            _genetic_pool.evolve()
            
            # Select new strategy for next trades
            _current_strategy = _strategy_selector.select(
                regime='RANGING',  # Could be enhanced with actual regime
                force_best=False
            )
            
            # Log pool state
            stats = _genetic_pool.get_stats()
            msg = (
                f"POOL: size={stats['population_size']}, "
                f"evolution={stats['evolution_count']}, "
                f"diversity={stats['diversity']}, "
                f"avg_fitness={stats['avg_fitness']:.3f}, "
                f"max_fitness={stats['max_fitness']:.3f}"
            )
            bus.emit("LOG_OUTPUT", {"message": msg}, time.time())
            
    except Exception as e:
        import logging as _log_evo
        _log_evo.getLogger(__name__).error(f"Strategy fitness update error: {e}")


# ────────────────────────────────────────────────────────────────────────────
# PATCH: V5 RL Training (Experience Replay & Q-Learning)
# ────────────────────────────────────────────────────────────────────────────

def train_rl_agent(trade, market_data=None, learning_state=None):
    """
    Train DQN agent on closed trade (experience replay).
    
    Called after every trade close. Records outcome as (state, action, reward, next_state)
    and trains the agent.
    
    Args:
        trade: Closed trade object
        market_data: Current market data (for state)
        learning_state: Learning system state (for state)
    """
    global _rl_agent, _state_builder, _reward_engine, _prev_state, _prev_action, _episode_reward
    
    if _rl_agent is None or _state_builder is None or _reward_engine is None:
        return
    
    try:
        # Compute reward for closed trade
        reward = _reward_engine.compute({
            'pnl': trade.net_pnl_pct / 100 if hasattr(trade, 'net_pnl_pct') else 0.0,
            'exit_reason': trade.close_reason.value if hasattr(trade, 'close_reason') else 'unknown',
            'duration_seconds': trade.duration_seconds if hasattr(trade, 'duration_seconds') else 0,
            'bars_held': 1,
        })
        
        _episode_reward[0] += reward
        
        # Build next state (from market data if available)
        if market_data is not None and learning_state is not None:
            next_state = _state_builder.build(market_data, learning_state)
        else:
            next_state = None
        
        # Record experience (state, action, reward, next_state, done)
        if _prev_state is not None and _prev_action is not None:
            done = True  # Trade is done
            _rl_agent.remember(_prev_state, _prev_action, reward, next_state or _prev_state, done)
            
            # Train agent on batch
            _rl_agent.replay(batch_size=32)
            
            # Log RL progress every 50 trades
            if _reward_engine.reward_count % 50 == 0:
                bus = get_event_bus()
                rl_stats = _rl_agent.get_stats()
                msg = (
                    f"🧠 RL STATUS: epsilon={rl_stats['epsilon']:.3f}, "
                    f"steps={rl_stats['training_steps']}, "
                    f"q_table={rl_stats['q_table_size']}, "
                    f"avg_reward={_reward_engine.avg_reward:.5f}"
                )
                bus.emit("LOG_OUTPUT", {"message": msg}, time.time())
        
        # Update previous state/action for next iteration
        _prev_state = next_state or _prev_state
        _prev_action = None  # Reset action (will be chosen by agent next cycle)
        
    except Exception as e:
        import logging as _log_rl
        _log_rl.getLogger(__name__).error(f"RL agent training error: {e}")


# ────────────────────────────────────────────────────────────────────────────
# RL Agent Safety Hooks (called by V3 self-healing when needed)
# ────────────────────────────────────────────────────────────────────────────

def rl_force_exploration():
    """Force RL agent to explore (during crisis/stall)."""
    global _rl_agent
    if _rl_agent:
        _rl_agent.force_exploration(epsilon=1.0)


def rl_force_exploitation():
    """Force RL agent to exploit best strategy (during safe mode)."""
    global _rl_agent
    if _rl_agent:
        _rl_agent.force_exploitation(epsilon=0.05)



_start_time = time.time()
from src.services.portfolio_discovery import get_active_symbols
W           = 60


# ── ANSI palette ──────────────────────────────────────────────────────────────

class C:
    GRN = "\033[92m"
    RED = "\033[91m"
    YLW = "\033[93m"
    CYN = "\033[96m"
    BLU = "\033[94m"
    MGT = "\033[95m"
    WHT = "\033[97m"
    GRY = "\033[90m"
    BLD = "\033[1m"
    DIM = "\033[2m"
    RST = "\033[0m"


def g(text, color):
    return f"{color}{text}{C.RST}"


# ── Bars ──────────────────────────────────────────────────────────────────────
#
#  Thin-line style (inspired by modern UI):
#    filled  ━  U+2501  thick horizontal
#    empty   ─  U+2500  thin horizontal
#    bubble  ●  shown at the fill point with % label
#
BAR_W = 22   # all bars same width


def cbar(val, total=1.0, w=BAR_W, lo=0.45, hi=0.60):
    """
    Thin progress bar with floating % bubble at the tip.

        ━━━━━━━━━━━━●─────────  45%
    """
    r   = min(max(val / total if total else 0, 0.0), 1.0)
    f   = max(int(w * r) - 1, 0)
    col = C.GRN if r >= hi else (C.YLW if r >= lo else C.RED)
    pct = f"{r*100:.0f}%"
    filled = col + "\u2501" * f
    tip    = col + "\u25cf"          # ●
    empty  = C.GRY + "\u2500" * (w - f - 1)
    label  = " " + g(pct, col + C.BLD)
    return filled + tip + empty + label + C.RST


def blue_bar(val, total, w=BAR_W):
    """
    Blue stepped bar for calibration — caps at 100%.

        ━━━━━━━━━━━━●─────────  46%
    """
    r   = min(max(val / total if total else 0, 0.0), 1.0)
    f   = max(int(w * r) - 1, 0)
    col = C.CYN if r >= 1.0 else C.BLU
    pct = "100%" if r >= 1.0 else f"{r*100:.0f}%"
    filled = col + "\u2501" * f
    tip    = col + "\u25cf"
    empty  = C.GRY + "\u2500" * (w - f - 1)
    label  = " " + g(pct, col + C.BLD)
    return filled + tip + empty + label + C.RST


def pnl_bar(profit, scale=0.001, w=BAR_W):
    """
    Directional P&L bar — green ▶ right / red ◀ left.

        ▶━━━━━━━━━━━━●─────────  +0.00012
    """
    r    = min(abs(profit) / scale, 1.0)
    f    = max(int(w * r) - 1, 0)
    col  = C.GRN if profit >= 0 else C.RED
    sign = "\u25b6" if profit >= 0 else "\u25c4"
    filled = col + sign + "\u2501" * f
    tip    = col + "\u25cf"
    empty  = C.GRY + "\u2500" * (w - f - 1)
    return filled + tip + empty + C.RST


def steps_bar(current, total, labels=None, w=None):
    """
    Step progress:  Step 1 ━━━● Step 2 ───  Step 3 ───
    current: 1-based index of active step
    """
    out = []
    for i in range(1, total + 1):
        label = (labels[i - 1] if labels and i <= len(labels)
                 else f"Krok {i}")
        if i < current:
            out.append(g(f"{label}", C.GRN) + g(" \u2501\u2501\u2501 ", C.GRN))
        elif i == current:
            out.append(g(f"\u25cf {label}", C.BLU + C.BLD) + g(" \u2500\u2500\u2500 ", C.GRY))
        else:
            out.append(g(f"{label}", C.GRY) + (g(" \u2500\u2500\u2500 ", C.GRY) if i < total else ""))
    return "".join(out)


# ── Helpers ───────────────────────────────────────────────────────────────────

def sep(char="\u2500"):
    return g(char * (W - 4), C.GRY)


def section(icon, title):
    return f"\n  {icon}  {g(title, C.BLD + C.WHT)}\n  {sep()}"


def price_arrow(curr, prev):
    if curr > prev * 1.0001: return g("\u25b2", C.GRN)
    if curr < prev * 0.9999: return g("\u25bc", C.RED)
    return g("\u2500", C.GRY)


def uptime():
    s = int(time.time() - _start_time)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m}m {s}s"


def since_fmt(secs):
    if secs is None or secs <= 0: return "-"
    if secs < 60:   return f"{int(secs)}s"
    if secs < 3600: return f"{int(secs/60)}m {int(secs%60)}s"
    return f"{int(secs/3600)}h {int((secs%3600)/60)}m"


def regime_label(regimes):
    total = sum(regimes.values())
    if not total: return g("cekam na data", C.GRY)
    dominant = max(regimes, key=regimes.get)
    pct = regimes[dominant] / total * 100
    info = {
        "BULL_TREND":  (C.GRN, "BULL TREND  silny vzestup"),
        "BEAR_TREND":  (C.RED, "BEAR TREND  silny pokles"),
        "RANGING":     (C.YLW, "RANGING     bocni pohyb"),
        "QUIET_RANGE": (C.GRY, "QUIET       bez pohybu"),
        "HIGH_VOL":    (C.MGT, "VOLATILNI   velke vykyvy"),
        "TREND":       (C.GRN, "TREND"),
        "CHOP":        (C.YLW, "CHOP  bocni"),
    }
    col, label = info.get(dominant, (C.WHT, dominant))
    return g(f"{label}  ({pct:.0f}%)", col)


# ── Status ────────────────────────────────────────────────────────────────────

def print_status():
    import logging as _log
    _dashboard_log = logging.getLogger("dashboard") if "logging" in dir() else _log.getLogger("dashboard")

    m   = get_metrics()
    lp  = m.get("last_prices", {})
    ls  = m.get("last_signals", {})
    ops = get_open_positions()

    # ── V10.13x.1: Canonical trade stats — single source of truth ────────────
    engine        = MetricsEngine()
    recent_trades = load_history(limit=500)
    canonical     = engine.compute_canonical_trade_stats(recent_trades)
    recent_stats  = engine.compute_recent_window_stats(recent_trades)

    t             = canonical["trades_total"]
    wins          = canonical["wins"]
    losses        = canonical["losses"]
    flats         = canonical["flats"]
    wr            = canonical["winrate"]
    profit        = canonical["net_pnl"]
    profit_factor = canonical["profit_factor"]
    expectancy    = canonical["expectancy"]
    best          = canonical["best_trade"]
    worst         = canonical["worst_trade"]
    _decisive     = wins + losses

    # Operational fields still from learning_event (not closed-trade derived)
    drawdown   = m["drawdown"]
    win_streak = m["win_streak"]
    los_streak = m["loss_streak"]
    conf       = m["confidence_avg"]
    gen        = m["signals_generated"]
    exe        = m["signals_executed"]
    blk        = m["blocked"]
    flt        = m["signals_filtered"]
    since      = m.get("since_last")
    pf         = profit_factor if t > 0 else 1.0
    exp        = expectancy    if t > 0 else 0.0

    # ── V10.13x.1 Source + Reconciliation logs ─────────────────────────────
    _rs_src = "canonical_recent_window" if recent_stats["known"] else "unavailable"
    _log.getLogger("dashboard").info(
        "[V10.13x.1 SRC] header=canonical_closed_trades symbols=canonical_closed_trades "
        "regimes=canonical_closed_trades exits=canonical_closed_trades "
        "recent=%s calibration=%s", _rs_src, _rs_src)

    _sym_cnt  = sum(s["count"]   for s in canonical["per_symbol"].values())
    _reg_cnt  = sum(r["count"]   for r in canonical["per_regime"].values())
    _exit_cnt = sum(s["count"]   for s in canonical["per_exit_type"].values())
    _sym_pnl  = sum(s["net_pnl"] for s in canonical["per_symbol"].values())
    _counts_ok = (t == 0) or (wins + losses + flats == t)
    _sym_ok    = (t == 0) or (_sym_cnt  == t)
    _reg_ok    = (t == 0) or (_reg_cnt  == t)
    _exit_ok   = (t == 0) or (_exit_cnt == t)
    _pnl_ok    = (t == 0) or (abs(_sym_pnl - profit) < 1e-9)
    _recent_ok = recent_stats["known"] or (t == 0)
    _recon_ok  = all([_counts_ok, _sym_ok, _reg_ok, _exit_ok, _pnl_ok, _recent_ok])
    _log.getLogger("dashboard").info(
        "[V10.13x.1 RECON] counts_ok=%s symbol_ok=%s regime_ok=%s exit_ok=%s "
        "recent_ok=%s status=%s",
        _counts_ok, _sym_ok, _reg_ok, _exit_ok, _recent_ok,
        "OK" if _recon_ok else "MISMATCH")
    if not _recon_ok:
        _log.getLogger("dashboard").warning(
            "[V10.13x.1 RECON] total=%d sym_sum=%d reg_sum=%d exit_sum=%d "
            "pnl_total=%.8f pnl_symbol=%.8f",
            t, _sym_cnt, _reg_cnt, _exit_cnt, profit, _sym_pnl)

    # ── Header ────────────────────────────────────────────────────────────────
    status_tag = (g(" AKTIVNI ", C.BLD + C.GRN) if m["ready"]
                  else g(" TRENINK ", C.YLW))
    print(f"\n{g('=' * W, C.CYN)}")
    print(g(f"  CRYPTOMASTER  |  {uptime()}  |{status_tag}", C.BLD + C.CYN))
    print(g("=" * W, C.CYN))

    # ── Live prices ───────────────────────────────────────────────────────────
    print(section("", "ZIVE CENY  (Binance · kazde 1 s)"))
    for sym in get_active_symbols():
        short = sym.replace("USDT", "")
        if sym not in lp:
            print(f"    {g(short, C.WHT):<4}  {g('cekam...', C.GRY)}")
            continue
        curr, prev = lp[sym]
        arr  = price_arrow(curr, prev)
        pct  = (curr - prev) / prev * 100 if prev else 0
        pcol = C.GRN if pct > 0 else (C.RED if pct < 0 else C.GRY)
        open_tag = g("  [OPEN]", C.YLW + C.BLD) if sym in ops else ""
        print(f"    {g(short, C.WHT + C.BLD):<4}  "
              f"{g(f'${curr:>14,.4f}', C.WHT)}   "
              f"{arr}  {g(f'{pct:+.3f}%', pcol)}"
              f"{open_tag}")

    # ── Trade count by symbol ─────────────────────────────────────────────────
    per_sym_c = canonical.get("per_symbol", {})
    if t > 0:
        print(section("", "POCET OBCHODU"))
        print(f"    {g('Mena', C.GRY):<5}  {g('Pocet', C.GRY):>6}")
        print(f"    {g('-' * 25, C.GRY)}")
        for sym in sorted(per_sym_c.keys()):
            short = sym.replace("USDT", "")
            cs = per_sym_c[sym]
            cnt = cs.get("count", 0)
            if cnt > 0:
                print(f"    {g(short, C.WHT + C.BLD):<5}  {g(str(cnt), C.WHT):>6}")
        print(f"    {g('-' * 25, C.GRY)}")
        print(f"    {g('CELKEM', C.WHT + C.BLD):<5}  {g(str(t), C.WHT + C.BLD):>6}")

    # ── Open positions ────────────────────────────────────────────────────────
    if ops:
        print(section("", "OTEVRENE POZICE"))
        for sym, pos in ops.items():
            short   = sym.replace("USDT", "")
            curr    = lp.get(sym, (pos["entry"], pos["entry"]))[0]
            entry   = pos["entry"]
            action  = pos["action"]
            tp_pct  = pos["tp_move"] * 100
            sl_pct  = pos["sl_move"] * 100
            size    = pos["size"]
            move    = (curr - entry) / entry
            if action == "SELL":
                move *= -1
            pnl  = move * size
            pcol = C.GRN if pnl >= 0 else C.RED
            act  = g(action, C.GRN if action == "BUY" else C.RED)
            # Format TP/SL or Trailing Stop label
            if pos.get("is_trailing"):
                trail_sl_pct = (pos["trail_price"] * 1.5 * pos["signal"].get("atr", entry * 0.003)) / entry * 100 if entry else 0
                sl_str = g(f'🚀 TRAILING', C.CYN + C.BLD)
            else:
                sl_str = g(f'TP:{tp_pct:.2f}%  SL:{sl_pct:.2f}%', C.GRY)

            print(f"    {g(short, C.WHT + C.BLD):<4}  {act}  "
                  f"{g(f'${entry:,.4f}', C.GRY)}"
                  f"{g('->', C.GRY)}"
                  f"{g(f'${curr:,.4f}', C.WHT)}  "
                  f"{g(f'{pnl:+.6f}', pcol)}  "
                  f"{sl_str}")

    # ── Trading performance ───────────────────────────────────────────────────
    print(section("", "VYSLEDKY OBCHODOVANI"))
    if t == 0:
        print(f"    {g('Zadne uzavrene obchody – robot se zahriva...', C.GRY)}")
    else:
        w_pct   = wr * 100
        wr_col  = C.GRN if wr >= 0.55 else (C.YLW if wr >= 0.45 else C.RED)
        pr_col  = C.GRN if profit >= 0 else C.RED
        dd_col  = C.GRN if drawdown < 0.001 else (C.YLW if drawdown < 0.005 else C.RED)
        pf_col  = C.GRN if pf >= 1.5 else (C.YLW if pf >= 1.0 else C.RED)
        exp_col = C.GRN if exp > 0 else C.RED

        print(f"    {g('Obchody', C.GRY)}    {g(str(t), C.WHT + C.BLD)}  "
              f"({g(f'OK {wins}', C.GRN)}  {g(f'X {losses}', C.RED)}  "
              f"{g(f'~ {flats}', C.GRY)})")

        if not canonical["reconciliation"]["verified"]:
            alerts_str = "; ".join(canonical["reconciliation"]["alerts"])
            print(f"    {g(f'RECON MISMATCH: {alerts_str}', C.RED + C.BLD)}")

        if _decisive < 10:
            _wr_note = g(f"(malo dat: {_decisive}/10 rozhodujicich)", C.GRY)
            print(f"    {g('WR_canonical', C.GRY)}     {g('N/A', C.GRY + C.BLD)}  {_wr_note}")
        else:
            print(f"    {g('WR_canonical', C.GRY)}     "
                  f"{g(f'{w_pct:.1f}%', wr_col + C.BLD)}  "
                  f"{cbar(wr, 1.0, lo=0.45, hi=0.55)}  "
                  f"{g('cil 55%', C.GRY)}  "
                  f"{g('(vsechny uzavrene, bez remiz)', C.GRY)}")

        print(f"    {g('Zisk (uzavrene)', C.GRY)}  "
              f"{g(f'{profit:+.8f}', pr_col + C.BLD)}  "
              f"{pnl_bar(profit)}")

        print(f"    {g('Drawdown', C.GRY)}    "
              f"{g(f'{drawdown:.8f}', dd_col)}  "
              f"{g('(pokles od vrcholu)', C.GRY)}")

        if win_streak >= 2:
            print(f"    {g('Serie', C.GRY)}       "
                  f"{g(f'FIRE {win_streak}x vyhra v rade!', C.GRN + C.BLD)}")
        elif los_streak >= 2:
            print(f"    {g('Serie', C.GRY)}       "
                  f"{g(f'STOP {los_streak}x prohra v rade', C.RED)}")

        print(f"    {g('-' * 40, C.GRY)}")
        print(f"    {g('Profit Factor', C.GRY)}  "
              f"{g(f'{pf:.2f}x', pf_col + C.BLD)}  "
              f"{g('(zisk / ztrata, cil > 1.5)', C.GRY)}")
        print(f"    {g('Expectancy', C.GRY)}     "
              f"{g(f'{exp:+.8f}', exp_col)}  "
              f"{g('(prumerny vynos / obchod)', C.GRY)}")
        if best:
            print(f"    {g('Nejlepsi', C.GRY)}      "
                  f"{g(f'+{best:.8f}', C.GRN)}   "
                  f"{g('Nejhorsi', C.GRY)}  "
                  f"{g(f'{worst:.8f}', C.RED)}")
        if since is not None:
            print(f"    {g('Posledni obchod', C.GRY)}  "
                  f"{g(since_fmt(since), C.WHT)} {g('zpet', C.GRY)}")

    # ── Exit Attribution (Economic, canonical source) ─────────────────────────
    per_exit = canonical.get("per_exit_type", {})
    if per_exit and t > 0:
        print(section("", "VYSLEDKY PODLE TYPU UZAVRENI"))
        _exit_total_pnl = sum(s["net_pnl"] for s in per_exit.values())
        _abs_pnl        = abs(_exit_total_pnl) or 1.0
        _exit_rows = sorted(per_exit.items(), key=lambda x: x[1]["net_pnl"], reverse=True)
        for et, s in _exit_rows:
            ec    = s["count"];  ew = s["wins"];  el = s["losses"]
            epnl  = s["net_pnl"];  eavg = s["avg_pnl"]
            epct  = s["pct_of_total"]
            eppnl = abs(epnl) / _abs_pnl * 100
            ewr   = ew / (ew + el) if (ew + el) > 0 else None
            ewr_s = (g(f"WR {ewr*100:.0f}%", C.GRN if (ewr or 0) >= 0.55 else
                       (C.YLW if (ewr or 0) >= 0.45 else C.RED)) if ewr is not None
                     else g("WR N/A", C.GRY))
            pcol  = C.GRN if epnl >= 0 else C.RED
            print(f"    {g(et[:20], C.WHT + C.BLD):<22}  "
                  f"{g(str(ec), C.WHT):>3}  {ewr_s}  "
                  f"net {g(f'{epnl:+.8f}', pcol)}  "
                  f"avg {g(f'{eavg:+.8f}', pcol)}  "
                  f"{epct:.0f}% obch  {eppnl:.0f}% pnl")

    # ── Per-symbol breakdown (canonical) ──────────────────────────────────────
    per_sym_c = canonical.get("per_symbol", {})
    if per_sym_c and t > 0:
        print(section("", "VYSLEDKY PO MENACH"))
        print(f"    {g('Mena', C.GRY):<5}  "
              f"{g('Obch', C.GRY):>4}  "
              f"{g('WR', C.GRY):>5}  "
              f"{g('Bar', C.GRY):<20}  "
              f"{g('Zisk', C.GRY):>12}")
        print(f"    {g('-' * 50, C.GRY)}")
        for sym in get_active_symbols():
            short = sym.replace("USDT", "")
            cs = per_sym_c.get(sym)
            if not cs:
                print(f"    {g(short, C.GRY):<5}  {g('-', C.GRY)}")
                continue
            str_    = cs["count"]
            swins   = cs["wins"]
            slosses = cs["losses"]
            sproft  = cs["net_pnl"]
            s_dec   = swins + slosses
            swr     = swins / s_dec if s_dec > 0 else None
            if swr is None:
                swr_s = g("N/A", C.GRY + C.BLD);  icon = g("-", C.GRY)
            else:
                wcol  = C.GRN if swr >= 0.55 else (C.YLW if swr >= 0.45 else C.RED)
                swr_s = g(f"{swr*100:.0f}%", wcol + C.BLD)
                icon  = g("OK", C.GRN) if swr >= 0.55 else (g("?", C.YLW) if swr >= 0.45 else g("X", C.RED))
            pcol = C.GRN if sproft >= 0 else C.RED
            print(f"    {g(short, C.WHT + C.BLD):<5}  "
                  f"{g(str(str_), C.WHT):>4}  "
                  f"{swr_s:>5}  "
                  f"{cbar(swr or 0.0, 1.0, lo=0.45, hi=0.55)}  "
                  f"{g(f'{sproft:+.8f}', pcol):>12}  {icon}")

    # ── Learning ──────────────────────────────────────────────────────────────
    from src.services.learning_event import get_ev_stats, get_close_stats
    ev_st  = get_ev_stats()
    cl_st  = get_close_stats()

    print(section("", "UCENI – STAV A USPESNOST"))

    # Calibration progress (canonical decisive count)
    if _decisive >= 50:
        cal_label = g("KALIBROVAN  ✓", C.GRN + C.BLD)
        cal_note  = g(f"({_decisive} rozhodujicich obchodu)", C.GRY)
    else:
        cal_label = g(f"{_decisive} / 50 rozhodujicich", C.BLU + C.BLD)
        cal_note  = g(f"({50 - _decisive} zbyva)", C.GRY)
    print(f"    {g('Kalibrace', C.GRY)}      "
          f"{cal_label}  "
          f"{blue_bar(_decisive, 50)}  "
          f"{cal_note}")

    # Learning trend + recent-window (canonical only; N/A when unavailable)
    if recent_stats["known"]:
        _rc_w  = recent_stats["window"]
        _rwr_w = recent_stats["wr"]
        _delta = _rwr_w - wr if wr > 0 else 0.0
        if _rc_w >= 10:
            if _delta > 0.05:    _trend_s = "ZLEPŠUJE SE"
            elif _delta < -0.05: _trend_s = "ZHORŠUJE SE"
            else:                _trend_s = "STABILNÍ"
            _tcol = C.GRN if "ZLEP" in _trend_s else (C.RED if "ZHOR" in _trend_s else C.YLW)
        else:
            _trend_s = "SBÍRÁ DATA...";  _tcol = C.GRY
        _dcol = C.GRN if _delta >= 0 else C.RED
        print(f"    {g('Trend uceni', C.GRY)}    {g(_trend_s, _tcol + C.BLD)}")
        print(f"    {g(f'Poslednich {_rc_w}', C.GRY)}    "
              f"{g(f'{_rwr_w*100:.1f}%', C.WHT)}  vs  prumer {g(f'{wr*100:.1f}%', C.WHT)}  "
              f"{g(f'({_delta:+.1%})', _dcol)}")
    else:
        print(f"    {g('Trend uceni', C.GRY)}    "
              f"{g('N/A', C.GRY + C.BLD)}  "
              f"{g('(zadne rozhodujici obchody)', C.GRY)}")
        print(f"    {g('Poslednich', C.GRY)}       "
              f"{g('N/A  (nedostatek recent dat)', C.GRY)}")

    # EV performance (session ring-buffer)
    if ev_st["count"] > 0:
        ev_avg     = ev_st["avg"];  ev_min = ev_st["min"]
        ev_max     = ev_st["max"];  ev_cnt = ev_st["count"]
        ev_avg_col = C.GRN if ev_avg >= 0.1 else (C.YLW if ev_avg >= 0.05 else C.RED)
        print(f"    {g('EV vykon', C.GRY)}       "
              f"prumer {g(f'{ev_avg:.3f}', ev_avg_col + C.BLD)}  "
              f"min {g(f'{ev_min:.3f}', C.GRY)}  "
              f"max {g(f'{ev_max:.3f}', C.GRY)}  "
              f"{g(f'({ev_cnt} obch)', C.GRY)}")
    else:
        print(f"    {g('EV vykon', C.GRY)}       {g('N/A', C.GRY)}")

    # Close-reason summary (session ring-buffer)
    total_cl = sum(v["n"] for v in cl_st.values())
    if total_cl > 0:
        def _pct(*keys):
            return sum(cl_st.get(k, {}).get("pct", 0.0) for k in keys)
        tp_pct = _pct("TP", "MICRO_TP", "PARTIAL_TP_25", "PARTIAL_TP_50",
                      "PARTIAL_TP_75", "HARVEST_PROFIT", "TIMEOUT_PROFIT")
        sl_pct = _pct("SL")
        tr_pct = _pct("trail", "TRAIL_SL", "TRAIL_PROFIT")
        sc_pct = _pct("SCRATCH_EXIT", "STAGNATION_EXIT", "BREAKEVEN_STOP",
                      "early_exit", "wall_exit")
        to_pct = _pct("timeout", "TIMEOUT_FLAT", "TIMEOUT_LOSS")
        print(f"    {g('Uzavreni', C.GRY)}       "
              f"TP {g(f'{tp_pct:.0f}%', C.GRN if tp_pct >= 40 else C.YLW)}  "
              f"SL {g(f'{sl_pct:.0f}%', C.RED if sl_pct >= 40 else C.YLW)}  "
              f"trail {g(f'{tr_pct:.0f}%', C.GRN if tr_pct >= 10 else C.GRY)}  "
              f"scratch {g(f'{sc_pct:.0f}%', C.RED if sc_pct >= 40 else C.YLW)}  "
              f"timeout {g(f'{to_pct:.0f}%', C.RED if to_pct >= 30 else C.YLW)}")
    else:
        print(f"    {g('Uzavreni', C.GRY)}       {g('N/A', C.GRY)}")

    # Win-prob calibration quality (gated on known recent-window + sufficient decisive count)
    if recent_stats["known"] and _decisive >= 5:
        cal_drift = abs(conf - wr)
        cal_col   = C.GRN if cal_drift < 0.08 else (C.YLW if cal_drift < 0.15 else C.RED)
        cal_note2 = "dobre" if cal_drift < 0.08 else ("ok" if cal_drift < 0.15 else "odkalibrovan")
        print(f"    {g('Kalibrace p', C.GRY)}    "
              f"p={g(f'{conf*100:.1f}%', C.WHT)}  WR={g(f'{wr*100:.1f}%', C.WHT)}  "
              f"odchylka {g(f'{cal_drift*100:.1f}pp', cal_col + C.BLD)}  "
              f"{g(cal_note2, cal_col)}")
    elif not recent_stats["known"]:
        print(f"    {g('Kalibrace p', C.GRY)}    "
              f"{g('N/A  (chybi recent rozhodujici obchody)', C.GRY)}")

    # Regime-specific WR table (canonical source)
    per_reg_c = canonical.get("per_regime", {})
    if per_reg_c and t > 0:
        print(f"    {g('WR dle rezimu', C.GRY)}")
        regime_order = ["BULL_TREND", "BEAR_TREND", "RANGING", "QUIET_RANGE", "HIGH_VOL"]
        _rlabels = {"BULL_TREND": "BULL ", "BEAR_TREND": "BEAR ",
                    "RANGING": "RANGE", "QUIET_RANGE": "QUIET", "HIGH_VOL": "HVOL "}
        for reg in regime_order:
            if reg not in per_reg_c:
                continue
            rc_r  = per_reg_c[reg]
            rnt   = rc_r["count"]
            r_dec = rc_r["wins"] + rc_r["losses"]
            rwr2  = rc_r["wins"] / r_dec if r_dec > 0 else None
            label = _rlabels.get(reg, reg[:5])
            if rwr2 is None:
                print(f"      {g(label, C.WHT + C.BLD)}  {g('N/A', C.GRY)}  "
                      f"{g(f'({rnt} obch)', C.GRY)}")
            else:
                rcol = C.GRN if rwr2 >= 0.55 else (C.YLW if rwr2 >= 0.45 else C.RED)
                print(f"      {g(label, C.WHT + C.BLD)}  "
                      f"{cbar(rwr2, 1.0, lo=0.45, hi=0.55)}  "
                      f"{g(f'{rwr2*100:.0f}%', rcol + C.BLD)}  "
                      f"{g(f'({rnt} obch)', C.GRY)}")

    # ── Auditor status ────────────────────────────────────────────────────────
    from bot2.auditor import is_in_cooldown, get_position_size_mult
    from src.services.learning_event import trades_in_window, trades_per_hour
    in_cd    = is_in_cooldown()
    sz_mult  = get_position_size_mult()
    t15      = trades_in_window(900)
    t1h      = trades_per_hour()

    # V10.13b: Use actual RDE thresholds instead of auditor placeholders
    try:
        from src.services.realtime_decision_engine import _last_ev_threshold, _last_score_threshold
        ev_thr = _last_ev_threshold
        score_thr = _last_score_threshold
    except Exception:
        ev_thr = 0.0
        score_thr = 0.0

    ev_col   = C.GRN if ev_thr <= 0.05 else C.YLW
    score_col = C.GRN if score_thr <= 0.5 else C.YLW
    sz_col   = C.GRN if sz_mult >= 1.0 else (C.YLW if sz_mult >= 0.5 else C.RED)
    cd_tag   = g("  COOLDOWN", C.RED + C.BLD) if in_cd else g("  aktivni", C.GRN)
    print(section("", "AUDITOR  (ochrana strategie)"))
    print(f"    {g('EV prah', C.GRY)}              "
          f"{g(f'{ev_thr:.3f}', ev_col + C.BLD)}  "
          f"{g(f'score prah {score_thr:.3f}', score_col)}  "
          f"{g(f't15={t15}  t60={t1h}', C.GRY)}"
          f"{cd_tag}")
    print(f"    {g('Velikost pozice', C.GRY)}      "
          f"{g(f'{sz_mult:.2f}x', sz_col + C.BLD)}  "
          f"{g('EV-only · loss streak → scale · DD halt 40%', C.GRY)}")

    # ── Strategy / Signals ────────────────────────────────────────────────────
    print(section("", "STRATEGIE  (ADX + EMA + MACD + BB + RSI)"))

    # V10.13d: Get current-cycle stats
    try:
        from src.services.signal_generator import get_cycle_stats as get_sg_stats
        sg_stats = get_sg_stats()
        cycle_candidates = sg_stats.get("candidates_generated", 0)
    except (ImportError, Exception):
        cycle_candidates = 0

    passed = max(0, gen - flt - blk)
    eff = passed / gen * 100 if gen else 0
    eff_col = C.GRN if eff > 2 else C.YLW

    print(f"    {g('Rezim trhu', C.GRY)}   {regime_label(m['regimes'])}")
    # V10.13d: Show current-cycle candidates separately from historical
    print(f"    {g('Signaly (THIS CYCLE)', C.GRY)}  "
          f"{g(str(cycle_candidates), C.WHT)} kandidati  "
          f"(cele: {g(str(gen), C.GRY)} zachyceno  "
          f"{g(str(exe), C.GRN)} provedeno)")
    print(f"    {g('Filtrace', C.GRY)}      "
          f"{g(f'{eff:.1f}%', eff_col)}  "
          f"{g('projde filtrem', C.GRY)}  "
          f"{g('TP: 1.2xATR  /  SL: 0.8xATR  (RR 1.5:1)  EV-only', C.GRY)}")

    # ── Last signals ──────────────────────────────────────────────────────────
    if ls:
        print(section("", "POSLEDNI ROZHODNUTI"))
        for sym in get_active_symbols():
            short = sym.replace("USDT", "")
            if sym not in ls:
                # V10.13a: Show actual block reason instead of generic "zadny signal"
                block_info = _symbol_block_reasons.get(sym, (None, None, None))
                if block_info[1]:
                    reason_str = block_info[1]
                else:
                    reason_str = "zadny signal"
                print(f"    {g(short, C.WHT + C.BLD):<4}  {g(reason_str, C.GRY)}")
                continue
            sig    = ls[sym]
            action = sig["action"]
            sprice = sig["price"]
            sconf  = sig["confidence"] * 100
            sev    = sig.get("ev", 0)
            sreg   = sig.get("regime", "")
            res    = sig.get("result")
            is_buy = action == "BUY"
            act    = g("KUPUJ ", C.GRN + C.BLD) if is_buy else g("PRODEJ", C.RED + C.BLD)
            rtag   = (g("  VYHRA",  C.GRN + C.BLD) if res == "WIN"
                      else g("  PROHRA", C.RED + C.BLD) if res == "LOSS" else "")
            ev_tag = g(f"  ev:{sev:.3f}", C.CYN) if sev else ""
            reg_short = {"BULL_TREND": "BULL", "BEAR_TREND": "BEAR",
                         "RANGING": "RANGE", "QUIET_RANGE": "QUIET"}.get(sreg, sreg[:5])
            print(f"    {g(short, C.WHT + C.BLD):<4}  {act}  "
                  f"{g(f'${sprice:,.4f}', C.WHT)}  "
                  f"{g(f'p:{sconf:.0f}%', C.GRY)}"
                  f"{ev_tag}  {g(reg_short, C.GRY)}"
                  f"{rtag}")

    # ── Footer ────────────────────────────────────────────────────────────────
    # 3-step progress: Sbírám data → Trénink → Aktivní
    if m["ready"]:
        step = 3
    elif t >= 50:
        step = 2
    else:
        step = 1
    print(f"\n  {sep()}")
    print(f"  {steps_bar(step, 3, ['Sbiram data', 'Trenink', 'Aktivni'])}")
    print(f"  {sep()}")
    if m["ready"]:
        print(f"  {g('STAV:', C.BLD)}  "
              f"{g('AKTIVNI – robot je kalibrovany a obchoduje!', C.GRN + C.BLD)}")
    else:
        needs = []
        if t < 50:      needs.append(g(f"obchody {t}/50", C.YLW))
        if wr <= 0.55:  needs.append(g(f"winrate {wr*100:.0f}%->55%", C.YLW))
        if profit <= 0: needs.append(g("zisk > 0", C.YLW))
        joined = ",  ".join(needs)
        print(f"  {g('STAV:', C.BLD)}  {g('TRENINK', C.YLW + C.BLD)}  "
              f"{g('(', C.GRY)}{joined}{g(')', C.GRY)}")
    print(g("=" * W, C.CYN) + "\n")


# ── Pre-live audit (periodic health check, replay from Firestore) ─────────────

def _run_pre_live_audit() -> None:
    """
    Run pre_live_audit in replay mode every PRE_AUDIT_INTERVAL seconds.

    Replays the last 20 closed trades through the full sizing chain, checks
    invariants, and publishes a summary to Firebase (audit/latest).
    Non-blocking: any exception is caught and logged; bot loop continues.
    """
    try:
        from src.services.pre_live_audit import run_audit as _pa_run
        print("\n[bot2] ── pre_live_audit ─────────────────────────────────────")
        results, ci_pass = _pa_run(
            n_trades = 20,
            verbose  = False,   # quiet — summary only in bot2 log
            seed     = 42,
            replay   = True,    # use real closed trades from Firestore
        )
        # ── Publish audit summary to Firebase for observability ───────────────
        try:
            from src.services.firebase_client import get_db
            _db = get_db()
            if _db is not None:
                _passed  = [r for r in results if r.passed]
                _sizes   = [r.s_final     for r in _passed]
                _rbs     = [r.risk_budget for r in _passed]
                _blocked = len(results) - len(_passed)
                _mono_v  = sum(len(r.monotone_violations) for r in results)
                _summary = {
                    "ci_pass":             ci_pass,
                    "timestamp":           time.time(),
                    "mode":                "replay",
                    "total_trades":        len(results),
                    "blocked_trades":      _blocked,
                    "blocked_ratio":       round(_blocked / max(len(results), 1), 4),
                    "monotone_violations": _mono_v,
                    "avg_size":            round(sum(_sizes) / max(len(_sizes), 1), 6),
                    "avg_risk_budget":     round(sum(_rbs)   / max(len(_rbs),   1), 4),
                }
                _db.document("audit/latest").set(_summary)
        except Exception as _fb_exc:
            print(f"[bot2] audit Firebase publish skipped: {_fb_exc}")

        status = "PASS" if ci_pass else "FAIL"
        print(f"[bot2] pre_live_audit complete  ci={status}")
        print("[bot2] ─────────────────────────────────────────────────────────")
    except Exception as exc:
        print(f"[bot2] pre_live_audit skipped: {exc.__class__.__name__}: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────

# Self-healing system globals
_anomaly_detector = None
_state_history = None

# ════════════════════════════════════════════════════════════════════════════════
# V10.13a: Cycle tracking and block reason reporting
# ════════════════════════════════════════════════════════════════════════════════

def track_symbol_block_reason(sym: str, reason_code: str, reason_str: str) -> None:
    """Track the last block reason for a symbol.

    V10.13a: Used to display per-symbol decision status in live output.
    """
    global _symbol_block_reasons
    _symbol_block_reasons[sym] = (reason_code, reason_str, time.time())


def track_cycle_stats(candidates: int, passed: int, executed: int, block_reasons_dict: dict) -> None:
    """Update cycle statistics for end-of-cycle reporting.

    V10.13a: Accumulates per-cycle metrics for diagnosis.
    """
    global _cycle_stats
    _cycle_stats["candidates_generated"] = candidates
    _cycle_stats["candidates_passed"] = passed
    _cycle_stats["candidates_executed"] = executed
    _cycle_stats["block_reasons"] = block_reasons_dict.copy() if block_reasons_dict else {}


def print_cycle_summary(now: float) -> None:
    """Print authoritative cycle-level summary.

    V10.13q: Enhanced with entry kill attribution telemetry.
    Shows:
    - Market data freshness (ticks, symbols updated)
    - Pre-filter candidate tracking (prefilter drops with reasons)
    - Candidate generation and pass rates
    - Hard vs soft blocks (SKIP_SCORE_HARD/SOFT, FAST_FAIL_HARD/SOFT, OFI_TOXIC_HARD/SOFT)
    - V10.13q: Final kill attribution (which layer actually rejected each candidate)
    - Active EV and score thresholds
    - Unblock mode and idle state
    """
    global _cycle_stats, _symbol_block_reasons

    try:
        from src.services.realtime_decision_engine import get_ev_threshold, get_score_threshold, get_kill_audit_summary
        from src.services.adaptive_recovery import is_unblock_mode
        from src.services.learning_event import METRICS
        from src.services.signal_generator import get_cycle_stats as get_sg_stats

        ev_thr = get_ev_threshold()
        score_thr = get_score_threshold()
        unblock = is_unblock_mode()
        idle_sec = safe_idle_seconds(METRICS.get("last_trade_time"), now)  # BUG FIX: last_trade_time (not last_trade_ts)

        # V10.13d: Get upstream signal generation stats
        sg_stats = get_sg_stats()
        ticks_received = sg_stats.get("ticks", 0)
        symbols_updated = sg_stats.get("symbols_updated", 0)
        prefilter_drops = sg_stats.get("prefilter_drops", {})

        # V10.13c: Count block reasons, separating hard and soft
        block_counts = _cycle_stats.get("block_reasons", {})
        top_block = max(block_counts.items(), key=lambda x: x[1])[0] if block_counts else "NONE"

        # V10.13c: Extract hard vs soft block counts for all blockers
        score_hard = block_counts.get("SKIP_SCORE_HARD", 0)
        score_soft = block_counts.get("SKIP_SCORE_SOFT", 0)
        fast_fail_hard = block_counts.get("FAST_FAIL_HARD", 0)
        fast_fail_soft = block_counts.get("FAST_FAIL_SOFT", 0)
        ofi_hard = block_counts.get("OFI_TOXIC_HARD", 0)
        ofi_soft = block_counts.get("OFI_TOXIC_SOFT", 0)

        # Format breakdown string
        hard_soft_str = ""
        if any([score_hard, score_soft, fast_fail_hard, fast_fail_soft, ofi_hard, ofi_soft]):
            hard_soft_str = (
                f"  | score_hard={score_hard} score_soft={score_soft} "
                f"ff_hard={fast_fail_hard} ff_soft={fast_fail_soft} "
                f"ofi_hard={ofi_hard} ofi_soft={ofi_soft}"
            )

        # V10.13d: Format upstream diagnostics
        upstream_str = f"  | ticks={ticks_received} syms={symbols_updated}"
        if prefilter_drops:
            drop_summary = ", ".join(f"{sym}:{reason}" for sym, reason in sorted(prefilter_drops.items())[:5])
            upstream_str += f" drops=[{drop_summary}]"

        # V10.13q: Add kill attribution summary
        kill_audit = get_kill_audit_summary()
        kill_str = ""
        if kill_audit["cycle_kills"]:
            top_kills = sorted(kill_audit["cycle_kills"].items(), key=lambda x: -x[1])[:3]
            kill_str = "  | kills=[" + ", ".join(f"{r}={c}" for r, c in top_kills) + "]"

        if kill_audit["cycle_rescues"]:
            rescue_str = "  | rescues=[" + ", ".join(f"{r}={c}" for r, c in kill_audit["cycle_rescues"].items()) + "]"
        else:
            rescue_str = ""

        # V10.13r: Add bootstrap telemetry if cold-start mode is active
        bootstrap_str = ""
        try:
            from src.services.realtime_decision_engine import is_cold_start, get_bootstrap_summary
            if is_cold_start():
                bs_summary = get_bootstrap_summary()
                if bs_summary.get("relaxed_ofi") or bs_summary.get("softened_fast_fail") or bs_summary.get("freq_relief") or bs_summary.get("threshold_relief"):
                    uptime_min = (_curr_time - bs_summary.get("start_ts", _curr_time)) / 60.0
                    global_n = 0
                    try:
                        from src.services.learning_event import METRICS as _M_bs
                        global_n = _M_bs.get("trades", 0)
                    except Exception:
                        pass
                    bootstrap_str = (
                        f"  | [V10.13r_BOOTSTRAP] active=True global_n={global_n} uptime_min={uptime_min:.1f} "
                        f"relaxed_ofi={bs_summary.get('relaxed_ofi', 0)} "
                        f"softened_ff={bs_summary.get('softened_fast_fail', 0)} "
                        f"freq_relief={bs_summary.get('freq_relief', 0)} "
                        f"threshold_relief={bs_summary.get('threshold_relief', 0)}"
                    )
        except Exception:
            pass

        # V10.13s: Add reset integrity telemetry if mismatch was detected/corrected
        reset_integrity_str = ""
        try:
            from src.services.realtime_decision_engine import _reset_integrity_state
            if _reset_integrity_state.get("validation_run") and _reset_integrity_state.get("mismatch_detected"):
                reset_integrity_str = (
                    f"  | [V10.13s_RESET_INTEGRITY] mismatch_detected=True "
                    f"effective_n={_reset_integrity_state.get('effective_completed_trades', 0)} "
                    f"stale_cleared={'True' if _reset_integrity_state.get('stale_metrics_cleared') else 'False'}"
                )
        except Exception:
            pass

        print(
            f"[V10.13q CYCLE] "
            f"gen={_cycle_stats['candidates_generated']} "
            f"pass={_cycle_stats['candidates_passed']} "
            f"exe={_cycle_stats['candidates_executed']} "
            f"top={top_block} "
            f"ev_thr={ev_thr:.4f} score_thr={score_thr:.4f} "
            f"unblock={'Y' if unblock else 'N'} idle={idle_sec:.0f}s{upstream_str}{hard_soft_str}{kill_str}{rescue_str}{bootstrap_str}{reset_integrity_str}"
        )
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).debug(f"Cycle summary error: {e}")


def main():
    # V10.13s: Explicit startup tracing with canonical version
    import sys
    from src.core.version import get_version_string
    from src.services.learning_instrumentation import format_lm_counters

    version_str = get_version_string()
    print("\n" + "="*80, file=sys.stderr, flush=True)
    print(f"🚀 MAIN() STARTING — {version_str}", file=sys.stderr, flush=True)
    print("="*80, file=sys.stderr, flush=True)
    
    # V10.13s Phase 2: Print learning pipeline instrumentation counters
    try:
        counters_str = format_lm_counters()
        print(f"{counters_str}", file=sys.stderr, flush=True)
    except Exception as _lm_counter_err:
        print(f"[WARNING] Failed to print LM counters: {_lm_counter_err}", file=sys.stderr, flush=True)

    # Initialize event bus handlers (Zero Bug V2 Migration Phase 1)
    print("  [1/7] Initializing event bus handlers...", file=sys.stderr, flush=True)
    _init_event_handlers()

    # Initialize self-healing system (Autonomous Failure Detection)
    # V10.12i: Declare global last_trade_ts to avoid UnboundLocalError
    print("  [2/7] Initializing self-healing system...", file=sys.stderr, flush=True)
    global _anomaly_detector, _state_history, last_trade_ts
    try:
        if AnomalyDetector:
            _anomaly_detector = AnomalyDetector()
            _state_history = StateHistory(max_size=100)
        else:
            _anomaly_detector = None
            _state_history = None
    except Exception as e:
        import logging
        logging.warning(f"Self-healing init failed: {e}")
        _anomaly_detector = None
        _state_history = None

    # Initialize V4 self-evolving strategy system (Genetic Algorithm)
    print("  [3/7] Initializing genetic algorithm system...", file=sys.stderr, flush=True)
    global _genetic_pool, _strategy_selector, _current_strategy
    try:
        if GeneticPool:
            _genetic_pool = GeneticPool(size=20)
            _strategy_selector = StrategySelector(_genetic_pool)
            _current_strategy = _strategy_selector.select(regime="RANGING", force_best=False)
        else:
            _genetic_pool = None
            _strategy_selector = None
            _current_strategy = None
    except Exception as e:
        import logging
        logging.warning(f"Genetic algorithm init failed: {e}")
        _genetic_pool = None
        _strategy_selector = None
        _current_strategy = None

    # Initialize V5.1 reinforcement learning system (RLAgent from services)
    global _rl_agent, _state_builder, _reward_engine
    _rl_agent = rl_agent_instance  # V5.1: Use services RL agent
    _state_builder = None  # Legacy - not used in V5.1
    _reward_engine = None  # Legacy - not used in V5.1

    bus = get_event_bus()
    if _genetic_pool:
        msg = f"✅ V4 Genetic Pool initialized: {_genetic_pool}, Current strategy: {_current_strategy}"
        bus.emit("LOG_OUTPUT", {"message": msg}, time.time())

    if _rl_agent:
        msg = f"🧠 V5.1 RL Agent initialized: {_rl_agent}"
        bus.emit("LOG_OUTPUT", {"message": msg}, time.time())

    # Initialize async learning flush worker (V10.13n - Latency Fix)
    # Background thread queues and flushes learning updates asynchronously
    # Prevents 100+ ms latency spikes from on_price() critical path
    print("  [3.5/7] Starting async learning flush worker...", file=sys.stderr, flush=True)
    try:
        from src.services.state_manager import start_learning_flush_worker
        start_learning_flush_worker()
        print("  [3.5/7] Learning flush worker started ✓", file=sys.stderr, flush=True)
    except Exception as e:
        import logging
        logging.warning(f"Learning flush worker init failed: {e}")
        print(f"  [3.5/7] Learning flush worker failed: {e}", file=sys.stderr, flush=True)

    print("  [4/7] Initializing Firebase...", file=sys.stderr, flush=True)
    init_firebase()
    print("  [4/7] Firebase initialized ✓", file=sys.stderr, flush=True)

    print("  [5/7] Running daily budget report...", file=sys.stderr, flush=True)
    daily_budget_report()
    print("  [5/7] Daily budget report done ✓", file=sys.stderr, flush=True)

    # V10.13b: Explicit hydration BEFORE bootstrap (after Firebase ready, before trades replayed)
    print("  [6/7] Hydrating learning state from Redis...", file=sys.stderr, flush=True)
    print("\n[V10.13b] ── Hydrating learning state from Redis ────────────────────")
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from src.services.learning_event import explicit_hydrate_from_redis as _hyd_metrics
        metrics_hydration = loop.run_until_complete(_hyd_metrics())
        print(f"  Metrics:  {metrics_hydration.get('source')} → {metrics_hydration.get('trades', 0)} trades")
    except Exception as e:
        print(f"  Metrics:  hydration error → {e}")
        metrics_hydration = {"source": "error"}

    try:
        from src.services.learning_monitor import explicit_hydrate_from_redis as _hyd_lm
        lm_hydration = loop.run_until_complete(_hyd_lm())
        print(f"  Learning Monitor: {lm_hydration.get('source')} → {lm_hydration.get('pairs', 0)} pairs")
    except Exception as e:
        print(f"  Learning Monitor: hydration error → {e}")
        lm_hydration = {"source": "error"}

    print("  [6/7] Hydration complete ✓", file=sys.stderr, flush=True)
    print()

    print("  [7/7a] Loading trade history from Firebase...", file=sys.stderr, flush=True)
    _history = load_history()
    print(f"  [7/7a] Loaded {len(_history) if _history else 0} trades ✓", file=sys.stderr, flush=True)

    # DB-vanish detection: Firebase connected but zero trades returned.
    # Could be a genuine first run or a collection wipe.  Either way, the
    # bot enters bootstrap mode (trades=0 < 150 threshold) automatically.
    # Log clearly so the Railway log makes the cause obvious.
    if _history is not None and len(_history) == 0:
        bus = get_event_bus()
        msg = "⚠️  [DB_WIPE] Firebase returned 0 trades — starting in full bootstrap mode. Session gate bypassed, debounce bypassed, force-trade guard active."
        bus.emit("LOG_OUTPUT", {"message": msg}, time.time())

    print("  [7/7b] Bootstrapping from history...", file=sys.stderr, flush=True)
    bootstrap_from_history(_history)
    print("  [7/7b] Bootstrap complete ✓", file=sys.stderr, flush=True)

    # V10.13b: Log bootstrap status to confirm hydration completed
    print("  [7/7c] Logging bootstrap status...", file=sys.stderr, flush=True)
    log_bootstrap_status()
    print("  [7/7c] Bootstrap status logged ✓", file=sys.stderr, flush=True)

    print("  [8/8] Running warmup indicators...", file=sys.stderr, flush=True)
    warmup()
    print("  [8/8] Warmup complete ✓", file=sys.stderr, flush=True)

    # V10.13s: Detect and correct stale warm-start contamination after reset
    print("  [V10.13s] Validating runtime state consistency...", file=sys.stderr, flush=True)
    try:
        from src.services.realtime_decision_engine import (
            validate_runtime_state_consistency,
            apply_reset_integrity_corrections,
            compute_effective_maturity
        )
        _val_result = validate_runtime_state_consistency()
        if _val_result.get("mismatch"):
            print(f"  [V10.13s] ⚠️  State mismatch detected — applying corrections", file=sys.stderr, flush=True)
            apply_reset_integrity_corrections()
            print(f"  [V10.13s] ✅ Stale metrics cleared", file=sys.stderr, flush=True)
        else:
            print(f"  [V10.13s] ✅ State consistency validated", file=sys.stderr, flush=True)

        # V10.13s: Compute unified maturity oracle — all modules read from this now
        print("  [V10.13s] Computing unified maturity oracle...", file=sys.stderr, flush=True)
        _maturity = compute_effective_maturity()
        print(f"  [V10.13s] ✅ Maturity computed: trades={_maturity.get('effective_trade_count')} "
              f"bootstrap={_maturity.get('bootstrap_mode')} cold_start={_maturity.get('cold_start_mode')}",
              file=sys.stderr, flush=True)
    except Exception as _v13s_err:
        import logging as _log_v13s
        _log_v13s.getLogger(__name__).debug(f"V10.13s validation error: {_v13s_err}")

    print("\n✅ BOOTSTRAP COMPLETE — Starting main event loop...\n", file=sys.stderr, flush=True)

    t = threading.Thread(target=start)
    t.daemon = True
    t.start()

    # Phase 5: Start Audit Worker (Redis -> Firestore bridge)
    def _run_audit_worker():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(src.services.audit_worker.start())

    t_audit = threading.Thread(target=_run_audit_worker)
    t_audit.daemon = True
    t_audit.start()

    def _run_signal_engine():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(src.services.signal_engine.start())

    t_sig = threading.Thread(target=_run_signal_engine)
    t_sig.daemon = True
    t_sig.start()

    while True:
        time.sleep(10)

        # V10.14.b: Execution gate — block all operations when system is HALTED.
        # This ensures a HARD failure in any module (guard, auditor, invariants)
        # propagates here and stops all audit / metrics / trading activity.
        try:
            from src.core.system_state import is_halted as _sys_halted
            if _sys_halted():
                import logging as _log
                _log.getLogger(__name__).warning(
                    "[MAIN_LOOP] System HALTED — skipping cycle (manual guard.reset() required)"
                )
                continue
        except (ImportError, AttributeError):
            pass  # if import fails, continue normally (fail-open for monitoring)

        global _last_audit, _last_metrics, _last_pre_audit
        now = time.time()

        # V10.13d: Reset per-cycle signal generation stats at start of cycle
        try:
            from src.services.signal_generator import reset_cycle_stats
            reset_cycle_stats()
        except (ImportError, Exception):
            pass  # Fail silently if module not available

        # V10.13q: Reset per-cycle kill audit (entry rejection telemetry)
        try:
            from src.services.realtime_decision_engine import reset_kill_audit, reset_bootstrap_state
            reset_kill_audit()
            reset_bootstrap_state()  # V10.13r: Reset cycle-level bootstrap counters
        except (ImportError, Exception):
            pass  # Fail silently if not available

        # V10.13L: Advance fault clear timers (fault persistence grace period)
        try:
            from src.services.runtime_fault_registry import _tick_clear_timers
            _tick_clear_timers()
        except (ImportError, Exception):
            pass  # Fail silently if registry not available

        # ────────────────────────────────────────────────────────────────────
        # PATCH 5: Call watchdog to monitor trade frequency
        # ────────────────────────────────────────────────────────────────────
        watchdog(now)

        # ════════════════════════════════════════════════════════════════════
        # V5.1 ADAPTIVE RECOVERY CYCLE — Stall detection + self-healing
        # ════════════════════════════════════════════════════════════════════
        try:
            from src.services.adaptive_recovery import (
                update_adaptive_state,
                stall_recovery,
            )
            from src.services.learning_event import trades_in_window, METRICS

            # Count trades in last cycle and signals generated
            trades_last_60s = len(trades_in_window(60)) if hasattr(trades_in_window, '__call__') else 0
            signals_gen = METRICS.get("signals_generated", 0)
            # V10.12h: Use safe idle computation to prevent unix-time-sized values
            # Note: Use local var name to avoid shadowing global last_trade_ts list
            last_trade_ts_value = METRICS.get("last_trade_time") or now  # BUG FIX: last_trade_time (not last_trade_ts)
            no_trade_time = safe_idle_seconds(last_trade_ts_value, now)

            # Update adaptive systems
            stall_status = update_adaptive_state(
                trades_last_n=trades_last_60s,
                signals_generated=signals_gen,
                no_trade_time=no_trade_time,
            )

            if stall_status == "RECOVERY_TRIGGERED":
                print(f"🚨 [V5.1] STALL RECOVERY ACTIVATED at {now:.0f}s")
                # Reset filter counters and force exploration in next cycle
                METRICS["recovery_active"] = True
                METRICS["recovery_timestamp"] = now
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).debug(f"Adaptive recovery cycle error: {e}")

        # ────────────────────────────────────────────────────────────────────
        # PATCH: SELF-HEALING CYCLE (Autonomous Failure Detection & Recovery)
        # ────────────────────────────────────────────────────────────────────
        # This is the CRITICAL POSITION: after all operations, before audit
        if _anomaly_detector and _state_history:
            try:
                # V10.12i: Use safe idle computation instead of raw timestamp arithmetic
                safe_no_trade_duration = safe_idle_seconds(last_trade_ts[0], now)

                # Build current state snapshot from metrics
                current_state = type('State', (), {
                    'equity': float(get_metrics().get('equity', 1.0)),
                    'drawdown': float(get_metrics().get('max_dd', 0.0)),
                    'no_trade_duration': safe_no_trade_duration,
                    'signal_count': 0,  # Will be updated by signal generator
                })()
                
                # Check for anomalies
                anomalies = _anomaly_detector.check(current_state)
                
                # Handle each anomaly
                for anomaly in anomalies:
                    handle_anomaly(anomaly, current_state)
                
                # Auto-rollback if critical
                current_state = _state_history.rollback_if_needed(current_state, anomalies)
                
                # Save snapshot for recovery
                _state_history.save(current_state)
                
                # Check failsafe
                if failsafe_halt(current_state):
                    bus = get_event_bus()
                    msg = "🛑 FAILSAFE: Trading disabled (safe_mode + DD>45%)"
                    bus.emit("LOG_OUTPUT", {"message": msg}, now)
                    
            except Exception as _heal_ex:
                import logging as _log_heal
                _log_heal.getLogger(__name__).error(f"Self-heal cycle error: {_heal_ex}")

        if now - _last_audit >= AUDIT_INTERVAL:
            run_audit()
            _last_audit = now

        if now - _last_metrics >= METRICS_INTERVAL:
            _pos = get_open_positions()
            execution_data = None
            try:
                from src.services.dashboard_live import dashboard_snapshot, dashboard_metrics
                snap  = dashboard_snapshot(_pos)
                met   = dashboard_metrics()
                fscore = float(snap.get("failure", 0.0))
                # Serialise symbols dict: round float values for Firestore
                syms = {
                    sym: {"ev": round(float(v["ev"]), 5),
                          "size": round(float(v["size"]), 5),
                          "reg": str(v["reg"])}
                    for sym, v in snap.get("symbols", {}).items()
                }
                execution_data = {
                    "equity":       round(float(snap.get("equity",   1.0)), 6),
                    "drawdown":     round(float(snap.get("drawdown", 0.0)), 6),
                    "exposure":     round(float(snap.get("exposure", 0.0)), 4),
                    "failure_score": round(fscore, 3),
                    "control":      "HALT" if fscore > 3.0 else "WARN" if fscore > 1.5 else "OK",
                    "sharpe":       round(float(met.get("sharpe",   0.0)), 4),
                    "avg_edge":     round(float(met.get("avg_edge", 0.0)), 6),
                    "exec_winrate": round(float(met.get("winrate",  0.0)), 4),
                    "max_dd":       round(float(met.get("max_dd",   0.0)), 4),
                    "symbols":      syms,
                }
            except Exception as _ex:
                pass

            monitor_data = None
            try:
                from src.services.learning_monitor import lm_snapshot
                monitor_data = lm_snapshot()
            except Exception:
                pass

            # Refresh FX rate once per hour
            if time.time() - _fx_last_fetch > _FX_REFRESH_SECS:
                _refresh_fx_rate()

            save_metrics_full(get_metrics(), _pos,
                              execution=execution_data,
                              monitor=monitor_data,
                              fx_usd_czk=_fx_usd_czk or None)
            _last_metrics = now

            # V10.13s.1: Invalidate canonical state cache after metrics flush
            invalidate_cache()

        if now - _last_pre_audit >= PRE_AUDIT_INTERVAL:
            _run_pre_live_audit()
            _last_pre_audit = now

        try:
            from src.services.learning_monitor import meta_update
            meta_update()
            # V10.13s.1: Invalidate canonical state after learning update
            invalidate_cache()
        except Exception:
            pass

        # ────────────────────────────────────────────────────────────────────
        # PATCH 3.2: Consolidate rendering — single atomic render per cycle
        # ────────────────────────────────────────────────────────────────────
        # Build unified snapshot (all metrics, positions, learning state)
        try:
            from src.services.learning_monitor import lm_snapshot
            lm_snap = lm_snapshot()
        except Exception:
            lm_snap = {}
        
        dashboard_snapshot_data = {
            "cycle_time": now,
            "positions": len(get_open_positions()),
            "learning": lm_snap,
        }
        
        # Single atomic render call (deduplication happens inside)
        atomic_render(dashboard_snapshot_data, "CYCLE SNAPSHOT")
        
        # Legacy dashboard calls (if needed for backward compatibility)
        # These will be deduplicated by atomic_render if content hasn't changed
        try:
            print_status()
        except Exception:
            pass
        
        try:
            dashboard_loop(get_open_positions())
        except Exception:
            pass

        try:
            from src.services.learning_monitor import print_learning_monitor
            print_learning_monitor()
        except Exception:
            pass

        # V10.13s.1: Print canonical state for diagnostic purposes
        try:
            print_canonical_state()
        except Exception:
            pass

        # ────────────────────────────────────────────────────────────────────
        # V10.13a: Print cycle summary with per-symbol block reasons
        # ────────────────────────────────────────────────────────────────────
        print_cycle_summary(now)

        # ────────────────────────────────────────────────────────────────────
        # V10.13g: Enhanced exit harvest summary — shows if harvests are working
        # ────────────────────────────────────────────────────────────────────
        try:
            from src.services.learning_event import _close_reasons as _cr
            
            # Core profit-harvest levels (V10.13g)
            _tp = _cr.get('TP', 0)
            _sl = _cr.get('SL', 0)
            _micro = _cr.get('MICRO_TP', 0)
            _be = _cr.get('BREAKEVEN_STOP', 0)
            _p25 = _cr.get('PARTIAL_TP_25', 0)
            _p50 = _cr.get('PARTIAL_TP_50', 0)
            _p75 = _cr.get('PARTIAL_TP_75', 0)
            _trail = _cr.get('TRAIL_SL', 0) + _cr.get('TRAIL_PROFIT', 0)
            _scratch = _cr.get('SCRATCH_EXIT', 0)
            _stag = _cr.get('STAGNATION_EXIT', 0)
            _harvest = _cr.get('HARVEST_PROFIT', 0)
            _tp_profit = _cr.get('TIMEOUT_PROFIT', 0)
            _tp_flat = _cr.get('TIMEOUT_FLAT', 0)
            _tp_loss = _cr.get('TIMEOUT_LOSS', 0)
            
            # Summary line with harvest breakdown
            print(
                f"[V10.13g EXIT] "
                f"TP={_tp} SL={_sl} "
                f"micro={_micro} be={_be} "
                f"partial=({_p25},{_p50},{_p75}) "
                f"trail={_trail} "
                f"scratch={_scratch} stag={_stag} "
                f"harvest={_harvest} "
                f"t_profit={_tp_profit} t_flat={_tp_flat} t_loss={_tp_loss}"
            )
            
            # Harvest rate calculation
            total_exits = (_tp + _sl + _micro + _be + _p25 + _p50 + _p75 + _trail +
                           _scratch + _stag + _harvest + _tp_profit + _tp_flat + _tp_loss)
            if total_exits > 0:
                harvested = _tp + _micro + _be + _p25 + _p50 + _p75 + _trail + _harvest
                harvest_pct = (harvested / total_exits) * 100
                print(f"  → Harvest rate: {harvest_pct:.1f}% ({harvested}/{total_exits})")
        except Exception as e:
            import logging
            logging.debug(f"Exit summary error: {e}")

        # ────────────────────────────────────────────────────────────────────
        # V10.13L: Runtime Safety State Dashboard
        # ────────────────────────────────────────────────────────────────────
        try:
            from src.services.runtime_fault_registry import (
                get_state as get_safety_state,
                is_trading_allowed,
                get_fault_snapshot,
            )

            safety_state = get_safety_state()
            trading_ok = is_trading_allowed()

            if safety_state != "OK":
                faults = get_fault_snapshot()
                print("\n⚠️  SAFETY STATE")
                print(f"  State: {safety_state}")
                print(f"  Trading: {'ENABLED' if trading_ok else 'DISABLED'}")

                fault_dict = faults.get("faults", {})
                if fault_dict:
                    for comp, fault_info in fault_dict.items():
                        error_msg = fault_info.get("error", "unknown error")
                        print(f"  Fault: {comp} — {error_msg}")
                else:
                    print(f"  State: {safety_state} (no active faults)")
        except Exception as e:
            pass

        # ────────────────────────────────────────────────────────────────────
        # V10.13m: Exit Attribution Audit Dashboard
        # ────────────────────────────────────────────────────────────────────
        try:
            from src.services.smart_exit_engine import smart_exit

            audit = smart_exit.get_audit_summary()

            if audit["winners"] or audit["near_miss"] or audit["top_rejects"]:
                print("\n📊 [V10.13m EXIT_AUDIT]")

                # Winners summary
                if audit["winners"]:
                    winner_str = " ".join(
                        [f"{exit_type}={count}" for exit_type, count in
                         sorted(audit["winners"].items(), key=lambda x: x[1], reverse=True)]
                    )
                    print(f"  winners: {winner_str}")

                # Near-miss summary
                if audit["near_miss"]:
                    near_miss_str = " ".join(
                        [f"{reason}={count}" for reason, count in
                         sorted(audit["near_miss"].items(), key=lambda x: x[1], reverse=True)]
                    )
                    print(f"  near_miss: {near_miss_str}")

                # Top rejection reasons
                if audit["top_rejects"]:
                    print("  top_rejects:")
                    for reason, count in audit["top_rejects"]:
                        print(f"    {reason}={count}")
        except Exception as e:
            pass


if __name__ == "__main__":
    main()
