"""Compatibility CLI entrypoint for legacy runners.

This repository's live runtime starts via `start.py` / `bot2.main`, but some
older deploy or CI configurations still invoke `python main.py` and
`python main.py signals`.
"""

from __future__ import annotations

import os
import sys
from typing import Sequence


USAGE = """Usage:
  python main.py
  python main.py start
  python main.py signals [SYMBOL]
"""


def _ensure_repo_on_path() -> None:
    repo_root = os.path.dirname(os.path.abspath(__file__))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def run_bot() -> int:
    """Start the long-running bot runtime."""
    _ensure_repo_on_path()
    from bot2.main import main as bot_main

    bot_main()
    return 0


def run_signals(symbol: str | None = None) -> int:
    """Run the legacy finite signal-evaluation command."""
    _ensure_repo_on_path()
    from src.services.evaluator import evaluate_signals

    evaluate_signals(symbol=symbol)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])

    if not args:
        return run_bot()

    cmd = args.pop(0).lower()

    if cmd in {"start", "run", "bot"}:
        return run_bot()

    if cmd == "signals":
        symbol = args[0] if args else None
        return run_signals(symbol=symbol)

    if cmd in {"-h", "--help", "help"}:
        print(USAGE)
        return 0

    print(f"Unknown command: {cmd}", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
