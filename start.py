import sys
import os
import traceback

print("[START] START.PY BOOTING...")

# =========================
# FIX PYTHON PATH
# =========================
sys.path.append(os.getcwd())

print("[PATH] ROOT FILES:", os.listdir())

if os.path.exists("src"):
    print("[PATH] SRC:", os.listdir("src"))

if os.path.exists("src/services"):
    print("[PATH] SERVICES:", os.listdir("src/services"))

# =========================
# SAFE START
# =========================
try:
    print("[IMPORT] IMPORTING MAIN...")
    from bot2.main import main

    print("[START] STARTING MAIN...")
    main()

except Exception as e:
    print("[ERROR] CRASH DETECTED:")
    print(e)
    traceback.print_exc()