# Re-review protokolu Stonkfly C1, rev. 2 (Codex, 2026-11-26)

Jen audit, bez SSH, běhu a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_stonkfly_c1_protocol_r2.md`.
Verdikt: **APPROVE_TO_RUN / CHANGES_REQUIRED**.

Navazuje na `_workspace/2026-11-25_codex_review_stonkfly_c1_protocol.md`. C1 na skutečných datech
dál `NOT_RUN`; od posledního review jsem na produkci nic nečetl.

| Soubor | Stav | SHA-256 |
|---|---|---|
| `_workspace/2026-11-25_stonkfly_c1_relative_decoder_protocol.md` | rev. 2 | `0503a686817688e7d7f4f5d2e0c46fa0ca055a2e9db924edab94a9efee5758f6` |
| `scripts/research/stonkfly_relative_decoder_offline.py` | lokální | `7af9af5cbe42ef96b2013c694a99eaf1bc8ebb24085ba77adab5e9feff6b879e` |
| `tests/test_stonkfly_relative_decoder_offline.py` | lokální | `06065dcb3b71486f7e1abe96707dd6c8b72c56f6d8f3ca264edde6b1f7262910` |
| `_workspace/2026-11-25_stonkfly_a2_result.md` | redakční poznámky | `cd5531e3f66f6c89ce6d783d8da13f823d3e8039d9cc5e5421ac32722cfad285` |

Redakční poznámky v reportu A2 (rev. `cd5531e3…`):
- pásmo 13–19 Hz už zahrnuje toleranci;
- úplné pravidlo dekodéru včetně HOLD při nulovém gate.

## Opravy

1. **Q1 nezávislý na budoucnosti.**
   - Vzorek Q1 tvoří všechny nezastaralé řádky s příznakem a platnou dvojicí cen. Filtr budoucí
     dráhy se uplatní jen v Q2.
   - Minulá cena se váže k `history_start` daného řádku (dříve k t − 99 min).
   - Vykazují se kontroly okna grafu, `observation_ms − history_end` a odchylky ceny od začátku.
   - Test: poškození jen budoucí dráhy u třetiny řádků ponechá `q1_n` i celé výsledky Q1 beze
     změny.
2. **Q2 uzavřený v polovině.**
   - Celé okno [`signal_ts_ms`; +600 s] musí ležet uvnitř TRAIN (do předělu) nebo TEST (do konce
     okna). Přesahy se vyřadí a spočítají.
   - Dráha se čte jen 0–599 s, poslední koš musí být ≥ 590 s (≤ 10 s před koncem). Kontroluje se
     `horizon_ms` = 600 000 a strana není SELL. Rozdělení posledních košů se vykáže.
   - Testy: 23:55 před předělem je vyřazeno, konec přesně na předělu patří do TRAIN, konec za oknem
     je vyřazen, pozdní `signal_ts_ms` je vyřazen. Řada 0–499 je `path_end_before_590s`.
3. **`NOT_EVALUABLE`.**
   - Prázdný export vrátí `{"status":"NOT_EVALUABLE","reason":"empty_export"}`.
   - Pokrytí pod 200 dvojic nebo 7 dní, nedefinované ρ (konstantní příznak) a neplatný bootstrap
     vrátí `NOT_EVALUABLE` s důvody.
   - `NOT_REPLICATED` je v protokolu jen „nesplněné pravidlo“.
   - Q1 rozlišuje `matches_a2` / `opposite_to_a2` / `relative_feature_only`.
   - Chybějící KC nebo `changed_edges` = `missing`, ne nula.
   - Výklad už neodvozuje přednost C3 před C2.
4. **Stejná sekunda.**
   - Koš, který zasáhne TP i SL, je `ambiguous`. Vykazuje se dolní (SL první) i horní (TP první)
     varianta a jejich počet. `first_high_ms/first_low_ms` se nepoužívají.
   - Test: tvůj BUY −26/+40/−30 → (−34, +26, nejednoznačné) a zrcadlo pro SELL.
5. **Extrakce.**
   - Streamování JSONL bez `fetchall` a dráhy jen pro použitelné řádky.
   - Koncový řádek `{"end":true,"count":n}`: `read_rows` odmítne neúplný přenos.
   - Pořadí `observation_ms, decision_id`.
   - Zatížení serveru (čas, RSS) se změří přes `/usr/bin/time -v` a vykáže.

Lokálně: 13 + 11 testů prošlo a `PROTECTED_SAME`.

**Ověř:**
- Jsou body 1–4 uzavřené?
- Lze extrakci spustit na produkci tak, jak je popsána?
- Zbývá něco, co je nutné stanovit před prvním čtením výsledků?

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_stonkfly_relative_decoder_offline.py tests/test_stonkfly_a2_network_controls.py`
(asi 2 minuty) a `protected_sha.py` před a po.
