# Stonkfly C1: review výsledku (Codex, 2026-11-26), přepis verdiktu

Codex review provedl, ale soubor reportu se mu nepodařilo vytvořit. Zde je jeho verdikt přepsaný
operátorem z odpovědi Codexu (bez úprav obsahu).

| Bod | Verdikt |
|---|---|
| A: platnost běhu | **ACCEPT** |
| B: výklad | **APPROVE** |
| C: další krok | C2 jen jako úzce vymezená výzkumná diagnostika plasticity. Pro cíl P/L ponechat Stonkfly ve shadow režimu, k C3 nepokračovat bez nové nezávislé hypotézy. |

## Zdůvodnění podle Codexu

- **Úplnost dat:** kontrolní řádek JSONL potvrzuje všech 9 287 řádků. Hashe výsledku i exportu
  odpovídají zadání.
- **Co Codex sám neověřoval:** produkční DB znovu nečetl. Údaje 26 s, 19,7 MB a smazání
  dočasného souboru v `/tmp` přebírá z reportu operátora.
- **Q1** splňuje předem dané pravidlo na TRAIN i TEST.
- **Q2** pravidlo replikace nesplňuje, což neprokazuje absenci vztahu.
- **Relativní dekodér:** −8,78 bps (TRAIN) a −8,60 bps (TEST), tedy blízko započteným nákladům.
- **C2** má smysl jen jako úzká výzkumná diagnostika plasticity. Nejdřív by musela ověřit dopřednou
  aktivaci Kenyonových buněk při vypnuté odměně. Samotné zjištění příčiny jejich ticha cíl P/L
  nepodpoří.
- **Pro cíl P/L** výsledky podporují ponechání Stonkfly v režimu shadow. Nedávají důvod pokračovat
  k C3 bez nové nezávislé hypotézy.
- **Upřesnění počtů:**
  - 9 287 je počet všech nezastaralých řádků.
  - Q2 použilo 8 786 přijatých trajektorií.
  - Počet dvojic se liší podle příznaku.

## Rozhodnutí (Claude)

Stonkfly zůstává beze změny v shadow / `observation_only` režimu (operátor: nevypínat). C2 se
zatím nespouští, protože nepodporuje cíl P/L. Lze ho otevřít jako samostatný výzkumný úkol na
izolovaném stroji. C3 se nezačíná bez nové nezávislé hypotézy.
