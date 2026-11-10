# Přehled nákladů a učení (offline, zmrazené vstupy)

Schéma 3. Ceník k 2026-11-10 (datovaný scénář, ne ověřený tier účtu).

## Čtyři otázky

| Otázka | Stav | Důkaz |
|---|---|---|
| Jsou data použitelná? | PARTIAL | 28 rozsahů mezer v pokrytí futures screenu; checksum != coverage |
| Umí learner lépe seřadit kandidáty? | PENDING | jen ověřený zmrazený verdikt C1 |
| Má vybraná politika kladný net? | NOT_VERIFIED | kladný lift není důkaz kladného post-cost výsledku |
| Je připravena změna bota? | NO | vyžaduje nový protokol, review a autorizovanou replikaci |

Pokrytí: **PARTIAL**, rozsahů mezer 28, chybějících řádků (v intervalu zdroje) 10990.

## Bod zvratu WR (dvoubodová aproximace, neplatí při timeoutech)

| náklad bps | WR_BE |
|---:|---:|
| 0 | 41.67 % |
| 9 | 56.67 % |
| 15 | 66.67 % |
| 18 | 71.67 % |
| 20 | 75.00 % |

## Futures screen: náklad bodu zvratu (HOLDOUT, odvození)

| Hyp. | Target | n | gross [CI] | bod zvratu | rozpočet s rezervou 3 | konzervativně z dolní meze |
|---|---|---:|---|---:|---:|---:|
| H1 | r15 | 9026 | 0.74 [-0.24; 1.85] | 0.74 | -2.26 | -3.24 |
| H1 | tpsl | 9026 | -0.04 [-0.48; 0.42] | -0.04 | -3.04 | -3.48 |
| H2 | r15 | 19097 | 0.27 [-0.20; 0.69] | 0.27 | -2.73 | -3.20 |
| H2 | tpsl | 19097 | 0.51 [0.16; 0.84] | 0.51 | -2.49 | -2.84 |
| H3 | r15 | 16825 | 0.15 [-0.47; 0.80] | 0.15 | -2.85 | -3.47 |
| H3 | tpsl | 16825 | -0.04 [-0.41; 0.33] | -0.04 | -3.04 | -3.41 |
| H4 | r15 | 17562 | 0.41 [-0.08; 0.88] | 0.41 | -2.59 | -3.08 |
| H4 | tpsl | 17562 | 0.41 [0.09; 0.73] | 0.41 | -2.59 | -2.91 |
| H5 | r15 | 37723 | -0.23 [-0.73; 0.26] | -0.23 | -3.23 | -3.73 |
| H5 | tpsl | 37723 | 0.05 [-0.24; 0.35] | 0.05 | -2.95 | -3.24 |
| H6 | r15 | 66876 | 0.29 [-0.28; 0.83] | 0.29 | -2.71 | -3.28 |
| H6 | tpsl | 66876 | 0.55 [0.17; 0.94] | 0.55 | -2.45 | -2.83 |
| H7 | r15 | 13310 | 0.88 [-0.24; 1.94] | 0.88 | -2.12 | -3.24 |
| H7 | tpsl | 13310 | 0.75 [0.21; 1.34] | 0.75 | -2.25 | -2.79 |

## C1

Stav: **PENDING**.

Čtení: raw post-cutoff obchody ne (nástroj je nikdy nečte); zmrazený výsledek C1 ne; zmrazený agregát mu ne.

Vstupy: manifest očekávaný `None`, přečtený `None` (shoda ne); výsledek očekávaný `None`, přečtený `None` (shoda ne); mu přečtené `None` (identita bytů, ne důkaz správnosti mu).

Důvod: no frozen prereg_result.json supplied.

Záporný rozpočet = rezerva nevychází ani při nulovém nákladu. Maker mění i výběr a ceny fillů; nelze odvodit pouhým odečtením menšího fee.
