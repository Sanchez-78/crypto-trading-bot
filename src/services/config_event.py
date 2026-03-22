from src.core.event_bus import event_bus
from src.core.events import CONFIG_UPDATED

current_config = {}


def update_config(config):
    global current_config
    current_config = config
    print("⚙️ Config updated")


event_bus.subscribe(CONFIG_UPDATED, update_config)