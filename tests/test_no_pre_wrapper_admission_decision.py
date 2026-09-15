"""Production-linked RED gate: the admit/don't-admit decision lives IN the wrapper.

External audit 2026-09-15 (Q1) found that routing every call-site *through*
`canonical_admit()` did not make it the single decision point. Four sites still
decided admission BEFORE calling it, so a rejected candidate never reached the
choke at all:

    realtime_decision_engine.py:3037   if sampler_result.get("allowed"):
    realtime_decision_engine.py:4121   if sampler_result.get("allowed"):
    realtime_decision_engine.py:4206   if sampler_result.get("allowed"):
    paper_trade_executor.py:4798       if decision.strict_ev_allowed or not is_blocked:

Two consequences, both real:

1. "One wrapper" is not "one decision point" -- the actual yes/no happened
   upstream, in four separate places, each free to drift.
2. A candidate rejected by the upstream gate produced NO canonical result at
   all: no BLOCKED record, no reason, no attribution. It was invisible to the
   very path that is supposed to be authoritative.

The fix is NOT to duplicate the gate logic inside the wrapper -- that would
change which candidates are admitted. The upstream component still computes
its decision; it now PASSES that decision to `canonical_admit(gate=...)`, and
the wrapper is the one place that acts on it. Admitted set is unchanged;
the decision's structural home moves.

PAPER-only: `open_paper_position` is monkeypatched in the behavioural tests,
so no position, cooldown or persistence side effect is produced.
"""

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src"

# A "verdict gate" is a branch on a verdict some component RETURNED --
# `sampler_result.get("allowed")`, `ov["allowed"]`, `decision.strict_ev_allowed`.
# That is an admission decision taken outside the wrapper.
#
# Deliberately NOT matched: bare local booleans like `_econ_bad_allowed` or
# `_forced_allowed`. Those are early-exit guards deciding whether a code path
# runs at all (ordinary control flow, several frames up); routing them through
# the wrapper would change semantics rather than relocate a decision. They are
# inventoried and justified in the report instead.
_VERDICT_PATTERNS = (
    re.compile(r"\.get\(\s*['\"]allowed['\"]\s*\)"),
    re.compile(r"\[\s*['\"]allowed['\"]\s*\]"),
    re.compile(r"\.strict_ev_allowed\b"),
    re.compile(r"\bis_blocked\b"),
)


def _parented(tree):
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent
    return tree


def _ancestors(node):
    cur = getattr(node, "_parent", None)
    while cur is not None:
        yield cur
        cur = getattr(cur, "_parent", None)


def test_a_gated_canonical_admit_call_must_receive_the_verdict():
    """RED-1: a verdict may gate a call only if it is PASSED IN as gate=.

    Two shapes are acceptable, and this asserts the boundary between them:

    * no verdict gate at all -- the RDE training sites, where the branch was
      removed outright and the wrapper now acts on `gate=sampler_result`;
    * a verdict gate retained purely to skip expensive preparation, PROVIDED
      the same verdict is handed to `canonical_admit(gate=...)`.

    What it forbids is the original defect: branching on a component's verdict,
    consuming it in the caller, and calling the wrapper as though no decision
    had been made. In that shape the verdict can silently drift from what the
    wrapper acts on, and a rejection leaves no canonical trace.

    This is deliberately NOT "no `if` may exist". Demanding that would either
    run costly signal preparation for every rejected candidate or invite a
    no-op call added solely to satisfy the assertion -- test-gaming, which this
    project's evidence-first rules exclude. Each retained gate is inventoried
    with its justification in the accompanying report.
    """
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = _parented(ast.parse(path.read_text(encoding="utf-8")))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            pytest.fail(f"cannot parse production source {path}: {exc}")

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "canonical_admit"):
                continue

            gating = [
                (anc.lineno, ast.unparse(anc.test))
                for anc in _ancestors(node)
                if isinstance(anc, ast.If)
                and any(p.search(ast.unparse(anc.test)) for p in _VERDICT_PATTERNS)
            ]
            if not gating:
                continue

            passes_gate = any(kw.arg == "gate" for kw in node.keywords)
            if not passes_gate:
                for lineno, test_src in gating:
                    offenders.append(
                        f"{path.relative_to(SRC.parent)}:{node.lineno} "
                        f"gated by `if {test_src}` (line {lineno}) "
                        "but does not pass gate="
                    )

    assert not offenders, (
        "a verdict decides admission before canonical_admit() and is then "
        "dropped instead of being handed to it:\n  " + "\n  ".join(offenders)
    )


def test_canonical_admit_accepts_a_gate_verdict():
    """RED-2: the wrapper takes the upstream verdict as an explicit input."""
    from src.services import paper_trade_executor as pte

    tree = ast.parse(
        (SRC / "services" / "paper_trade_executor.py").read_text(encoding="utf-8")
    )
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "canonical_admit"),
        None,
    )
    assert fn is not None
    assert "gate" in {a.arg for a in fn.args.kwonlyargs}, \
        "canonical_admit has no kw-only `gate` parameter"
    assert hasattr(pte, "canonical_admit")


def test_rejected_gate_blocks_without_reaching_the_choke(monkeypatch):
    """RED-3: a rejected verdict returns BLOCKED and never opens a position."""
    from src.services import paper_trade_executor as pte

    called = []
    monkeypatch.setattr(
        pte, "open_paper_position",
        lambda **kw: called.append(kw) or {"status": "opened", "trade_id": "x"},
    )

    result = pte.canonical_admit(
        signal={"symbol": "BTCUSDT", "action": "BUY"},
        price=100.0,
        ts=1.0,
        route="PAPER_TRAINING",
        reason="PAPER_TRAINING",
        extra=None,
        gate={"allowed": False, "reason": "training_sampler_rate_capped"},
    )

    assert result["outcome"] == "BLOCKED"
    assert result["status"] == "blocked"
    # The upstream component's own reason must survive verbatim -- the whole
    # point is that a rejection is now RECORDED rather than vanishing.
    assert result["reason"] == "training_sampler_rate_capped"
    assert result.get("gate_rejected") is True
    assert not called, "a rejected candidate still reached open_paper_position()"


def test_rejected_gate_without_a_reason_is_still_explicit(monkeypatch):
    """RED-4: a verdict with no reason yields a named reason, never blank."""
    from src.services import paper_trade_executor as pte

    monkeypatch.setattr(
        pte, "open_paper_position",
        lambda **kw: {"status": "opened", "trade_id": "x"},
    )

    result = pte.canonical_admit(
        signal={"symbol": "BTCUSDT", "action": "BUY"},
        price=100.0, ts=1.0, route="P0_GATE", reason="P0_GATE",
        extra=None, gate={"allowed": False},
    )
    assert result["outcome"] == "BLOCKED"
    assert result["reason"] == "upstream_gate_rejected"


def test_allowed_gate_proceeds_normally(monkeypatch):
    """RED-5: an allowed verdict is a passthrough -- admitted set unchanged."""
    from src.services import paper_trade_executor as pte

    seen = {}

    def _fake_open(*, signal, price, ts, reason, extra=None):
        seen["extra"] = dict(extra or {})
        return {"status": "opened", "trade_id": "paper_ok"}

    monkeypatch.setattr(pte, "open_paper_position", _fake_open)

    result = pte.canonical_admit(
        signal={"symbol": "BTCUSDT", "action": "BUY"},
        price=100.0, ts=1.0, route="RDE_TAKE", reason="RDE_TAKE",
        extra={"paper_source": "rde_take"},
        gate={"allowed": True},
    )
    assert result["outcome"] == "OPENED"
    assert seen["extra"]["admission_route"] == "RDE_TAKE"


def test_absent_gate_is_unchanged_behaviour(monkeypatch):
    """RED-6: callers with no upstream verdict keep working exactly as before."""
    from src.services import paper_trade_executor as pte

    monkeypatch.setattr(
        pte, "open_paper_position",
        lambda **kw: {"status": "opened", "trade_id": "paper_nogate"},
    )
    result = pte.canonical_admit(
        signal={"symbol": "BTCUSDT", "action": "BUY"},
        price=100.0, ts=1.0, route="PAPER_EXPLORE", reason="PAPER_EXPLORE",
        extra=None,
    )
    assert result["outcome"] == "OPENED"
    assert result.get("gate_rejected") is None
