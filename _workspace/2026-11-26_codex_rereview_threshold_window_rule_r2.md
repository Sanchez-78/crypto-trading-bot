# Re-review pravidla po měřicím okně, rev. 2 (2026-11-26)

## Verdikt: CHANGES_REQUIRED

Nezávisle jsem ověřil SHA-256 evaluátoru a testů; oba odpovídají pinům v zadání. Výsledky okna jsem nepočítal, k DB ani serveru jsem se nepřipojil a testy jsem znovu nespouštěl.

## Opravy potvrzené

- Gate populace je platná predikce `>= -25`; zpřísnění porovnává ponechané s nově vyřazenými uvnitř této populace.
- Minimum 1 000 počítá jen gate populaci; chybějící predikce a řádky pod −25 jsou popisné.
- CLI už nepřijímá `--now`; běh před `END + 1800 s` se odmítá.
- WR je mimo rozhodovací pravidlo a změna konfigurace není automatická; případný postimage jde k samostatnému review.

## Zbývající problém: Holm se při netestovatelném kandidátu počítá jen z jednoho p

`evaluate()` přidá p-hodnotu do `pvalues` pouze pokud má daný řez alespoň 100 ponechaných obchodů a alespoň jeden nově vyřazený (`threshold_window_eval.py`, část `for cut in CUTS`). Když například řez −10 nemá žádné nově vyřazené obchody, ale řez 0 testovatelný je, −10 se z rodiny vynechá. `holm()` pak vidí jedinou hypotézu a testuje ji na celé hladině 0,025 místo 0,0125. To odporuje předregistraci Holmovy korekce přes oba předem stanovené kandidáty a může neoprávněně označit řez 0 jako způsobilý.

Vždy předejte do Holmovy procedury oba předem stanovené kandidáty. Netestovatelnému řezu přiřaďte `None`/p=1 tak, aby zůstal v rodinném počtu a nemohl být zamítnut; p-hodnota druhého kandidáta pak musí projít správným prvním krokem na 0,0125. Přidejte integrační test, kde D_-10 je prázdné, D_0 je neprázdné a p pro řez 0 leží mezi 0,0125 a 0,025; výsledek musí být `KEEP_CURRENT`.

## Další fail-closed nesoulad v reportu

`prepare()` mění chybějící nebo neplatné `pnl_usd` na `0.0` pomocí `_num(...) or 0.0`. Evaluátor pak vydá kumulativní USD/PF jako by byly úplné, přestože reportuje jen nulu. Rozhodovací test běží z `pnl_pct`, ale USD metriky jsou součástí výstupu a protokol říká, že neplatný řádek znamená fail-closed. Při `pnl_usd` NULL/nečíselné hodnotě buď běh odmítněte, nebo metriku označte jako nevyhodnotitelnou a explicitně spočítejte chybějící hodnoty. Přidejte odpovídající test.

Po těchto opravách lze pravidlo znovu schválit. Do té doby může být případné vyhodnocení pouze bez následné změny prahu a musí být předáno Codexu k auditu.
