import sys
import os
import traceback
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env before importing anything else
# Use explicit path to avoid stack frame issues
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

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