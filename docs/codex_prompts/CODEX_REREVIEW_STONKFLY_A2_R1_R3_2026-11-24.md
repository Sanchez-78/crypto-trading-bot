# Cílené re-review: Stonkfly A2 po nálezech A2-R1 až A2-R3 (Codex, 2026-11-24)

Jen audit. Report napiš česky do `_workspace/2026-11-24_codex_rereview_stonkfly_a2_r1_r3.md`.
Verdikt APPROVE / CHANGES_REQUIRED: je protokol připravený k jednomu baseline běhu na dočasném
izolovaném stroji?

Navazuje na `_workspace/2026-11-24_codex_rereview_stonkfly_a2_protocol.md`. Změny jsou lokální a
necommitnuté: `scripts/research/stonkfly_a2_network_controls.py`,
`tests/test_stonkfly_a2_network_controls.py` a `_workspace/2026-11-24_stonkfly_a2_runbook.md`.

## A2-R1: dekodér a aktivita sítě

- `output_verdict()` vrací zvlášť:
  - `decoder_moved_by`: frozen `difference_hz` ± `NOISE_HZ` proti rozsahu opakování prázdného
    snímku, nebo jiné labely;
  - `activity_moved_by`: navíc `ACTIVITY_FIELDS` = `left_hz`, `right_hz` (± 1 Hz) a `gate_spikes`,
    `KC_spikes`, `total_spikes` (± max(`COUNT_ABS_TOL` 1, `COUNT_REL_TOL` 0,10 × průměr prázdného
    snímku)).
  - Pole, které backend nevrací, se neporovnává a je vidět v `activity_fields_compared`.
- `conclude()` vyhodnocuje v tomto pořadí:
  1. neúplné → NOT_VERIFIED;
  2. graf změní dekodér → INPUT_REACHES_DECODER;
  3. hustá kontrola nedosáhne prahu vstupu → INCONCLUSIVE;
  4. dekodér změní jen hustá kontrola → SUPPORTS_WEAK_INPUT (jen při WEAK), jinak INCONCLUSIVE;
  5. změní se jen aktivita → DECODER_INVARIANT_NETWORK_RESPONDS;
  6. jinak NETWORK_INSENSITIVE_TO_DENSE_INPUT.
- Původní NETWORK_INSENSITIVE zmizel.
- Testy: tvůj první reproduktor (levá i pravá +10 Hz, gate i KC 100) →
  DECODER_INVARIANT_NETWORK_RESPONDS; slepá hustá kontrola → INCONCLUSIVE ve třech variantách výstupu.

## A2-R2: spustitelnost

- Runbook kopíruje přesný minimální seznam modulů: `src/__init__.py`, `src/services/__init__.py`,
  `src/services/stonkfly/*.py`, `strategy_contracts.py` a `strategy_registry.py`. Seznam pochází
  z `sys.modules` po importu runneru a všech modulů Stonkfly.
- Data leží v `/srv/a2/data`, pracovní adresář je `/srv/a2/code`.
- Nový `--smoke` (`smoke()`) naimportuje všechny moduly a spustí `environment()`:
  - skutečné verze Pythonu, numpy, pandas a pyarrow, architektura a `source_signature` proti
    `EXPECTED_ENVIRONMENT` (produkce, zjištěno jen čtením);
  - pravidlo, že data neleží pod `cwd`;
  - `preflight()`.
- Ostrý `run()` tutéž kontrolu opakuje a při neshodě vrátí `BLOCKED`.
- Výjimka při spuštění statické sondy (např. `child.start()`) dá strukturovaný `ERROR` → PARTIAL.

## A2-R3: úplnost

`completeness()` musí projít, jinak je výsledek PARTIAL, kombinovaný i vstupní verdikt je
NOT_VERIFIED a `incomplete` vypíše důvody. Podmínky:
- obě statické metriky s číslem pro všechny snímky;
- `REPEATS` pozorování u každého snímku;
- sekvence s `len(FRAMES)` pozorováními;
- prázdné `errors`.

Test pokrývá 8 případů: chyba, chybějící i krátká sekvence, chybějící R8, R8 bez snímku, chyba
statické části, chybějící snímek a málo opakování. Tvoje reprodukce teď vracejí PARTIAL /
NOT_VERIFIED. Tvůj reproduktor nemá sekvenci, takže je PARTIAL i první případ; varianta se
sekvencí je v testu.

## Ověření

- 11 testů A2. S `test_stonkfly_input_sensitivity.py`, `test_stonkfly_integration.py` a
  `test_paper_neural_context.py`: 115 passed, 1 skipped, `PROTECTED_SAME`.
- Šest mutací zachytí testy:
  - aktivita ignorovaná;
  - kontrola slepé husté kontroly vypnutá;
  - kontrola sekvence vypnutá;
  - kontrola R8 vypnutá;
  - počet opakování nekontrolovaný;
  - pravidlo cesty k datům vypnuté.
- Práh 10 % zůstává beze změny podle tvého rozhodnutí.

**Ověřit:**
- Jsou R1–R3 uzavřené?
- Jsou tolerance pro počty spiků (max(1, 10 %)) přijatelné jako předem pevná pravidla?
- Je seznam modulů v runbooku úplný?

Bez SSH, nasazení, commitu a placených zdrojů. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_stonkfly_a2_network_controls.py tests/test_stonkfly_input_sensitivity.py tests/test_stonkfly_integration.py tests/test_paper_neural_context.py`
s kontrolou `protected_sha.py` před a po.
