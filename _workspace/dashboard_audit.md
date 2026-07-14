# Dashboard / Android API Audit — 2026-07-14

Scope: `src/services/dashboard_web.py` (Flask, port 5001), `start_flask_dashboard.py`,
`systemd/cryptomaster-dashboard.service`, vs. the Android contract in
`.claude/skills/android-dashboard-contract/SKILL.md`.
Requirement: "Dashboard and API must work for the external (Android) application and always show correct metrics."
No code was modified; diffs below are PROPOSED only.

---

## 1. Contract expected by the Android app (SKILL.md)

Top-level JSON of the metrics endpoint:

| Field | Type | Notes |
|---|---|---|
| `open_positions` | **array** of `{trade_id, symbol, side, entry_price, current_price, tp, sl, pnl_pct, hold_s, age_s}` | array, not a count |
| `closed_today` | number | trades closed since UTC start-of-day |
| `total_trades` | number | |
| `win_rate_pct` | number | |
| `profit_factor` | number | |
| `learning_status` | `"UČENÍ" \| "PŘIPRAVEN" \| "VYPNUTO"` | Czech only |
| `recommendation` | `"KOUPIT" \| "PRODAT" \| "ČEKAT" \| "POČKAT"` | Czech only |
| `last_update_utc` | ISO8601, `Z` suffix, **millisecond** precision | e.g. `2026-06-08T10:15:30.123Z` |

Note: the richer Firebase-side contracts (`src/services/app_metrics_contract.py`,
`src/services/dashboard_snapshot_contract.py`) already carry Czech context blocks; the HTTP
endpoint audited here is the one that does not satisfy the skill contract.

---

## 2. Contract mismatches in `/api/dashboard/metrics` (`src/services/dashboard_web.py`)

Primary payload is built by `get_live_metrics_from_cache()` (lines 104–268, return dict 248–268).

| # | Mismatch | Location |
|---|---|---|
| M1 | `closed_today` **missing** entirely (all 3 response variants) | dashboard_web.py:248–268, 1125–1142, 1268–1285 |
| M2 | `total_trades` **missing** (API has `closed_trades` / `lifetime_closed_trades` instead) | dashboard_web.py:249–251 |
| M3 | `learning_status` **missing** — no Czech label anywhere in dashboard_web.py (`grep UČENÍ` → 0 hits in this file) | whole file |
| M4 | `recommendation` **missing** | whole file |
| M5 | `last_update_utc` **missing** — API uses `timestamp` / `last_update` keys | dashboard_web.py:260–261, 1135–1136, 1278–1279 |
| M6 | `open_positions` is an **int count**; the array is under a different key `open_positions_list` | dashboard_web.py:252–253 |
| M7 | Position objects use `age_seconds` / `current_hold_s`, contract wants `age_s` / `hold_s` | dashboard_web.py:237–238 (also 1211, 1222) |
| M8 | Position `pnl_pct` is **hardcoded `0.0`** even though `entry_price` and `current_price` are both available — Android always shows 0% on open positions | dashboard_web.py:241 (and fallback path 1214) |
| M9 | Timestamp precision: `datetime.now(...).isoformat()` emits **microseconds** (`.123456Z`), and `datetime.fromtimestamp(int_ts)` emits **no fraction at all** (`...:30Z`). Contract demands `.SSS` milliseconds; a strict `yyyy-MM-dd'T'HH:mm:ss.SSS'Z'` parser on Android fails on both. | dashboard_web.py:86, 199–200, 242, 247, 1091, 1188, 1431–1432 |

---

## 3. Metrics-correctness findings (WR / PF / PnL sourcing)

The 2026-07-03 fix is correct for the happy path: `get_live_metrics_from_cache()` sources
WR from the durable learning rolling window (lines 147–149), PF/lifetime_n from
`paper_adaptive_learning_state.json` (lines 127, 255), session detail from
`cache.sqlite:closed_trades` (156–204), with rolling-window fallback (206–208). The dead
`trades` table is correctly avoided **only on this path**.

Remaining problems:

| # | Finding | Location |
|---|---|---|
| C1 | **Dead-table fallback chain still live.** If the learning state JSON is missing/empty (`rolling` empty AND `lifetime_n == 0` → returns `None`, line 133–134), `metrics()` falls back to port-5000 proxy and then to `learning_database.sqlite:trades` — the table with **no writer since 2026-06-26**. This is exactly the stale-June-26-data failure mode again. | dashboard_web.py:1032–1034 → 1099–1111, 1153–1169, 1233–1235 |
| C2 | Fallback "profit_factor" is a **win/loss count ratio**, not gross-profit/gross-loss: `wins / (losses + 0.0001)`. Mathematically wrong metric. | dashboard_web.py:1177 |
| C3 | `/api/dashboard/metrics/enhanced` PF formula is degenerate — evaluates to `1.0` for any nonzero total (`abs(x/x)`), `0.0` otherwise. Also reads only the dead `trades` table, with columns (`outcome`, `net_pnl_pct`, `closed_ts`) that don't match the real schema → silently zeros. | dashboard_web.py:1327–1359 (formula at 1356) |
| C4 | **Mixed basis in one payload**: `win_rate_pct` = lifetime rolling window, `profit_factor` = lifetime, but `net_pnl` = **session-only** sum from ephemeral cache.sqlite (reset on bot restart, line 258). After a restart the app shows e.g. WR 54% over 100 trades next to Net P&L $0.00. Should expose both (`session_net_pnl` + a durable lifetime expectancy-based figure) or label the basis. | dashboard_web.py:153–164, 258 |
| C5 | When learning state exists but `rolling` is empty (fresh window) and `lifetime_n > 0`, `win_rate_pct` shows `0.0` rather than unknown/lifetime WR. | dashboard_web.py:147–149 |
| C6 | `/api/trades/recent` order is correct (cache.sqlite → runtime cache → journalctl → 24h-limited legacy DB → durable rolling → `[]`). Only nit: legacy DB fallback uses a **relative** path (cwd-dependent). | dashboard_web.py:1528 |
| C7 | `populate_trades_from_logs()` (writes to the dead `trades` table via `os.system` journalctl) is **dead code — never called**. Candidate for deletion, not required for the fix. | dashboard_web.py:280–338 |
| **C8** | **CONFIRMED LIVE BUG — SELL trades displayed with inverted `pnl_pct` and `side=BUY`** (see §3.1) | dashboard_web.py:187–188, 192, 1419–1420, 1424; local_persistent_cache.py:45–62, 237–238; paper_trade_executor.py:2480–2498 |

### 3.1 C8 — Root cause of the "wrong sign pnl_usd / win" live evidence (14:31 UTC 2026-07-14)

Observed: ADAUSDT `paper_26d068c6cc7c` entry 0.16385 → exit 0.16355, API returned
`side=BUY, pnl_pct=-0.18309, pnl_usd=+0.0007155, win=1`; ETHUSDT 1881.365 → 1874.265
`pnl_pct=-0.377, pnl_usd=+0.001687`; while ETHUSDT `paper_fab01517ed80` 1866.475 → 1863.925
had a consistent `pnl_usd=-0.000883`.

**Traced write path** (`close_paper_position` → `_save_paper_trade_closed` → `save_closed_trade`):

1. `_calculate_pnl()` **is side-aware** — `src/services/paper_trade_executor.py:893–896`
   (`SELL: gross = (entry - exit)/entry`). Net = gross − fees − slippage
   (paper_trade_executor.py:905).
2. `closed_trade` dict (paper_trade_executor.py:2480–2498) sets
   `pnl_usd = net_pnl_usd = (net_pnl_pct/100) * size_usd` (line 2478, 2493) and
   `win = 1 if net_pnl_usd > 0` (line 2497). **Both side-aware and correct.**
   But the dict contains **NO `pnl_pct` key** (only `net_pnl_pct` / `gross_pnl_pct` —
   grep for `"pnl_pct"` in paper_trade_executor.py: 0 hits).
3. `save_closed_trade()` stores `trade.get("pnl_pct")` → **`None` → `pnl_pct` column is NULL**
   in cache.sqlite — `src/services/local_persistent_cache.py:238`.
   The `closed_trades` schema also has **no `side` column** (local_persistent_cache.py:45–62),
   so the direction is lost at persistence time.
4. The dashboard reader then "repairs" the NULL with a **long-only** formula and **hardcodes
   the side**:
   - `dashboard_web.py:187–188` — `if pp is None: pp = ((xp / ep - 1.0) * 100.0)`
   - `dashboard_web.py:192` — `'side': 'BUY'` (same pattern in `/api/trades/recent`:
     1419–1420, 1424).

**Conclusion:** the trades with "wrong sign" are **SELL/SHORT trades**. The stored
`pnl_usd` and `win` are CORRECT (price fell → short won → `pnl_usd > 0`, `win=1`); what is
wrong is the **displayed `pnl_pct` (long-formula, inverted sign for shorts) and `side`
(hardcoded BUY)**. Numeric proof with `size_usd = $0.50` and 4 bps round-trip costs:

- ADA short: gross +0.1831% − 0.04% = +0.1431% × $0.50 = **+$0.000716** ≈ reported +0.0007155 ✓
- ETH short: gross +0.3774% − 0.04% = +0.3374% × $0.50 = **+$0.001687** = reported exactly ✓
- ETH long (`fab01517ed80`): −0.1366% − 0.04% = −0.1766% × $0.50 = **−$0.000883** = reported exactly ✓

This also resolves the scale question: positions are sized `size_usd=0.5` (dashboard default
`p.get('size_usd', 0.5)`, dashboard_web.py:240), not $25 — pnl_usd magnitudes are correct.

Impact on Android: per-trade rows are self-contradictory (`side=BUY` + negative `pnl_pct`
+ `win=1`), so any client-side WR/PnL aggregation over `closed_trades_list` is corrupted.
The headline `win_rate_pct` itself comes from the learning rolling window (side-aware net
outcomes) and is NOT inflated — but it visibly disagrees with the trade list it ships with.

Minor related inconsistency: `win = net_pnl_usd > 0` (paper_trade_executor.py:2497) vs
`outcome` using a ±0.05% FLAT band (paper_trade_executor.py:908–911) — a +0.01% trade is
`win=1` but `outcome=FLAT`. Not the cause of C8; note only.

---

## 4. Robustness — can an endpoint return 500 to the app?

| Endpoint | Can 500? | Trigger | Location |
|---|---|---|---|
| `/api/dashboard/metrics` | **YES** | Learning-state JSON missing (primary returns `None`) + port-5000 API down → `sqlite3.connect` on `/opt/cryptomaster/local_learning_storage/learning_database.sqlite`; if the file/dir is missing → `OperationalError: unable to open database file`; if sqlite auto-creates an empty DB → `OperationalError: no such table: trades` (verified locally). Escapes to the outer handler which returns **HTTP 500**. | dashboard_web.py:1153–1169 → 1286–1289 |
| `/api/dashboard/metrics/enhanced` | YES (low prob.) | any unexpected exception in outer body | dashboard_web.py:1386–1389 |
| `/api/dashboard/readiness` | **YES** | import failure of `trading_readiness_checker`/`readiness_monitor` (e.g. run without wrapper — see §5) or any runtime error | dashboard_web.py:1674–1676 |
| `/api/dashboard/readiness/status` | **YES** | same | dashboard_web.py:1686–1688 |
| `/api/dashboard/learning-state` | **YES** | malformed JSON state file etc. (missing file is handled, 1700–1707; parse error is not) | dashboard_web.py:1754–1756 |
| `/api/trades/recent` | No | always returns `jsonify([])` on failure | dashboard_web.py:1598–1600 |

Handled well already: missing `cache.sqlite` (guarded `os.path.exists` + try/except, 156–204),
journalctl subprocess (`timeout=2`, try/except, 1451–1522; `FileNotFoundError` for a missing
binary is also caught), missing positions JSON (223–245), missing learning state in
`_load_learning_state` (49–56).

---

## 5. Systemd unit + the "missing dependencies" crash (2026-07-01)

Repo file `systemd/cryptomaster-dashboard.service`:

- `ExecStart=/opt/cryptomaster/venv/bin/python3 /opt/cryptomaster/src/services/dashboard_web.py` (line 12)
- `Restart=always`, `RestartSec=5`, `StartLimitBurst=3`, `Environment="PYTHONUNBUFFERED=1"`.

Findings:

1. **Repo unit has drifted from production.** Per commit 78a564c (2026-07-03) the runtime
   venv was moved to `/opt/dashboard_venv` and the unit points at the tracked wrapper
   `start_flask_dashboard.py`. Nothing in the repo references `/opt/dashboard_venv`
   (grep → 0 files); the checked-in unit still uses the OLD `/opt/cryptomaster/venv` +
   direct `dashboard_web.py`. Anyone redeploying this unit file reintroduces the crashed
   configuration.
2. CLAUDE.md pattern compliance: direct python (no Gunicorn) — OK; `-u` flag missing but
   `PYTHONUNBUFFERED=1` is equivalent; `RestartSec=5` vs documented `10` — cosmetic.
3. **Direct-run import degradation:** running `python3 /opt/cryptomaster/src/services/dashboard_web.py`
   puts `src/services/` (script dir) on `sys.path`, NOT `/opt/cryptomaster`. So
   `import src.services.readiness_monitor` (line 276) and
   `from src.services.recent_trades_cache import get_recent_trades` (line 1442) fail —
   silently (guarded), disabling readiness monitoring and the runtime trade cache, and
   making `/api/dashboard/readiness*` 500. The wrapper `start_flask_dashboard.py`
   (lines 14–16) fixes `sys.path` and cwd; the unit must exec the wrapper.
4. **Root cause of "missing dependencies":** the only third-party top-level import in
   dashboard_web.py is `flask` (line 7). `requirements.txt` does **NOT contain flask**
   (it lists requests, firebase-admin, redis, numpy, pandas, scikit-learn, joblib,
   python-dotenv, aiohttp, websockets, pytz, paramiko). Any venv (re)built from
   requirements.txt therefore lacks Flask → `ModuleNotFoundError: flask` on start →
   systemd crash-loop → `StartLimitBurst=3` → unit enters `failed` → UI serves nothing /
   client shows 5-day-old cached page. Matches the 2026-07-01 incident and the
   deploy-`git stash -u` venv-wipe described in 78a564c.

### Dependencies required in /opt/dashboard_venv

Minimal (everything else the dashboard imports lazily is stdlib or guarded):

```
flask>=3.0        # pulls werkzeug, jinja2, click, itsdangerous, markupsafe, blinker
```

No firebase-admin, no numpy, no psutil needed by dashboard_web.py itself. (If
`/api/dashboard/readiness` must be fully functional, its import chain
`readiness_monitor → paper_trade_executor → src.core.event_bus` is stdlib-only per current
headers, so still Flask-only.)

---

## 6. Minimal fix plan (proposed diffs — NOT applied)

Ordered by impact; each is independent and small (per CLAUDE.md "no overengineering",
narrow-patch rules).

### Fix 1 — `/api/dashboard/metrics` must never 500; kill the dead-table 500 path

```diff
--- a/src/services/dashboard_web.py
+++ b/src/services/dashboard_web.py
@@ -1286,4 +1286,17 @@ def metrics():
     except Exception as e:
         from datetime import datetime, timezone
-        iso_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
-        return jsonify({"error": str(e), "timestamp": iso_timestamp}), 500
+        iso_timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
+        # Contract: Android must always receive valid, parseable JSON (HTTP 200).
+        return jsonify({
+            "error": str(e),
+            "degraded": True,
+            "open_positions": 0, "open_positions_list": [],
+            "closed_trades_list": [],
+            "closed_today": 0, "total_trades": 0, "closed_trades": 0,
+            "win_rate_pct": 0.0, "profit_factor": 0.0, "net_pnl": 0.0,
+            "learning_status": "VYPNUTO",
+            "recommendation": "ČEKAT",
+            "exit_distribution": {},
+            "timestamp": iso_timestamp, "last_update": iso_timestamp,
+            "last_update_utc": iso_timestamp,
+        }), 200
```

(Alternative/stronger variant: delete the legacy port-5000 + `learning_database.sqlite`
fallback block, lines 1035–1285, and build the degraded response directly when
`get_live_metrics_from_cache()` returns `None`. Recommended once the above is verified,
since C1/C2 make that whole branch a stale/wrong-data generator.)

### Fix 2 — add the missing contract fields to the live payload

```diff
--- a/src/services/dashboard_web.py
+++ b/src/services/dashboard_web.py
@@ -244,8 +244,26 @@ def get_live_metrics_from_cache():
         except Exception:
             pass
 
-        iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
+        iso = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
+
+        # Android contract: closed_today from the durable rolling window (survives restarts)
+        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
+        closed_today = sum(
+            1 for e in rolling
+            if isinstance(e, (list, tuple))
+            and any(isinstance(x, (int, float)) and x > 1e9 and x >= midnight for x in e)
+        )
+
+        # Android contract: Czech learning status from durable state
+        if state.get('regime_tp_learning_enabled'):
+            learning_status = 'UČENÍ'
+        elif lifetime_n > 0:
+            learning_status = 'PŘIPRAVEN'
+        else:
+            learning_status = 'VYPNUTO'
+
         return {
             'closed_trades': lifetime_n,
+            'total_trades': lifetime_n,
+            'closed_today': closed_today,
             'session_closed_trades': session_n,
             'lifetime_closed_trades': lifetime_n,
@@ -258,6 +276,9 @@ def get_live_metrics_from_cache():
             'net_pnl': round(session_net, 6),
             'exit_distribution': exits,
+            'learning_status': learning_status,
+            'recommendation': 'ČEKAT',   # no live signal feed in this process; ČEKAT is the safe honest default
             'timestamp': iso,
             'last_update': iso,
+            'last_update_utc': iso,
             'data_source': 'learning_state+cache.sqlite',
```

Note on M6: keep `open_positions` as an int and `open_positions_list` as the array —
changing the type of `open_positions` would break the existing web UI (HTML template reads
the count) and the Firebase snapshot consumers. Instead confirm with the Android client
which key it reads; if it truly requires `open_positions` to be an array, add a
contract-versioned alias endpoint rather than mutating this shared payload.

### Fix 3 — position objects: contract keys + real pnl_pct

```diff
--- a/src/services/dashboard_web.py
+++ b/src/services/dashboard_web.py
@@ -229,6 +229,10 @@ def get_live_metrics_from_cache():
             for pid, p in iterable:
                 ets = float(p.get('entry_ts', now_ts))
+                _ep = float(p.get('entry_price', 0))
+                _cp = float(p.get('last_price', p.get('entry_price', 0)))
+                _side = p.get('side', 'BUY')
+                _pnl = ((_cp / _ep - 1.0) * 100.0) if _ep else 0.0
+                if _side.upper() in ('SELL', 'SHORT'):
+                    _pnl = -_pnl
                 open_positions_list.append({
                     'trade_id': str(pid)[:12], 'symbol': p.get('symbol', 'N/A'),
-                    'side': p.get('side', 'BUY'),
+                    'side': _side,
-                    'entry_price': float(p.get('entry_price', 0)),
-                    'current_price': float(p.get('last_price', p.get('entry_price', 0))),
+                    'entry_price': _ep,
+                    'current_price': _cp,
                     'tp': float(p.get('tp', 0)), 'sl': float(p.get('sl', 0)),
                     'entry_ts': ets, 'age_seconds': int(now_ts - ets),
+                    'age_s': int(now_ts - ets),
                     'current_hold_s': int(now_ts - ets),
+                    'hold_s': int(now_ts - ets),
                     'regime': p.get('regime', 'N/A'),
                     'size_usd': float(p.get('size_usd', 0.5)),
-                    'pnl_pct': 0.0, 'status': 'OPEN',
+                    'pnl_pct': round(_pnl, 4), 'status': 'OPEN',
```

(Additive keys `age_s`/`hold_s` keep old consumers working.)

### Fix 4 — millisecond ISO timestamps everywhere

Replace every `.isoformat().replace('+00:00', 'Z')` on `datetime.now(...)` and
`datetime.fromtimestamp(...)` with `.isoformat(timespec='milliseconds').replace('+00:00', 'Z')`.
Occurrences: dashboard_web.py:86, 199, 200, 242, 247, 1057, 1076, 1091, 1188, 1221, 1239–1240,
1251–1252, 1288, 1299, 1388, 1431–1432, 1494, 1498, 1549, 1554. One mechanical
`replace_all`-style edit per pattern; guarantees `.SSS` even for integer epoch inputs.

### Fix 5 — readiness/learning-state endpoints: degrade with 200

```diff
--- a/src/services/dashboard_web.py
+++ b/src/services/dashboard_web.py
@@ -1674,3 +1674,4 @@ def readiness_check():
     except Exception as e:
         log.error(f"[READINESS_CHECK_ERROR] {e}", exc_info=True)
-        return jsonify({"error": str(e), "readiness_score": 0, "is_ready_for_trading": False}), 500
+        return jsonify({"error": str(e), "readiness_score": 0, "is_ready_for_trading": False,
+                        "blocker_reasons": ["service_degraded"]}), 200
@@ -1686,3 +1687,3 @@ def readiness_status():
     except Exception as e:
         log.error(f"[READINESS_STATUS_ERROR] {e}", exc_info=True)
-        return jsonify({"error": str(e)}), 500
+        return jsonify({"error": str(e), "status": "degraded"}), 200
@@ -1754,3 +1755,4 @@ def learning_state():
     except Exception as e:
         log.error(f"[LEARNING_STATE_ERROR] {e}", exc_info=True)
-        return jsonify({"error": str(e), "status": "error"}), 500
+        return jsonify({"error": str(e), "status": "error", "learning_enabled": False,
+                        "regime_tp_strategy": {}, "lifetime_closes": 0}), 200
```

### Fix 6 — dependencies: make the dashboard venv reproducible

New file `requirements-dashboard.txt` (used to build `/opt/dashboard_venv`; do NOT bloat it
with bot deps, and do NOT add flask to the bot's requirements.txt unless the bot venv also
serves Flask):

```diff
--- /dev/null
+++ b/requirements-dashboard.txt
@@ -0,0 +1,2 @@
+# /opt/dashboard_venv — dashboard_web.py needs ONLY Flask (2026-07-01 outage: venv rebuilt without it)
+flask>=3.0
```

### Fix 7 — align the checked-in systemd unit with production (78a564c)

```diff
--- a/systemd/cryptomaster-dashboard.service
+++ b/systemd/cryptomaster-dashboard.service
@@ -9,7 +9,8 @@
 User=root
 WorkingDirectory=/opt/cryptomaster
 Environment="PYTHONUNBUFFERED=1"
-ExecStart=/opt/cryptomaster/venv/bin/python3 /opt/cryptomaster/src/services/dashboard_web.py
+# Venv lives OUTSIDE the repo (deploy runs `git stash -u`); wrapper fixes sys.path/cwd.
+ExecStart=/opt/dashboard_venv/bin/python3 -u /opt/cryptomaster/start_flask_dashboard.py
 Restart=always
-RestartSec=5
+RestartSec=10
```

Still "direct python, no Gunicorn/supervisor" — complies with the CLAUDE.md PERMANENT FIX.
Pre-deploy check remains: `curl http://localhost:5001/api/dashboard/metrics`.

### Fix 8 — C8: persist `net_pnl_pct` + `side`; stop long-only recompute (HIGHEST PRIORITY with Fix 1)

8a — writer (`src/services/local_persistent_cache.py`): persist what the executor already
computed correctly.

```diff
--- a/src/services/local_persistent_cache.py
+++ b/src/services/local_persistent_cache.py
@@ -61,6 +61,12 @@ def _init_db():
             synced_to_firebase INTEGER DEFAULT 0
         )
     """)
+
+    # C8 migration: legacy cache.sqlite lacks the side column (direction was lost)
+    try:
+        cursor.execute("ALTER TABLE closed_trades ADD COLUMN side TEXT")
+    except sqlite3.OperationalError:
+        pass  # column already exists
@@ -224,23 +230,25 @@ def save_closed_trade(trade: Dict[str, Any]):
             cursor.execute("""
                 INSERT OR REPLACE INTO closed_trades
-                (trade_id, symbol, entry_ts, exit_ts, entry_price, exit_price,
+                (trade_id, symbol, side, entry_ts, exit_ts, entry_price, exit_price,
                  pnl_usd, pnl_pct, win, exit_reason, regime, mfe, mae, synced_to_firebase)
-                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
+                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
             """, (
                 trade.get("trade_id"),
                 trade.get("symbol"),
+                trade.get("side") or trade.get("action") or "BUY",
                 trade.get("entry_ts"),
                 trade.get("exit_ts"),
                 trade.get("entry_price"),
                 trade.get("exit_price"),
                 trade.get("pnl_usd"),
-                trade.get("pnl_pct"),
+                # executor emits net_pnl_pct (side-aware, cost-inclusive); pnl_pct key does not exist
+                trade.get("pnl_pct") if trade.get("pnl_pct") is not None else trade.get("net_pnl_pct"),
                 1 if trade.get("win") else 0,
```

8b — reader (`src/services/dashboard_web.py`, both cache readers: metrics 179–201 and
`/api/trades/recent` 1411–1433). Read `side`; for legacy rows (NULL `pnl_pct`/`side`) make
the fallback sign-consistent with the stored side-aware `pnl_usd` instead of assuming long:

```diff
--- a/src/services/dashboard_web.py
+++ b/src/services/dashboard_web.py
@@ -179,17 +179,29 @@ def get_live_metrics_from_cache():
-                for r in cur.execute(
-                    "SELECT trade_id, symbol, entry_price, exit_price, pnl_usd, pnl_pct, "
-                    "exit_reason, entry_ts, exit_ts, regime, win "
-                    "FROM closed_trades ORDER BY exit_ts DESC LIMIT 30"
-                ):
-                    tid, sym, ep, xp, pu, pp, reason, ets, xts, regime, win = r
+                _q = ("SELECT trade_id, symbol, entry_price, exit_price, pnl_usd, pnl_pct, "
+                      "exit_reason, entry_ts, exit_ts, regime, win, {side} "
+                      "FROM closed_trades ORDER BY exit_ts DESC LIMIT 30")
+                try:
+                    rows = list(cur.execute(_q.format(side="side")))
+                except sqlite3.OperationalError:      # legacy DB without side column
+                    rows = [r + (None,) for r in cur.execute(_q.format(side="NULL"))]
+                for r in rows:
+                    tid, sym, ep, xp, pu, pp, reason, ets, xts, regime, win, side = r
                     ep = float(ep or 0)
                     xp = float(xp or 0)
                     if pp is None:
-                        pp = ((xp / ep - 1.0) * 100.0) if ep else 0.0
+                        pp = ((xp / ep - 1.0) * 100.0) if ep else 0.0
+                        if (side or '').upper() in ('SELL', 'SHORT'):
+                            pp = -pp                 # short: direction-corrected
+                        elif side is None and pu is not None and pp * float(pu) < 0:
+                            pp = -pp                 # legacy row: trust side-aware pnl_usd sign
@@
                     closed_trades_list.append({
-                        'trade_id': tid, 'symbol': sym, 'side': 'BUY',
+                        'trade_id': tid, 'symbol': sym, 'side': (side or 'BUY'),
```

(Apply the identical pattern at dashboard_web.py:1411–1433 / 1419–1420 / 1424 in
`recent_trades()`.)

Note: 8a fixes all NEW rows at the source; 8b's `pp * pu < 0` heuristic only exists so the
30 most recent LEGACY rows (written before 8a deploys) stop showing inverted signs. It
self-obsoletes as new rows arrive.

### Explicitly NOT proposed (avoid overengineering / risk)
- No rewrite of the port-5000 proxy chain beyond making it non-fatal (Fix 1); deletion is a
  follow-up once Fix 1 is verified in production.
- No change to `open_positions` type (see Fix 2 note) without confirming the Android parser.
- No removal of dead `populate_trades_from_logs()` in the same patch (separate cleanup).
- No Gunicorn/WSGI changes (forbidden by CLAUDE.md).

---

## 7. Verification checklist (post-patch, pre-deploy)

```bash
# 1. venv sanity
/opt/dashboard_venv/bin/python3 -c "import flask; print(flask.__version__)"
# 2. contract fields
curl -s http://localhost:5001/api/dashboard/metrics | jq 'keys'   # closed_today,total_trades,learning_status,recommendation,last_update_utc present
curl -s http://localhost:5001/api/dashboard/metrics | jq '.last_update_utc'  # ...SSSZ (ms)
curl -s http://localhost:5001/api/dashboard/metrics | jq '.learning_status'  # Czech value
# 3. degradation drills (staging): rename learning-state JSON, cache.sqlite, stop port-5000 API
#    → endpoint must return HTTP 200 valid JSON each time (watch for the old 500 at line 1289)
# 4. C8 sign consistency: for every trade in closed_trades_list,
#    sign(pnl_pct) must equal sign(pnl_usd) and win must match pnl_usd > 0
curl -s http://localhost:5001/api/dashboard/metrics | jq '[.closed_trades_list[]
  | select((.pnl_pct > 0 and .pnl_usd < 0) or (.pnl_pct < 0 and .pnl_usd > 0)
           or (.win == 1 and .pnl_usd < 0) or (.win == 0 and .pnl_usd > 0))] | length'  # must be 0
# 5. SELL trades must carry side=SELL, not BUY:
sqlite3 /opt/cryptomaster/local_learning_storage/cache.sqlite \
  "SELECT trade_id, side, pnl_pct, pnl_usd, win FROM closed_trades ORDER BY exit_ts DESC LIMIT 10;"
# 6. run the android-dashboard-contract skill gates
```
