# External Audit Verdict — WR>50 Single-Path Refactor (2026-09-15)

**Vydáno proti:** `EXTERNAL_AUDIT_WR50_COMPLETE_PACKAGE_2026-09-15.md`
**Spot-check (orchestrující relace):** Q1's citace v `realtime_decision_engine.py`
ověřena přímo proti zdrojovému kódu na `wr50/canonical-single-path-phase2` —
`sampler_result.get("allowed")` je skutečně reálné admission rozhodnutí PŘED
voláním `canonical_admit()`. Verdikt je věrohodný, ne halucinace.

## Nezávislý verdikt

Větev `wr50/canonical-single-path-phase2` **není v současném stavu bezpečná
k merge do main.** Release gate je technicky opravený, ale kontroluje jen
čistotu cest a přítomnost artefaktů — ne správnost architektury, metrik ani
produkčního chování.

**REAL trading zůstává absolutní NO-GO.**

### Q1 — Je `canonical_admit()` skutečně jediná cesta?

**PARTIAL, nikoli plně SINGLE PATH.** Wrapper (`paper_trade_executor.py:1589–1650`)
skutečně deleguje a normalizuje výsledek, ale před ním zůstávají reálná
rozhodovací místa: RDE (`realtime_decision_engine.py:3028–3066, 4112–4150,
4197–4235`), P0 gate/evidence (`paper_trade_executor.py:4790–4845`),
exploration (`paper_exploration.py:709–725`), P0.8 pipeline
(`p0_8_plus_live_pipeline.py:233–312`). Wrapper navíc sám dopočítává
`effective_hold_s`, není čistý passthrough. „Jeden wrapper" ≠ „jedno
rozhodovací místo."

### Q2 — Je VOID oprava metodologicky správná?

**Převážně sound, evidence neúplná.** `TradeOutcome.VOID` odlišen od `FLAT`,
`compute_win_rate()` vylučuje jen VOID, `_qualified_window_metrics()`
pokrývá legacy i nový marker, anti-gaming test existuje. Chybí: kombinovaný
test VOID+legacy TIMEOUT_NO_PRICE v jednom okně; důkaz že všechny klientské
cesty čtou stejné pole; jistota že VOID nikdy neovlivní P&L součty.

### Q3 — Stačí ruční hashování po testech?

**Nestačí.** Dokázalo zachytit dva incidenty (řádek v produkční DB, smazaný
`paper_open_positions.json`), ale to dokazuje jen že disciplína fungovala,
ne že systém byl bezpečný. `PYTEST_CURRENT_TEST` guard je obejitelný
subprocessy, multiprocessingem, vymazáním environmentu, hardcoded
absolutními cestami. Nutný permanentní, strukturální integrity guard, ne
spoléhání na operátora.

### Q4 — Priorita prací

1. **P0/P1 produkční bezpečnost hostu** (dashboard `0.0.0.0:5001` bez
   efektivní auth jako root, disk ~96 %) — **NAD** dokončením WR50.
2. Dokončit sink isolation sweep (24 pre-existing failures, ne všechny
   hardcoded cesty pokryty).
3. Odstranit/prokázat absenci pre-wrapper admission rozhodnutí.
4. Stabilizace testů a attribution persistence.
5. Teprve pak Phase 4 shadow kohorta.

### Q5 — Podmínky pro budoucí WR>50 tvrzení

≥500 kvalifikovaných post-fix obchodů; ≥250/zdroj při srovnání zdrojů;
předem fixovaný `code_version`/`config_version`/`segment_key`/holdout;
Wilson 95% CI dolní mez >50 %; bootstrap 95% CI P&L dolní mez >0; žádné
NULL/UNKNOWN/duplicate/chybějící exit rows; kompletní exit taxonomie;
jeden canonical writer pro všechny zdroje. **Historické 99/118 a 57/221
jsou stale/nehomogenní a NESMÍ sloužit jako důkaz.**

## Finální doporučení

**Merge: NE — podmíněně zamítnuto.** Pět konkrétních podmínek před dalším
posouzením: (1) dokončit sink isolation + automatický integrity guard,
(2) odstranit/prokázat absenci všech pre-wrapper admission decisions,
(3) doplnit mixed VOID/legacy test + client-field stability guard,
(4) zopakovat R3-F baseline měření proti skutečnému `main`, ne proti
mezilehlému commitu, (5) nechat znovu posoudit nezávislým reviewerem.

**Deploy: ABSOLUTNÍ NO-GO.**

## Kontext — trojí nezávislá shoda

Tento verdikt je třetí nezávislý, disinterested check téhož dne (2026-09-15),
který dospěl ke stejné opatrné odpovědi:
1. `CLAUDE_EXTERNAL_AUDIT_PACKAGE_RECONCILIATION_2026-09-15.md` — našel a
   opravil skutečný bug v `release_gate.py` (nikdy necommitnutý, `return False`
   natvrdo).
2. `CLAUDE_MERGE_DECISION_2026-09-15.md` — odmítl mergovat, dokud neproběhne
   přesně tahle revize.
3. Tento dokument — provedl tu revizi, došel k `NE`.

Žádná z těchto tří relací neměla motivaci větev schválit; všechny nezávisle
skončily u opatrnosti. To je silný signál, že opatrnost je správná odpověď,
ne jen shoda okolností.
