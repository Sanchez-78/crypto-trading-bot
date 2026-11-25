# Stonkfly A2: založení dočasného serveru na Hetzneru (návod pro operátora, 2026-11-25)

Účel: jeden běh A2 podle schváleného runbooku `_workspace/2026-11-24_stonkfly_a2_runbook.md`. Produkční
server 78.47.2.198 se nemění.

## 1. Připrav si veřejný SSH klíč (na tomto PC)

V PowerShellu:

```powershell
Get-Content $env:USERPROFILE\.ssh\hetzner_root.pub | Set-Clipboard
```

Klíč je teď ve schránce. Je to veřejná část a smí se vložit do Hetzneru. Jeho otisk (fingerprint) je
`SHA256:prMSEAZVgGPo0kuuew0N8/skKS1sfDMgs5fKshhGhaU`.

## 2. Hetzner Cloud Console

1. Otevři https://console.hetzner.cloud a přihlas se.
2. **Doporučeno:** založ nový projekt (`+ New project`), např. `a2-temp`. V odděleném projektu
   nemůžeš omylem sáhnout na nic produkčního a na konci smažeš všechno najednou.
3. V projektu otevři **Security → SSH keys → Add SSH key**.
   - Vlož klíč ze schránky (Ctrl+V).
   - Jméno: `hetzner_root`.
   - Hetzner pak ukáže otisk. Musí končit `…KS1sfDMgs5fKshhGhaU`.

## 3. Vytvoření serveru (`Servers → Add Server` / `Create Server`)

| Položka | Nastavení |
|---|---|
| Location | libovolná v EU (Nuremberg, Falkenstein nebo Helsinki) |
| Image | **Ubuntu 24.04** |
| Type | **Shared vCPU, x86 (Intel/AMD)**, **8 GB RAM**, např. CX32/CX33 nebo CPX31/CPX32 podle aktuální nabídky. **Ne** Arm64 (řada CAX): A2 vyžaduje `x86_64` a na Armu skončí jako BLOCKED. Dedicated vCPU není potřeba. |
| Networking | **Public IPv4 zapnout**. IPv6 může zůstat. Bez IPv4 se k serveru nemusím připojit. |
| SSH keys | zaškrtni `hetzner_root` (pak se nevytváří heslo pro root) |
| Volumes | žádné (disk serveru stačí, A2 potřebuje ~1 GB) |
| Firewalls | doporučeno: `Create Firewall` s jediným pravidlem Inbound **TCP 22** (SSH), jinak vše zavřeno |
| Backups | vypnuto |
| Placement groups, Labels, Cloud config | nic |
| Name | `a2-temp` |

Klikni **Create & Buy now**. Do minuty server běží a v přehledu uvidíš jeho **IPv4 adresu**.

## 4. Pošli mi IP adresu

Stačí napsat např. „server je 1.2.3.4“. Já pak:
1. ověřím otisk hostitele a připojím se klíčem `hetzner_root`;
2. nahraju ověřený balíček `C:\Projects\_stonkfly_a2_bundle\` (410 MB, 23/23 hashů podle manifestu)
   a spustím `a2_setup.sh`, tedy instalaci a nejdřív `--smoke`;
3. pokud vyjde `SMOKE_OK`, spustím jediný ostrý běh (`bash a2_setup.sh run`);
4. stáhnu výsledek do `_workspace/stonkfly_eval_20261123/` a napíšu ti, že server můžeš smazat.

Na serveru nebude `.env`, žádné klíče k burze, Firebase ani runtime DB. Jen veřejný balík modelu, data
MaleCNS a výzkumné skripty.

## 5. Smazání po běhu (důležité kvůli účtování)

Hetzner účtuje server po hodinách, **i když je vypnutý**, dokud ho nesmažeš.
- **Servers → `a2-temp` → … → Delete**, potvrdit jménem.
- Pokud jsi zakládal projekt `a2-temp`, můžeš potom smazat i firewall a celý projekt.
- Primární IPv4 se smaže se serverem. Pokud se Hetzner zeptá, nech ji smazat.

Cena: server s 8 GB stojí řádově 1–2 centy za hodinu plus IPv4. Běh včetně instalace má trvat
jednotky hodin, celkem tedy desítky centů.
