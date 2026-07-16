"""Centralized startup validation for trading-env flags (audit PR2 / P2, 2026-07-16).

Three env vars each influence the *traded side* of a paper signal. Combined
carelessly they can silently flip the bot onto the exact side it was configured
to avoid — the "double-flip footgun". This module is the single fail-closed gate
that refuses to start into such an ambiguous configuration.

Pipeline (order in which each flag touches the side), verified against
signal_generator.py:

    PAPER_FADE_SIDES     "both"(default) | "buy_only" | "sell_only"
        DEV_FADE side filter (signal_generator.py:846-853, reachable only
        inside `if _DEV_FADE:`). Drops the anti-edge side BEFORE execution —
        a deliberate one-sided selection.
    SIGNAL_INVERT_TEST   "1" flips BUY<->SELL for EVERY final signal right
        before evaluate_signal() (signal_generator.py:1141) — applied AFTER
        the fade side filter. This IS an active double-flip with a one-sided
        fade: the filter keeps BUY, then this flips it to SELL => the bot
        trades exactly the anti-edge side that was dropped.
    PAPER_INVERT_SIGNAL  "true" flips BUY<->SELL inside _get_scored_edge
        (signal_generator.py:489). On the DEV_FADE path this flip is
        immediately OVERWRITTEN when `action` is recomputed from dev_bps
        (signal_generator.py:846), so today it does NOT reach the fade filter
        and is NOT an active double-flip. It is still rejected here as a
        conservative, fail-closed measure: the combination is ambiguous and
        one code-reorder away from becoming live, and the deploy-time guard
        (hetzner-set-fade-sides.yml) already refuses it — keeping both guards
        consistent.

Truth table (does the traded side stay unambiguous?):

    fade_sides           invert_active   verdict
    both                 no              OK  (default)
    both                 yes             OK  (symmetric flip; no side dropped)
    buy_only / sell_only no              OK  (documented reversible experiment)
    buy_only / sell_only SIGNAL_INVERT_TEST   INVALID — active double-flip
    buy_only / sell_only PAPER_INVERT_SIGNAL  INVALID — conservative (see above)

Fail-closed: refuse to start rather than risk trading the opposite side
unnoticed. This guard never auto-corrects (it does not silently pick a side) —
it only refuses. The check is intentionally conservative: it also fires when
PAPER_DEVIATION_FADE is off (fade filter inert), because a one-sided
PAPER_FADE_SIDES is only ever set with DEV_FADE in mind, so the pairing is a
config smell regardless.

This does NOT change DEV_FADE logic; it only validates the env combination.
"""
import logging
import os

log = logging.getLogger(__name__)

INVALID_COMBINATION_MARKER = "[INVALID_TRADING_ENV_COMBINATION]"

_ONE_SIDED_FADE = {"buy_only", "sell_only"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


class InvalidTradingEnvError(RuntimeError):
    """Raised when trading-env flags form an ambiguous traded-side combination."""


def _is_true(val) -> bool:
    return str(val).strip().lower() in _TRUE_VALUES


def _active_invert_flags(env) -> list[str]:
    """Return the human-readable names of any active signal-inversion flags."""
    flags = []
    if _is_true(env.get("SIGNAL_INVERT_TEST", "")):
        flags.append("SIGNAL_INVERT_TEST=1")
    if _is_true(env.get("PAPER_INVERT_SIGNAL", "")):
        flags.append("PAPER_INVERT_SIGNAL=true")
    return flags


def check_trading_env(env=None) -> list[str]:
    """Return a list of violation strings (empty == configuration is safe)."""
    env = os.environ if env is None else env
    fade = str(env.get("PAPER_FADE_SIDES", "both")).strip().lower()
    invert_flags = _active_invert_flags(env)

    violations = []
    if fade in _ONE_SIDED_FADE and invert_flags:
        violations.append(
            f"PAPER_FADE_SIDES={fade} together with {'+'.join(invert_flags)} "
            f"double-flips the traded side: the fade filter drops the anti-edge "
            f"side, then the inversion trades exactly that dropped side."
        )
    return violations


def validate_trading_env(env=None) -> None:
    """Fail-closed startup guard. Raises InvalidTradingEnvError on ambiguity.

    Call once at process startup, before any trading loop begins.
    """
    for violation in check_trading_env(env):
        log.critical("%s %s", INVALID_COMBINATION_MARKER, violation)
        raise InvalidTradingEnvError(
            f"{INVALID_COMBINATION_MARKER} refusing to start into ambiguous "
            f"trading config: {violation}"
        )
