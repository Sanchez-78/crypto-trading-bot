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

# install_staged <stage root> <app root> <FILES>: install only from the stage
install_staged() {
  local stage="$1" app="$2" f
  for f in $3; do install -m 644 "$stage/$f" "$app/$f"; done
}
