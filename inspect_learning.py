#!/usr/bin/env python3
import os
import sys

# Read learning_monitor.py
with open(r'C:\Projects\CryptoMaster_srv\src\services\learning_monitor.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find all function definitions
print("=== FUNCTIONS IN learning_monitor.py ===")
for i, line in enumerate(lines):
    if line.strip().startswith('def '):
        print(f"{i+1:4d}: {line.rstrip()}")

print("\n=== FIRST 100 LINES ===")
for i, line in enumerate(lines[:100]):
    try:
        print(f"{i+1:4d}: {line.rstrip()}")
    except UnicodeEncodeError:
        print(f"{i+1:4d}: [Unicode chars - skipped]")
