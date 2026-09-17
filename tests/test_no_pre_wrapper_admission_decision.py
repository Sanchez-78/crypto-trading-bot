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
    # signal_router's evaluation names its verdict `admitted`, not `allowed`.
    # Omitting it meant p0_8_plus_live_pipeline's gate was not recognised as a
    # verdict at all, so that call-site was skipped entirely -- proven by
    # deleting its gate= and watching this test still pass.
    re.compile(r"\.admitted\b"),
    re.compile(r"\[\s*['\"]admitted['\"]\s*\]"),
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


def _enclosing_function(tree, node):
    """The FunctionDef lexically containing `node`, or None."""
    for anc in _ancestors(node):
        if isinstance(anc, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return anc
    return None


def _verdict_gates_for(tree, node):
    """Every verdict branch that can prevent `node` from being reached.

    Covers BOTH shapes, which is the correction the re-review forced:

    * ancestor `if <verdict>:` -- the call sits inside the positive branch;
    * guard clause -- `if not <verdict>: return/continue/raise` appearing
      EARLIER in the same function, which is what `paper_exploration.py` and
      `p0_8_plus_live_pipeline.py` use. The first version of this test searched
      only ancestors, so it was blind to guard clauses and silently dropped two
      real production sites from the "fixed" inventory while reporting two
      different ones as a supposed superset.
    """
    gates = []

    for anc in _ancestors(node):
        if isinstance(anc, ast.If):
            src = ast.unparse(anc.test)
            if any(pat.search(src) for pat in _VERDICT_PATTERNS):
                gates.append((anc.lineno, src))

    fn = _enclosing_function(tree, node)
    if fn is not None:
        for stmt in ast.walk(fn):
            if not isinstance(stmt, ast.If) or stmt.lineno >= node.lineno:
                continue
            # A guard clause is one whose body always leaves: its LAST
            # statement is an exit. Requiring every statement to be an exit
            # was wrong -- real guards log, throttle and branch before
            # returning, which is precisely the shape of
            # paper_exploration.py's `if not ov.get("allowed")`. That mistake
            # made this test silently vacuous for the two sites it exists to
            # cover (caught by mutating gate=ov to gate={"allowed": True} and
            # seeing it still pass).
            if not stmt.body:
                continue
            if not isinstance(
                stmt.body[-1], (ast.Return, ast.Continue, ast.Break, ast.Raise)
            ):
                continue
            src = ast.unparse(stmt.test)
            if any(pat.search(src) for pat in _VERDICT_PATTERNS):
                gates.append((stmt.lineno, src))

    return gates


# Identifiers too generic to prove two expressions refer to the same verdict.
_TRIVIAL_NAMES = frozenset({
    "allowed", "get", "bool", "True", "False", "None", "not", "reason",
    "str", "int", "float", "dict", "is_blocked",
})


def _identifiers(expr_src):
    try:
        tree = ast.parse(expr_src, mode="eval")
    except SyntaxError:  # pragma: no cover
        return set()
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
    return {n for n in names if n not in _TRIVIAL_NAMES}


def test_a_gated_canonical_admit_call_must_receive_the_same_verdict():
    """RED-1: a verdict may gate a call only if THAT verdict is passed in.

    Strengthened after the 2026-09-16 re-review, which found two defects in the
    first version of this test:

    1. It searched only ancestor `if` statements, so guard-clause/early-return
       gates were invisible. Two real production sites were silently absent
       from the inventory while two different ones were reported, and the
       result was presented as a superset of the audit's list. It was not --
       it was a different set.
    2. It only checked that SOME `gate=` keyword existed, never that the value
       was the verdict that did the gating. `gate={"allowed": True}` would have
       satisfied it identically, which is no contract at all.

    So this now requires the gate= expression to share a non-trivial identifier
    with the gating expression -- `ov` with `not ov.get("allowed")`,
    `r.evaluation.admitted` with `not r.evaluation.admitted`, and so on.

    Still deliberately NOT "no `if` may exist": demanding that would run costly
    signal preparation for every rejected candidate, or invite a no-op call
    added solely to satisfy an assertion.
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

            gates = _verdict_gates_for(tree, node)
            if not gates:
                continue

            gate_kw = next((kw for kw in node.keywords if kw.arg == "gate"), None)
            where = f"{path.relative_to(SRC.parent)}:{node.lineno}"
            if gate_kw is None:
                for lineno, src in gates:
                    offenders.append(
                        f"{where} gated by `{src}` (line {lineno}) "
                        "but passes no gate="
                    )
                continue

            gate_ids = _identifiers(ast.unparse(gate_kw.value))
            if not any(gate_ids & _identifiers(src) for _, src in gates):
                offenders.append(
                    f"{where} passes gate={ast.unparse(gate_kw.value)!r} which "
                    "shares no identifier with the verdict that gated it: "
                    + "; ".join(f"`{src}` (line {ln})" for ln, src in gates)
                )

    assert not offenders, (
        "admission verdicts are decided before canonical_admit() and not "
        "handed to it:\n  " + "\n  ".join(offenders)
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
