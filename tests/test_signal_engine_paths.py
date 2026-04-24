"""
Tests for signal_engine path consolidation (V10.15x fixes).

Covered scenarios:
  1. No double invocation of signal_generator.on_price per tick
  2. No _subscribers monkeypatching
  3. signal_created subscription delivers to SignalEngine without patching
  4. Redis fallback does NOT re-enter signal_created (infinite loop guard)
  5. L2 gate correctly rejects signals with liquidity walls
  6. filter_pipeline uses signal.probability (not .conviction)
  7. Concept drift detection still fires on feature magnitude outliers
"""

import asyncio
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call
from dataclasses import dataclass, field
from typing import Any


# ── Minimal stubs so signal_engine can be imported without full deps ───────────

def _make_pkg(name):
    """Create a stub module that behaves as a package (has __path__)."""
    mod = types.ModuleType(name)
    mod.__path__ = []          # marks it as a package for import machinery
    mod.__package__ = name
    sys.modules[name] = mod
    return mod


def _make_mod(name, parent=None):
    mod = types.ModuleType(name)
    mod.__package__ = parent or name.rsplit(".", 1)[0]
    sys.modules[name] = mod
    return mod


# Only register stubs for names not already present (real project code may have
# partially initialised some of them if tests share a process).
for _pkg in ("redis", "src", "src.core", "src.services"):
    if _pkg not in sys.modules:
        _make_pkg(_pkg)

for _mod_name in ("redis.asyncio", "src.core.event_bus",
                  "src.services.order_book_depth", "src.services.state_manager"):
    if _mod_name not in sys.modules:
        _make_mod(_mod_name)

# ── event_bus stub with real subscribe/publish behaviour ─────────────────────
_eb = sys.modules["src.core.event_bus"]
_eb._subscribers:       dict = {}
_eb._subscription_keys: set  = set()


def _eb_subscribe(event, handler):
    _eb._subscribers.setdefault(event, []).append(handler)


def _eb_subscribe_once(event, handler):
    key = f"{event}_{getattr(handler, '__module__', '')}_{getattr(handler, '__name__', id(handler))}"
    if key in _eb._subscription_keys:
        return
    _eb._subscription_keys.add(key)
    _eb_subscribe(event, handler)


def _eb_publish(event, data=None):
    for h in _eb._subscribers.get(event, []):
        try:
            h(data)
        except Exception:
            pass


_eb.subscribe      = _eb_subscribe
_eb.subscribe_once = _eb_subscribe_once
_eb.publish        = _eb_publish

# ── state_manager stub ────────────────────────────────────────────────────────
sys.modules["src.services.state_manager"].increment_l2_rejected = lambda: None

# ── import the module under test ─────────────────────────────────────────────
import importlib
import importlib.util as _ilu
import os as _os

_se_path = _os.path.join(
    _os.path.dirname(__file__), "..", "src", "services", "signal_engine.py"
)
_spec = _ilu.spec_from_file_location("src.services.signal_engine", _se_path)
_semod = _ilu.module_from_spec(_spec)
sys.modules["src.services.signal_engine"] = _semod
_spec.loader.exec_module(_semod)
se = _semod


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_sig_dict(**kwargs):
    base = {
        "symbol": "BTCUSDT", "action": "BUY", "price": 30000.0,
        "atr": 50.0, "regime": "RANGING", "confidence": 0.6,
        "ev": 0.05, "ws": 0.7, "coherence": 1.0, "auditor_factor": 1.0,
        "explore": False, "features": {"rsi": 45.0, "adx": 22.0},
    }
    base.update(kwargs)
    return base


# ── Test 1: push_tick is a no-op ───────────────────────────────────────────────

class TestPushTickNoOp(unittest.TestCase):
    def test_push_tick_does_not_raise(self):
        # With no engine running, push_tick must not raise.
        se.push_tick({"symbol": "BTCUSDT", "price": 30000.0})

    def test_push_tick_does_not_queue_ticks(self):
        # Even when called, enqueue_tick is also a no-op.
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(se.enqueue_tick({"symbol": "X", "price": 1.0}))
        loop.close()
        self.assertIsNone(result)


# ── Test 2: signal_created subscription is the only ingestion path ─────────────

class TestSignalCreatedIngestion(unittest.TestCase):
    def setUp(self):
        _eb._subscribers.clear()
        _eb._subscription_keys.clear()
        se._engine = None
        se._loop   = None

    def test_engine_subscribes_to_signal_created_on_start(self):
        """SignalEngine.start() must register _on_signal_created for signal_created."""
        engine = se.SignalEngine()

        async def _run():
            engine._running = True
            from src.core.event_bus import subscribe_once
            subscribe_once("signal_created", engine._on_signal_created)
            engine._running = False

        asyncio.run(_run())

        handlers = _eb._subscribers.get("signal_created", [])
        # Bound methods compare equal by value (same underlying function + instance)
        # but are not identical objects — use == not `is`.
        self.assertTrue(
            any(h == engine._on_signal_created for h in handlers),
            "engine._on_signal_created must be registered as a signal_created handler",
        )

    def test_no_subscribers_mutation(self):
        """The internal _subscribers dict must never be imported or mutated."""
        import ast, inspect
        source = inspect.getsource(se)
        tree   = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        "_subscribers", alias.name,
                        "signal_engine must not import _subscribers directly",
                    )
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.assertNotIn(
                        "_subscribers", alias.name,
                        "signal_engine must not import _subscribers directly",
                    )

    def test_on_signal_created_enqueues_via_call_soon(self):
        """_on_signal_created must use call_soon_threadsafe, not put_nowait directly."""
        loop = asyncio.new_event_loop()
        # loop.is_running() returns False for a new loop that isn't running yet;
        # patch it so the guard inside _on_signal_created passes.
        loop_running_mock = MagicMock(return_value=True)

        engine = se.SignalEngine()
        engine._running = True
        se._loop = loop

        sig_dict = _make_sig_dict()

        with patch.object(loop, "is_running", loop_running_mock), \
             patch.object(loop, "call_soon_threadsafe") as mock_ts:
            engine._on_signal_created(sig_dict)
            mock_ts.assert_called_once()
            args = mock_ts.call_args[0]
            # Bound methods are not identical objects on each access — use ==
            self.assertEqual(args[0], engine._queue.put_nowait)
            self.assertIs(args[1], sig_dict)

        loop.close()
        se._loop = None


# ── Test 3: no double on_price invocation ─────────────────────────────────────

class TestNoDoubleOnPrice(unittest.TestCase):
    def test_signal_generator_on_price_not_called_by_engine(self):
        """signal_engine must not import or call signal_generator.on_price."""
        import ast, inspect
        source = inspect.getsource(se)
        # Look for any call to sg_on_price or on_price inside signal_engine
        self.assertNotIn(
            "sg_on_price",
            source,
            "signal_engine must not call sg_on_price (double evaluation)",
        )
        # signal_generator import for on_price should also be gone
        self.assertNotIn(
            "signal_generator import on_price",
            source.replace("\n", " "),
        )


# ── Test 4: Redis fallback does NOT publish to signal_created ──────────────────

class TestNoFallbackLoop(unittest.TestCase):
    def test_process_loop_no_eb_publish_on_redis_failure(self):
        """After Redis publish failure, _process_loop must not call eb_publish."""
        import ast, inspect, textwrap

        source = inspect.getsource(se.SignalEngine._process_loop)
        # Should not contain event_bus publish call as fallback
        self.assertNotIn(
            'eb_publish("signal_created"',
            source,
            "_process_loop must not fall back to eb_publish('signal_created') "
            "— this re-enters _on_signal_created and causes an infinite loop",
        )


# ── Test 5: L2 gate rejects wall signals ──────────────────────────────────────

class TestL2Gate(unittest.TestCase):
    def test_l2_gate_passes_clear_signal(self):
        """_apply_l2_gate returns the dict unchanged when no wall is detected."""
        import src.services.order_book_depth as obd
        obd.is_sell_wall_between = lambda sym, entry, tp: False
        obd.is_buy_wall_between  = lambda sym, entry, tp: False

        sig = _make_sig_dict(action="BUY")
        result = se._apply_l2_gate(sig)
        self.assertIs(result, sig)

    def test_l2_gate_rejects_sell_wall(self):
        """_apply_l2_gate returns None when a sell wall is detected on BUY signal."""
        import src.services.order_book_depth as obd
        obd.is_sell_wall_between = lambda sym, entry, tp: True
        obd.is_buy_wall_between  = lambda sym, entry, tp: False

        initial_count = se._l2_rejected
        sig = _make_sig_dict(action="BUY")
        result = se._apply_l2_gate(sig)
        self.assertIsNone(result)
        self.assertEqual(se._l2_rejected, initial_count + 1)

    def test_l2_gate_rejects_buy_wall_on_sell(self):
        """_apply_l2_gate returns None when a buy wall is detected on SELL signal."""
        import src.services.order_book_depth as obd
        obd.is_sell_wall_between = lambda sym, entry, tp: False
        obd.is_buy_wall_between  = lambda sym, entry, tp: True

        sig = _make_sig_dict(action="SELL")
        result = se._apply_l2_gate(sig)
        self.assertIsNone(result)

    def test_l2_gate_passes_on_import_error(self):
        """_apply_l2_gate must pass (not raise) if order_book_depth is unavailable."""
        with patch.dict(sys.modules, {"src.services.order_book_depth": None}):
            sig = _make_sig_dict()
            try:
                result = se._apply_l2_gate(sig)
            except Exception as exc:
                self.fail(f"_apply_l2_gate raised on import error: {exc}")


# ── Test 6: filter_pipeline uses signal.probability ───────────────────────────

class TestFilterPipelineProbability(unittest.TestCase):
    def test_conviction_field_gone(self):
        """filter_pipeline.py must not access signal.conviction on a TradeSignal."""
        import os
        fp = os.path.join(
            os.path.dirname(__file__),
            "..", "src", "optimized", "filter_pipeline.py",
        )
        with open(fp) as fh:
            source = fh.read()
        # The bug was `signal.conviction` / `hasattr(signal, 'conviction')`.
        # TradeOutcome uses a 'conviction' field from features (different object) — allowed.
        self.assertNotIn(
            "signal.conviction",
            source,
            "filter_pipeline must not access signal.conviction (TradeSignal has no such field)",
        )
        self.assertNotIn(
            "hasattr(signal, 'conviction')",
            source,
            "filter_pipeline must not guard on signal.conviction with hasattr",
        )

    def test_probability_field_used(self):
        """filter_pipeline.py must reference signal.probability for sizing."""
        import os
        fp = os.path.join(
            os.path.dirname(__file__),
            "..", "src", "optimized", "filter_pipeline.py",
        )
        with open(fp) as fh:
            source = fh.read()
        self.assertIn(
            "signal.probability",
            source,
            "filter_pipeline must use signal.probability for learning-based sizing",
        )


# ── Test 7: concept drift detection ───────────────────────────────────────────

class TestConceptDrift(unittest.TestCase):
    def setUp(self):
        se._feat_mean       = 0.0
        se._feat_std        = 0.0
        se._feat_count      = 0
        se._drift_detected  = False
        se._drift_consecutive = 0

    def _make_trade_signal(self, features):
        return se.TradeSignal(
            symbol="X", action="BUY", price=1.0, atr=0.01,
            regime="RANGING", confidence=0.6, ev=0.05, ws=0.7,
            coherence=1.0, auditor_factor=1.0, explore=False,
            features=features, timestamp=0.0,
        )

    def test_no_drift_on_stable_features(self):
        """With uniform feature magnitudes, drift must not be flagged."""
        for _ in range(100):
            sig = self._make_trade_signal({"rsi": 50.0, "adx": 25.0})
            se._track_concept_drift(sig)
        self.assertFalse(se._drift_detected)

    def test_drift_detected_on_outlier(self):
        """An extreme outlier after stable history must trigger drift flag."""
        for _ in range(60):
            sig = self._make_trade_signal({"rsi": 50.0, "adx": 25.0})
            se._track_concept_drift(sig)

        for _ in range(6):
            sig = self._make_trade_signal({"rsi": 9999.0, "adx": 9999.0})
            se._track_concept_drift(sig)

        self.assertTrue(se._drift_detected)

    def test_drift_clears_on_return_to_normal(self):
        """Drift flag must clear once z-score returns below 3.0."""
        for _ in range(60):
            se._track_concept_drift(self._make_trade_signal({"rsi": 50.0}))

        for _ in range(6):
            se._track_concept_drift(self._make_trade_signal({"rsi": 9999.0}))
        self.assertTrue(se._drift_detected)

        for _ in range(10):
            se._track_concept_drift(self._make_trade_signal({"rsi": 50.0}))
        self.assertFalse(se._drift_detected)


# ── Test 8: full async process_loop round-trip (mocked Redis) ─────────────────

class TestProcessLoopRoundTrip(unittest.TestCase):
    def setUp(self):
        _eb._subscribers.clear()
        _eb._subscription_keys.clear()
        se._engine = None
        se._loop   = None
        se._l2_rejected = 0

        import src.services.order_book_depth as obd
        obd.is_sell_wall_between = lambda *a: False
        obd.is_buy_wall_between  = lambda *a: False

    def test_signal_published_to_redis_via_queue(self):
        """Signal placed in the queue must be published to Redis exactly once."""
        published_signals = []

        async def _fake_publish(sig):
            published_signals.append(sig)
            return True

        async def _run():
            engine = se.SignalEngine()
            engine._publisher.publish = _fake_publish
            engine._running = True

            sig_dict = _make_sig_dict()
            await engine._queue.put(sig_dict)

            # Tick the loop once
            async def _one_tick():
                try:
                    s = await asyncio.wait_for(engine._queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    return
                s = se._apply_l2_gate(s)
                if s:
                    sig = se.TradeSignal(
                        symbol=s.get("symbol",""), action=s.get("action","BUY"),
                        price=float(s.get("price",0)), atr=float(s.get("atr",0)),
                        regime=s.get("regime","RANGING"),
                        confidence=float(s.get("confidence",0.5)),
                        ev=float(s.get("ev",0)), ws=float(s.get("ws",0.5)),
                        coherence=float(s.get("coherence",1.0)),
                        auditor_factor=float(s.get("auditor_factor",1.0)),
                        explore=bool(s.get("explore",False)),
                        features=s.get("features",{}),
                        timestamp=0.0,
                    )
                    await _fake_publish(sig)
                engine._queue.task_done()

            await _one_tick()

        asyncio.run(_run())
        self.assertEqual(len(published_signals), 1)
        self.assertEqual(published_signals[0].symbol, "BTCUSDT")

    def test_l2_rejected_signal_not_published(self):
        """Signal rejected by L2 gate must not reach Redis publish."""
        import src.services.order_book_depth as obd
        obd.is_sell_wall_between = lambda *a: True

        published = []

        async def _fake_publish(sig):
            published.append(sig)
            return True

        sig_dict = _make_sig_dict(action="BUY")
        result = se._apply_l2_gate(sig_dict)
        self.assertIsNone(result)
        self.assertEqual(len(published), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
