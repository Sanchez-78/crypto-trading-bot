#!/usr/bin/env python3
"""Effective-environment checks for deploy_bot_files.sh (review 77, P1).

Layers, in the order the running bot sees them:
1. systemd Environment= (unit + drop-ins, including the managed drop-in);
2. systemd EnvironmentFile= entries, which override Environment=;
3. /opt/cryptomaster/.env loaded by start.py via python-dotenv (override=False): it only
   fills keys that are still missing (verified on the server 2026-11-11: the effective unit
   has no EnvironmentFile=, .env is loaded by dotenv).
The preflight refuses a planned key that layer 2 or 3 also sets (an override, or a typo that
would be silently ignored); the postcheck reads the real environment of MainPID (layers 1-2)
and applies layer 3 the same way before checking invariants.

    deploy_env_check.py pre  --environment "<systemctl Environment>" \
                             --env-files "<systemctl EnvironmentFiles>" --dotenv <path> --vars "K=V ..."
    deploy_env_check.py post --environ /proc/<pid>/environ --dotenv <path> --vars "K=V ..."
Exit 0 = ok, 2 = refused (message on stderr).
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

FALSY = {"false", "0", "no", "off"}
STRICT_BOOL_KEYS = ("PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED", "RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED",
                    "STONKFLY_ENABLED", "STONKFLY_PAIRED_ENABLED", "PAPER_STONKFLY_CONTEXT_ENABLED")
# paper_trade_executor.exploration_bucket_cap() silently falls back to 2 on bad values.
STRICT_INT_KEYS = {"PAPER_EXPLORE_MAX_OPEN_PER_BUCKET": (1, 7)}
ENV_FILE_ITEM = re.compile(r"(\S+) \(ignore_errors=(yes|no)\)")


class Refused(ValueError):
    pass


def parse_env_file(text: str) -> dict:
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.removeprefix("export ").split("=", 1)
            env[key.strip()] = value.strip().strip("'\"")
    return env


def parse_kv(source: str) -> dict:
    return dict(kv.split("=", 1) for kv in shlex.split(source) if "=" in kv)


def env_files(listing: str) -> list[tuple[Path, bool]]:
    """Parse `systemctl show -p EnvironmentFiles --value` ("path (ignore_errors=no)" items)."""
    items = [(Path(p), flag == "yes") for p, flag in ENV_FILE_ITEM.findall(listing)]
    # Every character must belong to a recognised item (review 78, R2): a partially parsed
    # listing would silently drop an EnvironmentFile from the model.
    if ENV_FILE_ITEM.sub("", listing).strip():
        raise Refused("cannot parse EnvironmentFiles")
    return items


def file_layers(listing: str) -> list[dict]:
    layers = []
    for path, ignore in env_files(listing):
        try:
            layers.append(parse_env_file(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            if not ignore:
                raise Refused(f"EnvironmentFile missing: {path}")
    return layers


def check_invariants(env: dict) -> None:
    if env.get("TRADING_MODE") != "paper_train":
        raise Refused("TRADING_MODE is not paper_train")
    for key in ("ENABLE_REAL_ORDERS", "LIVE_TRADING_CONFIRMED"):
        if env.get(key, "false").lower() not in FALSY:
            raise Refused(f"{key} is not false")
    for key in STRICT_BOOL_KEYS:
        # candle_cache_v1 silently treats unknown values as "off"; a typo must fail.
        if env.get(key, "false") not in {"true", "false"}:
            raise Refused(f"{key} must be true or false")
    for key, (low, high) in STRICT_INT_KEYS.items():
        value = env.get(key)
        # bounded digit count before int(): a huge digit string must be Refused, not ValueError
        if value is not None and not (re.fullmatch(r"[0-9]{1,3}", value) and low <= int(value) <= high):
            raise Refused(f"{key} must be an integer in [{low}, {high}]")


def _fill_dotenv(env: dict, dotenv: dict) -> dict:
    return {**dotenv, **env}  # override=False: existing process values win


def preflight(environment: str, files_listing: str, vars_: str, dotenv_text: str = "") -> dict:
    planned = parse_kv(vars_)
    layers = file_layers(files_listing)
    dotenv = parse_env_file(dotenv_text)
    for name, layer in [("EnvironmentFile", l) for l in layers] + [(".env (dotenv)", dotenv)]:
        clash = sorted(set(planned) & set(layer))
        if clash:
            raise Refused(f"{name} also sets {clash}; remove it there before deploying")
    env = {**parse_kv(environment), **planned}  # 1. Environment= incl. the new drop-in
    for layer in layers:                          # 2. EnvironmentFile= overrides
        env.update(layer)
    env = _fill_dotenv(env, dotenv)               # 3. dotenv fills missing keys only
    for key, value in planned.items():
        if env.get(key) != value:
            raise Refused(f"effective {key} would not be {value}")
    check_invariants(env)
    return env


def postcheck(environ: bytes, vars_: str, dotenv_text: str = "") -> dict:
    proc = dict(item.split("=", 1) for item in environ.decode("utf-8", "replace").split("\0") if "=" in item)
    for key, value in parse_kv(vars_).items():
        if proc.get(key) != value:
            raise Refused(f"running process has {key}={proc.get(key)!r}, expected {value!r}")
    env = _fill_dotenv(proc, parse_env_file(dotenv_text))
    check_invariants(env)
    return env


def verify_staged_import(tree: str, files: list[str], pinned: dict, pycache_prefix: str) -> None:
    """Import every deployed module from the validation tree and prove it is the pinned source.

    Explicit Refused, never assert: `python -O`/PYTHONOPTIMIZE strips asserts (review 80, N2).
    """
    import hashlib
    import importlib
    import os
    if not pycache_prefix or os.path.realpath(sys.pycache_prefix or "") != os.path.realpath(pycache_prefix):
        raise Refused("validator must run with an empty, dedicated pycache prefix")
    for path in files:
        if path not in pinned:
            raise Refused(f"no pinned hash for {path}")
        source = os.path.join(tree, path)
        with open(source, "rb") as handle:
            raw = handle.read()
        if hashlib.sha256(raw).hexdigest() != pinned[path]:
            raise Refused(f"tree bytes differ from pin: {path}")
        compile(raw, source, "exec")  # the exact pinned bytes must compile
        module = importlib.import_module(path.removesuffix(".py").replace("/", "."))
        if os.path.realpath(getattr(module, "__file__", "") or "") != os.path.realpath(source):
            raise Refused(f"imported elsewhere: {path}")
        cached = module.__spec__.cached if module.__spec__ else None
        if cached is not None and (not os.path.realpath(cached).startswith(os.path.realpath(pycache_prefix))
                                   or os.path.exists(cached)):
            raise Refused(f"bytecode cache used for {path}")


_PRICE_MAX, _TS_MAX, _DURATION_MAX = 1e9, 1e11, 1e7   # USD price, epoch seconds, seconds
# field -> (lower bound "gt0" (> 0) or "ge0" (>= 0), upper bound, required, null allowed).
# Upper bounds are far above any live value but keep settlement arithmetic finite.
_POSITION_NUMERIC_FIELDS = {
    "entry_price": ("gt0", _PRICE_MAX, True, False),
    "tp": ("gt0", _PRICE_MAX, True, False),
    "sl": ("gt0", _PRICE_MAX, True, False),
    "size_usd": ("gt0", 1e6, True, False),
    "entry_ts": ("gt0", _TS_MAX, True, False),
    "timeout_s": ("gt0", _DURATION_MAX, True, False),
    # Key required (the loader migrates a missing one); null is the P0.8+ canonical value.
    "max_hold_s": ("gt0", _DURATION_MAX, True, True),
    "paper_fee_round_trip_fraction": ("ge0", 0.1, True, False),
    "paper_slippage_round_trip_fraction": ("ge0", 0.1, True, False),
    # Optional, but compared or subtracted without a guard on every tick when present.
    "max_seen": ("gt0", _PRICE_MAX, False, False),
    "min_seen": ("gt0", _PRICE_MAX, False, False),
    "_dyn_exit_features_ts": ("ge0", _TS_MAX, False, False),
    "created_at": ("gt0", _TS_MAX, False, False),
    # Optional and read through guards or _safe_float; null tolerated, a value must still be sane.
    "last_price": ("gt0", _PRICE_MAX, False, True),
    "last_price_ts": ("ge0", _TS_MAX, False, True),
    "max_seen_ts": ("ge0", _TS_MAX, False, True),
    "min_seen_ts": ("ge0", _TS_MAX, False, True),
    "dynamic_exit_initial_stop": ("gt0", _PRICE_MAX, False, True),
    "_dyn_exit_atr_bps": ("ge0", 1e6, False, True),
}
_POSITION_LABEL_FIELDS = ("regime", "explore_bucket", "training_bucket", "bucket", "paper_source",
                          "strategy_id", "mode", "source")


def open_positions_count(text: str) -> int:
    """Count open PAPER positions in the executor state file, or refuse (ALLOW_OPEN_POSITIONS path).

    Accepts only the canonical live shape written by paper_trade_executor.open_paper_position():
    a mapping trade_id -> position dict, for which _load_paper_state() fills in or changes no
    economically relevant value (reviews 2026-11-23 A1, R1). Per record:
      - own trade_id equals the key and is a non-empty string without surrounding whitespace
        (the close journal refuses an empty id, so such a position could never close; review R2);
        non-empty symbol;
      - side is BUY or SELL (the loader would default a missing side to BUY);
      - entry_price, entry_ts, size_usd, tp, sl, timeout_s positive finite numbers
        (the loader defaults missing size_usd/tp/sl; tp/sl 0 or null too);
      - tp and sl on the correct side of entry for the direction;
      - max_hold_s key present (else the loader migrates it), value null or positive finite
        (the P0.8+ path stores null, which the loader keeps; at exit the executor reads null as
        PAPER_MAX_POSITION_AGE_S, which is also the timeout_s that path stores);
      - pinned cost snapshot: paper_cost_contract_version 1 and finite nonnegative
        fee/slippage fractions (otherwise the close is blocked or uses current settings);
      - training positions (training_bucket C_WEAK_EV_TRAIN or paper_source training_sampler)
        carry training_bucket and created_at. The loader may still lower their timeout_s to
        min(max_hold_s, timeout_s, PAPER_MAX_POSITION_AGE_S), which is exactly the effective hold
        the executor already uses for training positions, so the exit does not change.
    The whole state must also serialize with json.dumps(allow_nan=False), as the close journal
    and the state writer require (no NaN/Infinity in any field). Every field the tick/close path
    uses directly in arithmetic or comparisons (_POSITION_NUMERIC_FIELDS, incl. max_seen/min_seen,
    timestamps and the dynamic-exit cache) must, when present, be a finite number inside a bounded
    range, and the label fields must be strings (review R4). The bounds keep everything derived at
    settlement (fee * 100, price moves, USD P/L) finite. Non-dict records, metadata keys,
    wrapper {"positions": ...}, legacy lists and scalars are
    Refused (the loader would skip or reshape them). Over-strict refusal of an old but valid state
    only makes the opt-in SKIP. The executor is not imported here (import has runtime side
    effects); tests cross-check this contract against the real loader. An empty mapping counts 0.
    """
    import json
    import math
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise Refused(f"positions state is not JSON: {type(exc).__name__}")
    if not isinstance(data, dict):
        raise Refused(f"positions state must be a mapping, got {type(data).__name__}")
    # The close journal and the state writer serialize whole records with allow_nan=False, so a
    # NaN/Infinity (or an overflowing literal like 1e999) anywhere, even in an optional nested
    # field, would make the position unclosable (review R3).
    try:
        json.dumps(data, allow_nan=False)
    except (ValueError, RecursionError) as exc:
        raise Refused(f"positions state is not strictly serializable: {type(exc).__name__}")

    def number(value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    for key, pos in data.items():
        if key in ("positions", "metadata"):
            raise Refused(f"unsupported positions state key: {key}")
        if not isinstance(pos, dict):
            raise Refused(f"position {key!r} is not an object")
        if pos.get("trade_id") != key:
            raise Refused(f"position {key!r} trade_id mismatch")
        if not key or key != key.strip():
            raise Refused(f"position {key!r} has an empty or padded trade_id")
        symbol = pos.get("symbol")
        if not (isinstance(symbol, str) and symbol.strip()):
            raise Refused(f"position {key!r} has no symbol")
        side = pos.get("side")
        if side not in ("BUY", "SELL"):
            raise Refused(f"position {key!r} has no valid side")
        for field, (low, high, required, nullable) in _POSITION_NUMERIC_FIELDS.items():
            if field not in pos:
                if required:
                    raise Refused(f"position {key!r} has no {field}")
                continue
            value = pos[field]
            if value is None and nullable:
                continue
            if not (number(value) and (value > 0 if low == "gt0" else value >= 0) and value <= high):
                raise Refused(f"position {key!r} has no valid {field}")
        for field in _POSITION_LABEL_FIELDS:
            if pos.get(field) is not None and not isinstance(pos[field], str):
                raise Refused(f"position {key!r} field {field} is not a string")
        entry, tp, sl = pos["entry_price"], pos["tp"], pos["sl"]
        if not (tp > entry > sl if side == "BUY" else tp < entry < sl):
            raise Refused(f"position {key!r} tp/sl not on the {side} side of entry")
        if pos.get("paper_cost_contract_version") != 1:
            raise Refused(f"position {key!r} has no valid pinned cost snapshot")
        if pos.get("training_bucket") == "C_WEAK_EV_TRAIN" or pos.get("paper_source") == "training_sampler":
            if not pos.get("training_bucket") or "created_at" not in pos:
                raise Refused(f"training position {key!r} lacks training_bucket/created_at")
    return len(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    pre = sub.add_parser("pre")
    pre.add_argument("--environment", required=True)
    pre.add_argument("--env-files", required=True)
    pre.add_argument("--vars", required=True)
    pre.add_argument("--dotenv", type=Path, required=True)
    post = sub.add_parser("post")
    post.add_argument("--environ", type=Path, required=True)
    post.add_argument("--vars", required=True)
    post.add_argument("--dotenv", type=Path, required=True)
    positions = sub.add_parser("positions")
    positions.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.mode == "positions":
        try:
            print(open_positions_count(args.file.read_text(encoding="utf-8")))
        except (Refused, OSError, UnicodeDecodeError) as exc:
            print(f"POSITIONS REFUSED: {exc}", file=sys.stderr)
            return 2
        return 0
    dotenv = args.dotenv.read_text(encoding="utf-8") if args.dotenv.exists() else ""
    try:
        if args.mode == "pre":
            preflight(args.environment, args.env_files, args.vars, dotenv)
        else:
            postcheck(args.environ.read_bytes(), args.vars, dotenv)
    except Refused as exc:
        print(f"ENV_CHECK REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"ENV_CHECK {args.mode} ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
