# V5 PAPER Bot - Deployment Requirements

## New Dependencies Added

### Flask (for Metrics HTTP Server)
```
flask>=2.0.0
```

The learning metrics API requires Flask to provide HTTP endpoints for the Android app.

## Installation

### Option 1: Add to existing requirements.txt
```bash
pip install flask
```

### Option 2: Add to requirements.txt
```txt
flask>=2.0.0
```

### Option 3: Docker/Container
```dockerfile
RUN pip install flask
```

## Impact

- **No changes to bot core logic**: Flask runs in background thread
- **Performance**: Minimal overhead (metrics collection on-demand)
- **Port**: Uses port 5000 (configurable in http_server.py)
- **Thread model**: HTTP server runs in daemon thread, doesn't block bot

## Verification

Once Flask is installed, verify deployment with:

```bash
# Test imports work
python -c "
from src.v5_bot.api.metrics_api import MetricsCollector, LearningHistory
from src.v5_bot.api.http_server import MetricsHTTPServer
print('✓ All learning metrics components available')
"

# Start bot (will also start HTTP server)
python -m src.v5_bot.paper

# In another terminal, test the endpoint
curl http://localhost:5000/metrics/learning-history
```

## Existing Dependencies

The bot already uses:
- `asyncio` - Bot main loop
- `dataclasses` - Data structures
- `typing` - Type hints
- `logging` - Logging
- `datetime` - Timestamp handling

These are all part of Python standard library.

## Production Deployment

The HTTP server starts automatically when the bot starts. No additional configuration needed beyond:

1. Installing Flask
2. Ensuring port 5000 is accessible (or change port in `__main__.py`)

The metrics HTTP server will be available immediately after bot startup.

## Optional Configuration

To change HTTP server port, edit `src/v5_bot/paper/__main__.py`:

```python
# Default: port 5000
http_server = MetricsHTTPServer(host="0.0.0.0", port=5000)

# Custom port example:
http_server = MetricsHTTPServer(host="0.0.0.0", port=8080)
```

To disable HTTP server (not recommended):
- Comment out or remove the http_server initialization and start code in __main__.py

## Testing in Dev Environment

Without Flask installed, you can still test the metrics_api module directly:

```python
from src.v5_bot.paper.runner import V5BotRunner
from src.v5_bot.api.metrics_api import MetricsCollector

runner = V5BotRunner()
collector = MetricsCollector(runner=runner, firebase_repo=runner.firebase, feed=runner.feed)

# This works without Flask
learning_history = collector.collect_learning_history()
print(learning_history.total_trades_closed)
```

The HTTP server integration only requires Flask.
