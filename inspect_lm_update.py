#!/usr/bin/env python3
import sys

# Read learning_monitor.py and extract lm_update function
with open(r'C:\Projects\CryptoMaster_srv\src\services\learning_monitor.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find lm_update function (starts at line 318)
print("=== lm_update FUNCTION (lines 318-421) ===")
for i in range(317, min(421, len(lines))):
    try:
        print(f"{i+1:4d}: {lines[i].rstrip()}")
    except:
        print(f"{i+1:4d}: [unicode]")

# Now check trade_executor.py
print("\n\n=== CHECKING trade_executor.py FOR lm_update CALL ===")
with open(r'C:\Projects\CryptoMaster_srv\src\services\trade_executor.py', encoding='utf-8') as f:
    trade_exec_lines = f.readlines()

for i, line in enumerate(trade_exec_lines):
    if 'lm_update' in line.lower():
        # Print context around the lm_update call
        start = max(0, i-3)
        end = min(len(trade_exec_lines), i+10)
        print(f"\nFound at line {i+1}:")
        for j in range(start, end):
            try:
                print(f"{j+1:4d}: {trade_exec_lines[j].rstrip()}")
            except:
                print(f"{j+1:4d}: [unicode]")
        print("---")
