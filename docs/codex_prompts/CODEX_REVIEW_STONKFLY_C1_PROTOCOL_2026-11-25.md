# Review protokolu Stonkfly C1 (offline relativní dekodér) a opravy reportu A2 (Codex, 2026-11-25)

Jen audit, bez SSH, běhu a commitu. Report napiš česky do
`_workspace/2026-11-25_codex_review_stonkfly_c1_protocol.md`.

Verdikty:
- **A:** opravený report A2. APPROVE / CHANGES_REQUIRED.
- **B:** protokol C1 **před během**. APPROVE_TO_RUN / CHANGES_REQUIRED.

## A. Opravy reportu A2 podle tvého review

Soubor `_workspace/2026-11-25_stonkfly_a2_result.md` (sha256 `80ecdee5…`):
- **Pokus 1:** report přiznává statické metriky. `MemoryError` a `/proc` jsou označené jako
  nedoložené v uložených souborech.
- **Příčina asymetrie:** „strukturní příčina“ je nahrazena formulací „kladná výstupní základní
  hladina v čerstvém baseline stavu“ s výčtem možných původů.
- **Shoda variant:** „bit po bitu“ je nahrazeno „shodné exportované skaláry a labely“. Report
  zmiňuje i vliv `reward_mode=disabled`.
- **Rozptyl:** formulace „konzistentní s vývojem stavu“.
- **`falling`:** report uvádí, že leží na hraně pravidla.
- **Další krok:** pořadí C1 → C2 → C3.

**Ověř:** Odpovídá report nyní datům?

## B. Protokol C1 (pre-registrace, zatím nespuštěno)

Na produkci jsem jen jednou četl **schéma** (sloupce, klíče `metadata_json`, počty, okno grafu
99 min, interval ~5 min). Žádné výsledky `r600`, cenové cesty ani nové příznaky jsem nečetl.

| Soubor | Stav | SHA-256 |
|---|---|---|
| `_workspace/2026-11-25_stonkfly_c1_relative_decoder_protocol.md` | | `ad443ee8e42ff1d51f4c4f37b0f8a448470d5cdfc9d5bf342c143b43f89f32df` |
| `scripts/research/stonkfly_relative_decoder_offline.py` | lokální | `3c84d88a152b316ebed0120f3546357bd86fc602a3d601a16485cf8e2f8cb83c` |
| `tests/test_stonkfly_relative_decoder_offline.py` | lokální | `19b2fa571151f1fbb9deb4159abf956fd2d4b02d46a0acae6614832be04ed44f` |

Lokálně: 8 + 11 testů prošlo a `PROTECTED_SAME`.

Shrnutí protokolu:
- **Data:** živé predikce `stonkfly_frozen_paired_v1`, okno 13. 10. – 25. 11. 2026. TRAIN je
  před 10. 11., TEST od 10. 11.
- **Příznaky:** D, L, RD = D − klouzavý medián 12 předchozích, RL = totéž pro L.
- **Q1:** Spearman vs. minulý pohyb za okno grafu (99 min).
- **Q2:** Spearman vs. budoucí pohyb za 600 s.
- **Verdikt:** `REPLICATED` jen při denním bootstrap CI bez 0 na TRAIN i TEST se stejným
  znaménkem.
- **Dekodér:** pevný, RD ± 2 Hz, s popisnou ekonomikou.
- **Běh:** extrakce na serveru jen čtením (`mode=ro`, `query_only`, `nice`/`ionice`), analýza
  lokálně.

**Ověř:**
1. Je toto správná realizace tvého kroku C1? Klouzavá reference místo konstantní: konstantní odečet
   je monotónní posun D se stejnými pořadovými statistikami.
2. Je bezpečný postup: `extract` čte produkční DB, vypisuje řádky na stdout a nic nezapisuje?
3. Jsou kritéria, okna, příznaky a výklad předem dostatečně pevné proti ladění? Je vhodné
   rozdělení TRAIN/TEST?
4. Je přibližný výpočet `past_bps` z referenčních cen sousedních pozorování (tolerance ±3 min)
   přijatelný jako proxy trendu grafu?
5. Co je nutné změnit před během?

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_stonkfly_relative_decoder_offline.py tests/test_stonkfly_a2_network_controls.py`
(asi 2 minuty) a `protected_sha.py` před a po.
