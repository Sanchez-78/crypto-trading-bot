import subprocess
import time

print("🚀 Starting BOT SYSTEM...")

# spustí Bot2 (Brain)
brain = subprocess.Popen(["python", "bot2/main.py"])

# malá pauza
time.sleep(2)

# spustí Bot1 (Execution)
execution = subprocess.Popen(["python", "bot1/run.py"])

print("🧠 Brain + 🟢 Execution running")

# drží proces naživu
while True:
    time.sleep(60)