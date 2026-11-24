# Re-review R4 (`ALLOW_OPEN_POSITIONS=1`) — Codex, 2026-11-24

**Verdikt: CHANGES_REQUIRED.** Před dalším použitím `ALLOW_OPEN_POSITIONS=1`
je nutné opravit odmítání legitimního stavu po dynamickém trailing stopu.
Audit pouze lokálně; bez SSH, nasazení, změn runtime dat a commitu.

## Blokující nález R5 — trailing stop může překročit i TP

`deploy/research_eval/deploy_env_check.py:284–288` nově přijímá BUY pouze
při `sl < tp` (SELL pouze při `sl > tp`). To nestačí na živou dynamickou
exit cestu. `src/services/dynamic_trend_exit_v1.py:147–160` počítá nový
stop z **aktuální** ceny minus ATR vzdálenost a v `evaluate_exit():245–263`
vrací aktualizaci trailing stopu **před** vyhodnocením dosaženého targetu.
`paper_trade_executor.py:2821–2825` tuto hodnotu uloží jako `pos["sl"]`.
`_save_paper_state():795–801` odstraní jen tři runtime cache klíče; nový
`sl` zůstane v kanonickém JSON stavu.

Syntetická, ale skutečnými funkcemi vypočtená reprodukce:

```
BUY entry=100, tp=100.35, původní sl=99.7,
current_price=100.5, ATR=10 bps, MFE=50 bps
before_accepted 1
decision TRAILING_STOP_EXIT new_stop 100.4
after_refused position 'review-long' tp/sl not on the BUY side
```

Reproduktor: `_workspace/2026-11-24_r4_round2_repro.py`. Jde o běžně
možnou trajektorii +50 bps, ne o exotické numerické meze. Při dalším
uložení pozic (např. kvůli otevření či uzavření jiné pozice) bude tento
stav validátorem odmítnut, ačkoli jej exit engine sám vyrobil. Analogicky
SELL může mít `sl < tp` po poklesu pod target. Dřívější oprava `sl` za
vstupní cenou řešila jen část této třídy.

Oprava má rozlišit běžný TP/SL profil od `trend_cost_aware` s
`P0_8_PLUS_EVIDENCE_COLLECTION`. U dynamické pozice musí přijmout i stop,
který překročil target, pokud je původní stop (`dynamic_exit_initial_stop`)
na správné straně vstupu a všechny ceny zůstávají konečné a v mezích.
Pokud je původní stop při takto trailed stavu nepřítomný, odmítnutí je
konzervativní. Pro jiné profily nerozvolňovat invariant bez důkazu.
Regresní test musí vytvořit stop přes `dynamic_trend_exit_v1.evaluate_exit`,
uložit takto vzniklý stav a prokázat přijetí validátorem i obnovu/uzavření
skutečným executorem v `tmp_path`; na této verzi musí selhat.

## Ostatní změny R4

- Původní reprodukce extrémního poměru cen a vzdáleného budoucího času jsou
  odmítnuty; klíče ephemeral cache se odmítají. Omezení `entry >= 1e-6`,
  poměr cen ×2 a časový náskok 60 s jsou pro současné velké páry konzervativní.
  Neznamenají však obecný důkaz konečnosti pro libovolnou konečnou tržní cenu;
  test zkouší konkrétně 1e9 a 1e-9.
- Serverový živý stav se třemi pozicemi nebyl mnou znovu čten; výsledek
  `ACCEPTED 3` je tvrzení autora, **NOT_VERIFIED** v tomto review.
- `deploy_bot_files.sh` je oproti R3 změněn pouze komentářem. Příprava
  env-only vypnutí Stonkfly a tři Stonkfly klíče byly z nástroje odebrány.

## Ověření

- Testy ze zadání: **152 passed, 9 skipped** (Windows bez bash pro tyto
  případy). Číslo 161 autora zahrnovalo bashové testy.
- Reproduktor použil skutečné `evaluate_exit()` a validátor; výstup výše.
- Kontrola šesti chráněných souborů a `runtime/`, `src/runtime/` před/po:
  `PROTECTED_SAME`.
- Obnova skutečného serverového stavu, nasazení, restart: **NOT_RUN**.

Dokud je nález otevřen, výchozí čekání na nulový počet pozic zůstává
bezpečnou cestou; opt-in `ALLOW_OPEN_POSITIONS=1` neschvaluji.
