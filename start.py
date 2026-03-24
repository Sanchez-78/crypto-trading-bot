import sys
import os
import traceback

print("🚀 START.PY BOOTING...")

# =========================
# FIX PYTHON PATH
# =========================
sys.path.append(os.getcwd())

print("📁 ROOT FILES:", os.listdir())

if os.path.exists("src"):
    print("📁 SRC:", os.listdir("src"))

if os.path.exists("src/services"):
    print("📁 SERVICES:", os.listdir("src/services"))

# =========================
# SAFE START
# =========================
try:
    print("🚨 IMPORTING MAIN...")
    from bot2.main import main

    print("🚨 STARTING MAIN...")
    main()

except Exception as e:
    print("💥 CRASH DETECTED:")
    print(e)
    traceback.print_exc()