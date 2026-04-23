#!/usr/bin/env python3
"""
V10.13x Fresh Start Script
Forces clean import of new metrics reconciliation code
"""
import sys
import os

# Clean any cached imports
for module in list(sys.modules.keys()):
    if 'cryptomaster' in module.lower() or 'src.' in module or 'bot2.' in module:
        del sys.modules[module]

# Set path
sys.path.insert(0, os.getcwd())

print("[START] V10.13x Fresh Build Loading...")
print("[IMPORT] Verifying new code...")

# Force reload new code
from src.services.metrics_engine import MetricsEngine
from src.services.learning_monitor import lm_health_components

engine = MetricsEngine()
assert hasattr(engine, 'compute_canonical_trade_stats'), "Canonical stats missing!"
assert callable(lm_health_components), "Health components missing!"

print("[OK] V10.13x metrics reconciliation code loaded")
print("[IMPORT] Loading bot main...")

from bot2.main import main

print("[START] Starting bot with V10.13x...")
main()
