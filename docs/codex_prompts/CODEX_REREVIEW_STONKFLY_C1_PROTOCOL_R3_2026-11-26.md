# Re-review protokolu Stonkfly C1, rev. 3 (Codex, 2026-11-26)

Jen audit, bez SSH, běhu a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_stonkfly_c1_protocol_r3.md`.
Verdikt: **APPROVE_TO_RUN / CHANGES_REQUIRED**.

Navazuje na `_workspace/2026-11-26_codex_rereview_stonkfly_c1_protocol_r2.md`. C1 na skutečných
datech dál `NOT_RUN`; na produkci jsem od posledního review nic nečetl.

| Soubor | Stav | SHA-256 |
|---|---|---|
| `_workspace/2026-11-25_stonkfly_c1_relative_decoder_protocol.md` | rev. 3 | `010529f08af2c0e6f6202a273c263b325b063427e9c7dd8e455146622ff7f969` |
| `scripts/research/stonkfly_relative_decoder_offline.py` | lokální | `6c430bdf26a6ebc95abbb6793d021375f7660a22209cd009c6ac178493748330` |
| `tests/test_stonkfly_relative_decoder_offline.py` | lokální, 18 testů | `6c85b50cdd862fd2a6259c4afb862042ef24f29e3eab15717796499ebe6e3bdb` |

## Opravy

- **R2.1 (čas ceny):**
  - `extract` vyváží `p.decision_ms` (`dec_ms`).
  - `add_features` hledá minulou cenu podle `decision_ms` jiných řádků:
    - nejblíže k `history_start`;
    - tolerance ±180 s;
    - rozhodnutí musí předcházet vlastnímu rozhodnutí řádku.
  - Odchylku počítá ze stejného času. Polovina se dál určuje podle `observation_ms`.
  - `q1_n` je přejmenováno na `q1_rows_before_pairing`.
  - Kontroly nově vykazují i `decision_ms − observation_ms`.
  - Testy:
    - `test_past_price_is_paired_by_decision_time_not_observation_time`: tvůj případ +179/+184 s je
      odmítnut, +170/+175 s přijat s odchylkou 175 000 ms;
    - `test_q1_pairs_a_known_price_without_future_path`.
- **R2.2 (hranice na serveru):**
  - Kontrola `q2_half(t, signal_ts_ms)` je přesunutá **před** SELECT dráhy v `extract`.
  - Vyžaduje platný celočíselný `signal_ts_ms`, nenahrazuje ho `observation_ms`.
  - Kontroluje obě meze intervalu i polovinu podle `observation_ms`.
  - U přesahu se dráha nečte ani neodesílá (`r600`, `buy`, `sell`, `last_sec` = null). Řádek zůstává
    pro Q1 s důvodem `forward_window_crosses_boundary_or_invalid_start`.
  - Analýza výsledek znovu ověří (shoda s `q2_half` ze serveru).
  - Testy:
    - `test_extract_never_reads_a_path_that_crosses_a_boundary`: 23:55 před předělem i před koncem
      okna, rozhodnutí +5 s; řádek s koncem přesně na předělu zůstává v TRAIN s posledním košem 599;
    - `test_q2_forward_window_must_close_inside_its_half`: přesah o 1 ms, pozorování v TRAIN
      s rozhodnutím v TEST, start před oknem, `None` i `True` jako `signal_ts_ms`.
- **R2.3 (společný výklad Q1):**
  - Řádky RD/RL už nedostávají `relative_feature_only`; `sign_vs_a2` mají jen D a L.
  - `q1_summary` se odvodí až po zpracování celé čtveřice. Štítky jsou pevně dané v tabulce
    protokolu:
    - `direct_matches_a2`;
    - `direct_opposite_to_a2`;
    - `direct_conflicting_signs`;
    - `relative_only`;
    - `relative_replicated_direct_not_evaluable`;
    - `none_replicated`;
    - `NOT_EVALUABLE`.
  - Testy:
    - `test_q1_joint_reading_is_derived_from_all_four_features` (tvůj případ všech čtyř → štítek
      `direct_matches_a2`, dále jen relativní, nevyhodnotitelné D, rozporná a opačná znaménka, žádný
      a všechny NOT_EVALUABLE);
    - `test_analyse_reports_joint_q1_reading`.

Lokálně: 18 + 11 testů prošlo a `PROTECTED_SAME`.

**Ověř:**
- Jsou R2.1–R2.3 uzavřené?
- Lze spustit extrakci podle protokolu?

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_stonkfly_relative_decoder_offline.py tests/test_stonkfly_a2_network_controls.py`
(asi 2 minuty) a `protected_sha.py` před a po.
