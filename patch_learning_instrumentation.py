#!/usr/bin/env python3
"""
Patch learning_monitor.py to add comprehensive diagnostic logging.
This traces the full learning pipeline: update -> persist -> hydrate.
"""

# Read the file
with open(r'C:\Projects\CryptoMaster_srv\src\services\learning_monitor.py', encoding='utf-8') as f:
    content = f.read()

# Find the lm_update function and enhance it with diagnostics

# 1. Add logging right after the initial call log
search_str1 = '''    key = (sym, reg)
    # V10.13s Phase 3B: Log lm_update invocation for diagnostics
    log.debug(f"[LM_UPDATE_CALLED] {sym}/{reg} pnl={pnl:.6f} ws={ws:.4f} features={len(features)}")

    # Trade count
    lm_count[key] = lm_count.get(key, 0) + 1'''

replace_str1 = '''    key = (sym, reg)
    # V10.13s Phase 3B: Log lm_update invocation for diagnostics
    log.debug(f"[LM_UPDATE_CALLED] {sym}/{reg} pnl={pnl:.6f} ws={ws:.4f} features={len(features)}")
    log.debug(f"[LM_STATE_BEFORE] key={key} count_keys={list(lm_count.keys())}")

    # Trade count
    lm_count[key] = lm_count.get(key, 0) + 1'''

content = content.replace(search_str1, replace_str1)

# 2. Add logging before persist call
search_str2 = '''    # Persist to Redis (zero-loss cold start)
    try:
        from src.services.state_manager import flush_lm_update
        flush_lm_update('''

replace_str2 = '''    # Persist to Redis (zero-loss cold start)
    try:
        from src.services.state_manager import flush_lm_update
        log.debug(f"[LM_PRE_PERSIST] {sym}/{reg} count={lm_count.get(key, 0)} "
                  f"pnl_len={len(lm_pnl_hist.get(key, []))} "
                  f"ev_len={len(lm_ev_hist.get(key, []))} "
                  f"wr_len={len(lm_wr_hist.get(key, []))}")
        flush_lm_update('''

content = content.replace(search_str2, replace_str2)

# Write back
with open(r'C:\Projects\CryptoMaster_srv\src\services\learning_monitor.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("[OK] Patched learning_monitor.py with diagnostics")
print("  - Added [LM_STATE_BEFORE] logging")
print("  - Added [LM_PRE_PERSIST] logging")
