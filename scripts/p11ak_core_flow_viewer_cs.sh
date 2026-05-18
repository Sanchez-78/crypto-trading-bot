#!/bin/bash

# P1.1AK: Prohlížeč Core Flow Logů — zvýrazní skutečné obchodní/učící signály
# Ukazuje CORE FLOW (obchody, učení) vs DIAGNOSTIKA (technické detaily)
# Použití: bash p11ak_core_flow_viewer_cs.sh [--since "30 min ago"] [--color on|off]

set -e

SINCE="${1:--1h}"
if [ "$1" = "--since" ]; then
    SINCE="$2"
fi

COLOR="${3:-on}"
if [ "$2" = "--color" ]; then
    COLOR="$3"
fi

# Zjisti PID služby
PID=$(systemctl show -p MainPID --value cryptomaster 2>/dev/null || echo "NEZNAMY")

echo "============================================================"
echo "PROHLÍŽEČ CORE FLOW LOGŮ"
echo "============================================================"
echo "PID: $PID"
echo "Od: $SINCE"
echo ""

# Barevné kódy
if [ "$COLOR" = "on" ]; then
    BOLD='\033[1m'
    ZELENA='\033[92m'
    MODRA='\033[94m'
    ZLUTA='\033[93m'
    CERVENA='\033[91m'
    CYAN='\033[96m'
    PURPUROVA='\033[95m'
    RESET='\033[0m'
    DIM='\033[2m'
else
    BOLD=""
    ZELENA=""
    MODRA=""
    ZLUTA=""
    CERVENA=""
    CYAN=""
    PURPUROVA=""
    RESET=""
    DIM=""
fi

# Dočasný soubor pro logy
LOG_TMP="$(mktemp /tmp/p11ak_viewer_XXXXXX 2>/dev/null || mktemp)"
trap 'rm -f "$LOG_TMP"' EXIT

# Přečti journal do dočasného souboru
journalctl -u cryptomaster --since "$SINCE" --no-pager 2>/dev/null | grep "cryptomaster\[$PID\]" > "$LOG_TMP" 2>&1 || true

echo -e "${BOLD}=== CORE FLOW: Obchody a Učení ===${RESET}"
echo ""

# VSTUPY
echo -e "${ZELENA}${BOLD}→ VSTUPY:${RESET}"
grep "PAPIROVY_VSTUP\|PAPIROVY_NEG_EV_PROBE_PRIJAT" "$LOG_TMP" 2>/dev/null | tail -20 | while read line; do
    symbol=$(echo "$line" | grep -oE "symbol=[^ ]+" | cut -d= -f2)
    bucket=$(echo "$line" | grep -oE "bucket=[^ ]+" | cut -d= -f2)
    ev=$(echo "$line" | grep -oE "ev=[^ ]+" | cut -d= -f2)
    echo -e "  ${ZELENA}✓${RESET} $symbol bucket=$bucket ev=$ev"
done

echo ""

# VYSTUPY (jen [PAPER_EXIT] řádky, vyloučit kvalitní/atribučí diagnostiku)
echo -e "${PURPUROVA}${BOLD}← VÝSTUPY:${RESET}"
grep "\\[PAPER_EXIT\\]" "$LOG_TMP" 2>/dev/null | grep -v "PAPER_TRAIN_QUALITY_EXIT\|PAPER_TRAIN_ECON_ATTRIB" | tail -20 | while read line; do
    symbol=$(echo "$line" | grep -oE "symbol=[^ ]+" | cut -d= -f2)
    outcome=$(echo "$line" | grep -oE "outcome=[^ ]+" | cut -d= -f2)
    pnl=$(echo "$line" | grep -oE "pnl_pct=[^ ]+" | cut -d= -f2)
    reason=$(echo "$line" | grep -oE "reason=[^ ]+" | cut -d= -f2)
    # Tisk jen pokud jsou všechna povinná pole přítomna
    if [ -n "$symbol" ] && [ -n "$outcome" ] && [ -n "$pnl" ] && [ -n "$reason" ]; then
        echo -e "  ${PURPUROVA}✓${RESET} $symbol outcome=$outcome pnl=$pnl reason=$reason"
    fi
done

echo ""

# AKTUALIZACE UČENÍ
echo -e "${CYAN}${BOLD}📚 AKTUALIZACE UČENÍ:${RESET}"
grep "\\[LM_STATE_AFTER_UPDATE\\]" "$LOG_TMP" 2>/dev/null | tail -10 | while read line; do
    symbol=$(echo "$line" | grep -oE "symbol=[^ ]+" | cut -d= -f2)
    regime=$(echo "$line" | grep -oE "regime=[^ ]+" | cut -d= -f2)
    before=$(echo "$line" | grep -oE "before_total=[0-9]+" | cut -d= -f2)
    after=$(echo "$line" | grep -oE "after_total=[0-9]+" | cut -d= -f2)
    outcome=$(echo "$line" | grep -oE "outcome=[^ ]+" | cut -d= -f2)
    if [ -n "$symbol" ] && [ -n "$before" ] && [ -n "$after" ]; then
        echo -e "  ${CYAN}✓${RESET} $symbol $regime before_total=$before after_total=$after outcome=$outcome"
    fi
done

echo ""

# CHYBY/NESHODY (CERVENA)
echo -e "${CERVENA}${BOLD}⚠️  CHYBY A NESHODY:${RESET}"
ERROR_COUNT=$(grep -E "NESHODA|STAV_NESHODA|VYSTUP_CHYBEJICI|LM_AKTUALIZACE_NESHODA" "$LOG_TMP" 2>/dev/null | wc -l)
if [ "$ERROR_COUNT" -gt 0 ]; then
    grep -E "NESHODA|STAV_NESHODA|VYSTUP_CHYBEJICI|LM_AKTUALIZACE_NESHODA" "$LOG_TMP" 2>/dev/null | tail -10 | while read line; do
        msg=$(echo "$line" | sed 's/.*cryptomaster\[[0-9]*\]: //' | cut -c1-100)
        echo -e "  ${CERVENA}✗${RESET} $msg"
    done
else
    echo -e "  ${ZELENA}Žádné${RESET}"
fi

echo ""
echo -e "${BOLD}=== DIAGNOSTIKA: Technické Detaily ===${RESET}"
echo ""

# PŘEHLED POČITADEL
echo -e "${DIM}Počitadla (posledních 60 minut):${RESET}"
VSTUPY=$(grep "PAPIROVY_VSTUP" "$LOG_TMP" 2>/dev/null | wc -l)
VYSTUPY=$(grep "PAPIROVY_VYSTUP" "$LOG_TMP" 2>/dev/null | wc -l)
SONDY=$(grep "PAPIROVY_NEG_EV_PROBE_PRIJAT" "$LOG_TMP" 2>/dev/null | wc -l)
UCENI=$(grep "LM_STAV_AKTUALIZACE\|UCENI_AKTUALIZACE" "$LOG_TMP" 2>/dev/null | wc -l)
ODMITNUTY=$(grep "ODMIT" "$LOG_TMP" 2>/dev/null | wc -l)
PRESKOCENO=$(grep "PRESKOCENO" "$LOG_TMP" 2>/dev/null | wc -l)

echo -e "  ${DIM}PAPIROVY_VSTUP:            $VSTUPY${RESET}"
echo -e "  ${DIM}PAPIROVY_VYSTUP:           $VYSTUPY${RESET}"
echo -e "  ${DIM}PAPIROVY_NEG_EV_SONDA:     $SONDY${RESET}"
echo -e "  ${DIM}LM_STAV_AKTUALIZACE:       $UCENI${RESET}"
echo -e "  ${DIM}ODMITNUT:                  $ODMITNUTY${RESET}"
echo -e "  ${DIM}PRESKOCENO:                $PRESKOCENO${RESET}"

echo ""

# THROTTLE LOGY (potlačeny v základu)
echo -e "${DIM}Tlumené/Diagnostické Logy (skryté):${RESET}"
echo -e "  ${DIM}Použij 'journalctl' přímo pro HBLOCK, EXPLORE_SKIP, atd.${RESET}"

echo ""
echo "============================================================"
