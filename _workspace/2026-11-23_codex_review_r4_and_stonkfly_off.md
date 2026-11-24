# Nezávislé review R4 a návrhu vypnutí Stonkfly — 2026-11-24

Rozsah: lokální audit kódu a syntetická reprodukce. Bez SSH, nasazení, commitu,
změny konfigurace nebo runtime dat. Novější pokyn operátora výslovně odmítá
vypnutí Stonkfly a žádá jeho přepracování v rámci procesu rozhodování a učení.

## A — R4 `ALLOW_OPEN_POSITIONS`: CHANGES_REQUIRED

**P1: validátor přijme pozici, jejíž P/L přeteče.**
`deploy/research_eval/deploy_env_check.py:155–180,250–268` vyžaduje pouze
`entry_price > 0` a samostatné horní meze cen. Pozice BUY s
`entry_price=1e-300`, `tp=1e9`, `sl=5e-301`, jinak platnými poli projde
`open_positions_count()`. V `src/services/paper_trade_executor.py:1322–1326`
vznikne `(tp-entry_price)/entry_price = inf`; nemůže být serializována do
close journalu s `allow_nan=False`. Test mezí v zadání zkouší jednotlivé horní
meze, nikoli extrémní poměr cen. Důkaz: `_workspace/2026-11-24_r4_repro.py`
vypisuje `tiny_price_accepted 1`, `gross_return_finite False`.

**P1: validátor přijme vstupní čas v budoucnosti.**
`entry_ts=1e11` projde horní mezí `1e11`; v
`src/services/paper_trade_executor.py:3640` je však close odmítnut, pokud
`ts < entry_ts`. Pro aktuální čas se tedy záznam nedá uzavřít. Reproduktor
vypisuje `future_entry_accepted 1`, `close_time_valid_now False`.
Před restartem s otevřenými pozicemi musí validátor ověřit čas vůči
aktuálnímu času s výslovně omezenou tolerancí clock skew, nikoli jen rozsah.

**P2: tabulka polí není úplná pro případ podvrženého runtime cache objektu.**
`_dyn_exit_trend_features` není v seznamu; obyčejný JSON objekt ve vstupním
souboru je přijat, ač `paper_trade_executor.py:2781–2837` očekává runtime
features pro dynamický exit. Běžný writer tuto cache při ukládání odstraňuje
(`:795`), takže jde o nekanonický/podvržený stav a dopad na živou cestu nebyl
prokázán. Konzervativní validátor by přítomnost tohoto klíče odmítl.

Oprava A: test, který na předchozím kódu selže, musí prokázat odmítnutí
extrémního poměru cen a budoucího `entry_ts`; hranice přípustného poměru a
časové tolerance musí odpovídat skutečným vstupním invariantům executoru.
Pak znovu spusťte test skutečného loaderu a vypořádání v `tmp_path`.
Samotné oprávnění `ALLOW_OPEN_POSITIONS=1` nadále nepoužívat.

## B — vypnutí Stonkfly: SUPERSEDED / NENASAZOVAT

Původní zadání vyžaduje verdikt k nasazení tří hodnot `false`, ale tento
nasazovací cíl operátor 2026-11-24 výslovně změnil: Stonkfly se nemá vypnout.
Proto postup `LABEL=stonkfly-off` ani jeho rollback neschvaluji jako aktuální
akci. Kód podpory config-only deploy a striktních booleanů jsem v tomto kole
neschvaloval pro jiné použití; žádný krok na serveru nebyl proveden. Potřebný
směr je diagnostika a měřitelná shadow integrace, nikoli obchodování všech
konstantních BUY signálů.

## Ověření

- Cílené soubory z původního zadání: 177 passed, 17 skipped, 1 warning.
- Chráněné soubory: `protected_sha.py compare` → `PROTECTED_SAME`.
- Syntetická reprodukce: výstupy výše; importuje jen deploy validátor.
- Produkční stav a skutečný restart s podvrženou pozicí: NOT_RUN.

Detailní revize učení: `_workspace/2026-11-24_learning_stonkfly_audit.md`.
