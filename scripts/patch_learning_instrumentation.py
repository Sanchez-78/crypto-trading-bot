#!/usr/bin/env python3
"""
Patch trade_executor.py to add learning instrumentation counters.
"""

import re
import sys

FILE_PATH = r"C:\Projects\CryptoMaster_srv\src\services\trade_executor.py"

try:
    # Read the entire file
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check if already patched
    if 'increment_lm_update_called()' in content:
        print("[✓] trade_executor.py already patched")
        sys.exit(0)

    # Patch 1: Add increment_trades_closed() after record_trade_close()
    if 'record_trade_close(sym, reg_sig, profit)' in content:
        pattern1 = r'(    record_trade_close\(sym, reg_sig, profit\)\n)(\n    # BUG FIX:)'
        replacement1 = r'''\1    # V10.13s Phase 2: Increment counter to track trade close → learning pipeline
    increment_trades_closed()
\2'''
        content = re.sub(pattern1, replacement1, content)
        print("[✓] Added increment_trades_closed() call")

    # Patch 2: Add increments around lm_update() call
    if 'lm_update(sym, reg_sig, learning_pnl,' in content:
        # Pattern for the lm_update call across multiple lines
        pattern2 = r'(    # negative rapidly → pair_block deadlock after bootstrap wipe\.\n    )(lm_update\(sym, reg_sig, learning_pnl,\n              ws=pos\["signal"\]\.get\("ws", 0\.5\),\n              features=bool_f\))'
        replacement2 = r'''\1increment_lm_update_called()
    \2
    increment_lm_update_success()'''
        content = re.sub(pattern2, replacement2, content)
        print("[✓] Added increment_lm_update_called/success() calls")

    # Write back
    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"[✓] Successfully patched {FILE_PATH}")

except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr)
    sys.exit(1)
