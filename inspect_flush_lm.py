#!/usr/bin/env python3

with open(r'C:\Projects\CryptoMaster_srv\src\services\state_manager.py', encoding='utf-8') as f:
    lines = f.readlines()

# Print flush_lm_update function (starts at line 239, ends at ~330)
print("=== flush_lm_update FUNCTION (lines 239-330) ===")
for i in range(238, min(330, len(lines))):
    try:
        print(f"{i+1:4d}: {lines[i].rstrip()}")
    except:
        print(f"{i+1:4d}: [unicode]")

print("\n\n=== hydrate_lm FUNCTION (lines 331-372) ===")
for i in range(330, min(372, len(lines))):
    try:
        print(f"{i+1:4d}: {lines[i].rstrip()}")
    except:
        print(f"{i+1:4d}: [unicode]")
