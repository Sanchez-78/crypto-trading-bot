#!/usr/bin/env pwsh
<#
.SYNOPSIS
    RTK CryptoMaster Diagnostic Snapshot

.DESCRIPTION
    Captures compressed versions of key project diagnostics:
    - Git status and diffs
    - Test results
    - Linting issues
    - Code searches for critical patterns

.EXAMPLE
    .\rtk_snapshot.ps1
    Outputs to rtk_out\ directory
#>

Write-Host "=== RTK CryptoMaster Snapshot ===" -ForegroundColor Cyan
Write-Host "Saving compressed diagnostics to rtk_out\"
Write-Host ""

$OutDir = "rtk_out"
if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
}

# 1. Git Status
Write-Host "[1/8] Git status..." -ForegroundColor Yellow
rtk git status > "$OutDir\01_git_status.txt" 2>&1
Write-Host "      -> $OutDir\01_git_status.txt"

# 2. Git Diff
Write-Host "[2/8] Git diff..." -ForegroundColor Yellow
rtk git diff > "$OutDir\02_git_diff.txt" 2>&1
Write-Host "      -> $OutDir\02_git_diff.txt"

# 3. pytest
Write-Host "[3/8] Test results..." -ForegroundColor Yellow
rtk pytest > "$OutDir\03_pytest.txt" 2>&1
Write-Host "      -> $OutDir\03_pytest.txt"

# 4. Ruff Lint
Write-Host "[4/8] Linting check..." -ForegroundColor Yellow
rtk ruff check . > "$OutDir\04_ruff.txt" 2>&1
Write-Host "      -> $OutDir\04_ruff.txt"

# 5. Harvest Logic Search
Write-Host "[5/8] Harvest logic search..." -ForegroundColor Yellow
rtk grep "PARTIAL_TP\|SCRATCH_EXIT\|harvest" src > "$OutDir\05_harvest_search.txt" 2>&1
Write-Host "      -> $OutDir\05_harvest_search.txt"

# 6. Canonical State Search
Write-Host "[6/8] Canonical state search..." -ForegroundColor Yellow
rtk grep "canonical_state\|get_authoritative" src > "$OutDir\06_canonical_search.txt" 2>&1
Write-Host "      -> $OutDir\06_canonical_search.txt"

# 7. Firebase Quota Search
Write-Host "[7/8] Firebase quota search..." -ForegroundColor Yellow
rtk grep "_record_read\|_record_write\|quota" src\services\firebase_client.py > "$OutDir\07_firebase_quota.txt" 2>&1
Write-Host "      -> $OutDir\07_firebase_quota.txt"

# 8. Token Savings Report
Write-Host "[8/8] Token savings report..." -ForegroundColor Yellow
rtk gain > "$OutDir\08_token_gains.txt" 2>&1
Write-Host "      -> $OutDir\08_token_gains.txt"

Write-Host ""
Write-Host "=== Snapshot Complete ===" -ForegroundColor Green
Write-Host "All outputs saved to: $OutDir\"
Write-Host ""
Write-Host "Summary files:"
Get-ChildItem $OutDir | Format-Table Name, @{Name="Size";Expression={$_.Length}} -AutoSize

Write-Host ""
Write-Host "Quick View:"
Write-Host "  cat $OutDir\01_git_status.txt"
Write-Host "  cat $OutDir\02_git_diff.txt"
Write-Host "  cat $OutDir\03_pytest.txt"
