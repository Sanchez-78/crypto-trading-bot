# Re-review `ALLOW_OPEN_POSITIONS=1` po R3 — 2026-11-23

**Verdikt: CHANGES_REQUIRED** pro další použití opt-in. R3 samotné je opravené: `open_positions_count()` nyní odmítne nekonečná čísla již přítomná v načteném stavu, včetně vnořených polí. Zůstávají však dvě nezávislé třídy čitelných stavů, které validátor přijme a obnovený executor neumí bezpečně zpracovat. Žádná změna na serveru neproběhla.

## Nálezy

### R4a — P1: konečné vstupy přetečou až při výpočtu P/L

`deploy/research_eval/deploy_env_check.py:190–225` ověřuje u uložených nákladových frakcí pouze konečnost a nezápornost. Pozice stejného jinak kanonického tvaru jako testovací `_pos()` s `paper_fee_round_trip_fraction=1e308` projde (`open_positions_count(...) == 1`). Při uzavírání ale `paper_trade_executor.py:1287–1349` násobí tuto hodnotu stem (`fee_cost_pct = fee_pct * 100`), což dá `inf`. `close_paper_position()` vloží výsledek do `closed_trade` (`paper_trade_executor.py:3589–3690`) a `PaperCloseJournal.prepare()` jej serializuje s `allow_nan=False` (`paper_close_journal.py`), takže příprava uzavření selže. Stejný problém mohou způsobit jiné extrémní konečné hodnoty výpočtem hrubého výnosu či dolarového P/L. Validace původního JSON tedy sama o sobě nedokazuje serializovatelnost **odvozeného** výsledku.

Reprodukce `_workspace/allow_open_r3_overflow_repro.py` vytiskla `cost_state_accepted 1`, `fee_cost_pct_finite False` a `close_record_serializable False ValueError`. Reprodukce používá jen syntetický slovník a importuje pouze deploy validátor; výpočet odpovídá uvedené větvi executoru. Skutečné volání `close_paper_position()` nad tímto stavem jsem nespouštěl (`NOT_RUN`), protože by vyžadovalo izolaci jeho runtime závislostí. Kódová cesta k neúspěchu žurnálu je doložena čtením.

### R4b — P1: čitelný stav může zastavit tickový výstupní cyklus

Validátor nekontroluje volitelné `max_seen` a `min_seen`. Jinak platná pozice s `max_seen="broken"` projde (`open_positions_count(...) == 1`) a `_normalize_position_for_loading()` tuto hodnotu nemění (`paper_trade_executor.py:861–916`). `update_paper_positions()` ji potom přímo porovnává s aktuální číselnou cenou (`paper_trade_executor.py:2918–2923`), což vyhodí `TypeError` ještě před kontrolou TP/SL a timeoutu. V dané funkci kolem iterace není lokální obsluha této výjimky. Tím může vadný záznam zastavit aktualizaci i dalších otevřených pozic v ticku.

Stejná reprodukce vytiskla `extreme_state_accepted 1` a `tick_update_comparison_safe False TypeError`. Pro další použití opt-in je potřeba přinejmenším validovat přítomné `max_seen`/`min_seen` jako konečná kladná čísla; před schválením ověřit, zda mají jiná pole v tickové či close cestě stejně přímé operace bez ochrany. Nejde o návrh měnit obchodní parametry ani ekonomiku živého bota.

## Ověření R3 a rozsah

- Diff `3b53f3e..18cf49c`: změněn jen `deploy_env_check.py`, jeho test a dokumentace; `deploy_bot_files.sh` beze změny.
- Cílené testy podle zadání: **109 passed, 9 skipped** (`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py`). Přeskočené jsou bashové případy v tomto Windows prostředí; autor uvádí 118 průchodů ve svém prostředí, to jsem nezávisle neověřil.
- `protected_sha.py` před a po testech i reprodukci: **PROTECTED_SAME**. Předběžný otisk je v `_workspace/2026-11-23_r3_protected_before.json`.
- Bez SSH, nasazení, restartu, commitu a pushnutí. Produkční použitelnost `ALLOW_OPEN_POSITIONS=1` zůstává **NOT_VERIFIED** do opravy a nového review.

## Očekávaná oprava k re-review

Rozšířit preflight o kontrolu polí, s nimiž executor pracuje přímo (`max_seen`, `min_seen` a další zjištěná pole), a o kontrolu konečnosti odvozených settlement hodnot pro realistické ceny výstupu. Nové cílené testy mají na nynější implementaci selhat a po opravě projít. Při odmítnutí musí nasazovací skript skončit `SKIPPED` před prvním zápisem. Není nutné přidávat obecný druhý executor do deploy nástroje; stačí malá čistá validace jeho skutečného datového kontraktu.
