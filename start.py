import sys
import os

print("🚀 Starting BOT SYSTEM...")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(ROOT)

from bot2.main import main

main()