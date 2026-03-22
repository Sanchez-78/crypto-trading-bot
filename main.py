import time
from src.services.meta_agent import MetaAgent
from src.services.feature_engine import FeatureEngine
from src.services.portfolio_manager import PortfolioManager
from src.services.firebase_client import (
    load_recent_trades,
    load_compressed_trades,
    get_collection_count,
)
from src.services.auto_cleaner import run_cleanup

agent = MetaAgent()
fe = FeatureEngine()
pf = PortfolioManager()

loop = 0


def db_bar():
    raw = get_collection_count("signals")
    comp = get_collection_count("signals_compressed")

    total = raw + comp
    max_cap = 10000

    pct = min(int((total / max_cap) * 100), 100)
    bar = "█" * (pct // 5) + "-" * (20 - pct // 5)

    print(f"💾 [{bar}] {pct}% RAW={raw} COMP={comp}")


def run():
    global loop
    loop += 1

    import random
    prices = {"BTCUSDT": 100 + random.random()}

    closed = pf.update_trades(prices)

    for t, p, r in closed:
        t["signal"] = t["action"]

    for s, price in prices.items():
        fe.update(s, price)
        f = fe.build(s)

        a, c = agent.decide(f)
        t, _ = pf.open_trade(s, a, price, c)
        t["features"] = f

    raw = pf.trade_history[-200:]
    comp = load_compressed_trades(500)

    agent.learn_from_history(raw)
    agent.learn_from_compressed(comp)

    print(agent.get_progress())

    pf.print_status()
    db_bar()

    if loop % 20 == 0:
        run_cleanup()


while True:
    run()
    time.sleep(2)