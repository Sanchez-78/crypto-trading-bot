"""F8b — shadow (observation-only) excursion recorder.

External audit v5 §7/§8. The DEV_FADE paper strategy has no proven net edge and
actual paper execution is paused. To gather the intra-trade price-path evidence
that an offline E1–E4 TP/SL counterfactual needs — WITHOUT opening paper positions
or polluting learning/dashboard/Firebase — this module records, for every signal
that WOULD have opened a position, the 1-second directional price path and the
first-crossing time of each candidate barrier level, over a fixed horizon.

Design invariants (audit v5 §8):
  * HOT PATH is in-memory only: `on_tick` updates active observers, the current
    1s directional OHLC bucket, and the first-crossing ladder. No per-tick SQLite,
    no per-tick Firebase, no per-tick log.
  * Persistence happens ONCE per observation, when its horizon completes: one
    transaction writing shadow_excursion_observations + shadow_path_1s +
    shadow_first_crossing to a SEPARATE local sqlite (never the learning cache,
    never Firestore).
  * NO trading side effects: this module never opens a position, never writes a
    close, never touches learning/readiness/dashboard/real-order paths.
  * Default OFF: `enabled()` is False unless PAPER_DATA_COLLECTION_ONLY is truthy,
    so the integration hook is a cheap no-op in normal operation.

bps sign policy matches trade_excursion.py: signed favorable-direction bps —
positive = favorable (toward the side's profit), negative = adverse, side-aware.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

_SELL_SIDES = {"SELL", "SHORT"}
_TRUTHY = {"true", "1", "yes", "on"}
_EPS = 1e-9  # absorbs float representation error at exact ladder boundaries

DEFAULT_LADDER_BPS = "5,10,15,20,30,40,54,75,100"
DEFAULT_HORIZON_S = 300
DEFAULT_SECOND_MS = 1000


def enabled() -> bool:
    """Master switch. Observation-only data collection is OFF unless explicitly
    enabled — so the per-tick integration hook is a no-op in normal operation."""
    return os.getenv("PAPER_DATA_COLLECTION_ONLY", "false").strip().lower() in _TRUTHY


def _favorable_bps(side: str, entry_ref: float, price: float) -> float:
    """Signed favorable-direction bps (side-aware). +ve favorable, -ve adverse."""
    if entry_ref <= 0:
        return 0.0
    frac = (price - entry_ref) / entry_ref
    if str(side or "BUY").upper() in _SELL_SIDES:
        frac = -frac
    return frac * 10000.0


def _parse_ladder(raw: Optional[str]) -> List[int]:
    out: List[int] = []
    for tok in (raw or DEFAULT_LADDER_BPS).split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            v = int(round(float(tok)))
        except ValueError:
            continue
        if v > 0 and v not in out:
            out.append(v)
    return sorted(out)


class _Observer:
    """One in-memory observation. All updates are O(ladder) and allocation-light."""
    __slots__ = (
        "observation_id", "symbol", "side", "regime", "signal_ts_ms",
        "entry_ref_price", "horizon_ms", "features_json", "ladder",
        "buckets", "_cur_sec", "_cur", "first_cross", "sample_count",
        "feature_schema_version",
    )

    def __init__(self, observation_id: str, symbol: str, side: str, regime: str,
                 signal_ts_ms: int, entry_ref_price: float, horizon_ms: int,
                 ladder: List[int], features_json: str, feature_schema_version: int):
        self.observation_id = observation_id
        self.symbol = symbol
        self.side = side
        self.regime = regime
        self.signal_ts_ms = signal_ts_ms
        self.entry_ref_price = entry_ref_price
        self.horizon_ms = horizon_ms
        self.features_json = features_json
        self.feature_schema_version = feature_schema_version
        self.ladder = ladder
        self.buckets: List[Dict[str, Any]] = []
        self._cur_sec: Optional[int] = None
        self._cur: Optional[Dict[str, Any]] = None
        # (direction, level_bps) -> first_cross_ms ; direction in {"fav","adv"}
        self.first_cross: Dict[Tuple[str, int], int] = {}
        self.sample_count = 0

    def _flush_current(self) -> None:
        if self._cur is not None:
            self.buckets.append(self._cur)
            self._cur = None
            self._cur_sec = None

    def update(self, price: float, ts_ms: int, second_ms: int) -> None:
        bps = _favorable_bps(self.side, self.entry_ref_price, price)
        sec = (ts_ms - self.signal_ts_ms) // second_ms
        if sec != self._cur_sec:
            self._flush_current()
            self._cur_sec = sec
            self._cur = {
                "second_offset": int(sec),
                "open_bps": bps, "high_bps": bps, "low_bps": bps, "close_bps": bps,
                "first_high_ms": ts_ms, "first_low_ms": ts_ms,
                "sample_count": 0,
            }
        b = self._cur
        if bps > b["high_bps"]:
            b["high_bps"] = bps
            b["first_high_ms"] = ts_ms
        if bps < b["low_bps"]:
            b["low_bps"] = bps
            b["first_low_ms"] = ts_ms
        b["close_bps"] = bps
        b["sample_count"] += 1
        self.sample_count += 1
        # first-crossing ladder (favorable +L and adverse -L), record earliest ts.
        # _EPS absorbs float representation error so a price meant to sit exactly on
        # a level (e.g. +10.0 bps that computes as 9.99999999999) still registers.
        for lvl in self.ladder:
            if bps >= lvl - _EPS and ("fav", lvl) not in self.first_cross:
                self.first_cross[("fav", lvl)] = ts_ms
            if bps <= -lvl + _EPS and ("adv", lvl) not in self.first_cross:
                self.first_cross[("adv", lvl)] = ts_ms

    def path_rows(self) -> List[Dict[str, Any]]:
        self._flush_current()
        rows = []
        for b in self.buckets:
            first_extreme = "high" if b["first_high_ms"] <= b["first_low_ms"] else "low"
            rows.append({**b, "first_extreme": first_extreme})
        return rows


_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_excursion_observations (
    observation_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    regime TEXT NOT NULL,
    signal_ts_ms INTEGER NOT NULL,
    entry_ref_price REAL NOT NULL,
    horizon_ms INTEGER NOT NULL,
    feature_schema_version INTEGER NOT NULL,
    features_json TEXT,
    completed INTEGER NOT NULL,
    data_quality TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_path_1s (
    observation_id TEXT NOT NULL,
    second_offset INTEGER NOT NULL,
    open_bps REAL NOT NULL,
    high_bps REAL NOT NULL,
    low_bps REAL NOT NULL,
    close_bps REAL NOT NULL,
    first_high_ms INTEGER,
    first_low_ms INTEGER,
    first_extreme TEXT,
    sample_count INTEGER NOT NULL,
    PRIMARY KEY (observation_id, second_offset)
);
CREATE TABLE IF NOT EXISTS shadow_first_crossing (
    observation_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    level_bps INTEGER NOT NULL,
    first_cross_ms INTEGER NOT NULL,
    PRIMARY KEY (observation_id, direction, level_bps)
);
"""


class ShadowExcursionRecorder:
    """Thread-safe in-memory observer manager with once-per-observation persistence.

    All wall-clock is passed IN via ts_ms so the recorder is deterministic and unit
    testable; nothing here reads the system clock.
    """

    def __init__(self, db_path: Optional[str] = None, horizon_s: Optional[int] = None,
                 ladder_bps: Optional[str] = None, second_ms: Optional[int] = None,
                 source: str = "dev_fade_shadow"):
        self.db_path = db_path or os.getenv(
            "SHADOW_DB_PATH", "local_learning_storage/shadow_excursion.sqlite")
        self.horizon_ms = int(horizon_s if horizon_s is not None
                              else os.getenv("SHADOW_HORIZON_S", DEFAULT_HORIZON_S)) * 1000
        self.second_ms = int(second_ms if second_ms is not None
                             else os.getenv("SHADOW_SECOND_MS", DEFAULT_SECOND_MS))
        self.ladder = _parse_ladder(ladder_bps if ladder_bps is not None
                                    else os.getenv("SHADOW_LADDER_BPS"))
        self.source = source
        self._lock = threading.Lock()
        self._active: Dict[str, _Observer] = {}
        self._by_symbol: Dict[str, List[str]] = {}
        self._conn: Optional[sqlite3.Connection] = None

    # ── persistence ────────────────────────────────────────────────────────
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            d = os.path.dirname(self.db_path)
            if d:
                os.makedirs(d, exist_ok=True)
            # check_same_thread=False: the connection is cached on the process and
            # may be used from whichever thread finalizes an observation (a tick
            # thread) or flushes on shutdown (the main thread). Our _lock already
            # serializes every access, so cross-thread use is safe here — without
            # this, sqlite raises ProgrammingError and the observation is lost.
            self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def _data_quality(self, obs: _Observer) -> str:
        # "ok" if we saw at least ~1 sample/second over the horizon, else "sparse".
        want = max(1, self.horizon_ms // self.second_ms)
        return "ok" if obs.sample_count >= want else "sparse"

    def _persist(self, obs: _Observer, now_ms: int) -> None:
        rows = obs.path_rows()
        conn = self._db()
        with conn:  # single transaction
            conn.execute(
                """INSERT OR REPLACE INTO shadow_excursion_observations
                   (observation_id, source, symbol, side, regime, signal_ts_ms,
                    entry_ref_price, horizon_ms, feature_schema_version, features_json,
                    completed, data_quality, sample_count, created_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (obs.observation_id, self.source, obs.symbol, obs.side, obs.regime,
                 obs.signal_ts_ms, obs.entry_ref_price, obs.horizon_ms,
                 obs.feature_schema_version, obs.features_json, 1,
                 self._data_quality(obs), obs.sample_count, now_ms))
            conn.executemany(
                """INSERT OR REPLACE INTO shadow_path_1s
                   (observation_id, second_offset, open_bps, high_bps, low_bps,
                    close_bps, first_high_ms, first_low_ms, first_extreme, sample_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [(obs.observation_id, r["second_offset"], r["open_bps"], r["high_bps"],
                  r["low_bps"], r["close_bps"], r["first_high_ms"], r["first_low_ms"],
                  r["first_extreme"], r["sample_count"]) for r in rows])
            conn.executemany(
                """INSERT OR REPLACE INTO shadow_first_crossing
                   (observation_id, direction, level_bps, first_cross_ms)
                   VALUES (?,?,?,?)""",
                [(obs.observation_id, d, lvl, ts)
                 for (d, lvl), ts in sorted(obs.first_cross.items())])

    # ── hot path (in-memory only) ───────────────────────────────────────────
    def record_signal(self, observation_id: str, symbol: str, side: str, regime: str,
                       signal_ts_ms: int, entry_ref_price: float,
                       features: Optional[Dict[str, Any]] = None,
                       feature_schema_version: int = 1) -> bool:
        """Begin observing a signal that WOULD have opened a position. Returns True
        if an observer was started (False on duplicate id or invalid entry_ref)."""
        if entry_ref_price is None or entry_ref_price <= 0:
            return False
        obs = _Observer(
            observation_id, symbol, str(side or "BUY").upper(), str(regime or "?"),
            int(signal_ts_ms), float(entry_ref_price), self.horizon_ms, self.ladder,
            json.dumps(features, sort_keys=True) if features else None,
            feature_schema_version)
        with self._lock:
            if observation_id in self._active:
                return False
            self._active[observation_id] = obs
            self._by_symbol.setdefault(symbol, []).append(observation_id)
        return True

    def on_tick(self, symbol: str, price: float, ts_ms: int) -> None:
        """Feed a price tick. Updates every active observer for `symbol` and
        finalizes+persists any whose horizon has elapsed. In-memory hot path."""
        with self._lock:
            ids = list(self._by_symbol.get(symbol, ()))
            if not ids:
                return
            done: List[str] = []
            for oid in ids:
                obs = self._active.get(oid)
                if obs is None:
                    continue
                if ts_ms - obs.signal_ts_ms >= obs.horizon_ms:
                    self._persist(obs, ts_ms)
                    done.append(oid)
                else:
                    obs.update(float(price), int(ts_ms), self.second_ms)
            for oid in done:
                self._active.pop(oid, None)
                lst = self._by_symbol.get(symbol)
                if lst and oid in lst:
                    lst.remove(oid)

    def sweep_expired(self, now_ms: int) -> int:
        """Finalize+persist observers whose horizon has elapsed as of now_ms, even
        if their symbol has gone silent (no ticks drive their finalize). The
        integration should call this periodically so a stalled feed cannot leak
        observers unbounded. Returns the number persisted."""
        with self._lock:
            done = [oid for oid, obs in self._active.items()
                    if now_ms - obs.signal_ts_ms >= obs.horizon_ms]
            for oid in done:
                obs = self._active.pop(oid)
                self._persist(obs, now_ms)
                lst = self._by_symbol.get(obs.symbol)
                if lst and oid in lst:
                    lst.remove(oid)
            return len(done)

    def flush_all(self, now_ms: int) -> int:
        """Finalize+persist every still-active observer (e.g. on shutdown). Returns
        the number persisted."""
        with self._lock:
            n = 0
            for oid, obs in list(self._active.items()):
                self._persist(obs, now_ms)
                n += 1
            self._active.clear()
            self._by_symbol.clear()
            return n

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# ── module singleton + thin no-op-when-disabled hooks ──────────────────────────
_singleton: Optional[ShadowExcursionRecorder] = None
_singleton_lock = threading.Lock()


def get_recorder() -> Optional[ShadowExcursionRecorder]:
    """Return the process recorder, or None when data-collection is disabled."""
    global _singleton
    if not enabled():
        return None
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ShadowExcursionRecorder()
    return _singleton


def record_signal(*args, **kwargs) -> bool:
    """No-op (returns False) unless PAPER_DATA_COLLECTION_ONLY is enabled."""
    r = get_recorder()
    return r.record_signal(*args, **kwargs) if r is not None else False


def record_tick(symbol: str, price: float, ts_ms: int) -> None:
    """No-op unless PAPER_DATA_COLLECTION_ONLY is enabled."""
    r = get_recorder()
    if r is not None:
        r.on_tick(symbol, price, ts_ms)
