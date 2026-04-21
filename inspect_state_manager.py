#!/usr/bin/env python3
import sys

# Read state_manager.py and find flush_lm_update
with open(r'C:\Projects\CryptoMaster_srv\src\services\state_manager.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find flush_lm_update function
print("=== FUNCTIONS IN state_manager.py ===")
for i, line in enumerate(lines):
    if line.strip().startswith('def '):
        try:
            print(f"{i+1:4d}: {line.rstrip()}")
        except:
            print(f"{i+1:4d}: [unicode]")

# Find flush_lm_update specifically
print("\n=== SEARCHING FOR flush_lm_update ===")
for i, line in enumerate(lines):
    if 'flush_lm_update' in line:
        start = max(0, i-2)
        end = min(len(lines), i+30)
        print(f"\nFound at line {i+1}:")
        for j in range(start, end):
            try:
                print(f"{j+1:4d}: {lines[j].rstrip()}")
            except:
                print(f"{j+1:4d}: [unicode]")
        break
