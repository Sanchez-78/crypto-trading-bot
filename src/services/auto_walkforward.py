from src.services.firebase_client import load_history, load_auditor_state, save_auditor_state
import time

_LAST_RUN = 0

def calibrate_limits():
    """
    Auto-Walk-Forward Optimizace (AWO)
    Využívá historická data MAE (Maximum Adverse Excursion) pro dynamické posouvání Stop-Loss hranice.
    Každý trh se mění, místo tipování konstant (-0.40%) si algoritmus zpětně odsimuluje 
    přesnou historickou equity křivku a použije SL z nejziskovější nalezené varianty.
    """
    global _LAST_RUN
    # Spustit kalibraci pouze jednou za 12 hodin (nebo na tvrdý boot)
    if time.time() - _LAST_RUN < 43200:
        return
        
    trades = load_history(150)
    # Systém potřebuje plně zahřátá HF Quant data (alespoň 30 obchodů vybavených MAE senzory)
    valid_trades = [t for t in trades if "mae" in t and abs(float(t["mae"])) > 0.0]
    
    if len(valid_trades) < 30:
        return

    best_equity = -99999
    best_sl = 0.004
    
    # Testujeme SL od 0.15% do 0.80% (v krocích po 0.05%)
    sl_candidates = [x / 10000.0 for x in range(15, 85, 5)]
    
    for test_sl in sl_candidates:
        hypothetical_equity = 0.0
        
        for t in valid_trades:
            mae = float(t["mae"])
            actual_profit_pct = float(t.get("profit", 0.0)) / max(float(t.get("price", 1)), 1e-9)
            
            # Pokud MAE dosáhlo testovaného SL už předtím, než se obchod stihl zavřít v budoucnu
            # simulujeme dřívější ustřihnutí ztráty limitní páskou:
            if mae <= -test_sl:
                hypothetical_equity -= test_sl
            else:
                # Obchod přežil náš testovaný limit a zavřel se tam, kde doopravdy, bereme plný zisk
                hypothetical_equity += actual_profit_pct
                
        if hypothetical_equity > best_equity:
            best_equity = hypothetical_equity
            best_sl = test_sl

    print(f"🤖 AUTO-WALKFORWARD: Z předchozích MFE/MAE dat nalezen optimální SL limit: {best_sl*100:.2f}%")
    
    state = load_auditor_state()
    state["min_sl_pct"] = best_sl
    state["last_calibrated"] = time.time()
    save_auditor_state(state)
    
    _LAST_RUN = time.time()
    _CALIBRATED_SL = best_sl

_CALIBRATED_SL = 0.004

def get_best_sl():
    global _CALIBRATED_SL, _LAST_RUN
    if time.time() - _LAST_RUN > 43200:
        calibrate_limits()
    return _CALIBRATED_SL

