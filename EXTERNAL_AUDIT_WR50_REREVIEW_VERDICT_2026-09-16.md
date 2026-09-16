# WR>50 Re-review Verdict (2026-09-16) — MERGE STILL REJECTED

**Proti:** commity `6caa494`, `123c539`, `4e56031`, `c4cbdfd` na
`wr50/canonical-single-path-phase2`, reagující na
`EXTERNAL_AUDIT_WR50_VERDICT_2026-09-15.md`.

**Metoda:** oddělené detached worktrees na `c4cbdfd` a `main`,
`FORCE_LOCAL_STORAGE=1`, každá mutace vrácena, worktrees odstraněny po
použití. Repo nedotčeno. Žádný merge/push/deploy/SSH.

**Sebekorekce orchestrující session:** předchozí spot-check (přímé čtení
RDE diffu a `gate=` handleru) byl reálný, ale **neúplný** — ověřil jen
místa už známá z prvního auditu, nezachytil, že jiná citovaná místa byla
z "opraveného" seznamu tiše vypuštěna. Přijímám tuto korekci a beru ji
vážně.

## Q1 — FAIL NA PODSTATĚ

1. **3 ze 7 "opravených" míst předávají gate, který je prokazatelně vždy
   `allowed=True`** (mrtvý kód) — odmítnutí kandidáti tam pořád nezanechají
   žádný záznam.
2. **2 z původních 5 auditem citovaných míst stále nemají `gate=` vůbec**:
   `paper_exploration.py:714`, `p0_8_plus_live_pipeline.py:295`. AST
   inventář byl strukturálně slepý vůči guard-clause/early-return vzoru —
   tiše vypustil 2 reálná produkční místa, zatímco našel 2 jiná nová.
   "7 míst, o 2 víc než audit" byla **jiná množina**, ne nadmnožina.
3. Strukturální test vůbec nekontroluje, že předaný `gate=` je TA SAMÁ
   hodnota, co branch hlídala — `gate={"allowed": True}` by prošel stejně.

## Item 4 — FAIL NA ROZSAHU

Směr opravy je správný (ověřeno mutačně), ale porovnání pokrývalo jen ~2
soubory, ne celé repo. Plné srovnání (122 souborů, obě větve) našlo
**7 skutečných regresí** na branchi, žádná na main:
- 2 bezpečnostně relevantní testy (fill se booká podle ask/bid, ne podle
  candle close) — **tiše rozbité od úplně prvního commitu větve**
  (`2d68876`), přes 3 kola vlastní revize a 1 externí audit, nikdy
  nezachyceno až doteď.
- 1 test "paper, ne live" routing — nikdy se nespustí.
- 1 test OBSERVE fail-closed — odhaluje díru v pořadí importů přesně v tom
  mechanismu, co měl tento problém řešit.
- 3 testy timeout-close persistence — nová výjimková cesta jen na branchi.

## Nový nález, nikým dřív nevlajkovaný

Branch bandluje **dvě reálné změny produkčního chování** (corrupt JSON teď
vyhazuje výjimku místo tichého prázdného stavu; timeout-close teď vyhazuje
při selhání persistence) — rámováno jako "už hotová oprava", ne jako delta
téhle větve. Testovací soubor citovaný jako autoritativní kontrakt pro
jednu z nich je **netrackovaný v gitu na obou větvích** — nikdy neběžel v
žádném baseline srovnání.

## Q2 — PASS (ověřeno mutačně)

M7 i client-field guard skutečně zabíjí. Menší zbytek: guard pokrývá jen
browser klienta, ne Android appku (jiné repo).

## Q3 — PASS s reálnou mezerou

Backstop skutečně funguje (11 prošlo, přesně ten bypass scénář z auditu
zachycen). Ale: `runtime/v5_quota_usage.sqlite`,
`src/runtime/v5_quota_usage.sqlite`, `runtime/v5_trade_outbox.sqlite`
nejsou sledované vůbec — nalezeno, protože vlastní test-běh recenzenta tyto
soubory tiše změnil/smazal a nespustil se žádný banner. **Stejná třída
incidentu, co Q3 řešil, se pořád děje — jiným souborům.**

## Co by vedlo ke schválení (čtyři konkrétní body)

1. Doplnit `gate=` na `paper_exploration.py:714` a
   `p0_8_plus_live_pipeline.py:295`; rozšířit strukturální test, aby viděl
   guard-clause vzory a ověřoval, že `gate=` je ta samá výrazová hodnota.
2. Opravit 7 regresí (triviální aktualizace mock cílů); přeběhnout baseline
   na celém repu, ne dvou souborech, a u čísla uvádět rozsah.
3. Rozšířit integrity watch-list o 3 nově nalezené sink soubory; zapojit
   guard do dvou sinků, co volají jen `resolve_dir()`.
4. Explicitně zveřejnit ty dvě bundlované změny chování; přestat citovat
   netrackovaný test.

**Q4 (host security) a Q5 (WR evidence bar) zůstávají beze změny, správně
pořád otevřené. WR>50 zůstává `NOT_ACHIEVED`.**

Recenzent: "Round 4 is serious, largely honest work... But Q1 resolved the
SHAPE of the finding while leaving the PROPERTY undelivered at half the
call-sites... That is the same 'one wrapper is not one decision point' gap,
one level down. The first reviewer was right to reject, and these fixes do
not yet clear it."
