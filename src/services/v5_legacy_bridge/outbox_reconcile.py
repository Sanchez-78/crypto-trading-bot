"""Plan (never execute) reconciliation of terminal outbox rows -- DISABLED (2026-11-18).

Pure function, no Firebase/DB I/O, not wired into any runtime path. It turns terminal
outbox rows plus an externally read cloud state into an auditable action list.

Why a plan and not a replay: paper_open and paper_close both write v5_trades/{trade_id}
with set() WITHOUT merge (firebase_writer.flush_outbox), so blindly replaying an old
paper_open over an existing document would revert a closed trade to "open".

Document contract (event_models.py), checked fail-closed by doc_state(); the document's
trade_id must equal the key and EVERY field the writer always emits must be present with a
valid type (_OPEN_FIELDS / _CLOSE_FIELDS; symbol uppercase alphanumeric, side BUY/SELL,
times and prices finite and positive, real_orders_allowed False):
- open: LegacyPaperOpenEvent.to_dict() with event_type="paper_open" and no exit fields;
- closed: LegacyPaperCloseEvent.to_dict() with event_type="paper_close", incl. the trade
  result (exit_reason, pnl fields, fees, spread, duration). build_learning_update() and
  build_close_metadata() add no event_type and only re-write those fields with values of the
  same type, so a merged close still qualifies; any other type is not assumed to be a close;
- anything else (truncated or historical shapes, foreign trade_id, invalid values) is
  UNKNOWN: never written (at worst a needless deferral).
The plan compares state only, not payloads: an executor must also compare the local row
payload with the cloud document before acting.

Activation blocker: re-read + set() is not atomic. A future executor must write inside a
Firestore transaction (or an equivalent precondition) that re-checks identity and `expect`.

Compare-before-write contract for a future executor: actions run in plan order; `expect` is
the document state the action requires at write time -- the observed state, or the state
after the action named in `depends_on` (e.g. a learning merge after a planned close). The
executor must re-read the document, skip if it is not `expect`, and skip every action whose
dependency did not succeed. The snapshot alone never authorises a write.

Blocker to enabling (see _workspace/2026-11-18_claude_post_c1_remediation.md): the cloud
state must be read on the server with the bot's Firestore credentials (~2.1k document
reads), an executor with a write cap and a ledger needs its own review, and the operator
must confirm that anything still consumes v5_trades history at all.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

ENABLED = False  # planning only; there is deliberately no executor in this module

TRADE_EVENTS = ("paper_open", "paper_close", "learning_update")
SNAPSHOT_EVENTS = ("dashboard_publish", "readiness_publish", "quota_publish")
UNKNOWN = object()  # cloud state not read / unreadable


@dataclass(frozen=True)
class Row:
    event_type: str
    key: str
    error: str = ""


@dataclass(frozen=True)
class Action:
    event_type: str
    key: str
    action: str   # WRITE_OPEN | WRITE_CLOSE | MERGE_LEARNING | SKIP_* | UNKNOWN | DEFERRED_*
    reason: str
    error_class: str
    expect: str = "unknown"  # required state at write time: absent | open | closed | unknown
    depends_on: str = ""     # "<event_type>:<key>" that must have succeeded first, if any


def classify_error(error: Optional[str]) -> str:
    """Deterministic code bugs never reached Firestore; 429 was rejected; the rest is ambiguous."""
    e = error or ""
    if "must end on doc" in e or "has no attribute 'set'" in e:
        return "deterministic_code_error"
    if "429" in e or "uota" in e or "Resource" in e:
        return "quota_rejected"
    return "ambiguous"


def _number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # huge Python ints (not producible by Firestore int64)
        return False


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and _number(value) and value > 0


def _non_negative(value: object) -> bool:
    return isinstance(value, (int, float)) and _number(value) and value >= 0


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _optional_text(value: object) -> bool:
    return value is None or isinstance(value, str)


def _symbol(value: object) -> bool:
    return isinstance(value, str) and value.isascii() and value.isalnum() and value.isupper()


# Every field LegacyPaper{Open,Close}Event.to_dict() always writes, with its validator.
_COMMON_FIELDS = {
    "symbol": _symbol,
    "side": lambda v: v in ("BUY", "SELL"),
    "real_orders_allowed": lambda v: v is False,  # a PAPER record never allows real orders
    "metadata": lambda v: isinstance(v, Mapping),
    "created_at": _text,
}
_OPEN_FIELDS = {
    **_COMMON_FIELDS,
    "strategy_id": _optional_text, "regime": _optional_text, "bucket": _optional_text,
    "entry_ts": _positive, "entry_price": _positive, "size": _positive,
    "expected_move_bps": _number, "required_move_bps": _number,
    "cost_edge_ok": lambda v: type(v) is bool,
}
_CLOSE_FIELDS = {
    **_COMMON_FIELDS,
    "exit_ts": _positive, "exit_price": _positive, "exit_reason": _text,
    "gross_pnl": _number, "fees": _number, "spread": _number, "net_pnl": _number, "net_pnl_pct": _number,
    "duration_seconds": _non_negative,
    "learning_eligible": lambda v: type(v) is bool, "readiness_eligible": lambda v: type(v) is bool,
}


def _complete(doc: Mapping, fields: Mapping) -> bool:
    return all(name in doc and check(doc[name]) for name, check in fields.items())


def doc_state(doc: object, key: str) -> str:
    """absent | open | closed | unknown, per the writer contract above (fail closed)."""
    if doc is None:
        return "absent"
    if doc is UNKNOWN or not isinstance(doc, Mapping) or doc.get("trade_id") != key:
        return "unknown"
    event_type = doc.get("event_type")
    if event_type == "paper_close" and _complete(doc, _CLOSE_FIELDS):
        return "closed"
    if (event_type == "paper_open" and "exit_ts" not in doc and "exit_price" not in doc
            and _complete(doc, _OPEN_FIELDS)):
        return "open"
    return "unknown"


def plan(rows: Sequence[Row], cloud: Mapping[str, object], *, max_writes: int) -> list[Action]:
    """cloud[key]: None = document absent, mapping = document, UNKNOWN/missing = not read."""
    if max_writes < 0:
        raise ValueError("max_writes must be >= 0")
    closes = {r.key for r in rows if r.event_type == "paper_close"}
    # Close before learning before open, so a later step never undoes an earlier one.
    order = {"paper_close": 0, "learning_update": 1, "paper_open": 2}
    actions: list[Action] = []
    planned_close: set[str] = set()  # keys whose WRITE_CLOSE is in this plan (within the cap)
    writes = 0
    for r in sorted(rows, key=lambda r: (order.get(r.event_type, 3), r.key)):
        err = classify_error(r.error)
        if r.event_type in SNAPSHOT_EVENTS:
            actions.append(Action(r.event_type, r.key, "SKIP_SUPERSEDED", "point-in-time snapshot", err))
            continue
        if r.event_type not in TRADE_EVENTS:
            actions.append(Action(r.event_type, r.key, "SKIP_UNSUPPORTED", "unknown event type", err))
            continue
        observed = doc_state(cloud.get(r.key, UNKNOWN), r.key)
        if observed == "unknown":
            actions.append(Action(r.event_type, r.key, "UNKNOWN", "cloud state not read or not recognised",
                                  err, observed))
            continue
        expect, depends_on = observed, ""
        if r.event_type == "paper_close":
            if observed == "closed":
                act, why = "SKIP_PRESENT", "close already in cloud"
            else:
                act, why = "WRITE_CLOSE", f"document {observed}"
        elif r.event_type == "learning_update":
            if observed == "closed":
                act, why = "MERGE_LEARNING", "merge=True into the closed trade document"
            elif r.key in planned_close:
                act, why = "MERGE_LEARNING", "merge=True after the close planned for this key"
                expect, depends_on = "closed", f"paper_close:{r.key}"
            elif observed == "open":
                act, why = "DEFERRED_CLOSE_MISSING", "trade document is still open in cloud"
            else:
                act, why = "DEFERRED_NO_TRADE_DOC", "merge would create a learning-only document"
        else:  # paper_open
            if r.key in closes or observed != "absent":
                act, why = "SKIP_PRESENT", "never set() an open over an existing/closing trade"
            else:
                act, why = "WRITE_OPEN", "document absent and no close pending"
        if act.startswith(("WRITE", "MERGE")):
            if writes >= max_writes:
                act, why, depends_on = "DEFERRED_QUOTA", f"write cap {max_writes} reached", ""
            else:
                writes += 1
                if act == "WRITE_CLOSE":
                    planned_close.add(r.key)
        actions.append(Action(r.event_type, r.key, act, why, err, expect, depends_on))
    return actions
