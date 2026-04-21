#!/usr/bin/env python3
"""
Patch learning_monitor.py to add logging to lm_health() and lm_snapshot()
to show what state is actually being tracked and why pairs might be empty.
"""

with open(r'C:\Projects\CryptoMaster_srv\src\services\learning_monitor.py', encoding='utf-8') as f:
    content = f.read()

# 1. Add logging to lm_health function (line 473)
old1 = '''def lm_health():
    """
    Return a health score for the learning system, 0.0 to ~0.5'''

new1 = '''def lm_health():
    """
    Return a health score for the learning system, 0.0 to ~0.5'''

# Find and enhance lm_health to log state
old_health_body = '''    n = len(lm_count)
    if n == 0:
        return 0.0'''

new_health_body = '''    n = len(lm_count)
    log.debug(f"[LM_HEALTH_CHECK] lm_count keys={list(lm_count.keys())} total_pairs={n}")
    if n == 0:
        log.warning("[LM_HEALTH_ZERO] No learning data - lm_count is empty!")
        return 0.0'''

content = content.replace(old_health_body, new_health_body)

# 2. Add logging to lm_snapshot function (line 644)
old2 = '''def lm_snapshot():
    """Emit structured snapshot of current learning state for external monitoring.'''

new2 = '''def lm_snapshot():
    """Emit structured snapshot of current learning state for external monitoring.'''

# Add logging at the start of snapshot
old_snap_start = '''    return {
        "pairs": pairs_dict,
        "features": features_dict,'''

new_snap_start = '''    log.debug(f"[LM_SNAPSHOT] pairs_dict={list(pairs_dict.keys())} len={len(pairs_dict)} "
              f"features_dict={list(features_dict.keys())} len={len(features_dict)}")
    return {
        "pairs": pairs_dict,
        "features": features_dict,'''

content = content.replace(old_snap_start, new_snap_start)

# Write back
with open(r'C:\Projects\CryptoMaster_srv\src\services\learning_monitor.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("[OK] Patched learning_monitor.py health/snapshot functions")
print("  - Added logging to lm_health() to show why health=0")
print("  - Added logging to lm_snapshot() to show state dict content")
