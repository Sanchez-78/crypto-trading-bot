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
STRICT_BOOL_KEYS = ("PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED",)
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
    args = parser.parse_args(argv)
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
