#!/bin/bash
# Pinned-bytes helpers sourced by deploy_bot_files.sh (review 78, R1).
# The bytes that are validated are the bytes that are installed: files are copied once from
# the mutable source into a private stage, every check runs on the stage, the service tree is
# installed from the stage, and the installed bytes are compared with EXPECTED_SHA256 itself.

# expected_sha <file> <EXPECTED_SHA256 list> -> prints the pinned hash or nothing
expected_sha() {
  local f="$1" entry
  for entry in $2; do [ "${entry%%=*}" = "$f" ] && { printf '%s' "${entry#*=}"; return 0; }; done
  return 0
}

# stage_files <source dir (flat)> <stage root> <FILES>: one copy, private mode
stage_files() {
  local src="$1" stage="$2" f
  for f in $3; do
    mkdir -p "$stage/$(dirname "$f")"
    install -m 600 "$src/$(basename "$f")" "$stage/$f"
  done
}

# verify_pinned <root> <FILES> <EXPECTED_SHA256>: every root/f must match its pinned hash
verify_pinned() {
  local root="$1" f want got
  for f in $2; do
    want="$(expected_sha "$f" "$3")"
    [ -n "$want" ] || { echo "no EXPECTED_SHA256 for $f" >&2; return 2; }
    got="$(sha256sum < "$root/$f" | cut -d' ' -f1)"
    [ "$got" = "$want" ] || { echo "hash mismatch for $root/$f: $got != $want" >&2; return 2; }
  done
}

# build_tree <app root> <stage root> <tree> <FILES>: validation tree = the app's src without any
# bytecode, overlaid with the pinned files. python -B only stops *writing* .pyc; a copied stale
# .pyc (same mtime/size, or unchecked-hash) would otherwise be imported instead of the pinned
# source (review 79, N1). The live __pycache__ under the app is never touched here.
build_tree() {
  local app="$1" stage="$2" tree="$3" f
  mkdir -p "$tree"
  cp -r "$app/src" "$tree/src"
  find "$tree" -name __pycache__ -type d -prune -exec rm -rf {} +
  find "$tree" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
  for f in $4; do install -m 600 "$stage/$f" "$tree/$f"; done
  if [ -n "$(find "$tree" \( -name __pycache__ -o -name '*.pyc' -o -name '*.pyo' \) -print -quit)" ]; then
    echo "bytecode left in validation tree" >&2; return 2
  fi
}

# install_staged <stage root> <app root> <FILES>: install only from the stage
install_staged() {
  local stage="$1" app="$2" f
  for f in $3; do install -m 644 "$stage/$f" "$app/$f"; done
}
