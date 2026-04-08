# TRADING BOT — IMPLEMENTATION SKILL
> Token-efficient reference. Paste into Claude Code as project context.
> Stack: Python 3.10+ · numpy · pandas · ccxt · torch · statsmodels

---

## ARCHITECTURE OVERVIEW
```
project/
├── indicators.py     # RSI, MACD, BB, ATR, ADX, VWAP
├── strategies/
│   ├── trend.py      # MA crossover + ADX filter
│   ├── reversion.py  # Z-score, pairs trading (OU process)
│   ├── grid.py       # Geometric grid engine
│   └── dca.py        # Safety orders + value averaging
├── risk.py           # Kelly, ATR sizing, drawdown circuit breakers
├── backtest.py       # Walk-forward + Monte Carlo
├── execution.py      # ccxt wrapper, paper/live, kill switch
├── rl_agent.py       # DQN (PyTorch)
└── config.py         # All defaults in one place
```

---

## MODULE 1 — INDICATORS (`indicators.py`)

### Math Formulas
```
RSI:    RS = EWM(gain,α=1/14) / EWM(loss,α=1/14)  →  100 - 100/(1+RS)
MACD:   line = EMA(12) - EMA(26);  signal = EMA(9,line);  hist = line - signal
BB:     mid = SMA(20);  upper/lower = mid ± 2·STD(20);  %B = (P-lower)/(upper-lower)
ATR:    TR = max(H-L, |H-Cprev|, |L-Cprev|);  ATR = EWM(TR, α=1/14)
ADX:    +DM/-DM filtered;  DX = 100·|+DI−−DI|/(+DI++DI);  ADX = EWM(DX,14)
VWAP:   VWAP = Σ(P·V) / ΣV  (intraday cumulative)
```

### Code
```python
import numpy as np, pandas as pd

def rsi(c: pd.Series, n=14) -> pd.Series:
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    return 100 - 100/(1 + g/l)

def macd(c, fast=12, slow=26, sig=9):
    line = c.ewm(span=fast,adjust=False).mean() - c.ewm(span=slow,adjust=False).mean()
    signal = line.ewm(span=sig,adjust=False).mean()
    return line, signal, line - signal          # line, signal, histogram

def bb(c, n=20, k=2.0):
    m = c.rolling(n).mean(); s = c.rolling(n).std()
    return m+k*s, m, m-k*s, (c-m+k*s)/(2*k*s)  # upper, mid, lower, %B

def atr(h, l, c, n=14) -> pd.Series:
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def adx(h, l, c, n=14):
    a = atr(h, l, c, n)
    dp = h.diff().clip(lower=0); dm = (-l.diff()).clip(lower=0)
    dp[dp < dm] = 0; dm[dm <= dp] = 0          # keep only dominant DM
    di_p = 100*dp.ewm(alpha=1/n).mean()/a
    di_m = 100*dm.ewm(alpha=1/n).mean()/a
    dx = 100*(di_p-di_m).abs()/(di_p+di_m)
    return dx.ewm(alpha=1/n).mean(), di_p, di_m # ADX, +DI, -DI
```

---

## MODULE 2 — TREND FOLLOWING (`strategies/trend.py`)

### Logic
```
ENTRY LONG:  EMA_fast > EMA_slow  AND  ADX > 25  AND  Close > EMA_200
ENTRY SHORT: EMA_fast < EMA_slow  AND  ADX > 25  AND  Close < EMA_200
STOP:        Entry ± ATR × atr_mult   (default 2.0)
SIZE:        (account × risk%) / |Entry − Stop|   → risk_pct = 0.02
TRAIL:       max(current_stop, price − ATR × trail_mult)  (long)
TP:          Entry + (Entry − Stop) × rr_ratio   (default 2.5)
```

### Code
```python
from dataclasses import dataclass
import pandas as pd, numpy as np
from indicators import rsi, macd, bb, atr, adx

@dataclass
class TrendBot:
    fast_ma: int=9; slow_ma: int=21; trend_ma: int=200
    adx_thresh: float=25.; atr_mult: float=2.0; trail_mult: float=2.5
    risk_pct: float=0.02; rr_ratio: float=2.5; capital: float=10000.

    def signals(self, df: pd.DataFrame) -> pd.DataFrame:
        c, h, l = df.close, df.high, df.low
        df['ema_f']  = c.ewm(span=self.fast_ma, adjust=False).mean()
        df['ema_s']  = c.ewm(span=self.slow_ma, adjust=False).mean()
        df['ema_t']  = c.ewm(span=self.trend_ma, adjust=False).mean()
        df['atr']    = atr(h, l, c)
        df['adx'],_,_= adx(h, l, c)
        cross_up   = (df.ema_f > df.ema_s) & (df.ema_f.shift() <= df.ema_s.shift())
        cross_dn   = (df.ema_f < df.ema_s) & (df.ema_f.shift() >= df.ema_s.shift())
        trending   = df.adx > self.adx_thresh
        df['entry_long']  = cross_up & (c > df.ema_t) & trending
        df['entry_short'] = cross_dn & (c < df.ema_t) & trending
        df['stop_long']   = c - df.atr * self.atr_mult
        df['stop_short']  = c + df.atr * self.atr_mult
        df['risk']        = df.atr * self.atr_mult
        df['size']        = (self.capital * self.risk_pct) / df.risk.replace(0, np.nan)
        df['tp_long']     = c + df.risk * self.rr_ratio
        return df

    def update_trail(self, current_stop, price, atr_val, direction='long'):
        if direction == 'long':
            return max(current_stop, price - atr_val * self.trail_mult)
        return min(current_stop, price + atr_val * self.trail_mult)
```

---

## MODULE 3 — MEAN REVERSION (`strategies/reversion.py`)

### Math
```
Z-score:   Z = (P − Rolling_Mean(n)) / Rolling_Std(n)
           Entry: Z < −2.0 (long) / Z > +2.0 (short);  Exit: |Z| < 0.5

Pairs:     Spread = P1 − β·P2 − α   (OLS hedge ratio β)
           s-score = (Spread − Spread_mean) / Spread_std
           Enter at |s| > 1.0,  exit at s ≈ 0

OU process: dS = κ(μ−S)dt + σdW
            half_life = ln(2)/κ   (from OLS: delta_S = β·lag_S + ε,  κ = −β)
            Use pairs only if: half_life 5–30 bars  AND  ADF p < 0.05
```

### Code
```python
from scipy import stats
from statsmodels.tsa.stattools import adfuller

def zscore(prices: pd.Series, n=20):
    m, s = prices.rolling(n).mean(), prices.rolling(n).std()
    return (prices - m) / s

def zscore_signals(prices, n=20, entry=2., exit=0.5, stop=3.5):
    z = zscore(prices, n)
    return z, (z < -entry), (z > entry), (z.abs() < exit), (z.abs() > stop)

class PairsTrader:
    def __init__(self, lookback=60, entry_z=2., exit_z=0.5, stop_z=3.5):
        self.lb, self.ez, self.xz, self.sz = lookback, entry_z, exit_z, stop_z

    def hedge_ratio(self, p1, p2):
        b, a, r, *_ = stats.linregress(p2, p1)
        return b, a, r**2                      # β, α, R²

    def half_life(self, spread):
        s = spread.dropna(); lag = s.shift(1).dropna(); d = s.diff().dropna()
        b, *_ = stats.linregress(lag, d)
        return np.log(2) / max(-b, 1e-9)       # returns bars

    def is_tradeable(self, p1, p2):
        b, a, _ = self.hedge_ratio(p1, p2)
        spread = p1 - b*p2 - a
        hl = self.half_life(spread)
        pval = adfuller(spread.dropna())[1]
        return pval < 0.05 and 5 < hl < 60, pval, hl

    def signals(self, p1, p2):
        b, a, _ = self.hedge_ratio(p1.iloc[-self.lb:], p2.iloc[-self.lb:])
        spread = p1 - b*p2 - a
        z = zscore(spread, self.lb)
        return {'z': z, 'long_p1': z < -self.ez, 'short_p1': z > self.ez,
                'exit': z.abs() < self.xz, 'stop': z.abs() > self.sz,
                'hedge': b}
```

---

## MODULE 4 — GRID TRADING (`strategies/grid.py`)

### Math
```
Geometric:  P_n = Base × (1 + step%)^n   ← preferred (equal % profit)
Arithmetic: P_n = Base + n × step_$

Profit/cycle = order_size × step% − 2 × fee_rate
Capital_req  = levels_below × order_size × 1.5   (safety buffer)
Daily_return ≈ (daily_vol% / step%) × profit_per_cycle

Dynamic step = ATR_14 × mult  (0.3–0.8×);  pause if ADX > 28
```

### Code
```python
@dataclass
class GridBot:
    symbol: str; base: float; step: float=0.005; levels: int=10
    order_usd: float=100.; fee: float=0.001; geometric: bool=True

    def __post_init__(self):
        self.buys: list[float] = []; self.sells: list[float] = []; self.pnl = 0.

    def grid_price(self, n: int) -> float:
        return self.base*(1+self.step)**n if self.geometric else self.base+n*self.base*self.step

    def init(self, price: float) -> dict[str, list]:
        orders = {'buy': [], 'sell': []}
        for n in range(-self.levels, self.levels+1):
            p = self.grid_price(n)
            (orders['buy'] if p < price else orders['sell']).append(round(p, 8))
        self.buys, self.sells = orders['buy'], orders['sell']
        return orders

    def on_price(self, price: float) -> list[dict]:
        actions = []
        for bp in list(self.buys):
            if price <= bp:
                self.buys.remove(bp)
                sell_p = bp * (1 + self.step)
                self.sells.append(sell_p)
                actions.append({'fill': 'buy', 'at': bp, 'counter_sell': sell_p})
        for sp in list(self.sells):
            if price >= sp:
                self.sells.remove(sp)
                buy_p = sp / (1 + self.step)
                profit = (self.order_usd/buy_p)*(sp - buy_p) - self.order_usd*(sp+buy_p)*self.fee/buy_p
                self.pnl += profit
                self.buys.append(buy_p)
                actions.append({'cycle': 'complete', 'profit': round(profit, 4)})
        return actions

    def profit_per_cycle(self) -> float:
        return self.order_usd * self.step - 2 * self.order_usd * self.fee
```

---

## MODULE 5 — DCA BOT (`strategies/dca.py`)

### Math
```
Safety order n:   price_n  = entry × (1 − dev_n/100)
                  volume_n = base_vol × scale^n       (scale typically 1.5)
Avg entry:        Σ(price_i × vol_i) / Σ(vol_i)
Take profit:      avg_entry × (1 + tp% + 2×fee)       (recalc after each SO)
Break-even:       avg_entry × (1 + 2×fee)
Max capital:      base + Σ(base × scale^n) for n in 0..max_safety
```

### Code
```python
@dataclass
class DCABot:
    base_usd: float=100.; safety_usd: float=100.; max_so: int=5
    scale: float=1.5; devs: list=field(default_factory=lambda:[1.5,3,6,12,20])
    tp_pct: float=1.5; sl_pct: float=25.; fee: float=0.001

    def __post_init__(self):
        self.pos: list[tuple[float,float]] = []; self.so_n = 0
        self.entry = self.avg = self.tp = self.sl = 0.; self.active = False

    def start(self, price):
        qty = self.base_usd / price
        self.pos = [(price, qty)]; self.entry = price
        self.sl = price * (1 - self.sl_pct/100)
        self._recalc(); self.active = True
        return {'action':'open', 'price':price, 'qty':qty, 'tp':self.tp, 'sl':self.sl}

    def _recalc(self):
        tv = sum(p*q for p,q in self.pos); tq = sum(q for _,q in self.pos)
        self.avg = tv/tq if tq else 0
        self.tp  = self.avg * (1 + self.tp_pct/100 + 2*self.fee)

    def tick(self, price) -> dict | None:
        if not self.active: return None
        if price >= self.tp:
            self.active = False
            tq = sum(q for _,q in self.pos)
            return {'action':'tp','pnl': tq*(price-self.avg) - tq*(price+self.avg)*self.fee}
        if price <= self.sl:
            self.active = False
            tq = sum(q for _,q in self.pos)
            return {'action':'sl','loss': tq*(price-self.avg)}
        if self.so_n < min(self.max_so, len(self.devs)):
            so_price = self.entry * (1 - self.devs[self.so_n]/100)
            if price <= so_price:
                qty = (self.safety_usd * self.scale**self.so_n) / price
                self.pos.append((price, qty)); self.so_n += 1; self._recalc()
                return {'action':'safety','n':self.so_n,'avg':self.avg,'tp':self.tp}
        return None
```

---

## MODULE 6 — RISK MANAGER (`risk.py`)

### Formulas
```
Fixed Fractional:  size = (account × risk%) / |entry − stop|    [risk% = 0.01–0.02]
Kelly:             f* = (b·p − q)/b;  use_f = f* × 0.25        [b=win/loss, p=winrate]
ATR Sizing:        size = (account × risk%) / (ATR × atr_mult)
ERC (portfolio):   w_i = (1/σ_i) / Σ(1/σ_j)                   [equal risk contribution]

Drawdown tiers:
  daily_loss > 5%  → halve position sizes
  drawdown > 10%   → halt new trades
  drawdown > 15%   → full halt + alert
  drawdown > 20%   → kill switch + log
```

### Code
```python
class RiskManager:
    def __init__(self, account=10000., risk=0.02, max_dd=0.15,
                 daily_lim=0.05, max_pos=10, kelly_frac=0.25):
        self.account = self.peak = account
        self.risk = risk; self.max_dd = max_dd; self.daily_lim = daily_lim
        self.max_pos = max_pos; self.kf = kelly_frac
        self.daily_pnl = 0.; self.halt = False; self.open_pos = {}

    # ── Sizing ─────────────────────────────────────────────────────────
    def fixed_size(self, entry, stop) -> float:
        return (self.account * self.risk) / abs(entry - stop) if entry != stop else 0

    def kelly_size(self, winrate, avg_win, avg_loss) -> float:
        b = avg_win / max(avg_loss, 1e-9); p = winrate; q = 1 - p
        f = max(0, min((b*p - q)/b, 0.5)) * self.kf
        return self.account * f

    def atr_size(self, atr_val, mult=2.0) -> float:
        return (self.account * self.risk) / (atr_val * mult)

    # ── Circuit Breakers ────────────────────────────────────────────────
    def update(self, equity: float) -> dict:
        self.peak = max(self.peak, equity)
        dd = (self.peak - equity) / self.peak
        dl = -self.daily_pnl / self.account
        if dd > self.max_dd or dl > 0.20:
            self._kill(f"DD={dd:.1%}")
        elif dd > 0.10:
            self.halt = True
        elif dl > self.daily_lim:
            self.risk = max(0.005, self.risk * 0.5)
        return {'dd': dd, 'daily_loss': dl, 'halt': self.halt, 'risk': self.risk}

    def _kill(self, reason):
        self.halt = True
        import datetime, json
        with open('kill_log.jsonl','a') as f:
            f.write(json.dumps({'ts': str(datetime.datetime.utcnow()),
                                'reason': reason, 'equity': self.account}) + '\n')
        print(f'[KILL SWITCH] {reason}')

    def can_trade(self, sym) -> tuple[bool, str]:
        if self.halt:            return False, 'halt'
        if len(self.open_pos) >= self.max_pos: return False, 'max_pos'
        return True, 'ok'
```

---

## MODULE 7 — BACKTESTING (`backtest.py`)

### Metrics
```
Sharpe  = mean(ret)/std(ret) × √252          [target > 1.5]
Sortino = mean(ret)/std(ret<0) × √252        [target > 2.0]
Calmar  = annual_return / max_drawdown        [target > 0.5]
PF      = Σwins / |Σlosses|                  [target > 1.5]
Max DD  = max((peak−val)/peak)               [< 15%]

Walk-forward split: 60% train / 20% validation / 20% holdout
OOS ratio: OOS_Sharpe / IS_Sharpe > 0.6 → robust
Parameter sensitivity: ±10% change should not collapse Sharpe >50%
```

### Code
```python
def backtest(df: pd.DataFrame, signal_fn, capital=10000.,
             slippage=0.0002, fee=0.001) -> dict:
    df = signal_fn(df.copy())
    equity=[capital]; cash=capital; pos=qty=ep=0.
    trades=[]
    for _, r in df.iterrows():
        p = r.close
        if pos==0 and r.get('entry_long',False):
            fp = p*(1+slippage+fee); qty=cash*0.95/fp; cash-=qty*fp; ep=fp; pos=1
        elif pos==1 and r.get('exit',False):
            fp = p*(1-slippage-fee); pnl=qty*(fp-ep); cash+=qty*fp
            trades.append({'pnl':pnl}); pos=qty=0
        equity.append(cash if pos==0 else cash+qty*p)
    eq=pd.Series(equity); r=eq.pct_change().dropna()
    dd=(eq.cummax()-eq)/eq.cummax()
    wins=[t['pnl'] for t in trades if t['pnl']>0]
    loss=[abs(t['pnl']) for t in trades if t['pnl']<=0]
    return {'ret':eq.iloc[-1]/eq.iloc[0]-1,
            'sharpe':round(r.mean()/r.std()*252**.5,2) if r.std()>0 else 0,
            'max_dd':round(dd.max(),4), 'pf':sum(wins)/max(sum(loss),.01),
            'win_rate':len(wins)/max(len(trades),1), 'n':len(trades)}

def walk_forward(df, signal_fn_factory, params_list,
                 train=0.6, test=0.2, step=0.1):
    """Returns list of OOS results per window."""
    n = len(df); oos=[]
    i=0
    while i+int(n*(train+test)) <= n:
        tr = df.iloc[i:i+int(n*train)]
        te = df.iloc[i+int(n*train):i+int(n*(train+test))]
        best_s, best_p = -999, None
        for p in params_list:
            try:
                r = backtest(tr, signal_fn_factory(**p))
                if r['sharpe'] > best_s: best_s,best_p = r['sharpe'],p
            except: pass
        if best_p:
            r = backtest(te, signal_fn_factory(**best_p))
            r['params']=best_p; oos.append(r)
        i += int(n*step)
    return oos

def monte_carlo(trades, n=10000, capital=10000.) -> dict:
    pnls=[t['pnl'] for t in trades]
    results=[]; rng=np.random.default_rng()
    for _ in range(n):
        eq=capital+np.cumsum(rng.choice(pnls,len(pnls),replace=True))
        dd=((np.maximum.accumulate(np.r_[capital,eq])-np.r_[capital,eq])
            /np.maximum.accumulate(np.r_[capital,eq])).max()
        results.append((eq[-1],dd))
    f,d=zip(*results)
    return {'p5':np.percentile(f,5),'median':np.median(f),'p95':np.percentile(f,95),
            'worst_dd':np.percentile(d,95),'prob_ruin':sum(x<capital*.5 for x in f)/n}
```

---

## MODULE 8 — DQN AGENT (`rl_agent.py`)

### State / Reward Design
```
State vector (normalized, ~7–15 features):
  [RSI/100, MACD_hist/ATR, BB_%B, ADX/100, position(-1/0/1),
   unrealized_pnl/ATR, close/SMA20-1, volume_z, hour/24, ...]

Actions:  0=hold, 1=buy/long, 2=sell/close

Reward (Sharpe-based):
  r = delta_pnl / rolling_std(pnl, 20)  −  trade_cost × |action_changed|
  Penalize: large drawdowns (×0.1), holding losing position long
```

### Code
```python
import torch, torch.nn as nn
from collections import deque
import random, numpy as np

class QNet(nn.Module):
    def __init__(self, s_dim, n_act=3, h=128):
        super().__init__()
        self.net=nn.Sequential(nn.Linear(s_dim,h),nn.ReLU(),nn.Dropout(.1),
                               nn.Linear(h,h),nn.ReLU(),nn.Dropout(.1),nn.Linear(h,n_act))
    def forward(self,x): return self.net(x)

class DQN:
    def __init__(self, s_dim, lr=1e-3, gamma=.99, eps=1., eps_min=.05,
                 eps_decay=.995, batch=64, buf=50000, target_upd=100):
        self.n_act=3; self.gamma=gamma; self.eps=eps; self.eps_min=eps_min
        self.eps_decay=eps_decay; self.batch=batch; self.target_upd=target_upd
        self.q = QNet(s_dim); self.qt = QNet(s_dim)
        self.qt.load_state_dict(self.q.state_dict())
        self.opt = torch.optim.Adam(self.q.parameters(),lr=lr)
        self.buf = deque(maxlen=buf); self.steps=0

    def act(self, s) -> int:
        if random.random() < self.eps: return random.randrange(self.n_act)
        with torch.no_grad(): return self.q(torch.FloatTensor(s).unsqueeze(0)).argmax().item()

    def push(self, s, a, r, ns, done): self.buf.append((s,a,r,ns,done))

    def train_step(self) -> float:
        if len(self.buf)<self.batch: return 0.
        b=random.sample(self.buf,self.batch)
        s,a,r,ns,d=map(np.array,zip(*b))
        s,a,r,ns,d=(torch.FloatTensor(s),torch.LongTensor(a),torch.FloatTensor(r),
                    torch.FloatTensor(ns),torch.FloatTensor(d))
        q=self.q(s).gather(1,a.unsqueeze(1)).squeeze(1)
        with torch.no_grad(): tgt=r+self.gamma*self.qt(ns).max(1)[0]*(1-d)
        loss=nn.MSELoss()(q,tgt)
        self.opt.zero_grad(); loss.backward()
        nn.utils.clip_grad_norm_(self.q.parameters(),1.); self.opt.step()
        self.eps=max(self.eps_min,self.eps*self.eps_decay)
        self.steps+=1
        if self.steps%self.target_upd==0: self.qt.load_state_dict(self.q.state_dict())
        return loss.item()

def build_state(row, position, account, initial) -> np.ndarray:
    """Build normalized state. row = df.iloc[i] with indicators pre-computed."""
    atr_v = row.get('atr',1.)
    return np.array([
        row.get('rsi',50)/100,
        row.get('macd_hist',0)/max(atr_v,1e-8),
        row.get('pct_b',.5),
        row.get('adx',20)/100,
        float(position),
        (account-initial)/initial,
        row.get('trend_dev',0),         # close/sma20 - 1
    ], dtype=np.float32)

def sharpe_reward(pnl_hist, cur_pnl, traded=False, fee=.001):
    pnl_hist.append(cur_pnl)
    if len(pnl_hist)<2: return 0.
    rets=np.diff(pnl_hist[-20:]); std=rets.std()+1e-8
    return float(rets[-1]/std) - (fee if traded else 0.)
```

---

## MODULE 9 — EXECUTION (`execution.py`)

### Code
```python
import ccxt, pandas as pd
from typing import Optional

class Exchange:
    def __init__(self, ex_id: str, key: str, secret: str, paper=True):
        self.paper = paper
        cls = getattr(ccxt, ex_id)
        self.ex = cls({'apiKey':key,'secret':secret,'enableRateLimit':True})
        self.pb = {}; self.po = []   # paper balance, paper orders

    def ohlcv(self, sym, tf='1h', limit=500) -> pd.DataFrame:
        raw = self.ex.fetch_ohlcv(sym, tf, limit=limit)
        df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
        df.ts = pd.to_datetime(df.ts, unit='ms')
        return df.set_index('ts')

    def order(self, sym, side, qty, otype='market', price=None) -> dict:
        if self.paper: return self._paper(sym, side, qty, price)
        try:
            fn = self.ex.create_market_order if otype=='market' else self.ex.create_limit_order
            return fn(sym, side, qty) if otype=='market' else fn(sym, side, qty, price)
        except (ccxt.InsufficientFunds, ccxt.NetworkError) as e:
            return {'error': str(e)}

    def _paper(self, sym, side, qty, price=None) -> dict:
        tk = self.ex.fetch_ticker(sym)
        fp = tk['ask']*(1.001) if side=='buy' else tk['bid']*(0.999)
        base,quote = sym.split('/')
        if side=='buy':
            self.pb[quote]=self.pb.get(quote,0)-qty*fp; self.pb[base]=self.pb.get(base,0)+qty
        else:
            self.pb[quote]=self.pb.get(quote,0)+qty*fp; self.pb[base]=self.pb.get(base,0)-qty
        o={'id':f'p{len(self.po)}','status':'closed','filled':qty,'price':fp}
        self.po.append(o); return o

    def kill(self, sym=None):
        """Emergency: cancel all open orders."""
        if not self.paper:
            for o in self.ex.fetch_open_orders(sym or ''):
                try: self.ex.cancel_order(o['id'], sym)
                except: pass
```

---

## CONFIG (`config.py`)

```python
# All recommended defaults in one place
CFG = {
    # Indicators
    'rsi_period': 14, 'rsi_ob': 70, 'rsi_os': 30,
    'macd': (12, 26, 9), 'bb_period': 20, 'bb_std': 2.0,
    'atr_period': 14, 'adx_period': 14, 'adx_trend_thresh': 25,

    # Trend strategy
    'fast_ma': 9, 'slow_ma': 21, 'trend_ma': 200,
    'atr_stop_mult': 2.0, 'trail_mult': 2.5, 'rr_ratio': 2.5,

    # Grid
    'grid_step': 0.005, 'grid_levels': 10, 'grid_order_usd': 100,

    # DCA
    'dca_base': 100, 'dca_safety': 100, 'dca_max_so': 5,
    'dca_scale': 1.5, 'dca_devs': [1.5, 3.0, 6.0, 12.0, 20.0],
    'dca_tp_pct': 1.5, 'dca_sl_pct': 25.0,

    # Risk
    'risk_per_trade': 0.02, 'kelly_fraction': 0.25,
    'max_drawdown': 0.15, 'daily_loss_limit': 0.05, 'max_positions': 10,

    # Backtest
    'slippage': 0.0002, 'fee': 0.001,
    'wfo_train': 0.60, 'wfo_val': 0.20, 'wfo_holdout': 0.20,
    'mc_simulations': 10000,

    # DQN
    'dqn_lr': 1e-3, 'dqn_gamma': 0.99, 'dqn_eps_start': 1.0,
    'dqn_eps_min': 0.05, 'dqn_eps_decay': 0.995,
    'dqn_batch': 64, 'dqn_buf': 50000, 'dqn_target_upd': 100,

    # Performance thresholds (halt/retire if below)
    'min_sharpe': 1.5, 'max_dd_pct': 0.15, 'min_pf': 1.5, 'min_calmar': 0.5,
    'sharpe_decay_alert': 0.50,  # alert if rolling Sharpe drops 50% from baseline
    'reoptimize_months': 3,      # re-optimize every N months
}
```

---

## QUICK CHEATSHEET

| Signal | Entry | Exit | Stop |
|--------|-------|------|------|
| Trend | EMA cross + ADX>25 + price>EMA200 | EMA cross back | ATR×2 below entry |
| Mean Rev | Z < −2.0 | Z > −0.5 | Z > −3.5 |
| Grid | ATR-based step (0.5–1×ATR) | Cycle complete | Upper/lower grid breach |
| DCA | Market/signal | TP = avg × (1+tp%) | Hard SL at −25% |
| Pairs | \|s-score\| > 1.0 | s-score ≈ 0 | \|s-score\| > 3.0 |

| Metric | Minimum | Good | Kill |
|--------|---------|------|------|
| Sharpe | 1.5 | 2.0+ | < 0.75 (50% decay) |
| Max DD | < 20% | < 10% | > 15% → halt |
| PF | 1.5 | 2.0+ | < 1.1 |
| Win Rate | context | 55%+ (rev) | n/a |

```
POSITION SIZE = (Account × risk%) / |Entry − Stop|   [risk% ≤ 0.02]
KELLY SAFE    = f* × 0.25   where f* = (b·p − q)/b
ATR STOP      = Entry − ATR × 2.0   (long)
TRAIL STOP    = max(prev_stop, price − ATR × 2.5)
GRID PROFIT   = order_usd × step% − 2 × fee
HALF LIFE     = ln(2) / κ   (OU, from OLS delta~lag regression)
```

---

## DEPENDENCIES
```bash
pip install numpy pandas scipy statsmodels ccxt
pip install torch                        # DQN agent
pip install pandas-ta                    # alternative to TA-Lib
pip install backtrader vectorbt          # backtesting
pip install transformers                 # FinBERT sentiment
pip install praw tweepy python-telegram-bot
```
