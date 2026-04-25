"""
Secret-safe logging utilities for production hardening.

Sanitizes exception messages and log strings to prevent accidental exposure of
API keys, credentials, tokens, and other secrets in logs.

Minimal, defensive implementation: never raises exception, never over-filters.
Used in critical exception handlers only (firebase_client, market_stream).

Usage:
    from src.services.safe_logging import sanitize, safe_log_exception

    try:
        ...
    except Exception as e:
        print(f"Error: {safe_log_exception(e)}")
"""

import os
import re


# ── Sensitive environment variable names ────────────────────────────────────
_SENSITIVE_ENV_NAMES = [
    "BINANCE_API_KEY",
    "BINANCE_SECRET",
    "BINANCE_API_SECRET",
    "FIREBASE_KEY_BASE64",
    "FIREBASE_CREDENTIALS",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "PUSH_TOKEN",
]


def _get_secrets_to_mask() -> list[str]:
    """
    Build list of secret values to mask (only those with len >= 8).

    Min length 8 prevents accidental over-filtering of short generic words.
    Returns only non-empty secrets from environment.
    """
    secrets = []
    for env_name in _SENSITIVE_ENV_NAMES:
        secret = os.getenv(env_name, "")
        if secret and len(secret) >= 8:
            secrets.append(secret)
    return secrets


def sanitize(text: str) -> str:
    """
    Mask sensitive data in log messages.

    Safe to call on any input (never raises exception).
    Returns string with secrets replaced by [REDACTED].

    Masks:
    - Environment variable secret values (min length 8)
    - Patterns: key=value, key: value, Authorization: Bearer xxx, etc.

    Preserves:
    - Symbols (BTCUSDT, ETHUSDT, etc.)
    - Prices, EV, TP, SL, timeout, pnl, score values
    - Market regime names
    - Normal trading metrics

    Args:
        text: Any string or stringifiable object

    Returns:
        Sanitized string with secrets replaced
    """
    try:
        result = str(text) if text is not None else ""
    except Exception:
        return "[REDACTED]"

    # Phase 1: Mask environment secret values (min length 8)
    for secret in _get_secrets_to_mask():
        if secret in result:
            result = result.replace(secret, "[REDACTED]")

    # Phase 2: Mask pattern matches (case-insensitive)
    # Patterns: key=value, key: value, Authorization: Bearer xxx, api_key xxx, etc.
    # NOTE: Bearer pattern must come FIRST to match before other patterns
    patterns = [
        (r"(?i)(\bbearer)\s+\S+", r"\1 [REDACTED]"),  # Preserve Bearer case; must come first
        (r"(?i)(password|passwd|pwd)(\s*[:=]\s*)\S+", r"\1\2[REDACTED]"),  # Preserve delimiter
        (r"(?i)(token)(\s*[:=]\s*)\S+", r"\1\2[REDACTED]"),  # token only; preserve delimiter
        (r"(?i)(api_?key|secret|api_?secret)(\s*[:=]\s*)\S+", r"\1\2[REDACTED]"),  # Preserve delimiter
    ]

    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)

    return result


def safe_log_exception(e: Exception) -> str:
    """
    Format exception message safely (no secrets, never raises).

    Robust wrapper around exception formatting and sanitization.
    Never raises exception, even if e is malformed or unusual.

    Returns:
        String: "{ExceptionType}: {sanitized_message}"
        Or:     "[ERROR] Could not format exception" if something goes wrong
    """
    try:
        exc_type = type(e).__name__ if e else "UnknownException"
        exc_msg = str(e) if e else ""
        formatted = f"{exc_type}: {exc_msg}"
        return sanitize(formatted)
    except Exception:
        return "[ERROR] Could not format exception"
