"""Assemble the Czech task report from frozen calculations and integrity proofs."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET


def main():
    artifacts = Path(__file__).resolve().parent
    root = artifacts.parents[1]
    before = json.loads((artifacts / "before.json").read_text(encoding="utf-8"))
    current = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() if (root / name).is_file() else None
               for name in before["hashes"]}
    changed = [name for name in current if current[name] != before["hashes"][name]]
    assert not changed, changed
    result = json.loads((artifacts / "screen/report.json").read_text(encoding="utf-8"))
    source = root / "scripts/research/futures_flow_screen.py"
    assert result["study"]["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    downloads = json.loads((artifacts / "download/downloads.json").read_text(encoding="utf-8"))
    mutations = json.loads((artifacts / "mutations.json").read_text(encoding="utf-8"))
    suite = ET.parse(artifacts / "restored.xml").getroot().find("testsuite")
    missing = [item for item in downloads["files"] if item["status"] != "OK"]
    total_bytes = sum(item.get("bytes", 0) for item in downloads["files"])
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    (artifacts / "after.json").write_text(json.dumps(dict(head=head, branch=branch, hashes=current,
        preexisting_changes=changed, protected_unchanged=True), indent=2), encoding="utf-8")
    prefix = (artifacts / "preregistration.md").read_text(encoding="utf-8").split("## Výsledky\n", 1)[0]
    verdicts = ", ".join(f"{key}={row['verdict']}" for key, row in result["verdicts"].items())
    lines = [prefix, "## Výsledky skutečného běhu", "", verdicts + ".", "",
             "Předregistrace a testy vznikly 2026-11-09; úplný výpočet TRAIN → TEST → HOLDOUT proběhl 2026-11-10. "
             "Přesné začátky etap v UTC jsou v `screen/*.started.json`.", "",
             "Byla použita skutečná veřejná historická data, nikoli syntetické tržní výsledky. "
             "Syntetické fixtures sloužily pouze jednotkovým testům. Nebyl znovu otevřen C1 ani změněn bot.", "",
             (artifacts / "screen/report.md").read_text(encoding="utf-8"), "",
             "## Datové pokrytí a reprodukce", "",
             f"Období archivů: 2024-01 až {downloads['end_month']}; souborů {len(downloads['files'])}, "
             f"nedostupných {len(missing)}, ZIP data {total_bytes / 2**30:.3f} GiB. Všechny použité ZIPy ověřeny proti SHA-256 CHECKSUM; "
             "při čtení znovu proti zmrazenému manifestu. Úplný seznam je `futures_flow_20261109/download/downloads.json`.", "",
             "Žádný chybějící archiv." if not missing else "Nedostupné archivy: " + ", ".join(item["key"] for item in missing), "",
             "Počty níže jsou jen uvnitř příslušného bloku, bez warmupu. Přesné chybějící časové intervaly "
             "jsou v `report.json` → blok → coverage → sources → missing_ranges (UTC epoch ms); "
             "nevzniká cena ani metrika interpolací přes mezeru.", "",
             "| Blok | Symbol | Futures řádků / chybí | Spot řádků / chybí | Metrics řádků / chybí | Funding událostí |",
             "|---|---|---:|---:|---:|---:|"]
    for stage in ("TRAIN", "TEST", "HOLDOUT"):
        for item in result[stage]["coverage"]:
            sources = item["sources"]
            def counts(kind):
                row = sources[kind]
                return f"{row['rows']} / {row.get('missing_rows', 'N/A')}"
            lines.append(f"| {stage} | {item['symbol']} | {counts('futures')} | {counts('spot')} | {counts('metrics')} | {sources['funding']['rows']} |")
    gaps = {}
    for stage in ("TRAIN", "TEST", "HOLDOUT"):
        for item in result[stage]["coverage"]:
            for kind, source_coverage in item["sources"].items():
                for gap in source_coverage.get("missing_ranges", []):
                    key = (stage, kind, gap["start_ms"], gap["end_exclusive_ms"], gap["count"])
                    gaps.setdefault(key, []).append(item["symbol"])
    lines += ["", "Přesné mezery uvnitř dostupných archivů (konec intervalu je exkluzivní):", "",
              "| Blok | Data | Od UTC | Do UTC | Chybí na symbol | Symboly |", "|---|---|---|---|---:|---|"]
    for (stage, kind, start, end, count), symbols in gaps.items():
        fmt = lambda value: datetime.fromtimestamp(value / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
        lines.append(f"| {stage} | {kind} | {fmt(start)} | {fmt(end)} | {count} | {', '.join(symbols)} |")
    lines += ["", "### Zmrazený výběr z TRAIN", "",
              "| Hypotéza | Feature | Práh | Orientace |", "|---|---|---:|---:|"]
    for family, rule in result["TRAIN"]["selected"].items():
        lines.append(f"| {family} | {rule['feature']} | {rule['threshold']} | {rule['orientation']:+d} |"
                     if rule else f"| {family} | žádný způsobilý výběr | N/A | N/A |")
    model = result["TRAIN"]["model"]
    lines += ["", f"Pooled TRAIN medián efficiency ratio: {result['TRAIN']['regime_threshold']:.8f}. "
              + (f"H7: C={model['C']}, finální fit na {model['n_fit']} vzorcích. " if model else "H7 model není dostupný. ")
              + "Detaily CV a všechny TRAIN kandidáty obsahuje `screen/train.json`.", "",
              f"SHA-256 skriptu při výpočtu: `{result['study']['source_sha256']}`. "
              f"SHA-256 canonical manifestu dat: `{result['study']['manifest_sha256']}`.", ""]
    held = [stats for stats in result["HOLDOUT"]["statistics"].values() if stats and stats["n"]]
    if held:
        lines += ["### Číselná interpretace HOLDOUT", "",
                  "Rozsah průměrů jednotlivých zmrazených hypotéz (nejde o výnos společného portfolia):", ""]
        for target in ("r15", "tpsl"):
            for cost in (9, 18):
                values = [stats[target][f"net{cost}_bps"] for stats in held]
                lines.append(f"- {target.upper()} po {cost} bps: {min(values):+.4f} až {max(values):+.4f} bps na obchod.")
        wins = [stats["tpsl"]["wr_net9"] * 100 for stats in held]
        lines += [f"- TPSL WR po 9 bps: {min(wins):.2f}–{max(wins):.2f} %.", "",
                  "WR v hlavní tabulce je zlomek 0–1. N/A u podílu symbolu znamená, že žádný symbol nemá "
                  "kladný součet net9; nepředstavuje splnění podmínky diverzifikace.", ""]
    lines += ["", "Příkazy:", "", "```text",
              "rtk python -X utf8 scripts/research/futures_flow_screen.py --download-only --cache data/research/binance_futures --out _workspace/futures_flow_20261109/download --end-month 2026-10",
              "rtk python -X utf8 -B scripts/research/futures_flow_screen.py --offline --manifest _workspace/futures_flow_20261109/download/downloads.json --cache data/research/binance_futures --out _workspace/futures_flow_20261109/screen --end-month 2026-10",
              "rtk python _workspace/code_audit_20260921_runner.py tests/test_futures_flow_screen.py -q --tb=short",
              "rtk python -X utf8 _workspace/futures_flow_20261109/verify.py", "```", "",
              "Existující zmrazené stage soubory se načtou bez nového výpočtu. Změna kódu/dat/protokolu "
              "nebo přerušené první vyhodnocení vyvolá chybu; nemažte zámky pro získání druhého pohledu na HOLDOUT.", "",
              "Implementace: `scripts/research/futures_flow_screen.py`; testy: `tests/test_futures_flow_screen.py`. "
              "Jen stdlib a již přítomné numpy/pandas/scikit-learn, bez nových závislostí. "
              "Běh ověřen na Pythonu 3.14, numpy 2.4.3, pandas 3.0.1, scikit-learn 1.8.0; syntaxe odpovídá Pythonu 3.12.", "",
              "## Testy a kontrola rozsahu", "",
              "Aritmetika výsledků, náklady, součty rozkladů a shoda zmrazených etap ověřeny bez dalšího "
              "čtení tržních dat a bez opakování HOLDOUT (`result_integrity.json`).", "",
              f"Finální izolovaná sada: {suite.attrib['tests']} PASS, {suite.attrib['failures']} FAIL, {suite.attrib['errors']} ERROR. "
              "Spouštěn pouze požadovaný testovací soubor; žádná celá sada ani přístup k serveru.", "",
              "| Mutace | Očekávaná selhání testů |", "|---|---:|"]
    lines += [f"| {item['case']} | {item['failures']} |" for item in mutations if item["case"] != "restored"]
    lines += ["", "Podrobné logy/XML a `mutations.json` jsou pod `futures_flow_20261109/`. "
              "Mutace běžely pouze v izolované kopii. Síť i vytvoření privátní mutační kopie vyžadovaly povolení mimo sandbox; "
              "nešlo o přístup k Hetzneru. Při implementaci zachycena a opravena duplicitní deklarace funkce "
              "(před výpočty) a reálné milisekundové offsety funding timestampů. Offset se zachovává, nezaokrouhluje dolů.", "",
              "Před TRAIN výběrem a před TEST upřesněn H7: H6 hodnoty BTC jsou nula podle zadání 'jen alty'. "
              "Původní i upřesněná předregistrace a jejich hashe jsou zachovány v `preregistration_initial.md`, "
              "`preregistration.md`, `preregistration_clarification.json`. Žádná hypotéza, lookback, threshold ani kritérium "
              "nebyly změněny po pohledu na TEST.", "",
              f"Předchozích {len(current)} hashovaných souborů beze změny, včetně všech šesti runtime souborů. "
              f"HEAD před: `{before['head']}`, po: `{head}`; větev `{branch}`. "
              "V tomto úkolu jsem neprovedl commit/push/deploy/restart. Přidal jsem dva požadované kódové soubory, "
              "research cache a důkazní/reportové artefakty pod `_workspace`.", "",
              "HEAD se mezi původním snapshotem 9. 11. a dokončením 10. 11. změnil mimo příkazy tohoto úkolu. "
              "Reflog ukazuje `d210d56` (9. 11. 13:49 +01:00, Claude Code plugins) a `5cd463a` "
              "(10. 11. 08:02 +01:00, Autonomy daily log). Tyto existující změny zůstaly zachovány; "
              "shoda obsahu 516 hashovaných souborů včetně runtime je ověřena nezávisle na HEAD.", "",
              "| Chráněný soubor | SHA-256 před = po |", "|---|---|"]
    lines += [f"| `{name}` | `{current[name]}` |" for name in before["protected"]]
    lines += ["", "## NOT_VERIFIED a omezení", "",
              "- Nejde o fills ani výsledek aktuálního bota: model neaplikuje jeho portfolio, admission, learning a risk gates. "
              "Fixních 9/18 bps neřeší skutečný spread, funding cashflow, market impact ani latenci. Žádný návrh nasazení.",
              "- Režimy a UP/DOWN jsou předem zvolené trailing diagnostiky, nikoli důkaz market neutrality. "
              "Denní bootstrap a Holm omezují statistické omyly za svých předpokladů; nepokrývají všechny strukturální zlomy trhu.",
              "- Dostupnost historické hodnoty na t+interval je konzervativní model timestampu; skutečná publikační latence "
              "Binance není v archivech ověřena. Funding je záměrně zpožděn o vlastní interval.",
              "- Skutečné spuštění na Pythonu 3.12, nezávislé review a budoucí forward performance nejsou ověřeny. "
              "Ruff nebyl instalován. Výsledek NO_EDGE platí pro tuto předregistrovanou rodinu a cenový screen.", "",
              "Schémata, přechod spot timestampů na mikrosekundy a CHECKSUM mechanismus: "
              "[Binance public data](https://github.com/binance/binance-public-data). "
              "Data: [Binance Data Collection](https://data.binance.vision/).", ""]
    (root / "_workspace/64_codex_new_signal_source_screen.md").write_text("\n".join(lines), encoding="utf-8")
    print(verdicts)


if __name__ == "__main__":
    main()
