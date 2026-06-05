"""
Learning System Integration
Purpose: Connect paper trading closes → local storage learning records

This module hooks into paper trade execution to automatically:
1. Record all closed trades to local SQLite
2. Update learning metrics per symbol
3. Update calibration state (W/L by segment)
4. Provide learning data to decision engine (zero Firebase reads!)
"""

import logging
import time
from typing import Dict, Any, Optional
from src.services.local_learning_storage import get_storage

log = logging.getLogger(__name__)

# ============================================================================
# TRADE CLOSE HANDLER
# ============================================================================

def on_paper_trade_closed(
    trade_id: str,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    entry_ts: int,
    exit_ts: int,
    pnl_pct: float,
    pnl_usd: float,
    exit_reason: str,
    regime: str = "NEUTRAL",
    size_usd: float = 0.0,
    mfe_pct: float = 0.0,
    mae_pct: float = 0.0,
    cost_edge_ok: bool = False,
    learning_source: str = "paper_training",
) -> bool:
    """
    Called whenever a paper trade closes (from paper_trade_executor.py)

    This is the MAIN HOOK that captures all learning data without touching Firebase!

    Args:
        trade_id: Unique trade identifier
        symbol: e.g., 'BTCUSDT'
        side: 'BUY' or 'SELL'
        entry_price, exit_price: Trade prices
        entry_ts, exit_ts: Unix timestamps
        pnl_pct: Profit/loss percentage
        pnl_usd: Profit/loss in USD
        exit_reason: 'TP' / 'SL' / 'timeout' / 'stagnation' / 'scratch'
        regime: Market regime at time of trade
        size_usd: Position size
        mfe_pct: Max favorable excursion
        mae_pct: Max adverse excursion
        cost_edge_ok: Whether cost_edge validation passed
        learning_source: Origin of the trade signal

    Returns:
        True if recorded successfully
    """
    storage = get_storage()

    # 1. RECORD TO LOCAL STORAGE (instant write, no Firebase!)
    trade_dict = {
        'trade_id': trade_id,
        'symbol': symbol,
        'side': side,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'entry_ts': entry_ts,
        'exit_ts': exit_ts,
        'pnl_pct': pnl_pct,
        'pnl_usd': pnl_usd,
        'mfe_pct': mfe_pct,
        'mae_pct': mae_pct,
        'exit_reason': exit_reason,
        'regime': regime,
        'size_usd': size_usd,
        'cost_edge_ok': cost_edge_ok,
        'learning_source': learning_source,
    }

    success = storage.record_trade_close(trade_dict)
    if not success:
        log.error(f"[LEARNING] Failed to record trade {trade_id}")
        return False

    # 2. UPDATE CALIBRATION STATE (W/L by segment)
    result = _classify_result(pnl_pct)
    storage.update_calibration(symbol, regime, side, result)

    # 3. LOG LEARNING EVENT
    log.info(
        f"[LEARNING_RECORDED] symbol={symbol} side={side} regime={regime} "
        f"result={result} pnl_pct={pnl_pct:.4f} mfe={mfe_pct:.4f} exit={exit_reason}"
    )

    return True


def _classify_result(pnl_pct: float) -> str:
    """Classify trade result"""
    if pnl_pct > 0.001:  # > 0.1% profit
        return 'WIN'
    elif pnl_pct < -0.001:  # < -0.1% loss
        return 'LOSS'
    else:
        return 'BREAKEVEN'


# ============================================================================
# LEARNING DATA PROVIDERS (replaces Firebase reads!)
# ============================================================================

def get_symbol_learning_stats(symbol: str) -> Dict[str, float]:
    """
    Get learning stats for a symbol (ZERO Firebase reads!)

    Called by: realtime_decision_engine.py (for EV gating, calibration, etc.)

    Returns:
        {
            'pf': profit_factor (1.0 = breakeven, >1.05 = good),
            'wr': win_rate (0.0-1.0),
            'expectancy': avg pnl_pct per trade,
            'closed_trades': total closed trades,
            'pnl_total': cumulative PnL,
        }
    """
    storage = get_storage()
    metrics = storage.get_learning_metrics(symbol)

    return {
        'pf': metrics.get('profit_factor', 0.0),
        'wr': metrics.get('win_rate', 0.0),
        'expectancy': metrics.get('expectancy', 0.0),
        'closed_trades': metrics.get('closed_trades', 0),
        'pnl_total': metrics.get('pnl_total', 0.0),
    }


def get_all_learning_stats() -> Dict[str, Dict[str, float]]:
    """Get stats for all symbols (dashboard, reporting)"""
    storage = get_storage()
    return storage.get_all_metrics()


def get_segment_calibration(symbol: str, regime: str, side: str) -> Dict[str, float]:
    """
    Get calibration data for a specific segment (symbol/regime/side)

    Called by: decision engine (to adjust trade sizing/gating based on history)

    Returns:
        {
            'win_rate': empirical win rate,
            'confidence': 0-1 based on sample size,
            'sample_size': number of trades used,
        }
    """
    storage = get_storage()
    calib = storage.get_calibration(symbol, regime, side)

    if calib:
        return {
            'win_rate': calib['win_rate'],
            'confidence': calib['model_confidence'],
            'sample_size': calib['sample_size'],
        }
    else:
        return {
            'win_rate': 0.5,  # neutral default
            'confidence': 0.0,
            'sample_size': 0,
        }


# ============================================================================
# MIGRATION: Firebase → Local Storage
# ============================================================================

def migrate_firebase_to_local(firebase_client: Optional[Any] = None) -> bool:
    """
    One-time migration: Pull all learning data from Firebase and save to local storage

    Call this ONCE when transitioning from Firebase to local storage:
        from src.services.learning_integration import migrate_firebase_to_local
        migrate_firebase_to_local()

    Args:
        firebase_client: Optional Firebase client instance

    Returns:
        True if migration successful
    """
    storage = get_storage()

    if firebase_client is None:
        try:
            from src.services.firebase_client import FirebaseClient
            firebase_client = FirebaseClient()
        except Exception as e:
            log.error(f"[LEARNING_MIGRATION] Could not load Firebase client: {e}")
            return False

    try:
        log.info("[LEARNING_MIGRATION] Starting Firebase → Local migration...")

        # Try to load trades from Firebase
        try:
            trades_snapshot = firebase_client.db.collection("trades").stream()
            migrated_count = 0

            for doc in trades_snapshot:
                trade_data = doc.to_dict()

                # Convert Firebase timestamp to Unix
                if hasattr(trade_data.get('exit_ts'), 'timestamp'):
                    exit_ts = int(trade_data['exit_ts'].timestamp())
                else:
                    exit_ts = trade_data.get('exit_ts', int(time.time()))

                # Record to local storage
                trade_dict = {
                    'trade_id': doc.id,
                    'symbol': trade_data.get('symbol', 'UNKNOWN'),
                    'side': trade_data.get('side', 'BUY'),
                    'entry_price': float(trade_data.get('entry_price', 0)),
                    'exit_price': float(trade_data.get('exit_price', 0)),
                    'entry_ts': trade_data.get('entry_ts', int(time.time())),
                    'exit_ts': exit_ts,
                    'pnl_pct': float(trade_data.get('pnl_pct', 0)),
                    'pnl_usd': float(trade_data.get('pnl_usd', 0)),
                    'mfe_pct': float(trade_data.get('mfe_pct', 0)),
                    'mae_pct': float(trade_data.get('mae_pct', 0)),
                    'exit_reason': trade_data.get('exit_reason', 'unknown'),
                    'regime': trade_data.get('regime', 'NEUTRAL'),
                    'size_usd': float(trade_data.get('size_usd', 0)),
                    'cost_edge_ok': bool(trade_data.get('cost_edge_ok', False)),
                    'learning_source': trade_data.get('learning_source', 'firebase_import'),
                }

                if storage.record_trade_close(trade_dict):
                    migrated_count += 1

            log.info(f"[LEARNING_MIGRATION] ✅ Migrated {migrated_count} trades from Firebase")
            return True

        except Exception as e:
            log.warning(f"[LEARNING_MIGRATION] Firebase read failed (OK if no Firebase): {e}")
            return True  # Not critical - we can still use local storage

    except Exception as e:
        log.error(f"[LEARNING_MIGRATION] ❌ Migration failed: {e}")
        return False


# ============================================================================
# PERIODIC TASKS
# ============================================================================

def periodic_backup():
    """Call this periodically (e.g., hourly) to create backups"""
    storage = get_storage()
    storage.create_backup()


def periodic_sync_to_firebase(firebase_client: Optional[Any] = None):
    """
    Periodically sync local trades to Firebase (optional, for redundancy)

    This is NOT required for operation - local storage is the primary.
    Use this only if you want Firebase as a backup.

    Args:
        firebase_client: Optional Firebase client instance
    """
    if firebase_client is None:
        try:
            from src.services.firebase_client import FirebaseClient
            firebase_client = FirebaseClient()
        except Exception:
            return  # Firebase unavailable, skip

    storage = get_storage()

    try:
        # Get unsynced trades
        unsynced = storage.get_recent_trades(hours=24)  # Last 24 hours
        if not unsynced:
            return

        # Batch write to Firebase
        batch = firebase_client.db.batch()
        for trade in unsynced:
            doc_ref = firebase_client.db.collection("trades").document(trade['trade_id'])
            batch.set(doc_ref, dict(trade))

        batch.commit()
        log.info(f"[SYNC_TO_FIREBASE] Synced {len(unsynced)} trades")

    except Exception as e:
        log.warning(f"[SYNC_TO_FIREBASE] Sync failed (non-critical): {e}")


# ============================================================================
# REPORTING & DIAGNOSTICS
# ============================================================================

def get_learning_health_report() -> Dict[str, Any]:
    """Get comprehensive learning system health report"""
    storage = get_storage()
    stats = storage.get_stats()
    all_metrics = storage.get_all_metrics()

    return {
        'storage_status': 'OK' if stats.get('available') else 'ERROR',
        'db_path': stats.get('db_path'),
        'db_size_mb': stats.get('db_size_mb'),
        'total_trades_recorded': stats.get('total_trades'),
        'symbols_tracked': stats.get('tracked_symbols'),
        'symbols_with_metrics': list(all_metrics.keys()),
        'top_symbols': sorted(
            all_metrics.items(),
            key=lambda x: x[1]['closed_trades'],
            reverse=True
        )[:5],
    }
