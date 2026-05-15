#!/bin/bash

# P1.1AL: Regression test for audit counter normalization

set -e

# Define the helper functions (copied from audit script)
to_int() {
    local v
    v="$(printf '%s\n' "$1" | head -n1 | tr -dc '0-9')"
    [ -n "$v" ] && echo "$v" || echo 0
}

test_count=0
pass_count=0

# Helper to run a test
run_test() {
    local name="$1"
    local expected="$2"
    local value="$3"
    test_count=$((test_count+1))

    local result
    result=$(to_int "$value")

    if [ "$result" = "$expected" ]; then
        echo "✓ $name"
        pass_count=$((pass_count+1))
    else
        echo "✗ $name (got '$result', expected '$expected')"
    fi
}

# Test 1: to_int with multiline input (the bug case)
run_test "to_int multiline 0" "0" "$(printf '0\n0')"

# Test 2: to_int with single line
run_test "to_int single 3" "3" "3"

# Test 3: to_int with leading/trailing whitespace
run_test "to_int whitespace" "5" "  5  "

# Test 4: to_int with non-numeric (should become 0)
run_test "to_int non-numeric" "0" "abc"

# Test 5: to_int with mixed (should extract digits)
run_test "to_int mixed" "42" "prefix42suffix"

# Test 6: to_int with empty string (should become 0)
run_test "to_int empty" "0" ""

# Test 7: to_int with large number
run_test "to_int large" "999999" "999999"

# Test 8: to_int with triple newline (stress test)
run_test "to_int triple newline" "0" "$(printf '0\n0\n0')"

echo ""
echo "Results: $pass_count/$test_count tests passed"

if [ "$pass_count" -eq "$test_count" ]; then
    exit 0
else
    exit 1
fi
