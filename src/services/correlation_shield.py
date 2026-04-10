import math
import logging
from src.services.signal_generator import prices

log = logging.getLogger(__name__)

def get_correlation(sym1: str, sym2: str, window: int = 150) -> float:
    """
    Spočte Pearsonovu korelaci klouzavých výnosů mezi dvěma symboly.
    Větší window = delší kontext. Využívá data držená v signal_generatoru.
    """
    hist1 = prices.get(sym1, [])
    hist2 = prices.get(sym2, [])
    
    n = min(len(hist1), len(hist2), window)
    if n < 30:
        return 0.0
        
    x = hist1[-n:]
    y = hist2[-n:]
    
    # Práce s výnosy místo absolutních cen pro reálnou korelaci trendů
    rets1 = [x[i]/x[i-1] - 1 for i in range(1, len(x))]
    rets2 = [y[i]/y[i-1] - 1 for i in range(1, len(y))]
    
    if not rets1 or not rets2:
        return 0.0
        
    mx = sum(rets1) / len(rets1)
    my = sum(rets2) / len(rets2)
    
    cov = sum((rets1[i] - mx) * (rets2[i] - my) for i in range(len(rets1)))
    var_x = sum((xi - mx)**2 for xi in rets1)
    var_y = sum((yi - my)**2 for yi in rets2)
    
    if var_x == 0 or var_y == 0:
        return 0.0
        
    return cov / math.sqrt(var_x * var_y)

def is_safe_correlation(new_sym: str, action: str, open_positions: dict, threshold: float = 0.85) -> bool:
    """
    Vrátí False, pokud je nový vstup (new_sym + action) nebezpečně korelovaný
    s nějakou stávající otevřenou pozicí stejného směru. Zabrání to nabalení 
    expozice do jedné jediné tržní síly (např. dominanci pádu BTC).
    """
    for open_sym, pos in open_positions.items():
        if open_sym == new_sym:
            continue
            
        # Zajímají nás jen zdvojené pozice ve stejném směru (kumulace rizika)
        # Opačné akce (Hedge) jsou naopak vítané, jelikož korelaci zneužívají ve fluktuacích.
        pos_action = pos.get("action") if isinstance(pos, dict) else getattr(pos, "action", None)
        if pos_action == action:
            corr = get_correlation(new_sym, open_sym)
            if corr >= threshold:
                log.info("CORRELATION SHIELD: Blokováno %s. Shoda s %s (%.1f%%)",
                         new_sym, open_sym, corr * 100)
                return False
                
    return True
