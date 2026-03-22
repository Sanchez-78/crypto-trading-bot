import sys
import os

sys.path.append(os.getcwd())
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from bot1.execution_bot import ExecutionBot
from bot1.market_provider import MarketProvider


if __name__ == "__main__":
    print("🚀 Starting Execution Bot...")

    bot = ExecutionBot()
    market = MarketProvider()

    bot.run(market)