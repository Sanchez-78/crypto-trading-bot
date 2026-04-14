# CryptoMaster — Learning Monitor Fix Prompt
# Python 3.11+ | Append to existing bot | Apply blocks in order
# Context: Score=0/100, TIMING=331(67%), LOSS_CLUSTER=84(17%), FAST_FAIL=69(14%), QUIET_RSI=11(2%)
# WR: BTC_BULL=21%, BNB_BEAR=25%, WRP_BEAR=17% — all catastrophic (<30%)
# conv=0 all pairs — signals generated but NONE convert to trades → score has nothing to learn from
# Root causes: 1)timing filter unimplemented 2)LOSS_CLUSTER over-blocking 3)model trades against market

## B15: loss_cluster_filter.py — dynamic loss protection
# LOSS_CLUSTER=84 means protective mechanism fires too aggressively
# Distinguish: protective (would-have-lost) vs opportunity-cost (would-have-won)
# After 200+ signals: analyze which LOSS_CLUSTER blocks were correct → calibrate threshold
```python
from datetime import datetime,timedelta
from collections import deque
from bot_types import Trade,TradeResult,CloseReason
from dataclasses import dataclass,field

@dataclass
class LossClusterConfig:
    max_consec_losses:int=3         # block after N consecutive losses
    lookback_hours:float=4.0        # sliding window for recency
    cooldown_minutes:int=30         # how long to pause after cluster detected
    min_trades_required:int=5       # don't block if insufficient history
    severity_multiplier:float=1.5   # scale cooldown by loss magnitude

class LossClusterFilter:
    """
    Blocks entries during loss streaks but with regime-awareness.
    Distinguishes protective blocks from missed opportunities via audit log.
    LOSS_CLUSTER target: 84→30 blocks while keeping protective accuracy >70%.
    """
    def __init__(self,cfg:LossClusterConfig=None):
        self.cfg=cfg or LossClusterConfig()
        self._blocked_until:dict[str,datetime]={}  # symbol→unblock_time
        self._audit:deque=deque(maxlen=500)         # (timestamp,symbol,blocked,reason,was_correct)

    def should_block(self,symbol:str,recent_trades:list[Trade],regime:str="RANGING")->tuple[bool,str]:
        # Regime-aware: TRENDING allows faster re-entry (trend continuation valid)
        max_losses=self.cfg.max_consec_losses
        if regime=="TRENDING": max_losses=max(max_losses+1,5)  # more lenient: trends persist
        if regime=="VOLATILE": max_losses=max(max_losses-1,1)  # stricter: volatile=unpredictable

        # Check existing block
        if symbol in self._blocked_until:
            rem=(self._blocked_until[symbol]-datetime.now()).total_seconds()
            if rem>0: return True,f"LOSS_CLUSTER:cooldown {rem:.0f}s"
            del self._blocked_until[symbol]

        # Insufficient history → don't block (avoid blocking new pairs)
        closed=[t for t in recent_trades if t.close_reason!=CloseReason.VALIDATION]
        if len(closed)<self.cfg.min_trades_required: return False,""

        # Sliding window: only consider recent_trades within lookback
        cutoff=datetime.now()-timedelta(hours=self.cfg.lookback_hours)
        recent=[t for t in closed if t.closed_at and t.closed_at>cutoff]
        if not recent: return False,""

        # Count consecutive losses from most recent backward
        consec=0
        total_loss_pct=0.0
        for t in reversed(recent):
            if t.result==TradeResult.LOSS:
                consec+=1; total_loss_pct+=abs(t.net_pnl_pct)
            else: break

        if consec>=max_losses:
            # Scale cooldown by loss magnitude
            base_cd=self.cfg.cooldown_minutes*60
            scaled_cd=int(base_cd*(1+total_loss_pct/2*self.cfg.severity_multiplier))
            self._blocked_until[symbol]=datetime.now()+timedelta(seconds=scaled_cd)
            reason=f"LOSS_CLUSTER:{consec}losses/{self.cfg.lookback_hours}h pnl={total_loss_pct:.2f}% cd={scaled_cd//60}min"
            self._audit.append({"ts":datetime.now(),"symbol":symbol,"blocked":True,
                                 "consec":consec,"regime":regime,"total_loss":total_loss_pct})
            return True,reason
        return False,""

    def force_unblock(self,symbol:str): self._blocked_until.pop(symbol,None)

    def audit_accuracy(self)->dict:
        """After running: what % of LOSS_CLUSTER blocks were actually protective?"""
        blocks=[a for a in self._audit if a["blocked"]]
        return {"total_blocks":len(blocks),"by_regime":{
            r:sum(1 for b in blocks if b["regime"]==r) for r in ["TRENDING","RANGING","VOLATILE"]}}
```

## B16: learning_monitor.py — score engine + signal quality tracker
# Score=0/100 means no trades complete the full learn cycle
# conv=0 = pipeline rejects everything before trade opens → nothing to score
# Fix: score based on SIGNAL quality too, not just completed trades
```python
import numpy as np
from datetime import datetime,timedelta
from collections import defaultdict,deque
from dataclasses import dataclass,field
from bot_types import Trade,TradeResult,TradeSignal,Direction,CloseReason

@dataclass
class PairStats:
    symbol:str; direction:str
    n:int=0; wins:int=0; total_pnl:float=0.0
    ev:float=0.0; wr:float=0.0; conv:int=0  # conv=trades that actually opened
    rejection_counts:dict=field(default_factory=dict)
    score:float=0.0

class LearningMonitor:
    """
    Tracks signal quality, rejection patterns, and learning score.
    Score formula: weighted composite of WR(40%) + EV(30%) + conv_rate(20%) + consistency(10%)
    Score=0 diagnosis: conv=0 means signals never pass pipeline → WR/EV can't be measured.
    Fix: add signal_attempted counter separate from trades_opened.
    """
    SCORE_WEIGHTS={"wr":0.40,"ev":0.30,"conv":0.20,"consistency":0.10}
    MIN_TRADES_FOR_SCORE=10   # need ≥10 completed trades to compute meaningful score
    WR_THRESHOLD_DISABLE=0.30 # auto-disable direction if WR<30% after ≥20 trades
    WR_THRESHOLD_GOOD=0.55    # direction considered reliable above this

    def __init__(self):
        self._pair_stats:dict[str,PairStats]={}
        self._rejection_log:deque=deque(maxlen=2000)
        self._signal_log:deque=deque(maxlen=2000)
        self._disabled_directions:set=set()  # "BTC_BULL", "XRP_BEAR" etc.
        self._score_history:deque=deque(maxlen=100)

    # ── Logging ───────────────────────────────────────────────────────────────

    def log_signal(self,signal:TradeSignal,decision:str,meta:dict):
        """Call after every pipeline.evaluate() — whether accepted or rejected."""
        key=f"{signal.symbol}_{signal.direction.value}"
        entry={"ts":datetime.now(),"symbol":signal.symbol,"direction":signal.direction.value,
               "decision":decision,"strength":signal.expected_value,
               "regime":signal.regime,"atr":signal.atr}
        self._signal_log.append(entry)
        if key not in self._pair_stats:
            self._pair_stats[key]=PairStats(signal.symbol,signal.direction.value)
        ps=self._pair_stats[key]
        if decision in("ENTER","ENTER_REDUCED"): ps.conv+=1
        else:
            r=ps.rejection_counts; r[decision]=r.get(decision,0)+1

    def log_rejection(self,symbol:str,direction:str,reason:str,regime:str):
        self._rejection_log.append({"ts":datetime.now(),"symbol":symbol,
                                    "direction":direction,"reason":reason,"regime":regime})

    def log_trade_closed(self,trade:Trade):
        key=f"{trade.symbol}_{trade.direction.value}"
        if key not in self._pair_stats:
            self._pair_stats[key]=PairStats(trade.symbol,trade.direction.value)
        ps=self._pair_stats[key]
        ps.n+=1
        if trade.result==TradeResult.WIN: ps.wins+=1
        ps.total_pnl+=trade.net_pnl_pct
        ps.wr=ps.wins/ps.n if ps.n>0 else 0.0
        ps.ev=ps.total_pnl/ps.n if ps.n>0 else 0.0
        self._update_score(ps)
        self._check_auto_disable(key,ps)

    # ── Score Calculation ─────────────────────────────────────────────────────

    def _update_score(self,ps:PairStats):
        if ps.n<self.MIN_TRADES_FOR_SCORE: ps.score=0.0; return
        # WR component: 0=0%, 1=100% scaled to 0-1
        wr_s=ps.wr
        # EV component: normalized, cap at ±2%
        ev_s=np.clip((ps.ev+2)/4,0,1)
        # Conv rate: signals that actually opened / total signals attempted
        total_signals=ps.conv+sum(ps.rejection_counts.values())
        conv_s=ps.conv/total_signals if total_signals>0 else 0
        # Consistency: std of rolling pnl (lower=better), normalized
        # Simplified: use wr stability proxy
        consistency_s=min(1.0,ps.n/50)*wr_s  # improves as n grows
        ps.score=100*(self.SCORE_WEIGHTS["wr"]*wr_s+self.SCORE_WEIGHTS["ev"]*ev_s+
                      self.SCORE_WEIGHTS["conv"]*conv_s+self.SCORE_WEIGHTS["consistency"]*consistency_s)
        self._score_history.append({"ts":datetime.now(),"score":ps.score,"pair":ps.symbol})

    def _check_auto_disable(self,key:str,ps:PairStats):
        """Auto-disable direction if WR catastrophically low after sufficient trades."""
        if ps.n>=20 and ps.wr<self.WR_THRESHOLD_DISABLE:
            if key not in self._disabled_directions:
                self._disabled_directions.add(key)
                import logging; logging.getLogger(__name__).warning(
                    f"AUTO_DISABLE {key}: WR={ps.wr:.0%} n={ps.n} — direction suspended until manual review")

    def is_direction_disabled(self,symbol:str,direction:str)->bool:
        return f"{symbol}_{direction}" in self._disabled_directions

    def manual_reenable(self,symbol:str,direction:str): self._disabled_directions.discard(f"{symbol}_{direction}")

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def global_score(self)->float:
        """Weighted average score across all active pairs with ≥MIN_TRADES."""
        scored=[ps for ps in self._pair_stats.values() if ps.n>=self.MIN_TRADES_FOR_SCORE]
        if not scored: return 0.0
        return np.mean([ps.score for ps in scored])

    def rejection_breakdown(self)->dict:
        from collections import Counter
        reasons=[e["reason"] for e in self._rejection_log]
        return dict(Counter(reasons).most_common(10))

    def conv_rate(self)->float:
        """What % of signals actually open a trade."""
        total=len(self._signal_log)
        opens=sum(1 for s in self._signal_log if s["decision"] in("ENTER","ENTER_REDUCED"))
        return opens/total if total>0 else 0.0

    def diagnose(self)->dict:
        """Full diagnostic report — call when score=0."""
        rb=self.rejection_breakdown()
        top_reason=max(rb,key=rb.get) if rb else "none"
        conv=self.conv_rate()
        disabled=list(self._disabled_directions)
        total_signals=len(self._signal_log)
        return {
            "global_score":round(self.global_score(),1),
            "conv_rate_pct":round(conv*100,1),
            "total_signals_seen":total_signals,
            "total_trades_opened":sum(ps.conv for ps in self._pair_stats.values()),
            "rejection_breakdown":rb,
            "top_blocker":top_reason,
            "auto_disabled":disabled,
            "diagnosis":(
                "conv=0: pipeline rejects everything. Fix timing filter first." if conv==0
                else f"low_conv={conv:.0%}: {top_reason} dominates. Loosen that filter."
                if conv<0.1 else "sufficient_conv: check WR and EV quality."
            ),
            "pair_stats":{k:{"wr":f"{ps.wr:.0%}","ev":f"{ps.ev:+.4f}","n":ps.n,
                              "conv":ps.conv,"score":round(ps.score,1)}
                          for k,ps in self._pair_stats.items()},
        }
```

## B17: direction_bias_detector.py — fix WR<30% systematic wrong direction
# BTC_BULL=21%, BNB_BEAR=25%, XRP_BEAR=17% → model trades AGAINST market
# If WR<30% consistently, signal direction is INVERTED — flip or disable
# ContraryIndicator: if WR<30% after N trades, SHORT when signal says LONG and vice versa
```python
import numpy as np
from collections import deque
from bot_types import Direction,TradeResult

class DirectionBiasDetector:
    """
    Detects when a strategy consistently predicts wrong direction.
    WR<30% after ≥20 trades = statistically significant inverse signal.
    Options: DISABLE | FLIP | REDUCE_SIZE
    Thresholds: WR<0.30→warning, WR<0.25→auto_action, WR>0.55→reliable
    """
    def __init__(self,min_trades:int=20,flip_threshold:float=0.25,
                 disable_threshold:float=0.20,warning_threshold:float=0.30):
        self.min_trades=min_trades
        self.flip_t=flip_threshold
        self.dis_t=disable_threshold
        self.warn_t=warning_threshold
        self._history:dict[str,deque]={}  # key→deque of (result,pnl)

    def record(self,symbol:str,direction:str,result:TradeResult,pnl:float):
        key=f"{symbol}_{direction}"
        if key not in self._history: self._history[key]=deque(maxlen=100)
        self._history[key].append((result,pnl))

    def assess(self,symbol:str,direction:str)->dict:
        """Returns action: NORMAL|WARNING|FLIP|DISABLE + size_multiplier."""
        key=f"{symbol}_{direction}"
        if key not in self._history or len(self._history[key])<self.min_trades:
            return {"action":"NORMAL","size_mult":1.0,"wr":None,"n":0,"reason":"insufficient_data"}
        h=list(self._history[key])
        wins=sum(1 for r,_ in h if r==TradeResult.WIN)
        wr=wins/len(h); n=len(h)
        avg_pnl=np.mean([p for _,p in h])
        if wr<self.dis_t:
            return {"action":"DISABLE","size_mult":0.0,"wr":round(wr,3),"n":n,
                    "reason":f"WR={wr:.0%}<{self.dis_t:.0%} after {n} trades — direction unreliable"}
        if wr<self.flip_t:
            return {"action":"FLIP","size_mult":0.5,"wr":round(wr,3),"n":n,
                    "reason":f"WR={wr:.0%}<{self.flip_t:.0%} — consider flipping signal direction"}
        if wr<self.warn_t:
            return {"action":"WARNING","size_mult":0.75,"wr":round(wr,3),"n":n,
                    "reason":f"WR={wr:.0%}<{self.warn_t:.0%} — reduce size, monitor"}
        return {"action":"NORMAL","size_mult":1.0,"wr":round(wr,3),"n":n,"reason":"OK"}

    def apply(self,symbol:str,direction:str,signal_direction:Direction)->tuple[Direction,float,str]:
        """Returns (effective_direction, size_multiplier, reason)."""
        a=self.assess(symbol,direction)
        if a["action"]=="DISABLE": return signal_direction,0.0,a["reason"]
        if a["action"]=="FLIP":
            flipped=Direction.SHORT if signal_direction==Direction.LONG else Direction.LONG
            return flipped,a["size_mult"],f"FLIPPED:{a['reason']}"
        return signal_direction,a["size_mult"],a["reason"]

    def summary(self)->list[dict]:
        """All pairs sorted by WR ascending — worst first."""
        rows=[]
        for key,h in self._history.items():
            if len(h)<5: continue
            wins=sum(1 for r,_ in h if r==TradeResult.WIN); wr=wins/len(h)
            rows.append({"pair":key,"wr":round(wr,3),"n":len(h),"action":self.assess(*key.split("_",1))["action"]})
        return sorted(rows,key=lambda r:r["wr"])
```

## B18: timing_fix_urgent.py — emergency timing override
# TIMING=331(67%) = bot never enters even when signal is good
# Current state: timing filter likely too strict OR not using ATR regime windows yet
# This is the #1 fix — without trades nothing can learn
```python
from datetime import datetime,timedelta
import numpy as np

class EmergencyTimingOverride:
    """
    Temporary looser timing to break conv=0 deadlock.
    Once ≥50 trades accumulate, revert to strict AdaptiveTimingFilter.
    TEMPORARY — remove after learning system has enough data.
    """
    # Aggressive windows: allow signal up to 90% through candle in all regimes
    EMERGENCY_WINDOWS={"low":0.40,"normal":0.60,"high":0.85,"extreme":0.95}

    def __init__(self,candle_seconds:int=3600,trade_count_threshold:int=50):
        self.candle_seconds=candle_seconds
        self.threshold=trade_count_threshold
        self.active=True  # start in emergency mode

    def evaluate(self,signal_time:datetime,candle_open_time:datetime,
                 current_price:float,candle_open:float,
                 candle_high:float,candle_low:float,
                 atr:float,atr_pct_history:list,
                 completed_trades:int=0)->dict:
        # Auto-deactivate once we have enough data
        if completed_trades>=self.threshold:
            self.active=False

        elapsed=(signal_time-candle_open_time).total_seconds()
        time_frac=elapsed/self.candle_seconds
        atr_pct=(atr/current_price)*100 if current_price>0 else 0
        regime=self._classify(atr_pct,atr_pct_history)

        windows=self.EMERGENCY_WINDOWS if self.active else {"low":0.20,"normal":0.35,"high":0.60,"extreme":0.80}
        max_time=windows[regime]
        disp=abs(current_price-candle_open)/atr if atr>0 else 999
        range_ratio=(candle_high-candle_low)/atr if atr>0 else 0

        mode="EMERGENCY" if self.active else "NORMAL"
        if time_frac<=max_time and range_ratio<0.9:
            return {"action":"ENTER","size":1.0,"regime":regime,"mode":mode}
        if disp<0.35:
            return {"action":"ENTER_REDUCED","size":0.5,"regime":regime,"mode":mode}
        return {"action":"REJECT","size":0.0,"regime":regime,"mode":mode}

    def _classify(self,atr_pct:float,history:list)->str:
        if len(history)<20: return "normal"
        s=sorted(history); n=len(s)
        if atr_pct>s[int(n*0.95)]: return "extreme"
        if atr_pct>s[int(n*0.75)]: return "high"
        if atr_pct<s[int(n*0.25)]: return "low"
        return "normal"
```

## B19: quiet_rsi_filter.py — tighten QUIET_RSI (11 cases, but fix its logic)
# QUIET_RSI=11 = negligible BUT its threshold might be misconfigured
# RSI 40-60 = neutral zone. Currently blocks trades. Should ALLOW in ranging, BLOCK in trending.
```python
class QuietRSIFilter:
    """
    RSI neutrality filter. Regime-aware.
    RANGING: RSI 40-60 = ALLOW (mean reversion works from neutral)
    TRENDING: RSI 40-60 = BLOCK (no momentum = weak trend = don't enter)
    Solves: filter blocks 11 valid ranging entries unnecessarily.
    """
    def check(self,rsi:float,direction:str,regime:str)->tuple[bool,str]:
        is_neutral=40<=rsi<=60
        if not is_neutral: return True,f"RSI={rsi:.0f} not neutral"
        if regime=="RANGING":
            return True,f"QUIET_RSI={rsi:.0f} allowed in RANGING (mean reversion)"
        if regime=="TRENDING":
            return False,f"QUIET_RSI={rsi:.0f} in TRENDING = no momentum, skip"
        return True,f"RSI={rsi:.0f} neutral but VOLATILE regime allows"
```

## B20: Update filter_pipeline.py — wire all new components
```python
# Add to SignalFilterPipeline.__init__():
from loss_cluster_filter import LossClusterFilter,LossClusterConfig
from learning_monitor import LearningMonitor
from direction_bias_detector import DirectionBiasDetector
from timing_fix_urgent import EmergencyTimingOverride
from quiet_rsi_filter import QuietRSIFilter

# self.loss_cluster = LossClusterFilter(LossClusterConfig(max_consec_losses=3,lookback_hours=4))
# self.learning     = LearningMonitor()
# self.bias         = DirectionBiasDetector(min_trades=20,flip_threshold=0.25)
# self.timing_emergency = EmergencyTimingOverride(candle_seconds=3600,trade_count_threshold=50)
# self.quiet_rsi    = QuietRSIFilter()

# Updated evaluate() — add these checks in order after existing filters:

def evaluate_v2(self,signal,market,recent_trades:list,completed_trades:int=0)->tuple[str,dict]:
    # 0. Direction bias check
    eff_dir,size_mult,bias_reason=self.bias.apply(signal.symbol,signal.direction.value,signal.direction)
    if size_mult==0.0: return "BIAS_DISABLED",{"reason":bias_reason}
    if eff_dir!=signal.direction: signal=dataclasses.replace(signal,direction=eff_dir)

    # 1. Loss cluster (before cooldown — more specific)
    blocked,msg=self.loss_cluster.should_block(signal.symbol,recent_trades,signal.regime)
    if blocked: self.learning.log_rejection(signal.symbol,signal.direction.value,"LOSS_CLUSTER",signal.regime); return "LOSS_CLUSTER",{"msg":msg}

    # 2-7. Existing pipeline (spread,volume,movement,timing,mtf,obi)
    ok,r=self.validator.validate(signal)
    if not ok: return "VALIDATION",{"reason":r}
    locked,msg=self.cooldown.is_locked(signal.symbol)
    if locked: return "PAIR_BLOCK",{"msg":msg}
    ok,msg=self.spread.check(market["bid"],market["ask"])
    if not ok: return "FAST_FAIL_SPREAD",{"msg":msg}
    ok,msg=self.volume.check(market["volume"],market["hour"])
    if not ok: return "FAST_FAIL_VOLUME",{"msg":msg}

    # 8. QUIET_RSI — regime-aware
    rsi=market.get("rsi",50.0)
    ok,msg=self.quiet_rsi.check(rsi,signal.direction.value,signal.regime)
    if not ok: return "QUIET_RSI",{"msg":msg}

    # 9. Emergency timing (replaces B3 until 50 trades accumulated)
    timing=self.timing_emergency.evaluate(signal.timestamp,market["candle_open_time"],
        signal.entry_price,market["candle_open"],market["candle_high"],market["candle_low"],
        signal.atr,market["atr_pct_history"],completed_trades)
    if timing["action"]=="REJECT": return "TIMING",{"regime":timing["regime"],"mode":timing["mode"]}

    # 10. MTF + OBI (unchanged from B10)
    score,mtf_msg=mtf_score(market["data_1h"],market["data_15m"],market["data_5m"],signal.direction.value)
    mtf_sz=mtf_size(score)
    if mtf_sz==0.0: return "MTF_LOW",{"score":score}
    obi_r=adjusted_obi(market["bid_vols"],market["ask_vols"],market["prev_snapshots"])
    if obi_r["quality"] in("LOW","NEUTRAL"): return "OBI_WEAK",obi_r

    stops=calculate_sl_tp(signal.direction.value,signal.entry_price,signal.atr,signal.atr_ratio,signal.symbol)
    final_size=round(timing["size"]*mtf_sz*obi_r["size"]*size_mult,2)

    decision="ENTER" if final_size>=0.9 else "ENTER_REDUCED"
    result={"size":final_size,"bias":bias_reason,"timing_mode":timing["mode"],**stops}
    self.learning.log_signal(signal,decision,result)
    return decision,result
```

## B21: learning_bootstrap.py — break conv=0 deadlock
# If conv=0 for >2h, run bootstrap: loosen ALL filters temporarily for 20 trades
# Goal: generate training data so learning system can actually score signals
```python
from datetime import datetime,timedelta
import logging
logger=logging.getLogger(__name__)

class LearningBootstrap:
    """
    Emergency mode: if no trades open for BOOTSTRAP_TIMEOUT, loosen everything
    to generate minimum training data. Logs all bootstrap trades separately.
    Deactivates automatically after BOOTSTRAP_TRADES trades complete.
    """
    BOOTSTRAP_TIMEOUT_MIN=120   # 2h without a trade → activate bootstrap
    BOOTSTRAP_TRADES=20         # run N trades in bootstrap, then deactivate
    BOOTSTRAP_OVERRIDES={
        "min_probability":0.52→0.45,   # lower bar
        "min_obi_long":10.0→0.0,       # ignore OBI
        "max_obi_short":-10.0→0.0,
        "mtf_min_score":7.0→3.0,       # loosen MTF
        "timing_max_frac":0.35→0.75,   # allow older signals
    }

    def __init__(self):
        self.active=False; self.bootstrap_count=0; self.last_trade_time=datetime.now()

    def update_last_trade(self): self.last_trade_time=datetime.now()

    def check_activate(self,completed_trades:int)->bool:
        if self.bootstrap_count>=self.BOOTSTRAP_TRADES:
            if self.active: logger.info("BOOTSTRAP complete — reverting to strict filters"); self.active=False
            return False
        gap=(datetime.now()-self.last_trade_time).total_seconds()/60
        if gap>=self.BOOTSTRAP_TIMEOUT_MIN and not self.active:
            logger.warning(f"BOOTSTRAP activated: no trades for {gap:.0f}min, loosening filters for {self.BOOTSTRAP_TRADES} trades")
            self.active=True
        return self.active

    def record_trade(self):
        self.bootstrap_count+=1; self.update_last_trade()
        if self.bootstrap_count>=self.BOOTSTRAP_TRADES: self.active=False

    def get_overrides(self)->dict:
        """Return filter overrides when bootstrap is active."""
        if not self.active: return {}
        return {"min_probability":0.45,"min_obi_long":0.0,"max_obi_short":0.0,
                "mtf_min_score":3.0,"timing_max_frac":0.75}
```

## PRIORITY ORDER (implement in this exact sequence)
# 1. B18 EmergencyTimingOverride — FIRST. breaks conv=0. without trades nothing works.
# 2. B16 LearningMonitor.log_signal() — add to pipeline. start measuring conv_rate.
# 3. B17 DirectionBiasDetector — auto-disable BTC_BULL(21%WR), XRP_BEAR(17%WR)
# 4. B15 LossClusterFilter — tune threshold, add regime-awareness, prevent over-blocking
# 5. B19 QuietRSIFilter — make regime-aware (minor, 11 cases only)
# 6. B21 LearningBootstrap — safety net if conv still=0 after B18
# 7. B20 wire everything into filter_pipeline — integration

## EXPECTED OUTCOMES after implementation
# conv_rate:   0% → 15-30% (B18 emergency timing)
# TIMING:      331 → 80-120 (B18 + B3 proper ATR windows)
# LOSS_CLUSTER:84 → 25-35 (B15 regime-aware, scaled cooldown)
# FAST_FAIL:   69 → 30-40 (existing B5 ToD RVOL)
# WR BTC_BULL: 21% → disabled (B17 auto-disable <25% after 20 trades)
# WR XRP_BEAR: 17% → disabled (B17 auto-disable)
# Learning score: 0 → 20-45/100 after 50+ trades (B16 proper scoring)
# Global score target: 60+/100 after 200+ trades with calibrated filters

## DIAGNOSTICS — run after each session
# monitor.diagnose()           → full report
# bias.summary()               → worst WR pairs
# loss_cluster.audit_accuracy()→ protective vs opportunity-cost blocks
# pipeline.learning.rejection_breakdown() → top blockers
# bootstrap.check_activate()   → is emergency mode needed?

## NEW FILES
# loss_cluster_filter.py direction_bias_detector.py learning_monitor.py
# timing_fix_urgent.py quiet_rsi_filter.py learning_bootstrap.py
# Update: filter_pipeline.py (add B20 wiring)
