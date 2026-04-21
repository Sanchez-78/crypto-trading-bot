#!/usr/bin/env python3

with open(r'C:\Projects\CryptoMaster_srv\src\services\state_manager.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find _async_flush_lm_update
for i, line in enumerate(lines):
    if 'async def _async_flush_lm_update' in line:
        print(f"Found _async_flush_lm_update at line {i+1}")
        start = i
        end = min(len(lines), i+60)
        for j in range(start, end):
            try:
                print(f"{j+1:4d}: {lines[j].rstrip()}")
            except:
                print(f"{j+1:4d}: [unicode]")
        break
else:
    print("NOT FOUND - searching for similar patterns...")
    for i, line in enumerate(lines):
        if '_async_flush_lm' in line or 'flush_lm_update' in line:
            print(f"Line {i+1}: {line.rstrip()[:80]}")
