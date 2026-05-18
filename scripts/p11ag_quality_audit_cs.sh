#!/bin/bash

# P1.1AK: Audit kvality založený na snímku s atomárními čteními
# Analyzuje logy papírového tréninku z jediného snímku journalctl
# Použití: bash p11ag_quality_audit_cs.sh [--since "30 min ago"]

set -e

# P1.1AL: Bezpečné pomocné funkce pro počítání
na_cislo() {
    local v
    v="$(printf '%s\n' "$1" | head -n1 | tr -dc '0-9')"
    [ -n "$v" ] && echo "$v" || echo 0
}

pocet_vzoru() {
    local vzor="$1"
    local hodnota
    hodnota="$(grep -E "$vzor" "$LOG_TMP" 2>/dev/null | wc -l | tr -d '[:space:]')"
    na_cislo "$hodnota"
}

# Analyzuj argumenty
SINCE="${2:--1h}"
if [ "$1" = "--since" ]; then
    SINCE="$2"
fi

# Bezpečně zjisti PID služby
zjisti_pid() {
    systemctl show -p MainPID --value cryptomaster 2>/dev/null || echo "NEZNAMY"
}

# Zjisti čas spuštění služby
zjisti_cas_spusteni() {
    systemctl show -p ActiveEnterTimestamp --value cryptomaster 2>/dev/null || echo "neznamy"
}

# Zjisti git HEAD
zjisti_git_head() {
    git -C /opt/cryptomaster rev-parse --short HEAD 2>/dev/null || echo "N/A"
}

PID=$(zjisti_pid)
CAS_SPUSTENI=$(zjisti_cas_spusteni)
GIT_HEAD=$(zjisti_git_head)

echo "============================================================"
echo "P1.1AK Audit Kvality (Založený na Snímku)"
echo "============================================================"
echo "PID služby: $PID"
echo "Spuštění služby: $CAS_SPUSTENI"
echo "Git HEAD: $GIT_HEAD"
echo "Od: $SINCE"
echo ""

# P1.1AK: Vytvoř atomární snímek výstupu journalctl
LOG_TMP="$(mktemp /tmp/p11ak_audit_XXXXXX 2>/dev/null || mktemp)"
trap 'rm -f "$LOG_TMP"' EXIT

# Přečti journal jednou do souboru, filtruj podle PID
if ! journalctl -u cryptomaster --since "$SINCE" --no-pager 2>/dev/null | grep "cryptomaster\[$PID\]" > "$LOG_TMP" 2>&1; then
    # Fallback: zkus se start time služby
    journalctl -u cryptomaster --since "$CAS_SPUSTENI" --no-pager 2>/dev/null | grep "cryptomaster\[$PID\]" > "$LOG_TMP" 2>&1 || true
fi

# Zjisti metadata snímku
SNAP_LINES=$(wc -l < "$LOG_TMP" 2>/dev/null || echo "0")
SNAP_PRVNI=$(head -1 "$LOG_TMP" 2>/dev/null | awk '{print $1" "$2}' || echo "neznamy")
SNAP_POSLEDNI=$(tail -1 "$LOG_TMP" 2>/dev/null | awk '{print $1" "$2}' || echo "neznamy")

echo "Řádků snímku: $SNAP_LINES"
echo "První čas snímku: $SNAP_PRVNI"
echo "Poslední čas snímku: $SNAP_POSLEDNI"
echo ""

# Všechna počitadla používají soubor snímku (žádná další volání journalctl)
pocet_logu() {
    local filtr="$1"
    pocet_vzoru "$filtr"
}

echo "Počty Logů:"
echo "-------"

# Základní počitadla pipeline
VSTUPY=$(na_cislo "$(pocet_logu "PAPIROVY_VSTUP")")
VSTUP_KVALITA=$(na_cislo "$(pocet_logu "PAPIROVY_VSTUP_KVALITA")")
VYSTUP_KVALITA=$(na_cislo "$(pocet_logu "PAPIROVY_VYSTUP_KVALITA")")
VYSTUP_KVALITA_CHYBEJICI=$(na_cislo "$(pocet_logu "PAPIROVY_VYSTUP_KVALITA_CHYBEJICI")")
NESHODY=$(na_cislo "$(pocet_logu "PAPIROVY_KVALITA_NESHODA")")
ANOMALIE=$(na_cislo "$(pocet_logu "PAPIROVY_ANOMALIE")")
SOUHRNY=$(na_cislo "$(pocet_logu "PAPIROVY_KVALITA_SOUPIS")")
VYSTUPY=$(na_cislo "$(pocet_logu "PAPIROVY_VYSTUP")")
UCENI=$(na_cislo "$(pocet_logu "UCENI_AKTUALIZACE ok=True")")
LM_STAV_PO=$(na_cislo "$(pocet_logu "LM_STAV_PO_AKTUALIZACI")")
LM_NESHODA=$(na_cislo "$(pocet_logu "LM_AKTUALIZACE_NESHODA")")
SKORE_CHYBEJICI=$(na_cislo "$(pocet_logu "PAPIROVY_SKORE_CHYBEJICI_KONTEXT")")

# P1.1AK: Rozděluj počitadla podle zdroje a tréninku
VSTUPY_SKUTECNE=$(na_cislo "$(grep "PAPIROVY_VSTUP" "$LOG_TMP" 2>/dev/null | grep -c "bucket=C_WEAK_EV_TRAIN" 2>/dev/null || echo "0")")
VYSTUPY_TRENING=$(na_cislo "$(grep "PAPIROVY_VYSTUP" "$LOG_TMP" 2>/dev/null | grep -c "trening_bucket=C_WEAK_EV_TRAIN" 2>/dev/null || echo "0")")
VYSTUP_KVALITA_TRENING=$(na_cislo "$(grep "PAPIROVY_VYSTUP_KVALITA" "$LOG_TMP" 2>/dev/null | grep -c "trening_bucket=C_WEAK_EV_TRAIN" 2>/dev/null || echo "0")")
VSTUP_KVALITA_TIMEOUT=$(na_cislo "$(pocet_logu "PAPIROVY_VSTUP_KVALITA.*duvod=TIMEOUT_BEZ_CENY")")
BYPASS_CENY_HRANA=$(na_cislo "$(pocet_logu "BYPASS_CENY_HRANA")")
EKON_SOUPIS=$(na_cislo "$(pocet_logu "PAPIROVY_TRENING_EKON_SOUPIS")")

# P1.1AM: Atribuce a bypass log split
EKON_ATRIBUCE=$(na_cislo "$(pocet_logu "PAPIROVY_TRENING_EKON_ATRIBUCE")")
ATTR_POPLATEK_DOMINUJE=$(na_cislo "$(pocet_logu "atribuce=POPLATEK_DOMINUJE_POHYB")")
ATTR_TP_MALA_VZDAL=$(na_cislo "$(pocet_logu "atribuce=TP_MALA_VZDALENOST_PRO_MFE")")
ATTR_BYPASS_ZTRATA=$(na_cislo "$(pocet_logu "atribuce=BYPASS_CENY_HRANA_ZTRATA")")
ATTR_SPATN_SMER=$(na_cislo "$(pocet_logu "atribuce=SPATNY_SMER")")
ATTR_MALA_OBJEM=$(na_cislo "$(pocet_logu "atribuce=MALY_OBJEM_TIMEOUT")")
BYPASS_KANDIDAT=$(na_cislo "$(pocet_logu "BYPASS_CENY_HRANA_KANDIDAT")")
BYPASS_PRIJAT=$(na_cislo "$(pocet_logu "BYPASS_CENY_HRANA_PRIJAT")")

# P1.1AO: Diagnostika hladovění studentů
ODMIT_NEG_EV=$(na_cislo "$(pocet_logu "ODMIT_NEGATIVNI_EV")")
NEZNAM_BUCKET_PRESKOC=$(na_cislo "$(pocet_logu "PAPIROVY_PRUZKUM_PRESKOC.*bez_bucket_shody")")
HLADOVENI_STAV=$(na_cislo "$(pocet_logu "PAPIROVY_HLADOVENI_STAV")")
STAV_NESHODA=$(na_cislo "$(pocet_logu "PAPIROVY_STAV_NESHODA")")
NEG_EV_SONDA_PRIJATA=$(na_cislo "$(pocet_logu "PAPIROVY_NEG_EV_SONDA_PRIJATA")")
NEG_EV_SONDA_BLOKOVANA=$(na_cislo "$(grep "PAPIROVY_NEG_EV_SONDA_BLOKOVANA\|sonda_limit_" "$LOG_TMP" 2>/dev/null | wc -l | tr -d '[:space:]')")
NEG_EV_SONDA_VYSTUPY=$(na_cislo "$(grep "PAPIROVY_VYSTUP" "$LOG_TMP" 2>/dev/null | grep -c "C_NEG_EV_SONDA" 2>/dev/null || echo "0")")

echo "PAPIROVY_VSTUP:                     $VSTUPY"
echo "PAPIROVY_VSTUP_SKUTECNY (trening):  $VSTUPY_SKUTECNE"
echo "PAPIROVY_VSTUP_KVALITA:             $VSTUP_KVALITA"
echo "PAPIROVY_VYSTUP_KVALITA:            $VYSTUP_KVALITA"
echo "PAPIROVY_VYSTUP_KVALITA_CHYBEJICI:  $VYSTUP_KVALITA_CHYBEJICI"
echo "PAPIROVY_KVALITA_NESHODA:           $NESHODY"
echo "PAPIROVY_ANOMALIE:                  $ANOMALIE"
echo "PAPIROVY_KVALITA_SOUPIS:            $SOUHRNY"
echo "PAPIROVY_VYSTUP:                    $VYSTUPY"
echo "PAPIROVY_VYSTUP_TRENING_BUCKET:     $VYSTUPY_TRENING"
echo "PAPIROVY_VYSTUP_KVALITA_TRENING:    $VYSTUP_KVALITA_TRENING"
echo "PAPIROVY_VSTUP_KVALITA_TIMEOUT:     $VSTUP_KVALITA_TIMEOUT"
echo "UCENI_AKTUALIZACE ok=True:          $UCENI"
echo "LM_STAV_PO_AKTUALIZACI:             $LM_STAV_PO"
echo "LM_AKTUALIZACE_NESHODA:             $LM_NESHODA"
echo "PAPIROVY_SKORE_CHYBEJICI_KONTEXT:   $SKORE_CHYBEJICI"
echo "BYPASS_CENY_HRANA:                  $BYPASS_CENY_HRANA"
echo "PAPIROVY_TRENING_EKON_SOUPIS:       $EKON_SOUPIS"
echo ""

echo "Počty Atribucí:"
echo "-------"
echo "PAPIROVY_TRENING_EKON_ATRIBUCE:     $EKON_ATRIBUCE"
echo "ATTR_POPLATEK_DOMINUJE_POHYB:       $ATTR_POPLATEK_DOMINUJE"
echo "ATTR_TP_MALA_VZDALENOST_PRO_MFE:    $ATTR_TP_MALA_VZDAL"
echo "ATTR_BYPASS_CENY_HRANA_ZTRATA:      $ATTR_BYPASS_ZTRATA"
echo "ATTR_SPATNY_SMER:                   $ATTR_SPATN_SMER"
echo "ATTR_MALY_OBJEM_TIMEOUT:            $ATTR_MALA_OBJEM"
echo "BYPASS_CENY_HRANA_KANDIDAT:         $BYPASS_KANDIDAT"
echo "BYPASS_CENY_HRANA_PRIJAT:           $BYPASS_PRIJAT"
echo ""

echo "Hladovění Studentů:"
echo "-------"
echo "ODMITNUT_NEGATIVNI_EV:              $ODMIT_NEG_EV"
echo "NEZNAM_BUCKET_PRESKOC:              $NEZNAM_BUCKET_PRESKOC"
echo "HLADOVENI_STAV_LOGY:                $HLADOVENI_STAV"
echo "STAV_NESHODA_LOGY:                  $STAV_NESHODA"
echo "NEG_EV_SONDA_PRIJATA:               $NEG_EV_SONDA_PRIJATA"
echo "NEG_EV_SONDA_BLOKOVANA:             $NEG_EV_SONDA_BLOKOVANA"
echo "NEG_EV_SONDA_VYSTUPY:               $NEG_EV_SONDA_VYSTUPY"
echo ""

# P1.1AK: Korelace Trade-ID (ověření kvality výstupu per-trade)
echo "Korelace Trade-ID:"
echo "-------"
CHYBEJICI_POCET=0
CHYBEJICI_VYSTUPY=""
while read -r tid sym; do
    if ! grep -q "PAPIROVY_VYSTUP_KVALITA.*trade_id=$tid" "$LOG_TMP" 2>/dev/null; then
        CHYBEJICI_POCET=$((CHYBEJICI_POCET+1))
        CHYBEJICI_VYSTUPY="${CHYBEJICI_VYSTUPY}  trade_id=$tid symbol=$sym\n"
    fi
done < <(grep "PAPIROVY_VYSTUP.*trening_bucket=C_WEAK_EV_TRAIN" "$LOG_TMP" 2>/dev/null \
    | grep -oE "trade_id=[^ ]+ symbol=[^ ]+" \
    | awk '{print substr($1,10)" "substr($2,8)}')

echo "KVALITA_VYSTUP_CHYBEJICI_PODLE_TRADE_ID: $CHYBEJICI_POCET"
if [ "$CHYBEJICI_POCET" -gt 0 ]; then
    echo "Chybějící kvalitní výstupy:"
    echo -e "$CHYBEJICI_VYSTUPY"
fi
echo ""

# LM Stav
echo "LM Stav:"
echo "-------"
LM_POCET=$(grep "Celkem obchodů v LM" "$LOG_TMP" 2>/dev/null | tail -1 | grep -oE "[0-9]+" | tail -1 || true)
LM_POCET=$(na_cislo "${LM_POCET:-0}")
echo "Poslední Celkem obchodů v LM: $LM_POCET"
echo ""

# Diagnostika
echo "Diagnostika:"
echo "-------"

if [ "$VSTUPY" -gt 0 ] && [ "$VSTUP_KVALITA" -eq 0 ]; then
    echo "⚠️  [NESHODA] Existují vstupy ($VSTUPY) ale bez quality_entry logů!"
elif [ "$VSTUPY" -eq 0 ]; then
    echo "ℹ️  Žádné papírové tréninky vstup v tomto okně"
else
    if [ "$VSTUP_KVALITA" -ge "$VSTUPY" ]; then
        echo "✓ Logy kvalitních vstupů se shodují s počtem vstupů (vstupy=$VSTUPY kvalita=$VSTUP_KVALITA)"
    else
        echo "⚠️  Neshoda v počtu logů kvalitního vstupu: $VSTUPY vstupů, $VSTUP_KVALITA logů kvality"
    fi
fi

if [ "$NESHODY" -gt 0 ]; then
    echo "⚠️  Nalezeny $NESHODY neshody vstupů kvality"
fi

if [ "$VYSTUP_KVALITA_CHYBEJICI" -gt 0 ]; then
    echo "⚠️  Nalezeny $VYSTUP_KVALITA_CHYBEJICI chybějící logy kvalitního výstupu (mělo by být 0)"
fi

if [ "$CHYBEJICI_POCET" -gt 0 ]; then
    echo "⚠️  Nalezeno $CHYBEJICI_POCET chybějících kvalitních výstupů podle trade_id"
fi

if [ "$ANOMALIE" -gt 0 ]; then
    echo "⚠️  Nalezeny $ANOMALIE anomálie kvality"
fi

if [ "$SKORE_CHYBEJICI" -gt 0 ]; then
    echo "ℹ️  Nalezeno $SKORE_CHYBEJICI logů chybějícího kontextu skóre"
fi

if [ "$BYPASS_CENY_HRANA" -gt 0 ]; then
    echo "ℹ️  Nalezeno $BYPASS_CENY_HRANA logů bypass ceny hrana"
fi

if [ "$VYSTUPY_TRENING" -gt 0 ] && [ "$VYSTUP_KVALITA_TRENING" -eq 0 ]; then
    echo "⚠️  Existují tréninky výstupy ($VYSTUPY_TRENING) ale bez tréninků quality_exit logů!"
elif [ "$VYSTUPY_TRENING" -gt 0 ]; then
    echo "✓ Logy tréninku výstupů jsou přítomny (vystupy=$VYSTUPY_TRENING kvalita=$VYSTUP_KVALITA_TRENING)"
fi

if [ "$VYSTUPY_TRENING" -gt 0 ] && [ "$UCENI" -eq 0 ] && [ "$LM_STAV_PO" -eq 0 ]; then
    echo "⚠️  Existují tréninky výstupy ale bez logů aktualizace učení"
elif [ "$VYSTUPY_TRENING" -gt 0 ] && ([ "$UCENI" -gt 0 ] || [ "$LM_STAV_PO" -gt 0 ]); then
    echo "✓ Logy aktualizace učení jsou přítomny (UCENI_AKTUALIZACE=$UCENI LM_STAV=$LM_STAV_PO)"
fi

if [ "$LM_NESHODA" -gt 0 ]; then
    echo "⚠️  Nalezeny $LM_NESHODA neshody aktualizace LM (mělo by být 0)"
fi

if [ "$EKON_SOUPIS" -gt 0 ]; then
    echo "✓ Ekonomický soupis je zalogován (počet=$EKON_SOUPIS)"
fi

if [ "$HLADOVENI_STAV" -gt 0 ] && [ "$NEG_EV_SONDA_PRIJATA" -eq 0 ]; then
    echo "⚠️  Hladovění detekováno ale žádné sondy přijaty — zkontroluj limity/podmínky"
fi
if [ "$NEG_EV_SONDA_PRIJATA" -gt 0 ] && [ "$NEG_EV_SONDA_VYSTUPY" -eq 0 ]; then
    echo "ℹ️  Vstupy sond existují ale žádné výstupy zatím (obchody stále otevřeny)"
fi
if [ "$NEG_EV_SONDA_VYSTUPY" -gt 0 ]; then
    echo "✓ Výstupy sond dosaženy (vystupy=$NEG_EV_SONDA_VYSTUPY)"
fi

echo ""
echo "Ukázkové logy (posledních 25 kvalitních событí):"
echo "-------"
grep -E "PAPIROVY_VSTUP_KVALITA|PAPIROVY_VYSTUP_KVALITA|PAPIROVY_KVALITA_SOUPIS|PAPIROVY_ANOMALIE|PAPIROVY_SKORE_CHYBEJICI_KONTEXT|PAPIROVY_TRENING_EKON_SOUPIS|BYPASS_CENY_HRANA" "$LOG_TMP" 2>/dev/null | tail -25

echo ""
echo "Ukázkové logy atribucí (posledních 10):"
echo "-------"
grep "PAPIROVY_TRENING_EKON_ATRIBUCE" "$LOG_TMP" 2>/dev/null | tail -10

echo ""
echo "============================================================"
