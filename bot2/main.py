from threading import Thread

# importy aktivují subscribery
import bot1.execution_event
import src.services.portfolio_event
import src.services.evaluator_event
import bot2.learning_event
import src.services.config_event

from src.services.price_feed import price_feed


def main():
    print("🚀 EVENT DRIVEN SYSTEM STARTED")

    Thread(target=price_feed, daemon=True).start()

    while True:
        pass


if __name__ == "__main__":
    main()