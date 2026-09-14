"""Production-linked RED gate for the Phase 2 canonical admission contract.

Single-path policy (`CLAUDE_SINGLE_PATH_POLICY_2026-09-14.md`):

    signal -> canonical admission -> open_paper_position -> one close writer -> metrics

`rde_take`, `training_sampler`, exploration and the legacy callers are labels
on ONE flow, not separate decision branches.  These tests assert that contract
against the real production source, not against a copy or a model:

* RED-1 is a structural (AST) gate -- `open_paper_position()` may be called
  from exactly one place in `src/`, the body of `canonical_admit()`.  Every
  other admission call-site must route through the wrapper.
* RED-2..RED-5 are behavioural gates against the real SUT: the wrapper must
  normalise the result to OPENED/BLOCKED, must stamp the immutable attribution
  Phase 2 requires, must never invent attribution it does not have, and must
  never re-decide an admission the choke already decided.

PAPER-only: no test here enables REAL trading, opens a socket, or writes to a
production path.  `open_paper_position` is monkeypatched in the behavioural
tests so no position, cooldown or persistence side effect is produced.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src"
PTE = SRC / "services" / "paper_trade_executor.py"

# Phase 2 mandates these be persisted at open, from the canonical wrapper.
REQUIRED_ATTRIBUTION = (
    "admission_route",
    "code_version",
    "config_version",
    "effective_hold_s",
)


def _iter_python_sources():
    for path in sorted(SRC.rglob("*.py")):
        yield path


def _enclosing_function(tree, node):
    """Return the FunctionDef that lexically contains `node`, or None."""
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(fn):
                if sub is node:
                    return fn
    return None


def test_open_paper_position_is_called_only_from_canonical_admit():
    """RED-1: one admission choke, structurally enforced across all of src/."""
    offenders = []
    for path in _iter_python_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            pytest.fail(f"cannot parse production source {path}: {exc}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = None
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            if fname != "open_paper_position":
                continue
            owner = _enclosing_function(tree, node)
            if path == PTE and owner is not None and owner.name == "canonical_admit":
                continue  # the one legal call-site
            offenders.append(
                f"{path.relative_to(SRC.parent)}:{node.lineno} "
                f"(in {owner.name if owner else '<module>'})"
            )

    assert not offenders, (
        "open_paper_position() must be reached only through canonical_admit(); "
        "direct call-sites create a second admission branch:\n  "
        + "\n  ".join(offenders)
    )


def test_canonical_admit_exists_with_keyword_only_contract():
    """RED-2: the wrapper exists and takes the canonical keyword contract."""
    from src.services import paper_trade_executor as pte

    assert hasattr(pte, "canonical_admit"), "canonical_admit() is not defined"
    tree = ast.parse(PTE.read_text(encoding="utf-8"))
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "canonical_admit"),
        None,
    )
    assert fn is not None
    kwonly = {a.arg for a in fn.args.kwonlyargs}
    for required in ("signal", "price", "ts", "route", "reason", "extra"):
        assert required in kwonly, f"canonical_admit missing kw-only arg {required!r}"
    assert not fn.args.args, "canonical_admit must be keyword-only (no positional args)"


def test_canonical_admit_normalises_outcome_and_stamps_attribution(monkeypatch):
    """RED-3: OPENED outcome + immutable attribution reaches the choke."""
    from src.services import paper_trade_executor as pte

    seen = {}

    def _fake_open(*, signal, price, ts, reason, extra=None):
        seen["extra"] = dict(extra or {})
        seen["reason"] = reason
        return {"status": "opened", "trade_id": "paper_deadbeef"}

    monkeypatch.setattr(pte, "open_paper_position", _fake_open)

    result = pte.canonical_admit(
        signal={"symbol": "BTCUSDT", "action": "BUY", "ev": 0.2},
        price=100.0,
        ts=1.0,
        route="RDE_TAKE",
        reason="RDE_TAKE",
        extra={"paper_source": "rde_take", "max_hold_s": 300},
    )

    assert result["outcome"] == "OPENED"
    assert result["status"] == "opened"
    for key in REQUIRED_ATTRIBUTION:
        assert key in seen["extra"], f"canonical_admit did not stamp {key!r}"
    assert seen["extra"]["admission_route"] == "RDE_TAKE"
    assert isinstance(seen["extra"]["effective_hold_s"], float)


def test_canonical_admit_passes_block_reason_through_unchanged(monkeypatch):
    """RED-4: the wrapper must not re-decide an admission the choke decided."""
    from src.services import paper_trade_executor as pte

    def _fake_open(*, signal, price, ts, reason, extra=None):
        return {"status": "blocked", "reason": "paper_state_not_ready"}

    monkeypatch.setattr(pte, "open_paper_position", _fake_open)

    result = pte.canonical_admit(
        signal={"symbol": "BTCUSDT", "action": "BUY"},
        price=100.0,
        ts=1.0,
        route="PAPER_TRAINING",
        reason="PAPER_TRAINING",
        extra=None,
    )

    assert result["outcome"] == "BLOCKED"
    assert result["reason"] == "paper_state_not_ready", "block reason was rewritten"


def test_canonical_admit_never_invents_missing_attribution(monkeypatch):
    """RED-5: unknown version/segment stays UNKNOWN, never guessed."""
    from src.services import paper_trade_executor as pte

    monkeypatch.delenv("BOT_CODE_VERSION", raising=False)
    monkeypatch.delenv("BOT_CONFIG_VERSION", raising=False)

    seen = {}

    def _fake_open(*, signal, price, ts, reason, extra=None):
        seen.update(dict(extra or {}))
        return {"status": "opened", "trade_id": "paper_cafe"}

    monkeypatch.setattr(pte, "open_paper_position", _fake_open)

    pte.canonical_admit(
        signal={"symbol": "BTCUSDT", "action": "BUY"},
        price=100.0,
        ts=1.0,
        route="PAPER_EXPLORE",
        reason="PAPER_EXPLORE",
        extra=None,
    )

    assert seen["code_version"] == "UNKNOWN"
    assert seen["config_version"] == "UNKNOWN"
    # segment_key absent upstream must stay absent/UNQUALIFIED, never fabricated.
    assert seen.get("segment_key") in (None, "UNQUALIFIED")
