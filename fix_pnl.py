# QUICK FIX: PnL sign correction
import re

files = [
    "src/services/paper_trade_executor.py",
    "src/services/smart_exit_engine.py"
]

for fpath in files:
    with open(fpath) as f:
        content = f.read()
    
    # Search for any (exit - entry) / entry patterns
    if "(exit" in content and "entry" in content and "pnl" in content:
        print(f"Found potential PnL calculation in {fpath}")
        for i, line in enumerate(content.split('\n')):
            if ('exit' in line.lower() and 'entry' in line.lower() and 
                ('/' in line or '*' in line)):
                print(f"  Line {i+1}: {line}")
