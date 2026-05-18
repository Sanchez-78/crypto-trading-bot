"""
V10.13k: Duální Systém Logování — CORE FLOW (obchody/učení) vs DIAGNOSTIKA (technické)

CORE FLOW: Co bot skutečně dělá (jasné, barevné, jednoduché)
  - Vstup signálu/otevření obchodu
  - Výstup obchodu s výsledkem
  - Aktualizace LM (Learning Monitor)
  - Chyby/neshody (červené)
  - Atribuce (žluté)

DIAGNOSTIKA: Proč/jak to funguje (tmavé, skryté, technické)
  - Throttle logy
  - Kontroly kapacit
  - Ověření stavu
  - Vnitřní stav
"""

import logging
import sys
from typing import Optional

# ANSI barevné kódy
class Barvy:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Jasné barvy pro CORE FLOW
    ZELENA = "\033[92m"      # Vstup/úspěch
    MODRA = "\033[94m"       # Info obchodu
    ZLUTA = "\033[93m"       # Atribuce/varování
    CERVENA = "\033[91m"     # Chyba/neshoda
    CYAN = "\033[96m"        # Aktualizace učení
    PURPUROVA = "\033[95m"   # Výstup/uzavření

    # Tmavé barvy pro DIAGNOSTIKU
    TMAVA_ZELENA = "\033[32m"
    TMAVA_MODRA = "\033[34m"
    TMAVA_ZLUTA = "\033[33m"


class CoreFlowFormatterCS(logging.Formatter):
    """Formát CORE FLOW logů s barvou a zdůrazněním."""

    def format(self, record):
        if record.name.startswith("CORE_FLOW"):
            msg = record.getMessage()

            if "VSTUP" in msg or "PRIJAT" in msg:
                color = Barvy.ZELENA + Barvy.BOLD
                prefix = "→ VSTUP"
            elif "VYSTUP" in msg or "UZAVREN" in msg:
                color = Barvy.PURPUROVA + Barvy.BOLD
                prefix = "← VÝSTUP"
            elif "LM_STAV" in msg or "UCENI" in msg:
                color = Barvy.CYAN + Barvy.BOLD
                prefix = "📚 UČENÍ"
            elif "NESHODA" in msg or "CHYBA" in msg or "SELHANI" in msg:
                color = Barvy.CERVENA + Barvy.BOLD
                prefix = "⚠️  CHYBA"
            elif "ATRIBUCE" in msg or "atribuce=" in msg:
                color = Barvy.ZLUTA
                prefix = "📊 ATTR"
            else:
                color = Barvy.MODRA
                prefix = "ℹ️  INFO"

            return f"{color}{prefix:12}{Barvy.RESET} {msg}"

        return record.getMessage()


class DiagnosticsFormatterCS(logging.Formatter):
    """Formát DIAGNOSTIKY logů jako tmavé/skryté."""

    def format(self, record):
        msg = record.getMessage()
        return f"{Barvy.DIM}[DIAG] {msg}{Barvy.RESET}"


# Vytvoř oddělovače logů
_core_flow_logger = None
_diagnostics_logger = None


def _init_loggers():
    """Inicializuj duální systém logování."""
    global _core_flow_logger, _diagnostics_logger

    if _core_flow_logger is not None:
        return

    # CORE FLOW logger (stdout, jasné, důležité)
    _core_flow_logger = logging.getLogger("CORE_FLOW")
    _core_flow_logger.setLevel(logging.INFO)
    _core_flow_logger.propagate = False

    core_handler = logging.StreamHandler(sys.stdout)
    core_handler.setFormatter(CoreFlowFormatterCS())
    _core_flow_logger.addHandler(core_handler)

    # DIAGNOSTIKA logger (stdout, tmavé, technické)
    _diagnostics_logger = logging.getLogger("CORE_FLOW.DIAG")
    _diagnostics_logger.setLevel(logging.DEBUG)
    _diagnostics_logger.propagate = False

    diag_handler = logging.StreamHandler(sys.stdout)
    diag_handler.setFormatter(DiagnosticsFormatterCS())
    _diagnostics_logger.addHandler(diag_handler)


def log_vstup_obchodu(
    symbol: str,
    strana: str,
    cena: float,
    bucket: str,
    zdroj: str,
    ev: float,
    **kwargs
):
    """Zaloguj otevření obchodu (CORE FLOW)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"{symbol:8} {strana:4} @ {cena:10.2f} bucket={bucket:20} zdroj={zdroj:20} ev={ev:+.4f}"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.info(f"PAPIROVY_VSTUP {msg}")


def log_vystup_obchodu(
    symbol: str,
    trade_id: str,
    vysledek: str,
    pnl_pct: float,
    bucket: str,
    duvod: str,
    **kwargs
):
    """Zaloguj zavření obchodu (CORE FLOW)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"trade_id={trade_id} {symbol:8} vysledek={vysledek:8} pnl={pnl_pct:+6.2f}% bucket={bucket:20} duvod={duvod:15}"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.info(f"PAPIROVY_VYSTUP {msg}")


def log_aktualizace_uceni(
    obchody_v_lm: int,
    spolehlivost_kalibrace: Optional[float] = None,
    dominantni_atribuce: Optional[str] = None,
    **kwargs
):
    """Zaloguj aktualizaci LM (CORE FLOW)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"obchody_v_lm={obchody_v_lm}"
    if spolehlivost_kalibrace is not None:
        msg += f" spolehlivost={spolehlivost_kalibrace:.2f}"
    if dominantni_atribuce:
        msg += f" dominantni_atribuce={dominantni_atribuce}"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.info(f"LM_STAV_AKTUALIZACE {msg}")


def log_chyba(typ_chyby: str, zprava: str, **kwargs):
    """Zaloguj chybu/neshodu (CORE FLOW, CERVENA)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"{typ_chyby}: {zprava}"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.warning(f"CHYBA {msg}")


def log_atribuce(
    trade_id: str,
    symbol: str,
    atribuce: str,
    ztrata_pct: float,
    **kwargs
):
    """Zaloguj ekonomickou atribuci (CORE FLOW, ZLUTA)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"trade_id={trade_id} {symbol:8} atribuce={atribuce:25} ztrata={ztrata_pct:+6.2f}%"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.info(f"ATRIBUCE {msg}")


def log_diag(zprava: str, **kwargs):
    """Zaloguj technickou detail (DIAGNOSTIKA, TMAVA)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = zprava
    if extra:
        msg += f" {extra}"
    _diagnostics_logger.debug(msg)


# Exportuj pro použití v ostatních modulech
__all__ = [
    "log_vstup_obchodu",
    "log_vystup_obchodu",
    "log_aktualizace_uceni",
    "log_chyba",
    "log_atribuce",
    "log_diag",
]
