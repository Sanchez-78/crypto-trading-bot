# CryptoMaster — Claude Code Prompt
# Python 3.11+ | Binance Futures | freqtrade-compatible | Apply blocks in order

## CTX: Confirmed bugs→fixes
# TIMEOUT=WIN regardless PnL → classify by net_pnl only
# SL==TP allowed → reject before open
# PnL 0.000% display → 4 decimals
# zero-duration trades → min 60s guard
# fees missing → subtract 2×taker_fee
# OBI ignored → OBI vs direction check
# R/R unchecked → enforce min 1.5
# TIMING 47% → adaptive ATR windows (low:20%,norm:35%,high:60%,extreme:80%)
# PAIR_BLOCK 38% → regime matrix (TRENDING/RANGING/VOLATILE×result)
# FAST_FAIL 15% → ToD RVOL + z-score spread
# Target: rejection 60%→<20%, winrate +15-25pp

## B1: bot_types.py
```python
from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid

class Direction(str,Enum): LONG="LONG"; SHORT="SHORT"
class CloseReason(str,Enum): TP="TP"; SL="SL"; TIMEOUT="TIMEOUT"; MANUAL="MANUAL"; VALIDATION="VALIDATION"
class TradeResult(str,Enum): WIN="VÝHRA"; LOSS="PROHRA"; BREAKEVEN="BREAKEVEN"; PENDING="NEVYHODNOCEN"

@dataclass
class BotConfig:
    taker_fee_pct:float=0.001; min_sl_dist_pct:float=0.002; max_sl_dist_pct:float=0.03
    min_rr:float=1.5; max_rr:float=10.0; min_duration_sec:int=60; max_duration_sec:int=3600
    min_obi_long:float=10.0; max_obi_short:float=-10.0; pnl_decimals:int=4

@dataclass
class TradeSignal:
    symbol:str; direction:Direction; entry_price:float; sl_price:float; tp_price:float
    probability:float; expected_value:float; obi:float
    atr:float=0.0; atr_ratio:float=1.0; regime:str="RANGING"
    timestamp:datetime=field(default_factory=datetime.now)

@dataclass
class Trade:
    id:str=field(default_factory=lambda:str(uuid.uuid4())[:8])
    symbol:str=""; direction:Direction=Direction.LONG
    entry_price:float=0.0; exit_price:float=0.0; sl_price:float=0.0; tp_price:float=0.0
    probability:float=0.0; expected_value:float=0.0; obi:float=0.0; atr:float=0.0
    opened_at:Optional[datetime]=None; closed_at:Optional[datetime]=None
    max_profit_pct:float=0.0; max_drawdown_pct:float=0.0
    close_reason:Optional[CloseReason]=None; result:TradeResult=TradeResult.PENDING
    net_pnl_pct:float=0.0; raw_pnl_pct:float=0.0; rejection_reason:str=""; entry_size:float=1.0
    @property
    def duration_seconds(self)->Optional[int]:
        return int((self.closed_at-self.opened_at).total_seconds()) if self.opened_at and self.closed_at else None
    @property
    def is_open(self)->bool: return self.opened_at is not None and self.closed_at is None
```

## B2: signal_validator.py — 7 checks
```python
from bot_types import *
class SignalValidator:
    def __init__(self,cfg:BotConfig): self.cfg=cfg
    def validate(self,s:TradeSignal)->tuple[bool,str]:
        for ok,r in [self._sl_tp_equal(s),self._sl_dist(s),self._sides(s),self._rr(s),self._obi(s),self._prob(s),self._atr(s)]:
            if not ok: return False,r
        return True,"OK"
    def _sl_tp_equal(self,s):
        return (False,f"SL==TP({s.sl_price})") if abs(s.sl_price-s.tp_price)<s.entry_price*0.0001 else (True,"")
    def _sl_dist(self,s):
        d=abs(s.entry_price-s.sl_price)/s.entry_price
        if d<self.cfg.min_sl_dist_pct: return False,f"SL tight:{d*100:.3f}%"
        if d>self.cfg.max_sl_dist_pct: return False,f"SL wide:{d*100:.3f}%"
        return True,""
    def _sides(self,s):
        if s.direction==Direction.LONG:
            if s.sl_price>=s.entry_price: return False,"LONG:SL>=entry"
            if s.tp_price<=s.entry_price: return False,"LONG:TP<=entry"
        else:
            if s.sl_price<=s.entry_price: return False,"SHORT:SL<=entry"
            if s.tp_price>=s.entry_price: return False,"SHORT:TP>=entry"
        return True,""
    def _rr(self,s):
        rr=abs(s.entry_price-s.tp_price)/abs(s.entry_price-s.sl_price) if abs(s.entry_price-s.sl_price)>0 else 0
        if rr<self.cfg.min_rr: return False,f"R/R{rr:.2f}<{self.cfg.min_rr}"
        if rr>self.cfg.max_rr: return False,f"R/R{rr:.2f}>{self.cfg.max_rr}"
        return True,""
    def _obi(self,s):
        if s.direction==Direction.LONG and s.obi<self.cfg.min_obi_long: return False,f"LONG OBI={s.obi:.1f}"
        if s.direction==Direction.SHORT and s.obi>self.cfg.max_obi_short: return False,f"SHORT OBI={s.obi:.1f}"
        return True,""
    def _prob(self,s): return (False,f"P={s.probability:.0%}") if s.probability<0.52 else (True,"")
    def _atr(self,s):
        if s.atr<=0: return True,""
        sl_atr=abs(s.entry_price-s.sl_price)/s.atr
        return (False,f"SL={sl_atr:.2f}xATR<1.5") if sl_atr<1.5 else (True,"")
```

## B3: timing_filter.py — ATR-regime adaptive windows
# src: Maven Securities alpha decay, LuxAlgo +34% profitability
# Regime→max_candle_time%: low→20%, normal→35%, high→60%, extreme→80%
# ENTER_REDUCED = positive EV + uncertainty → Kelly-smaller size
```python
from datetime import datetime
class AdaptiveTimingFilter:
    REGIME_WINDOWS={"low":0.20,"normal":0.35,"high":0.60,"extreme":0.80}
    def __init__(self,candle_seconds:int=3600): self.candle_seconds=candle_seconds
    def evaluate(self,signal_time:datetime,candle_open_time:datetime,current_price:float,
                 candle_open:float,candle_high:float,candle_low:float,atr:float,atr_pct_history:list)->dict:
        elapsed=(signal_time-candle_open_time).total_seconds()
        time_frac=elapsed/self.candle_seconds
        atr_pct=(atr/current_price)*100 if current_price>0 else 0
        regime=self._classify(atr_pct,atr_pct_history)
        max_time=self.REGIME_WINDOWS[regime]
        disp=abs(current_price-candle_open)/atr if atr>0 else 999
        range_ratio=(candle_high-candle_low)/atr if atr>0 else 0
        if time_frac<=max_time and range_ratio<0.8: return {"action":"ENTER","size":1.0,"regime":regime}
        if disp<0.25: return {"action":"ENTER_REDUCED","size":0.5,"regime":regime}
        if disp<0.15 and range_ratio<0.8: return {"action":"ENTER_REDUCED","size":0.3,"regime":regime}
        return {"action":"REJECT","size":0.0,"regime":regime}
    def _classify(self,atr_pct:float,history:list)->str:
        if len(history)<20: return "normal"
        s=sorted(history); n=len(s)
        if atr_pct>s[int(n*0.95)]: return "extreme"
        if atr_pct>s[int(n*0.75)]: return "high"
        if atr_pct<s[int(n*0.25)]: return "low"
        return "normal"
```

## B4: cooldown_manager.py — regime detection + adaptive cooldown matrix
# src: Corbet&Katsiampa(2020) BTC asymmetric mean reversion
# Cooldown matrix [big_win>2%,small_win,small_loss,big_loss,stoploss] in candles:
# TRENDING:[1,2,2,3,4] RANGING:[4,6,8,12,16] VOLATILE:[3,4,5,8,10]
# Serial loss ≥3 consecutive → multiply 1.5×
```python
import numpy as np
from datetime import datetime,timedelta
from bot_types import CloseReason

def detect_regime(df)->str:
    # ADX + ATR ratio + Choppiness Index → TRENDING/RANGING/VOLATILE
    # Choppiness >61.8=ranging, <38.2=trending
    try:
        import ta
        adx=ta.trend.adx(df["high"],df["low"],df["close"],14).iloc[-1]
        atr_f=ta.volatility.average_true_range(df["high"],df["low"],df["close"],5)
        atr_s=ta.volatility.average_true_range(df["high"],df["low"],df["close"],20)
        atr_ratio=(atr_f/atr_s).iloc[-1]
        h14=df["high"].rolling(14).max(); l14=df["low"].rolling(14).min()
        atr1=ta.volatility.average_true_range(df["high"],df["low"],df["close"],1)
        chop=(100*np.log10(atr1.rolling(14).sum()/(h14-l14))/np.log10(14)).iloc[-1]
        sc={"TRENDING":0,"RANGING":0,"VOLATILE":0}
        if adx>25: sc["TRENDING"]+=2
        if atr_ratio>1.5: sc["VOLATILE"]+=2
        if chop>61.8: sc["RANGING"]+=2
        return max(sc,key=sc.get)
    except: return "RANGING"

class RegimeAdaptiveCooldown:
    MATRIX={"TRENDING":[1,2,2,3,4],"RANGING":[4,6,8,12,16],"VOLATILE":[3,4,5,8,10]}
    def __init__(self,candle_seconds:int=3600):
        self.candle_seconds=candle_seconds; self._locks:dict[str,datetime]={}; self._consec:dict[str,int]={}
    def lock(self,symbol:str,regime:str,pnl_pct:float,close_reason:CloseReason):
        m=self.MATRIX.get(regime,self.MATRIX["RANGING"])
        if close_reason==CloseReason.SL: c=m[4]
        elif pnl_pct>2.0: c=m[0]
        elif pnl_pct>0: c=m[1]
        elif pnl_pct>-1.0: c=m[2]
        else: c=m[3]
        if close_reason in(CloseReason.SL,CloseReason.TIMEOUT) and pnl_pct<0:
            self._consec[symbol]=self._consec.get(symbol,0)+1
        else: self._consec[symbol]=0
        if self._consec.get(symbol,0)>=3: c=int(c*1.5)
        self._locks[symbol]=datetime.now()+timedelta(seconds=c*self.candle_seconds)
    def is_locked(self,symbol:str)->tuple[bool,str]:
        if symbol not in self._locks: return False,""
        rem=(self._locks[symbol]-datetime.now()).total_seconds()
        if rem<=0: del self._locks[symbol]; return False,""
        return True,f"PAIR_BLOCK:{symbol} {rem:.0f}s"
    def force_unlock(self,symbol:str): self._locks.pop(symbol,None)
```

## B5: fast_fail_filters.py — ToD RVOL + z-score spread + movement
# src: Springer2024 38-exchange study: peak 16-17UTC, trough 3-4UTC, 42% swing
# Kaiko: BTC~1bps, mid-cap alts 3-8bps, small-caps 8-20+bps
```python
import numpy as np
from collections import deque

class AdaptiveVolumeFilter:
    def __init__(self,min_rvol:float=1.2,max_rvol:float=5.0):
        self.min_rvol=min_rvol; self.max_rvol=max_rvol
        self.tod:dict[int,deque]={h:deque(maxlen=100) for h in range(24)}
    def check(self,volume:float,hour:int)->tuple[bool,str]:
        hist=self.tod[hour]
        if len(hist)<5: self.tod[hour].append(volume); return True,"insufficient_history"
        rvol=volume/np.mean(hist); self.tod[hour].append(volume)
        if rvol<self.min_rvol: return False,f"FF:LOW_RVOL {rvol:.2f}x"
        if rvol>self.max_rvol: return False,f"FF:EXTREME_RVOL {rvol:.2f}x"
        return True,f"RVOL {rvol:.2f}x"

class AdaptiveSpreadFilter:
    def __init__(self,z_threshold:float=2.5):
        self.z_threshold=z_threshold; self.history:deque=deque(maxlen=100)
    def check(self,bid:float,ask:float)->tuple[bool,str]:
        mid=(bid+ask)/2; spread_bps=(ask-bid)/mid*10000 if mid>0 else 0
        self.history.append(spread_bps)
        if len(self.history)<10: return True,"insufficient_history"
        std=np.std(self.history); z=(spread_bps-np.mean(self.history))/std if std>0 else 0
        return (False,f"FF:HIGH_SPREAD z={z:.2f}") if z>self.z_threshold else (True,f"spread {spread_bps:.1f}bps z={z:.2f}")

class MovementFilter:
    def check(self,candle_high:float,candle_low:float,atr:float)->tuple[bool,str]:
        if atr<=0: return True,""
        ratio=(candle_high-candle_low)/atr
        return (False,f"FF:EXHAUSTED range={ratio:.2f}xATR") if ratio>0.8 else (True,f"range {ratio:.2f}xATR")
```

## B6: obi_filter.py — depth-weighted OBI + multi-factor spoofing
# src: Fabre&Challet(2025) 31% large orders spoof; Do&Putniņš(2023) AUC-ROC 0.97
# Cont,Kukanov&Stoikov(2014) R²≥50% 44/50 NYSE; arXiv:2507.22712 trade-events>LOB
# OBI interpretation: >+0.30 sp<0.2→HIGH full; >+0.30 sp0.2-0.5→MED 50%; >+0.30 sp>0.5→LOW skip
```python
import numpy as np

def depth_weighted_obi(bid_vols:list,ask_vols:list,n:int=10,decay:float=3.0)->float:
    n=min(n,len(bid_vols),len(ask_vols))
    w=np.array([0.5**(i/decay) for i in range(n)])
    wb=np.sum(np.array(bid_vols[:n])*w); wa=np.sum(np.array(ask_vols[:n])*w)
    d=wb+wa; return (wb-wa)/d if d>0 else 0.0

def spoof_score(bid_vols:list,ask_vols:list,prev_snapshots:list,n:int=10)->float:
    score=0.0; bv=np.array(bid_vols[:n],dtype=float)
    med=np.median(bv)
    score+=0.3*(np.sum(bv>3.0*med)/n if med>0 else 0)
    if n>=5:
        near=np.mean(bv[:2]); far=np.mean(bv[3:n])
        if near>0 and far/near>3.0: score+=0.3
    if len(prev_snapshots)>=3:
        churn=sum(abs(bv[i]-np.array(prev)[i])>0.5*max(float(bv[i]),float(np.array(prev)[i]),1e-9)
                  for prev in prev_snapshots[-5:] for i in range(3,min(n,len(prev))))
        score+=0.4*min(churn/max(5*(n-3),1),1.0)
    return min(score,1.0)

def adjusted_obi(bid_vols:list,ask_vols:list,prev_snapshots:list)->dict:
    obi=depth_weighted_obi(bid_vols,ask_vols)
    sp=spoof_score(bid_vols,ask_vols,prev_snapshots)
    adj=obi*(1.0-sp)
    if abs(adj)>=0.24 and sp<0.2: q,sz="HIGH",1.0
    elif abs(adj)>=0.15 and sp<0.5: q,sz="MEDIUM",0.5
    elif abs(adj)<0.10: q,sz="NEUTRAL",0.0
    else: q,sz="LOW",0.0
    return {"obi":obi,"spoof":sp,"adj_obi":adj,"quality":q,"size":sz}
```

## B7: sl_tp_calculator.py — ATR dynamic SL/TP per asset + regime adj
# src: LuxAlgo 2xATR stop → -32% max drawdown; Bialkowski(2023) 147 cryptos
# anti-hunt buffer +10% ATR; breakeven at 1.5×SL; Chandelier trail 3.5×ATR
# Asset base [sl_mult,tp_mult,atr_period]: BTC[2.0,3.0,14] ETH[2.2,3.2,14] SOL[2.7,3.7,10] default[3.0,4.0,10]
# Regime adj [atr_ratio→sl_adj]: <0.70→0.75× 0.70-1.20→1.0× 1.20-1.50→1.25× >1.50→1.50×
```python
ASSET_BASE={"BTC":{"sl":2.0,"tp":3.0,"period":14},"ETH":{"sl":2.2,"tp":3.2,"period":14},
            "SOL":{"sl":2.7,"tp":3.7,"period":10},"DEFAULT":{"sl":3.0,"tp":4.0,"period":10}}

def get_asset_key(symbol:str)->str:
    for k in ASSET_BASE:
        if k!="DEFAULT" and symbol.upper().startswith(k): return k
    return "DEFAULT"

def calculate_sl_tp(direction:str,entry:float,atr:float,atr_ratio:float=1.0,symbol:str="")->dict:
    b=ASSET_BASE[get_asset_key(symbol)]
    adj=1.50 if atr_ratio>1.50 else 1.25 if atr_ratio>1.20 else 0.75 if atr_ratio<0.70 else 1.00
    sl_dist=atr*b["sl"]*adj*1.10; tp_dist=atr*b["tp"]*adj
    if direction.upper()=="LONG": sl=entry-sl_dist; tp=entry+tp_dist; be=entry+sl_dist*1.5
    else: sl=entry+sl_dist; tp=entry-tp_dist; be=entry-sl_dist*1.5
    return {"sl":round(sl,8),"tp":round(tp,8),"breakeven_trigger":round(be,8),
            "rr_ratio":round(tp_dist/sl_dist,2),"sl_dist_pct":round(sl_dist/entry*100,4)}
```

## B8: mtf_filter.py — multi-timeframe confluence scoring
# src: freqtrade TrendRider 10k+trades→67.9%WR PF2.12; MTF 45%→58-70%WR (+15-25pp)
# Scoring 0-10: EMA_align(3pts)+ADX(1pt)+RSI/MACD(1pt)+EMA15m(1pt)+vol(1.5pt)+no_exhaust(1.5pt)
# ≥7.0→ENTER 1.0× | 4-6→ENTER 0.5× | <4→SKIP
# Timeframe hierarchy (Elder ~5x): 1h→trend, 15m→confirmation, 5m→entry
```python
def mtf_score(data_1h:dict,data_15m:dict,data_5m:dict,direction:str)->tuple[float,str]:
    try: import talib
    except ImportError: return 5.0,"talib_missing"
    c1h=data_1h["close"]; is_long=direction.upper()=="LONG"
    ema50=talib.EMA(c1h,50)[-1]; ema200=talib.EMA(c1h,200)[-1]
    adx=talib.ADX(data_1h["high"],data_1h["low"],c1h,14)[-1]
    rsi1h=talib.RSI(c1h,14)[-1]; _,_,hist1h=talib.MACD(c1h)
    ema_ok=(ema50>ema200) if is_long else (ema50<ema200)
    if not ema_ok: return 0.0,"1H_EMA_WRONG_SIDE"
    if adx<20: return 1.0,"1H_NO_TREND"
    score=3.0  # EMA aligned
    score+=1.0 if adx>25 else 0.5
    score+=1.0 if (rsi1h>50 if is_long else rsi1h<50) else 0
    score+=1.0 if (hist1h[-1]>0 if is_long else hist1h[-1]<0) else 0
    c15m=data_15m["close"]; rsi15m=talib.RSI(c15m,14)[-1]
    ema20=talib.EMA(c15m,20)[-1]; ema50m=talib.EMA(c15m,50)[-1]
    if is_long and rsi15m>75: return score,"15M_EXHAUSTED"
    if not is_long and rsi15m<25: return score,"15M_OVERSOLD"
    score+=1.0 if (ema20>ema50m if is_long else ema20<ema50m) else 0
    c5m=data_5m["close"]; rsi5m=talib.RSI(c5m,14)[-1]
    vol5m=data_5m.get("volume",[0]); vol_avg=sum(list(vol5m)[-20:])/20 if len(vol5m)>=20 else 0
    score+=1.5 if vol5m[-1]>vol_avg*1.5 and vol_avg>0 else 0
    score+=1.5 if (rsi5m<80 if is_long else rsi5m>20) else 0
    return score,f"MTF:{score:.1f}"

def mtf_size(score:float)->float:
    return 1.0 if score>=7.0 else 0.5 if score>=4.0 else 0.0
```

## B9: position_manager.py — tick monitoring + PnL classification
# CRITICAL BUG FIX: result based on ACTUAL net_pnl, NOT close_reason
# TIMEOUT + negative PnL = LOSS (was incorrectly WIN before fix)
```python
from datetime import datetime
from bot_types import *

class PositionManager:
    def __init__(self,cfg:BotConfig): self.cfg=cfg
    def check(self,trade:Trade,price:float)->tuple[bool,Optional[CloseReason],str]:
        if not trade.is_open: return False,None,"not_open"
        self._update(trade,price)
        if self._tp(trade,price): return True,CloseReason.TP,f"TP@{price}"
        if self._sl(trade,price): return True,CloseReason.SL,f"SL@{price}"
        elapsed=(datetime.now()-trade.opened_at).total_seconds()
        if elapsed>=self.cfg.max_duration_sec: return True,CloseReason.TIMEOUT,f"timeout_{elapsed:.0f}s"
        if elapsed<self.cfg.min_duration_sec: return False,None,f"min_guard_{elapsed:.0f}s"
        return False,None,"active"
    def _tp(self,t,p): return p>=t.tp_price if t.direction==Direction.LONG else p<=t.tp_price
    def _sl(self,t,p): return p<=t.sl_price if t.direction==Direction.LONG else p>=t.sl_price
    def _update(self,t,p):
        pnl=((p-t.entry_price)/t.entry_price if t.direction==Direction.LONG else (t.entry_price-p)/t.entry_price)*100
        if pnl>t.max_profit_pct: t.max_profit_pct=pnl
        if pnl<-t.max_drawdown_pct: t.max_drawdown_pct=abs(pnl)

class TradeClassifier:
    def __init__(self,cfg:BotConfig): self.cfg=cfg
    def classify(self,trade:Trade)->Trade:
        if not trade.entry_price or not trade.exit_price: return trade
        raw=((trade.exit_price-trade.entry_price)/trade.entry_price if trade.direction==Direction.LONG
             else (trade.entry_price-trade.exit_price)/trade.entry_price)
        net=raw-(2*self.cfg.taker_fee_pct)
        trade.raw_pnl_pct=round(raw*100,self.cfg.pnl_decimals)
        trade.net_pnl_pct=round(net*100,self.cfg.pnl_decimals)
        trade.result=TradeResult.WIN if net>0 else TradeResult.LOSS if net<0 else TradeResult.BREAKEVEN
        return trade
```

## B10: filter_pipeline.py — integrated pipeline cheapest→expensive
# Order: PAIR_BLOCK(O1)→SPREAD(O1)→VOLUME_TOD(O1)→MOVEMENT(O1)→TIMING(ATR)→MTF(multi-TF)→OBI(orderbook)
```python
from datetime import datetime
from bot_types import *
from timing_filter import AdaptiveTimingFilter
from cooldown_manager import RegimeAdaptiveCooldown
from fast_fail_filters import AdaptiveVolumeFilter,AdaptiveSpreadFilter,MovementFilter
from obi_filter import adjusted_obi
from sl_tp_calculator import calculate_sl_tp
from mtf_filter import mtf_score,mtf_size
from signal_validator import SignalValidator

class SignalFilterPipeline:
    def __init__(self,cfg:BotConfig,candle_seconds:int=3600):
        self.cfg=cfg; self.validator=SignalValidator(cfg)
        self.cooldown=RegimeAdaptiveCooldown(candle_seconds)
        self.timing=AdaptiveTimingFilter(candle_seconds)
        self.volume=AdaptiveVolumeFilter(); self.spread=AdaptiveSpreadFilter(); self.movement=MovementFilter()

    def evaluate(self,signal:TradeSignal,market:dict)->tuple[str,dict]:
        # market keys: bid,ask,volume,hour,candle_open_time,candle_open,candle_high,candle_low,
        #              atr_pct_history,bid_vols,ask_vols,prev_snapshots,data_1h,data_15m,data_5m
        ok,r=self.validator.validate(signal)
        if not ok: return "VALIDATION",{"reason":r}
        locked,msg=self.cooldown.is_locked(signal.symbol)
        if locked: return "PAIR_BLOCK",{"msg":msg}
        ok,msg=self.spread.check(market["bid"],market["ask"])
        if not ok: return "FAST_FAIL_SPREAD",{"msg":msg}
        ok,msg=self.volume.check(market["volume"],market["hour"])
        if not ok: return "FAST_FAIL_VOLUME",{"msg":msg}
        ok,msg=self.movement.check(market["candle_high"],market["candle_low"],signal.atr)
        if not ok: return "FAST_FAIL_MOVEMENT",{"msg":msg}
        timing=self.timing.evaluate(signal.timestamp,market["candle_open_time"],signal.entry_price,
                                    market["candle_open"],market["candle_high"],market["candle_low"],
                                    signal.atr,market["atr_pct_history"])
        if timing["action"]=="REJECT": return "TIMING",{"regime":timing["regime"]}
        score,mtf_msg=mtf_score(market["data_1h"],market["data_15m"],market["data_5m"],signal.direction.value)
        mtf_sz=mtf_size(score)
        if mtf_sz==0.0: return "MTF_LOW",{"score":score,"msg":mtf_msg}
        obi_r=adjusted_obi(market["bid_vols"],market["ask_vols"],market["prev_snapshots"])
        if obi_r["quality"] in("LOW","NEUTRAL"): return "OBI_WEAK",obi_r
        stops=calculate_sl_tp(signal.direction.value,signal.entry_price,signal.atr,signal.atr_ratio,signal.symbol)
        return "ENTER",{"size":round(timing["size"]*mtf_sz*obi_r["size"],2),"regime":timing["regime"],
                        "mtf_score":score,"obi":obi_r["adj_obi"],"spoof":obi_r["spoof"],**stops}

    def on_trade_closed(self,symbol:str,regime:str,pnl_pct:float,close_reason:CloseReason):
        self.cooldown.lock(symbol,regime,pnl_pct,close_reason)
```

## B11: orchestrator.py — main entry point
```python
from datetime import datetime
from bot_types import *
from filter_pipeline import SignalFilterPipeline
from position_manager import PositionManager,TradeClassifier
import logging
logger=logging.getLogger(__name__)

class TradeOrchestrator:
    # Usage: bot=TradeOrchestrator(); dec,meta=bot.on_signal(signal,mkt); closed=bot.on_price_tick(price)
    def __init__(self,cfg:BotConfig=None,candle_seconds:int=3600):
        self.cfg=cfg or BotConfig(); self.pipeline=SignalFilterPipeline(self.cfg,candle_seconds)
        self.manager=PositionManager(self.cfg); self.classifier=TradeClassifier(self.cfg)
        self.active:Optional[Trade]=None; self.history:list[Trade]=[]

    def on_signal(self,signal:TradeSignal,market:dict)->tuple[str,dict]:
        if self.active: return "BLOCKED",{"reason":"position_open"}
        decision,meta=self.pipeline.evaluate(signal,market)
        if decision not in("ENTER","ENTER_REDUCED"):
            t=Trade(symbol=signal.symbol,direction=signal.direction,entry_price=signal.entry_price,
                    sl_price=signal.sl_price,tp_price=signal.tp_price,
                    close_reason=CloseReason.VALIDATION,rejection_reason=f"{decision}:{meta}")
            self.history.append(t); logger.info(f"[{t.id}]REJECT {decision}:{meta}"); return decision,meta
        t=Trade(symbol=signal.symbol,direction=signal.direction,entry_price=signal.entry_price,
                sl_price=meta.get("sl",signal.sl_price),tp_price=meta.get("tp",signal.tp_price),
                probability=signal.probability,obi=signal.obi,atr=signal.atr,
                opened_at=datetime.now(),entry_size=meta.get("size",1.0))
        self.active=t
        logger.info(f"[{t.id}]OPEN {t.direction.value} {t.symbol}@{t.entry_price} SL={t.sl_price} TP={t.tp_price} sz={t.entry_size} rr={meta.get('rr_ratio')}")
        return decision,meta

    def on_price_tick(self,price:float)->Optional[Trade]:
        if not self.active: return None
        sc,reason,msg=self.manager.check(self.active,price)
        return self._close(price,reason) if sc else None

    def force_close(self,price:float)->Optional[Trade]:
        return self._close(price,CloseReason.MANUAL) if self.active else None

    def _close(self,exit_price:float,reason:CloseReason)->Trade:
        t=self.active; t.exit_price=exit_price; t.closed_at=datetime.now(); t.close_reason=reason
        t=self.classifier.classify(t)
        self.pipeline.on_trade_closed(t.symbol,"RANGING",t.net_pnl_pct,reason)
        self.active=None; self.history.append(t)
        logger.info(f"[{t.id}]CLOSE {t.result.value} PnL={t.net_pnl_pct:+.4f}% {reason.value} {t.duration_seconds}s")
        return t

    def stats(self)->dict:
        closed=[t for t in self.history if t.close_reason!=CloseReason.VALIDATION]
        if not closed: return {"msg":"no_trades"}
        wins=[t for t in closed if t.result==TradeResult.WIN]
        losses=[t for t in closed if t.result==TradeResult.LOSS]
        to_loss=[t for t in closed if t.close_reason==CloseReason.TIMEOUT and t.result==TradeResult.LOSS]
        return {"total":len(closed),"wins":len(wins),"losses":len(losses),
                "winrate_pct":round(len(wins)/len(closed)*100,1),
                "total_pnl_pct":round(sum(t.net_pnl_pct for t in closed),4),
                "avg_win_pct":round(sum(t.net_pnl_pct for t in wins)/len(wins),4) if wins else 0,
                "avg_loss_pct":round(sum(t.net_pnl_pct for t in losses)/len(losses),4) if losses else 0,
                "avg_dur_s":round(sum(t.duration_seconds or 0 for t in closed)/len(closed)),
                "timeout_losses":len(to_loss),  # KEY BUG INDICATOR
                "rejected":len([t for t in self.history if t.close_reason==CloseReason.VALIDATION]),
                "rejections":{k:v for k,v in __import__("collections").Counter(
                    t.rejection_reason.split(":")[0] for t in self.history
                    if t.close_reason==CloseReason.VALIDATION).items()}}
```

## B12: kronos_agent.py — optional Kronos AI signal layer
# AAAI2026 foundation model, 12B+ K-lines, 45 exchanges
# install: pip install torch transformers huggingface_hub
# download: snapshot_download("NeoQuasar/Kronos-small") + "NeoQuasar/Kronos-Tokenizer-base"
# evaluator_check: blocks trade if Kronos strongly disagrees (dir_prob>0.65, opposite direction)
```python
import numpy as np,logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
logger=logging.getLogger(__name__)

@dataclass
class KronosSignal:
    symbol:str; timeframe:str; timestamp:datetime; direction:str; direction_prob:float
    signal_strength:float; expected_volatility:float; volatility_elevated:bool
    forecast_closes:list; confidence_interval_pct:float; trade_recommended:bool; reason:str

class KronosAgent:
    SIGNAL_THRESHOLD=0.62; DIRECTION_THRESHOLD=0.55; MIN_CANDLES=64; FORECAST_LEN=24
    def __init__(self,symbol="BTC/USDT",timeframe="1h",model_size="small",mock=False):
        self.symbol=symbol; self.timeframe=timeframe; self.model_size=model_size
        self.mock=mock; self._loaded=False; self.predictor=None
    def load(self)->bool:
        if self.mock: self._loaded=True; return True
        try:
            from model import Kronos,KronosTokenizer,KronosPredictor
            tok=KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
            mdl=Kronos.from_pretrained(f"NeoQuasar/Kronos-{self.model_size}")
            self.predictor=KronosPredictor(mdl,tok); self._loaded=True; return True
        except Exception as e: logger.error(f"Kronos:{e}"); return False
    def analyze(self,df)->Optional[KronosSignal]:
        if not self._loaded or len(df)<self.MIN_CANDLES: return None
        df=df.copy(); df.columns=df.columns.str.lower()
        try:
            fc=self._forecast(df); d,p=self._direction(df,fc); v,ve=self._volatility(df,fc)
            ci=self._ci(fc); st=self._strength(p,ve,ci); rec=d!="NEUTRAL" and st>=self.SIGNAL_THRESHOLD
            return KronosSignal(self.symbol,self.timeframe,datetime.now(),d,p,st,v,ve,fc["closes"],ci,rec,f"{d} st={st:.2f} p={p:.0%}")
        except Exception as e: logger.error(f"Kronos analyze:{e}"); return None
    def _forecast(self,df)->dict:
        if self.mock:
            lc=df["close"].iloc[-1]; hv=df["close"].pct_change().std()
            rng=np.random.default_rng(42); n=50; s=np.zeros((n,self.FORECAST_LEN))
            for i in range(n):
                p=[lc]
                for _ in range(self.FORECAST_LEN): p.append(p[-1]*(1+rng.normal(0,hv)))
                s[i]=p[1:]
            return {"closes_samples":s,"closes":s.mean(0).tolist(),"highs":(s*1.003).mean(0).tolist(),"lows":(s*0.997).mean(0).tolist()}
        ohlcv=df[["open","high","low","close","volume"]].values[-512:]
        raw=self.predictor.predict(ohlcv,pred_len=self.FORECAST_LEN)
        return {"closes_samples":raw[:,:,3],"closes":raw[:,:,3].mean(0).tolist(),
                "highs":raw[:,:,1].mean(0).tolist(),"lows":raw[:,:,2].mean(0).tolist()}
    def _direction(self,df,fc):
        lc=df["close"].iloc[-1]; finals=fc["closes_samples"][:,-1]; pu=(finals>lc).mean()
        if pu>self.DIRECTION_THRESHOLD: return "LONG",float(pu)
        if 1-pu>self.DIRECTION_THRESHOLD: return "SHORT",float(1-pu)
        return "NEUTRAL",max(float(pu),float(1-pu))
    def _volatility(self,df,fc):
        hv=df["close"].pct_change().tail(100).std()*100
        hi=np.array(fc.get("highs",fc["closes"])); lo=np.array(fc.get("lows",fc["closes"]))
        pv=float(((hi-lo)/lo*100).mean()) if lo.any() else hv
        return pv,pv>hv*1.25
    def _ci(self,fc):
        s=fc["closes_samples"][:,-1]
        return float((np.percentile(s,95)-np.percentile(s,5))/np.mean(s)*100)
    def _strength(self,p,ve,ci):
        return float(np.clip(((p-0.5)/0.5*0.6+max(0.0,1.0-ci/20.0)*0.3)*(0.7 if ve else 1.0),0,1))
    def evaluator_check(self,direction:str,df)->tuple[bool,str]:
        s=self.analyze(df)
        if s is None: return True,"unavailable"
        if s.direction!="NEUTRAL" and s.direction!=direction and s.direction_prob>0.65:
            return False,f"KRONOS_BLOCK:{s.direction} p={s.direction_prob:.0%}"
        if s.signal_strength<0.55: return True,f"KRONOS_WARN:weak({s.signal_strength:.2f})"
        return True,f"KRONOS_OK:{s.direction}({s.signal_strength:.2f})"
```

## B13: strategies.py — 4 strategy categories × all timeframes
# Backtest refs: SupertrendMACD 11.61%ann 7yr PF2.12 | BBRSIRev 78%WR avg+1.4%/trade (RANGING only)
# FundingArb 19.26%APY maxDD0.85%(2025) | StatArb BTC/ETH 16.34%ann Sharpe2.45
# DynamicGrid 15-40%ann ranging | A-S market making: Hummingbot impl, PLOS ONE study
```python
import numpy as np,pandas as pd
from dataclasses import dataclass
from typing import Optional

@dataclass
class StrategySignal:
    signal:str; strength:float; reason:str; strategy:str; timeframe:str; regime_required:str

# ── TREND FOLLOWING (regime=TRENDING, ADX>25 required) ──────────────────────

class SupertrendMACDStrategy:
    # SuperTrend ATR(14)×3.5 + MACD(7,23,10) + ADX≥25 + vol≥1.2×avg
    # Best TF: 1h,4h. Flip signal stronger than continuation.
    NAME="SupertrendMACD"; REGIME="TRENDING"
    def __init__(self,atr_p=14,atr_m=3.5,mf=7,ms=23,ms2=10,adx_min=25):
        self.atr_p=atr_p; self.atr_m=atr_m; self.mf=mf; self.ms=ms; self.ms2=ms2; self.adx_min=adx_min
    def analyze(self,df:pd.DataFrame,tf:str="1h")->StrategySignal:
        try: import talib
        except: return StrategySignal("NEUTRAL",0,"talib_missing",self.NAME,tf,self.REGIME)
        c=df["close"].values; h=df["high"].values; l=df["low"].values
        adx=talib.ADX(h,l,c,14)[-1]
        if adx<self.adx_min: return StrategySignal("NEUTRAL",0,f"ADX={adx:.0f}<{self.adx_min}",self.NAME,tf,self.REGIME)
        atr=talib.ATR(h,l,c,self.atr_p)
        st=np.where(c>(h+l)/2-self.atr_m*atr,1,-1)
        _,_,hist=talib.MACD(c,self.mf,self.ms,self.ms2)
        vol_ok=df["volume"].iloc[-1]>df["volume"].rolling(20).mean().iloc[-1]*1.2
        st_flip=st[-1]!=st[-2]; strength=min(1.0,(adx-self.adx_min)/25)
        if st[-1]==1 and hist[-1]>0 and hist[-1]>hist[-2] and vol_ok:
            return StrategySignal("LONG",strength,f"ST_bull+MACD+vol {'flip' if st_flip else 'cont'}",self.NAME,tf,self.REGIME)
        if st[-1]==-1 and hist[-1]<0 and hist[-1]<hist[-2] and vol_ok:
            return StrategySignal("SHORT",strength,f"ST_bear+MACD+vol {'flip' if st_flip else 'cont'}",self.NAME,tf,self.REGIME)
        return StrategySignal("NEUTRAL",0,"no_align",self.NAME,tf,self.REGIME)

class EMABreakoutStrategy:
    # EMA 10/50/200 stack + price breaks recent 10-bar high/low + 1.5×vol surge
    # Best TF: 15m-4h swing
    NAME="EMABreakout"; REGIME="TRENDING"
    def __init__(self,f=10,m=50,s=200): self.f=f; self.m=m; self.s=s
    def analyze(self,df:pd.DataFrame,tf:str="1h")->StrategySignal:
        try: import talib
        except: return StrategySignal("NEUTRAL",0,"talib_missing",self.NAME,tf,self.REGIME)
        c=df["close"].values; h=df["high"].values; l=df["low"].values
        adx=talib.ADX(h,l,c,14)[-1]
        if adx<20: return StrategySignal("NEUTRAL",0,f"ADX={adx:.0f}<20",self.NAME,tf,self.REGIME)
        ef=talib.EMA(c,self.f)[-1]; em=talib.EMA(c,self.m)[-1]; es=talib.EMA(c,self.s)[-1]
        rh=max(h[-10:-1]); rl=min(l[-10:-1])
        vs=df["volume"].iloc[-1]>df["volume"].rolling(20).mean().iloc[-1]*1.5
        strength=min(1.0,adx/50)
        if ef>em>es and c[-1]>rh and vs: return StrategySignal("LONG",strength,"EMA_stack+breakout+vol",self.NAME,tf,self.REGIME)
        if ef<em<es and c[-1]<rl and vs: return StrategySignal("SHORT",strength,"EMA_bear+breakdown+vol",self.NAME,tf,self.REGIME)
        return StrategySignal("NEUTRAL",0,"no_breakout",self.NAME,tf,self.REGIME)

# ── MEAN REVERSION (regime=RANGING, ADX<25 required) ────────────────────────

class BBRSIMeanReversionStrategy:
    # BB(20,2) lower/upper touch + RSI<30/>70 + ADX<25 + BB_width>0.01 (avoid pre-breakout)
    # Exit: middle band. NEVER use in TRENDING — walking the bands = blow-up
    NAME="BBRSIReversion"; REGIME="RANGING"
    def __init__(self,bb_p=20,bb_s=2.0,rsi_p=14,os=30,ob=70,adx_max=25):
        self.bb_p=bb_p; self.bb_s=bb_s; self.rsi_p=rsi_p; self.os=os; self.ob=ob; self.adx_max=adx_max
    def analyze(self,df:pd.DataFrame,tf:str="1h")->StrategySignal:
        try: import talib
        except: return StrategySignal("NEUTRAL",0,"talib_missing",self.NAME,tf,self.REGIME)
        c=df["close"].values; h=df["high"].values; l=df["low"].values
        adx=talib.ADX(h,l,c,14)[-1]
        if adx>self.adx_max: return StrategySignal("NEUTRAL",0,f"TRENDING ADX={adx:.0f}",self.NAME,tf,self.REGIME)
        up,mid,lo=talib.BBANDS(c,self.bb_p,self.bb_s,self.bb_s)
        rsi=talib.RSI(c,self.rsi_p)[-1]
        bw=(up[-1]-lo[-1])/mid[-1]
        if bw<0.01: return StrategySignal("NEUTRAL",0,"BB_narrow_prebreakout",self.NAME,tf,self.REGIME)
        strength=min(1.0,(self.adx_max-adx)/self.adx_max)
        if c[-1]<=lo[-1] and rsi<self.os: return StrategySignal("LONG",strength,f"BB_low RSI={rsi:.0f}",self.NAME,tf,self.REGIME)
        if c[-1]>=up[-1] and rsi>self.ob: return StrategySignal("SHORT",strength,f"BB_up RSI={rsi:.0f}",self.NAME,tf,self.REGIME)
        return StrategySignal("NEUTRAL",0,f"no_extreme RSI={rsi:.0f}",self.NAME,tf,self.REGIME)

class ZScoreMeanReversionStrategy:
    # z=(price-rolling_mean)/rolling_std; entry z<-2.0 long, z>+2.0 short; exit z≈0
    # Lookback=half_life via OLS: hl=-ln(2)/theta where theta from Δp=θp_{t-1}+ε
    NAME="ZScoreReversion"; REGIME="RANGING"
    def __init__(self,z_entry=2.0,lookback=20,adx_max=22):
        self.z_entry=z_entry; self.lookback=lookback; self.adx_max=adx_max
    def analyze(self,df:pd.DataFrame,tf:str="4h")->StrategySignal:
        try:
            import talib
            adx=talib.ADX(df["high"].values,df["low"].values,df["close"].values,14)[-1]
            if adx>self.adx_max: return StrategySignal("NEUTRAL",0,f"TRENDING ADX={adx:.0f}",self.NAME,tf,self.REGIME)
        except: pass
        c=df["close"]; rm=c.rolling(self.lookback).mean(); rs=c.rolling(self.lookback).std()
        z=(c-rm)/rs; zv=z.iloc[-1]; strength=min(1.0,abs(zv)/(self.z_entry*2))
        if zv<-self.z_entry: return StrategySignal("LONG",strength,f"z={zv:.2f}<-{self.z_entry}",self.NAME,tf,self.REGIME)
        if zv>+self.z_entry: return StrategySignal("SHORT",strength,f"z={zv:.2f}>+{self.z_entry}",self.NAME,tf,self.REGIME)
        return StrategySignal("NEUTRAL",0,f"z={zv:.2f}",self.NAME,tf,self.REGIME)
    @staticmethod
    def half_life(s:pd.Series)->float:
        lag=s.shift(1); d=s-lag; lag=lag.dropna(); d=d.dropna()
        t=np.polyfit(lag,d,1)[0]; return -np.log(2)/t if t<0 else 20

# ── ARBITRAGE (regime=ANY) ────────────────────────────────────────────────────

class FundingRateArbitrageStrategy:
    # Delta-neutral: long_spot + short_perp = capture funding payments
    # 2025 avg APY 19.26%, maxDD 0.85% (Gate.com). Funding every 8h.
    # Entry: rate>0.0005 (0.05%/8h≈20%APY). Exit: rate<0.0001.
    # MAX LEVERAGE 3x. Risk: rate reversal, basis risk, liquidation on short leg.
    NAME="FundingArb"; REGIME="ANY"
    def __init__(self,min_r=0.0005,exit_r=0.0001,max_lev=3.0):
        self.min_r=min_r; self.exit_r=exit_r; self.max_lev=max_lev
    def analyze(self,funding_rate:float,predicted_rate:float=None,in_position:bool=False)->StrategySignal:
        ann=funding_rate*3*365*100
        if in_position:
            if funding_rate<self.exit_r: return StrategySignal("NEUTRAL",0,f"EXIT rate={funding_rate*100:.4f}%",self.NAME,"8h",self.REGIME)
            return StrategySignal("LONG",min(1.0,funding_rate/0.003),f"HOLD arb≈{ann:.1f}%APY",self.NAME,"8h",self.REGIME)
        if funding_rate<self.min_r: return StrategySignal("NEUTRAL",0,f"rate_low={funding_rate*100:.4f}%",self.NAME,"8h",self.REGIME)
        if predicted_rate is not None and predicted_rate<self.min_r*0.5:
            return StrategySignal("NEUTRAL",0.3,"rate_ok_but_reversal_predicted",self.NAME,"8h",self.REGIME)
        return StrategySignal("LONG",min(1.0,funding_rate/0.003),
                              f"ENTER arb rate={funding_rate*100:.4f}%≈{ann:.1f}%APY long_spot+short_perp max{self.max_lev}x",self.NAME,"8h",self.REGIME)

class StatisticalArbitrageStrategy:
    # Cointegrated pairs (BTC/ETH most stable). 16.34%ann Sharpe2.45 (IJSRA2026)
    # Method: Engle-Granger + OLS hedge_ratio + z-score. Re-test coint every 1-4 weeks!
    NAME="StatArb"; REGIME="ANY"
    def __init__(self,z_entry=2.0,z_exit=0.5,hedge_ratio:float=None,lookback=60):
        self.z_entry=z_entry; self.z_exit=z_exit; self.hr=hedge_ratio; self.lb=lookback
    def analyze(self,a1:pd.Series,a2:pd.Series,tf:str="1h")->dict:
        hr=self.hr or np.polyfit(a2[-self.lb:],a1[-self.lb:],1)[0]
        sp=a1-hr*a2; sm=sp.rolling(self.lb).mean().iloc[-1]; ss=sp.rolling(self.lb).std().iloc[-1]
        z=(sp.iloc[-1]-sm)/ss if ss>0 else 0; st=min(1.0,abs(z)/(self.z_entry*2))
        if z>self.z_entry:
            return {"a1":StrategySignal("SHORT",st,f"z={z:.2f}",self.NAME,tf,self.REGIME),
                    "a2":StrategySignal("LONG",st,f"z={z:.2f}",self.NAME,tf,self.REGIME),"z":z,"hr":hr}
        if z<-self.z_entry:
            return {"a1":StrategySignal("LONG",st,f"z={z:.2f}",self.NAME,tf,self.REGIME),
                    "a2":StrategySignal("SHORT",st,f"z={z:.2f}",self.NAME,tf,self.REGIME),"z":z,"hr":hr}
        return {"a1":StrategySignal("NEUTRAL",0,f"z={z:.2f}",self.NAME,tf,self.REGIME),
                "a2":StrategySignal("NEUTRAL",0,f"z={z:.2f}",self.NAME,tf,self.REGIME),"z":z,"hr":hr}
    @staticmethod
    def test_coint(s1:pd.Series,s2:pd.Series)->dict:
        try:
            from statsmodels.tsa.stattools import coint
            _,p,_=coint(s1,s2); return {"cointegrated":p<0.05,"pvalue":round(p,4)}
        except: return {"cointegrated":None,"error":"statsmodels_missing"}

# ── MARKET MAKING / GRID (regime=RANGING) ────────────────────────────────────

class DynamicGridStrategy:
    # ATR-adaptive spacing outperforms static grids 15-30%
    # Dec2024-Apr2025: BTC+9.6% SOL+21.88% vs buy-hold -16% -49%
    # spacing=clamp(ATR%×0.6, 1.0%, 4.0%); recalibrate hourly
    # STOP grid if regime=TRENDING or price exits range. MAX LEVERAGE 3x.
    NAME="DynamicGrid"; REGIME="RANGING"
    def __init__(self,capital:float,n:int=15,min_s:float=0.01,max_s:float=0.04,atr_m:float=0.6,max_lev:float=3.0):
        self.capital=capital; self.n=n; self.min_s=min_s; self.max_s=max_s; self.atr_m=atr_m; self.max_lev=max_lev
    def calculate(self,price:float,atr:float,regime:str="RANGING")->dict:
        if regime=="TRENDING": return {"active":False,"reason":"TRENDING_pause"}
        sp=np.clip(atr/price*self.atr_m,self.min_s,self.max_s); ppl=self.capital/self.n
        buys=[price*(1-sp*i) for i in range(1,self.n//2+1)]
        sells=[price*(1+sp*i) for i in range(1,self.n//2+1)]
        return {"active":True,"spacing_pct":round(sp*100,3),"per_level_usd":round(ppl,2),
                "buy_levels":[round(p,6) for p in buys],"sell_levels":[round(p,6) for p in sells],
                "stop_loss":round(buys[-1]*(1-sp*2),6),"atr_pct":round(atr/price*100,3)}
    def should_pause(self,price:float,lo:float,hi:float,regime:str)->tuple[bool,str]:
        if regime=="TRENDING": return True,"regime→TRENDING"
        if price<lo: return True,f"price<floor({lo})"
        if price>hi: return True,f"price>ceil({hi})"
        return False,"active"

class AvellanedaStoikovMarketMaker:
    # Inventory-aware MM: r=mid-q×γ×σ²×(T-t); spread=γσ²dt+(2/γ)ln(1+γ/κ)
    # Crypto: γ=0.1, κ=0.1, update σ from prior-day. Hummingbot native A-S support.
    # Inventory skew: reduce quotes on overexposed side (>50% max_inv)
    NAME="AvellanedaStoikov"; REGIME="RANGING"
    def __init__(self,gamma:float=0.1,kappa:float=0.1,T:float=1.0,min_spread:float=0.001,max_inv:float=0.3):
        self.g=gamma; self.k=kappa; self.T=T; self.ms=min_spread; self.mi=max_inv
    def quotes(self,mid:float,sigma:float,inv:float,t:float=0.5)->dict:
        dt=self.T-t; r=mid-inv*self.g*sigma**2*dt
        sh=max(self.g*sigma**2*dt/2+np.log(1+self.g/self.k)/self.g,self.ms*mid)
        bid=r-sh; ask=r+sh
        ir=abs(inv)/(self.mi*mid)
        if inv>0 and ir>0.5: bid*=(1-ir*0.002)
        elif inv<0 and ir>0.5: ask*=(1+ir*0.002)
        return {"bid":round(bid,8),"ask":round(ask,8),"spread_pct":round((ask-bid)/mid*100,4),
                "reservation":round(r,8),"inv_skew":round(inv*self.g*sigma**2*dt,8)}

# ── STRATEGY ROUTER ───────────────────────────────────────────────────────────
# Allocation half-Kelly: TRENDING→70%trend+10%meanrev+20%cash
#                        RANGING→60%meanrev+20%grid+20%fundarb
#                        VOLATILE→30%fundarb+70%cash

class StrategyRouter:
    def __init__(self,capital:float=10000):
        self.capital=capital
        self.st=SupertrendMACDStrategy(); self.eb=EMABreakoutStrategy()
        self.bb=BBRSIMeanReversionStrategy(); self.zs=ZScoreMeanReversionStrategy()
        self.fa=FundingRateArbitrageStrategy(); self.grid=DynamicGridStrategy(capital*0.2)
        self.avs=AvellanedaStoikovMarketMaker()
    def route(self,df:pd.DataFrame,regime:str,tf:str="1h",funding_rate:float=0.0)->list[StrategySignal]:
        signals=[]
        if regime=="TRENDING": signals+=[self.st.analyze(df,tf),self.eb.analyze(df,tf)]
        elif regime=="RANGING": signals+=[self.bb.analyze(df,tf),self.zs.analyze(df,tf)]
        if funding_rate!=0.0: signals.append(self.fa.analyze(funding_rate))
        active=[s for s in signals if s.signal!="NEUTRAL"]
        active.sort(key=lambda s:s.strength,reverse=True); return active
    @staticmethod
    def kelly_size(wr:float,aw:float,al:float,capital:float,frac:float=0.5)->float:
        b=aw/abs(al); return capital*max(0,(b*wr-(1-wr))/b)*frac
```

## B14: Add to orchestrator.py — regime-aware candle handler
```python
# In __init__ add: from strategies import StrategyRouter; self.router=StrategyRouter(capital=10000)

def on_candle(self,df:pd.DataFrame,regime:str,tf:str="1h",funding_rate:float=0.0,market:dict=None)->Optional[tuple]:
    if self.active: return None
    sigs=self.router.route(df,regime,tf,funding_rate)
    if not sigs: return None
    top=sigs[0]
    if top.signal=="NEUTRAL" or top.strength<0.4: return None
    from sl_tp_calculator import calculate_sl_tp
    atr=df["close"].diff().abs().rolling(14).mean().iloc[-1]; entry=df["close"].iloc[-1]
    stops=calculate_sl_tp(top.signal,entry,atr,1.0,df.attrs.get("symbol",""))
    sig=TradeSignal(symbol=df.attrs.get("symbol","UNK"),direction=Direction[top.signal],
                    entry_price=entry,sl_price=stops["sl"],tp_price=stops["tp"],
                    probability=min(0.95,0.5+top.strength*0.4),expected_value=top.strength,
                    obi=market.get("obi",0.0) if market else 0.0,atr=atr)
    return self.on_signal(sig,market) if market else None
```

## INVARIANTS (never break)
# result = f(net_pnl_pct) NOT f(close_reason)
# pnl always 4 decimals — no -0.000% display
# LONG→SL<entry→TP>entry | SHORT→SL>entry→TP<entry
# net = raw - 2×taker_fee always
# filter order: PAIR_BLOCK→SPREAD→VOLUME→MOVEMENT→TIMING→MTF→OBI
# log ALL rejections with metadata → empirical calibration loop

## DEPS
# pip install numpy pandas ta talib-binary statsmodels hmmlearn ccxt

## FILES
# bot_types.py signal_validator.py timing_filter.py cooldown_manager.py
# fast_fail_filters.py obi_filter.py sl_tp_calculator.py mtf_filter.py
# position_manager.py filter_pipeline.py orchestrator.py kronos_agent.py strategies.py

## STRATEGY MATRIX
# TRENDING  → SupertrendMACD(1h,4h) EMABreakout(15m-4h)    WR:67.9% PF:2.12
# RANGING   → BBRSIReversion(5m-1h) ZScoreReversion(1h-1d) WR:78%   avg:+1.4%
# ANY       → FundingArb(8h)~95%WR 19.26%APY maxDD0.85%  StatArb 16.34%ann Sh2.45
# RANGING   → DynamicGrid(1h calc,1m exec) 15-40%ann     A-S MM(1m-5m)
# AVOID     → Grid/BBRSIRev in TRENDING | Trend in RANGING | All directional in VOLATILE
