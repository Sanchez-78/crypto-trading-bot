#!/usr/bin/env python3
"""Apply surgical patches to paper_trade_executor.py and bot2/main.py"""
import re
import sys
import os

def apply_patch_paper_executor():
    """Apply edits to paper_trade_executor.py"""
    filepath = "/opt/cryptomaster/src/services/paper_trade_executor.py"
    with open(filepath, "r") as f:
        content = f.read()

    original = content

    # EDIT 1A: Add _get_v5_bridge helper
    if "_get_v5_bridge" not in content:
        insertion_point = content.find("_QUALITY_ENTRY_LOCK = __import__(\"threading\").RLock()")
        if insertion_point != -1:
            insertion_point = content.find("\n", insertion_point) + 1
            v5_helper = '''
# V5 Legacy Bridge integration (Phase 3)
_V5_BRIDGE = None
_V5_BRIDGE_LOCK = __import__("threading").RLock()


def _get_v5_bridge():
    """Lazy initialize V5 bridge singleton."""
    global _V5_BRIDGE
    if _V5_BRIDGE is None:
        with _V5_BRIDGE_LOCK:
            if _V5_BRIDGE is None:
                try:
                    from src.services.v5_legacy_bridge import V5LegacyBridge
                    _V5_BRIDGE = V5LegacyBridge()
                    log.info(
                        "[V5_BRIDGE_INIT] enabled=true real_orders_allowed=false service=cryptomaster.service"
                    )
                except Exception as e:
                    log.error(f"[V5_BRIDGE_INIT_FAILED] {e}")
                    _V5_BRIDGE = False
    return _V5_BRIDGE if _V5_BRIDGE is not False else None

'''
            content = content[:insertion_point] + v5_helper + content[insertion_point:]
            print("✓ Edit 1A: Added _get_v5_bridge helper")

    # EDIT 1B: Fix close_paper_position - dedup first, no early pop
    if "pos = _POSITIONS.pop(position_id)" in content:
        # Find and replace the opening
        old_pattern = r"(\s+with _POSITION_LOCK:\s+if position_id not in _POSITIONS:\s+return None\s+)pos = _POSITIONS\.pop\(position_id\)"
        new_code = r'''\1# Mark as being processed
    with _CLOSED_TRADES_LOCK:
        if position_id in _CLOSED_TRADES_THIS_SESSION:
            log.debug(f"[PAPER_CLOSE_DEDUPE] trade_id={position_id} already processed, skipping")
            return None

    # P0 FIX #1: Do NOT pop position yet - read-only access first
    with _POSITION_LOCK:
        if position_id not in _POSITIONS:
            return None
        pos = _POSITIONS[position_id]'''

        content = re.sub(old_pattern, new_code, content, flags=re.MULTILINE)
        print("✓ Edit 1B: Moved dedup check, removed early pop")

    # EDIT 1C: Add PAPER_ENTRY hook
    if "[V5_BRIDGE] Paper entry" not in content:
        entry_hook = '''
    # V5 Legacy Bridge: Record paper entry (Phase 3 hook)
    try:
        v5_bridge = _get_v5_bridge()
        if v5_bridge:
            from src.services.v5_legacy_bridge.event_models import LegacyPaperOpenEvent
            open_event = LegacyPaperOpenEvent(
                trade_id=trade_id,
                symbol=symbol,
                side=side,
                strategy_id=paper_source or "normal_rde_take",
                regime=position.get("regime", "NEUTRAL"),
                entry_ts=ts,
                entry_price=price,
                size=size_usd,
                bucket=bucket or training_bucket or "UNKNOWN",
                expected_move_bps=int((position.get("expected_move_pct", 0.0) or 0.0) * 10000),
                required_move_bps=int((position.get("required_move_pct", 0.23) or 0.23) * 10000),
                cost_edge_ok=position.get("cost_edge_ok", True),
                real_orders_allowed=False,
                metadata={"paper_source": paper_source or "normal_rde_take"},
            )
            v5_bridge.record_open(open_event)
    except Exception as e:
        log.error(f"[V5_BRIDGE] Paper entry hook failed: {e}")
'''
        pattern = r"(\n\s+_save_paper_state\(\)\s+\n\s+return trade_id)"
        content = re.sub(pattern, entry_hook + r"\1", content)
        print("✓ Edit 1C: Added PAPER_ENTRY hook")

    # EDIT 1D: Add close hook + outbox fallback
    if "[V5_BRIDGE_CLOSE_FAILED]" not in content:
        close_hook = '''
    # V5 Legacy Bridge: Record paper close (Phase 3 hook)
    close_event = None
    try:
        v5_bridge = _get_v5_bridge()
        if v5_bridge:
            from src.services.v5_legacy_bridge.event_models import LegacyPaperCloseEvent
            size_usd = _safe_float(pos.get("size_usd") or pos.get("final_size_usd"), 10.0)
            net_pnl = (pnl_data["net_pnl_pct"] / 100.0) * size_usd
            close_event = LegacyPaperCloseEvent(
                trade_id=position_id,
                symbol=pos["symbol"],
                side=pos.get("side", "BUY"),
                exit_ts=ts,
                exit_price=price,
                exit_reason=reason,
                gross_pnl=(pnl_data.get("gross_pnl_pct", 0.0) / 100.0) * size_usd,
                fees=(pnl_data.get("fee_pct", 0.0) / 100.0) * size_usd,
                spread=(pnl_data.get("slippage_pct", 0.0) / 100.0) * size_usd,
                net_pnl=net_pnl,
                net_pnl_pct=pnl_data.get("net_pnl_pct", 0.0),
                duration_seconds=int(duration_s),
                learning_eligible=not pos.get("quarantined", False),
                readiness_eligible=False,
                real_orders_allowed=False,
                metadata={"paper_source": pos.get("paper_source", "unknown")},
            )
            v5_bridge.record_close(close_event)
    except Exception as e:
        log.error(f"[V5_BRIDGE_CLOSE_FAILED] trade_id={position_id} enqueuing to outbox: {e}")
        try:
            from src.services.v5_legacy_bridge.outbox import get_durable_outbox
            outbox = get_durable_outbox()
            if outbox and close_event:
                outbox.enqueue(
                    "paper_close",
                    close_event.to_dict() if hasattr(close_event, 'to_dict') else {
                        "trade_id": position_id,
                        "symbol": pos.get("symbol", "N/A"),
                        "exit_reason": reason,
                        "exit_price": price,
                        "exit_ts": ts,
                        "net_pnl_pct": pnl_data.get("net_pnl_pct", 0.0),
                    },
                    idempotency_key=position_id,
                )
                log.info(f"[V5_BRIDGE_CLOSE_ENQUEUED] trade_id={position_id} for retry")
        except Exception as outbox_e:
            log.error(f"[V5_BRIDGE_OUTBOX_ENQUEUE_FAILED] trade_id={position_id} error={outbox_e}")
'''
        pattern = r'(log\.warning\(\s*"\[PAPER_EXIT\].*?\)\s*\n)'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + close_hook + content[insert_pos:]
            print("✓ Edit 1D: Added V5 close hook with outbox fallback")

    # EDIT 1E: Add position removal at end
    if "_POSITIONS.pop(position_id, None)" not in content:
        final_pop = '''
    # P0 FIX #1 (continued): NOW remove position from active, AFTER all processing succeeds
    with _POSITION_LOCK:
        _POSITIONS.pop(position_id, None)
'''
        pattern = r'(\n\s+)return closed_trade(\s*\n\s*(?:def |$))'
        content = re.sub(pattern, final_pop + r"\1return closed_trade\2", content)
        print("✓ Edit 1E: Added position removal at end")

    # Write back
    with open(filepath, "w") as f:
        f.write(content)
    print(f"✓ Saved paper_trade_executor.py")
    return True

def apply_patch_bot2_main():
    """Apply edits to bot2/main.py"""
    filepath = "/opt/cryptomaster/bot2/main.py"
    with open(filepath, "r") as f:
        content = f.read()

    # EDIT 2A: Update import
    if "_get_v5_bridge" not in content:
        old_import = "from src.services.paper_trade_executor import get_paper_open_positions"
        new_import = "from src.services.paper_trade_executor import _get_v5_bridge, get_paper_open_positions"
        content = content.replace(old_import, new_import)
        print("✓ Edit 2A: Updated import")

    # EDIT 2B: Add periodic metrics
    if "v5_bridge.publish_metrics" not in content:
        metrics_code = '''
            # V5 bridge metrics publishing (Phase 3)
            try:
                v5_bridge = _get_v5_bridge()
                if v5_bridge:
                    v5_bridge.publish_metrics(trading_stats=trading_stats)
                    v5_bridge.flush_outbox(limit=20)
            except Exception as _v5_publish_e:
                logging.debug(f"[V5_BRIDGE_METRICS_PUBLISH_ERROR] {_v5_publish_e}")
'''
        pattern = r"(\n\s+# Czech Cycle Report)"
        content = re.sub(pattern, "\n" + metrics_code + r"\1", content)
        print("✓ Edit 2B: Added periodic metrics publishing")

    # Write back
    with open(filepath, "w") as f:
        f.write(content)
    print(f"✓ Saved bot2/main.py")
    return True

if __name__ == "__main__":
    try:
        print("=" * 60)
        print("APPLYING SURGICAL PATCHES")
        print("=" * 60)
        apply_patch_paper_executor()
        print()
        apply_patch_bot2_main()
        print()
        print("=" * 60)
        print("✓ ALL PATCHES APPLIED")
        print("=" * 60)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
