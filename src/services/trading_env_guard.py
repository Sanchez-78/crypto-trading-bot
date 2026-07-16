"""Centralized startup validation for trading-env flags (audit PR2 / P2, 2026-07-16).

Three env vars each influence the *traded side* of a paper signal. Combined
carelessly they can silently flip the bot onto the exact side it was configured
to avoid — the "double-flip footgun". This module is the single fail-closed gate
that refuses to start into such an ambiguous configuration.

Pipeline (order in which each flag touches the side):

    PAPER_FADE_SIDES     "both"(default) | "buy_only" | "sell_only"
        DEV_FADE side filter (signal_generator.py). Drops the anti-edge side
        BEFORE execution — a deliberate one-sided selection.
    PAPER_INVERT_SIGNAL  "true" flips BUY<->SELL in the scoring path
        (signal_generator.py, after the regime/score gates).
    SIGNAL_INVERT_TEST   "1" flips BUY<->SELL for EVERY signal right before
        evaluate_signal() — applied AFTER the fade side filter.

Truth table (does the traded side stay unambiguous?):

    fade_sides   invert_active   verdict
    both         no              OK  (default)
    both         yes             OK  (symmetric flip; no side was dropped)
    buy_only     no              OK  (documented reversible experiment)
    sell_only    no              OK
    buy_only     yes             INVALID — filter keeps BUY, a later inversion
                                 flips it to SELL => trades the exact anti-edge
                                 side that was dropped
    sell_only    yes             INVALID (mirror image)

A one-sided fade selects a side on purpose; a downstream inversion silently
reverses that choice. Fail-closed: refuse to start rather than trade the
opposite side unnoticed. This guard never auto-corrects (it does not silently
pick a side) — it only refuses.

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
