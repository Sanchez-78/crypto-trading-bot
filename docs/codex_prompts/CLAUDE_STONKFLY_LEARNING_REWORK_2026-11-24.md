# Zadání pro Claude: Stonkfly zachovat, diagnostikovat a zapojit měřitelně do učení

Datum: 2026-11-24. Nadřazený pokyn operátora: **Stonkfly nevypínat**.
Původní plán `LABEL=stonkfly-off` je neaktuální. Výchozí běžící paired shadow
proces a evidence zůstanou zachované. Cílem není vykázat profit z konstantních
BUY signálů, nýbrž zjistit, zda neurální informace přináší měřitelný přínos
nad stejnými tržními daty a zda se model skutečně učí.

Před implementací přečti `AGENTS.md`, `docs/OPERATING_STATE.md`,
`_workspace/2026-11-24_learning_stonkfly_audit.md` a
`_workspace/stonkfly_eval_20261123/REPORT.md`. Respektuj dirty tree, zákaz
mazání runtime dat, zákaz nové větve, zákaz REAL a aktuální pravidla pro testy.
Neslévej staré kohorty. Neprováděj SSH/nasazení/restart bez nového schváleného
deploy zadání; tento dokument požaduje pouze lokální implementaci a testy.

## 1. Rozliš tři procesy

1. Native `paper_source_learning`: uzavřené PAPER obchody → odhad přijetí
   native kandidáta. Při `CONTROL=1.0` je adaptivní odmítání vypnuté.
2. Neural context: čerstvý frozen Stonkfly pár → metadata/bucket native BTC
   kandidáta. Native trade tím nepřechází do vlastnictví Stonkfly.
3. Connectome/plastic nebo trénovaný readout: samostatný výzkumný model, který
   dnes nedostává obchodní reward. `plastic` v názvu není důkaz učení.

Před každou změnou dolož dosažitelnost ze `start.py` a přesné soubory/řádky.
Zachovej jediný `p0_8_plus_live_pipeline` jako entry owner a jediný
`cryptomaster.service`. `Stonkfly → exchange/executor` zůstává zakázáno.

## 2. Fáze A — lokalizuj konstantní BUY a KC=0

Znovu použij existující `src/services/stonkfly/benchmark.py`, `frame.py`,
`paired_backend.py`, `research.py` a `scripts/stonkfly_research.py`. Nejprve
ověř, co už umí, a přidej jen chybějící diagnostiku. Pozor:
`StonkflyConfig.source_signature()` hashuje **všechny** `.py` v
`src/services/stonkfly/`; změna třeba jen `benchmark.py` způsobí při dalším
restartu nesoulad identity uloženého checkpointu a fail-closed deaktivaci
Stonkfly. Výzkumnou diagnostiku proto preferuj v `scripts/research/` mimo
hashovaný balík. Změny balíku či modelu vyžadují samostatný plán
verzování/migrace checkpointu, přesný dopad na obnovení stavu a nové review
před nasazením. Nepřepisuj starý checkpoint ani nepovoluj mismatch.
Na stejném verzovaném
modelu a checkpointu přehraj deterministické price profily: rising, falling,
flat, mirror a shuffled control. Pro každý krok zachovej input SHA-256,
frame profile, čas, source/model/dataset/checkpoint hash a separátní frozen /
plastic výsledky. Vypiš fotoreceptorové/senzorové aktivity, pokud je backend
skutečně poskytuje, dále KC_spikes, gate_spikes, left/right/difference_hz,
total_spikes, changed_edges, mean_efficacy a BUY/SELL/HOLD. Velká neurální
pole zůstanou jen lokálně; Firebase nesmí dostat raw arrays.

Rozliš příčinu: (a) frame se nemění, (b) mění se frame, ale ne vstup neuronů,
(c) vstup neuronů se mění, ale KC/gate ne, (d) neurální hodnoty se mění, ale
decoder dává stále BUY. Nedělej úpravy thresholdů, barev nebo vah naslepo.
Pokud MaleCNS data nejsou lokálně dostupná, implementuj testovatelné rozhraní
a statické diagnostiky, označ skutečný inference test `NOT_RUN` a uveď
integrity-checked dataset requirement. Na 4GB serveru nespouštěj druhou
connectome instanci vedle živé; použij vývojový stroj nebo pozdější schválené
provozní okno. Současný živý Stonkfly nevypínej kvůli tomuto zadání.

## 3. Fáze B — propojení rozhodnutí s outcome

Zachovej existující signal envelope a recorder. Každé Stonkfly pozorování
musí nést stabilní `decision_id`, `strategy_id`, `learning_source`, frame a
checkpoint hash, observation a decision timestamp, variantu a režim. Doplnění
dělej jen na stávající lokální evidence cestě a s limity velikosti.

Pro shadow rozhodnutí vytvoř **offline** outcome evaluator nad již uloženou
price trajectory. Použij existující cost/exit profil, explicitní product a
side semantics. Originální SELL nesmí automaticky znamenat futures SHORT;
`observation_only` zůstává výchozí. Bez úplné trajektorie, quote/cost dat či
jednoznačného exit pořadí vrať `NO_DATA` nebo konzervativní označený scénář.
Nevytvářej PAPER position ani nepiš do hlavních trade statistik. Frozen,
plastic a kontrolní varianty musejí sdílet identické časy, ceny, náklady a
exit pravidlo, ale mít oddělené evidence source/version.

Native BTC trade označený neurálním kontextem **nesmí** automaticky trénovat
Stonkfly; nebyl kauzálně otevřen jeho rozhodnutím. Pokud budoucí experiment
použije skutečný trade outcome, vyžaduj jednoznačný join na rozhodnutí,
symbol, side, observation/entry/exit čas a source, a přesně jednou doručený
reward. Ambiguita → žádný reward. Neobcházej P0 ani risk.

## 4. Fáze C — učící mechanismus jako oddělený experiment

Nejdřív vyžaduj proměnlivé a reprodukovatelné neurální features. Pak
porovnej dvě jasně pojmenované hypotézy:

- **Readout learning:** malý kalibrovaný model nad frozen raw neural scalars
  pro předpověď *post-cost* outcome. Jde o učení readoutu, ne o důkaz učení
  connectomu. Trénovat jen na minulých uzavřených případech, chronologicky;
  zamknout features/thresholdy před OOS. Native `closed_trades` obsahují jen
  kandidáty, které prošly cost/P0/pacing/risk; neoznačuj jejich výběrový
  vzorek za reprezentativní pro všechny Stonkfly observations.
- **Synaptic plasticity:** jen pokud lze doložit senzorickou/KC aktivitu a
  explicitní časový credit-assignment protokol. Opožděný 10min P/L nesmí být
  slepě poslán jako reward k následujícímu grafu. Použij frozen, plastic,
  shuffled-reward a reset-state kontrolu na téže sekvenci. Checkpoint identity,
  hash, atomický zápis a fail-closed mismatch zůstanou povinné.
  Samotná změna KC→MBON vah nestačí: zvlášť ověř, zda vůbec mění DNp20
  decoder a post-cost výsledek.

Nové verze experimentů musí mít nové `strategy_id`/`learning_source`, evidence
segment a config signature. Nesmí dědit P0 readiness z dosavadní historie.
Nový readout/context vliv na admission dej za samostatný env flag s default
`false`; při chybě se vrací k dosavadní native cestě. **Existující Stonkfly
shadow provoz tím zůstane zapnutý.** Nezvyšuj frekvenci inference ani počet
workerů. Zdokumentuj vliv neurálního wake na počet BTC evaluací a vytvoř
časově srovnatelný kontrolní scheduler/baseline, aby se zaměnila informace
neuronu s pouhým dodatečným tickem.

## 5. Předem dané hodnocení

Odděl train/validation/OOS chronologicky a před OOS ulož verzi dat, modelu,
nákladů, features a kritéria. Reportuj n, pokrytí, BUY/SELL/HOLD četnosti,
transition matrix, KC/gate aktivitu, shodu frozen/plastic, post-cost EV, WR,
PF, P/L, DD, nejistotu blokově po dnech, latency, stale/drop rate a
regime/long-short řezy. Porovnej s matched-frequency random, always-BUY,
flat a native price-only při stejných obchodních příležitostech. Výsledek
včetně `NO EDGE` musí být přijatelný. Žádný údaj z holdoutu nepoužívej k
dalšímu ladění. Současných 9bps je podhodnocený paper scénář; vedle něj
uveď explicitní citlivost k realistickým nákladům bez změny živého cost
modelu či starých kohort.

## 6. Safety a testy

Nezměň `TRADING_MODE`, REAL guardy, P0 prahy, risk, TP/SL, sizing, executor
ani Firestore kvóty. Stonkfly zůstává shadow-only a žádná jeho chyba nesmí
otevřít pozici ani zopakovat starý signal. Testy minimálně: deterministický
frame/hash bez lookahead; mirror a shuffled control; pair synchronizace;
frozen/plastic evidence separation; konstantní BUY detekce; přerušený
checkpoint a config mismatch; stale inference; bounded queue; chybějící nebo
ambivalentní reward; duplicate decision/outcome; shadow zero entry; P0
fail-closed; žádné raw arrays do Firebase; při vypnutém *novém* flagu shoda
native admission a učení s dnešní implementací. Každý behavior test ověř
mutací předchozího kódu. Cílené testy v `tmp_path`; před/po ověř šest
chráněných hashů přes `protected_sha.py`. Python syntaxe nejvýš 3.12.

## 7. Výstup

Do `_workspace/2026-11-24_claude_stonkfly_learning_rework.md` dej mapu živé
cesty, reprodukci kořenové příčiny BUY/KC=0 (nebo `NOT_VERIFIED`), přesný
diff po souborech, testy/mutace, integrity hash, resource odhad a jasně
oddělené výsledky frozen/plastic. Uveď, co běží na produkci a co je pouze
lokálně připraveno. Necommituj ani nenasazuj; předej lokální změny k
nezávislému review. Není-li plný model kvůli chybějícím datům dostupný,
nedoplňuj falešnou implementaci a konkrétní blocker dolož.
