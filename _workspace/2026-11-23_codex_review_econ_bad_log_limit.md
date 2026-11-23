# Review omezení `REJECT_ECON_BAD_ENTRY` — 2026-11-23

**Verdikt: CHANGES_REQUIRED (kód).** Nasazovací krok nebyl předmětem schválení. Zjištěný problém mění jen spolehlivost observability, nikoli obchodní rozhodnutí; příznak je ve výchozím stavu vypnutý.

## Blokující nález R1 — při jediné chybě loggeru se ztratí souhrn potlačených odmítnutí

`EconBadRejectLogLimiter.observe()` sestaví souhrn a ještě před jeho zápisem vynuluje počty starého okna (`src/services/realtime_decision_engine.py:797–805`). `_econ_bad_should_emit_reject_detail()` pak zkusí `log.warning(summary)`, ale výjimku jen spolkne (`:829–835`). Při přechodné chybě loggeru se staré potlačené počty už nedají z limiteru získat, a pozdější úspěšný zápis je neobsahuje. To odporuje požadavku na přesné souhrny.

**Nezávislá reprodukce:** Přímo ze současného zdroje jsem přes AST spustil pouze `_econ_bad_reject_category`, `EconBadRejectLogLimiter`, `_econ_bad_reject_log_limit_enabled` a `_econ_bad_should_emit_reject_detail` v izolovaných globálech, bez importu RDE a bez dotyku runtime DB. Tři odmítnutí `weak_ev` v prvním okně daly emit `[True, False, False]`. Po posunu času o 61 s jednorázově selhal `log.warning(summary)`. Limiter pak měl už jen nové okno `{'weak_ev': (1, 0)}` a žádný souhrn se nezapsal. Po další minutě úspěšný logger zapsal pouze `rejects=1 suppressed_details=0`; původní `rejects=3 suppressed_details=2` zmizely natrvalo.

Dosavadní `test_internal_or_logger_errors_never_hide_details_or_raise` (`tests/test_econ_bad_reject_log_limit.py:219–236`) ověřuje jen to, že při chybě nevznikne výjimka a aktuální detail se vypíše. Neověřuje zachování starého souhrnu po obnovení loggeru. Oprava má uchovat nezapsaný agregát v omezeném stavu a po obnovení jej vydat, případně použít jiný prokazatelně spolehlivý fallback. Přidej test pro jednorázovou chybu, následný úspěch a přesný počet obou oken; samostatně otestuj opakovanou chybu bez neomezeného růstu paměti a bez změny `return None`/`track_blocked`. Počty nepovažuj za uložené už pouhým sestavením řádky.

## Ostatní kontrolované vlastnosti

- Přesun z odmítací větve do `_econ_bad_reject_outputs()` zachovává pořadí `_update_econ_bad_near_miss → trace → track_blocked → print → flush → emit`, argumenty `score=_score_adj`, `coherence=_coh`, `ctx=_probe_ctx`, `override=override` a následující `return None` (`realtime_decision_engine.py:840–870, :3943–3952`). Nový výběr detailu je mezi near-miss a trace; při vypnutém příznaku vrací `True` a detaily se zapisují jako dřív.
- Při zapnutém příznaku `emit_detail=False` vypíná pouze řádku `[ECON_BAD_ENTRY_RETURN_TRACE]` (`:690–723`) a `print` (`:863–864`). Zbytek `_trace_econ_bad_entry_return()` včetně interního resolveru a invariantu `[ECON_BAD_READY_BUT_REJECTED]` zůstává před i za podmínkou; trace `TAKE` má výchozí `emit_detail=True`.
- Kategorie bere nejvýš 40 znaků `[a-z_]`; stav je chráněn zámkem a omezen na 16 pojmenovaných kategorií plus `other` (`:766–817`). Běžné okno a počty při úspěšném loggeru testy ověřují. Zpoždění posledního souhrnu do dalšího odmítnutí je výslovně zdokumentované; při konci procesu může poslední okno zůstat nevydané. To je neblokující známá mez pro tento lokální krok.
- Vložení helperu do RDE je v současné architektuře přiměřené: nasazovací nástroj instaluje připnutý jednotlivý soubor a další nový runtime modul by vyžadoval širší deploy. Produkční shoda RDE bajtů je `NOT_VERIFIED`; lokální preimage má SHA-256 `4a46037bf5d21c039ba374773b055534dd701ae814f26cf6019cb8e07edf11ae`, současný soubor `9ea893265888e06335bb44bb7195e1eeacc1688027506ec71ec307df77bce698`. Před nasazením je nutný artefakt z živé serverové preimage a samostatné review nasazení.

## Ověření

- Povolený cílený běh: `tests/test_econ_bad_reject_log_limit.py` a dva určené případy z `tests/test_v10_13u_patches.py`: **25 PASS, 1 deprecation warning**. První spuštění uvnitř sandboxu skončilo `PermissionError` při vytváření dočasného adresáře conftestu; stejný povolený příkaz mimo sandbox prošel. Jiné testy jsem nespouštěl.
- `_workspace/cache_isolation_repair_20261118/protected_sha.py`: snapshot před testy a následná kontrola **PROTECTED_SAME** pro šest chráněných souborů a oba runtime adresáře. Reproduktor R1 spustil jen AST výřez a runtime soubory neimportoval.
- `_workspace/econ_bad_journal_20261123/mutation_results.json` uvádí 10/10 zachycených mutací včetně per-reject výpisu a vynechání `track_blocked`; mutační skript jsem znovu nespouštěl. Současná sada nepokrývá ztrátu souhrnu při přechodné chybě loggeru.
- Neprováděl jsem SSH, deploy, restart, Firebase zápis, commit ani změnu produkčního kódu. Tato revize vytvořila pouze tento report a soubor se snapshotem chráněných hashů.

**Po opravě R1:** cílený regresní test, stejný povolený běh a nové nezávislé review. Schválení kódu nebude samo o sobě schválením nasazení ani důkazem delší retence journalu.
