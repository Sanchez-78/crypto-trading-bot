import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(ROOT)

print("🚀 Starting multi-symbol event-driven BOT SYSTEM")

from bot2.main import main

main()