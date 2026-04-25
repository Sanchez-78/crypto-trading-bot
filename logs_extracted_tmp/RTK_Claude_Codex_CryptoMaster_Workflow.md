# RTK Workflow pro Claude Code + Codex - CryptoMaster

Ucel: pouzivat RTK jako filtr pro dlouhe terminalove vystupy, aby Claude/Codex dostaval mensi a prehlednejsi kontext pri debugovani, review a analyze logu.

---

## 1. Aktualni stav na tomto stroji

RTK je na tomto PC nainstalovane a overene.

- `rtk --version` -> funkcni
- Claude Code -> globalni RTK hook je nakonfigurovany
- Codex -> globalni `AGENTS.md + RTK.md` integrace je nakonfigurovana
- `rtk gain`, `rtk git status`, `rtk read` -> funkcni

Globalni soubory:

- Claude: `C:\Users\Ja\.claude\RTK.md`
- Codex: `C:\codex\RTK.md`

---

## 2. Základní pravidlo

Pouzivej RTK vsude, kde muze byt vystup dlouhy nebo hlucny:

- `git status`
- `git diff`
- `pytest`
- `ruff check .`
- `grep` / `rg`
- `cat` / `Get-Content`
- logy

Typicke priklady:

```powershell
rtk git status
rtk git diff
rtk pytest
rtk ruff check .
rtk grep "RDE" .
rtk read src\services\realtime_decision_engine.py
rtk log logs\app.log
```

---

## 3. Claude Code workflow

Na tomto stroji je pro Claude Code aktivni globalni hook:

- hook: `rtk hook claude`
- `settings.json` je patchnuty
- `~/.claude/CLAUDE.md` odkazuje na `RTK.md`

Prakticky dopad:

- bezne shell prikazy muze Claude spoustet normalne
- RTK hook ma vystup komprimovat automaticky
- meta prikazy pouzivej primo pres `rtk`

Meta prikazy:

```powershell
rtk gain
rtk gain --history
rtk discover
rtk proxy pytest -q
```

Kdyz si nejsi jisty, je porad bezpecne pouzit explicitni `rtk ...`.

---

## 4. Codex workflow

Codex je na tomto stroji nakonfigurovany globalne pres:

- `C:\codex\AGENTS.md`
- `C:\codex\RTK.md`

Pro Codex pouzivej explicitni `rtk` prefix. To je aktualne nejcistsi a nejpredvidatelnejsi rezim.

Pouzivej:

```powershell
rtk git status
rtk git diff
rtk pytest
rtk ruff check .
rtk grep "PATTERN" .
rtk read PATH
rtk log PATH
```

Nepouzivej zbytecne surove dlouhe vystupy, pokud RTK umi stejny prikaz zkomprimovat.

---

## 5. Doporuceny debug workflow v CryptoMaster

Otevri projekt:

```powershell
cd C:\Projects\CryptoMaster_srv
```

Zakladni kontrola:

```powershell
rtk git status
rtk git diff
rtk pytest
```

Lint:

```powershell
rtk ruff check .
```

Cteni kodu:

```powershell
rtk read src\services\trade_executor.py
rtk read src\services\realtime_decision_engine.py
rtk grep "firebase" src
```

Logy:

```powershell
rtk log logs\app.log
```

Serverove logy:

```bash
journalctl -u cryptomaster -n 500 --no-pager | rtk log
```

---

## 6. RTK snapshot pro lokalni debug

Vytvor soubor `rtk_snapshot.ps1`:

```powershell
Write-Host "=== RTK CryptoMaster Snapshot ==="

$OutDir = "rtk_out"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "1/5 git status"
rtk git status > "$OutDir\01_git_status.txt"

Write-Host "2/5 git diff"
rtk git diff > "$OutDir\02_git_diff.txt"

Write-Host "3/5 pytest"
rtk pytest > "$OutDir\03_pytest.txt"

Write-Host "4/5 ruff"
rtk ruff check . > "$OutDir\04_ruff.txt"

Write-Host "5/5 search"
rtk grep "RDE" . > "$OutDir\05_rde_search.txt"

Write-Host ""
Write-Host "Hotovo. Vystupy jsou v:"
Write-Host "$OutDir"
```

Spusteni:

```powershell
powershell -ExecutionPolicy Bypass -File .\rtk_snapshot.ps1
```

---

## 7. Prompt doplnek pro Claude Code

Pouzij jako projektovy doplnek, ne jako nahradu globalni RTK konfigurace:

```text
Use RTK-aware shell usage in this repository.

Prefer RTK for long or noisy outputs:
- git status
- git diff
- pytest
- ruff check .
- grep / rg
- file reads
- logs

If the Claude RTK hook rewrites the command automatically, keep using the compressed output.
If needed, call RTK explicitly with:
- rtk git diff
- rtk pytest
- rtk ruff check .
- rtk grep "PATTERN" .
- rtk read PATH
- rtk log PATH

Focus on:
- broken files
- failing tests
- suspicious diffs
- runtime errors
- risky trading logic changes
- Firebase read/write risks
- deployment risks
```

---

## 8. Prompt doplnek pro Codex

```text
Use RTK explicitly for shell commands with potentially long output.

Preferred commands:
rtk git status
rtk git diff
rtk pytest
rtk ruff check .
rtk grep "PATTERN" .
rtk read PATH
rtk log PATH

Analyze the compressed output before editing.
Do not rewrite large parts of the project.
Make minimal safe patches.
Preserve existing CryptoMaster functionality, metrics, Firebase integration and live trading flow.
After edits, summarize:
- what changed
- why
- how verified
- what remains risky
```

---

## 9. Git workflow

Pred commitem:

```powershell
rtk git status
rtk git diff
rtk pytest
rtk ruff check .
```

Po oprave necommituj slepe vsechno:

```powershell
git add path\to\changed_file.py
git add path\to\test_file.py
git commit -m "fix: safe incremental patch"
git push
```

Nepouzivej automaticky `git add .`, pokud je worktree spinavy nebo obsahuje logy, snapshoty a experimenty.

---

## 10. Nejkratsi denni rutina

```powershell
cd C:\Projects\CryptoMaster_srv
rtk git status
rtk git diff
rtk pytest
```

Kdyz bot pada:

```powershell
rtk log logs\app.log
```

Kdyz hledas problem v RDE:

```powershell
rtk grep "RDE" .
rtk read src\services\realtime_decision_engine.py
```

---

## 11. Overeni po instalaci

Claude Code:

```powershell
rtk init --show -g
```

Codex:

```powershell
rtk init --show --codex -g
```

Obecne:

```powershell
rtk --version
rtk gain
rtk git status
```
