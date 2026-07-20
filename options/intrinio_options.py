"""
intrinio_options — устойчивый фетчер EOD-цепочек опционов (Intrinio) + VRP/GEX фичи.

Качаем ОДИН снапшот/день через get_options_prices_eod_by_ticker (пагинация),
кешируем по дню в parquet (resume — не перекачиваем), затем считаем дневные
VRP/IV-surface и GEX фичи. API-ключ берётся из env INTRINIO_API_KEY.

Smoke-test (1 день):  python intrinio_options.py SPY 2024-01-03
"""
import os
import time
import sys
import numpy as np
import pandas as pd

# путь относительно расположения модуля → проект портативен (переезд папки не ломает кэш)
CACHE_ROOT = os.environ.get('QUANT_CACHE_ROOT',
                            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache', 'intrinio'))


# ─────────────────────────────────────────────────────────────
# Клиент
# ─────────────────────────────────────────────────────────────
def get_api(api_key=None):
    import intrinio_sdk as intrinio
    key = api_key or os.environ.get('INTRINIO_API_KEY')
    if not key:
        raise RuntimeError('Нет ключа: задай env INTRINIO_API_KEY или передай api_key')
    intrinio.ApiClient().set_api_key(key)
    intrinio.ApiClient().allow_retries(True)
    return intrinio.OptionsApi()


# ─────────────────────────────────────────────────────────────
# Фетч одного дня (все контракты тикера) с пагинацией
# ─────────────────────────────────────────────────────────────
def _row(item):
    o, p = item.option, item.price
    return {
        'expiration': o.expiration, 'strike': o.strike, 'type': o.type,
        'close': p.close, 'bid': p.close_bid, 'ask': p.close_ask, 'mark': p.mark,
        'volume': p.volume, 'open_interest': p.open_interest,
        'iv': p.implied_volatility, 'delta': p.delta, 'gamma': p.gamma,
        'theta': p.theta, 'vega': p.vega,
    }


def fetch_day(symbol, date, api=None, page_size=1000, pause=0.1,
              recalc=False, model='black_scholes', max_retries=4):
    """Все контракты symbol за date → DataFrame. Пагинация + ретраи."""
    api = api or get_api()
    rows, next_page = [], ''
    while True:
        for attempt in range(max_retries):
            try:
                resp = api.get_options_prices_eod_by_ticker(
                    symbol, page_size=page_size, date=date,
                    recalculate_stats=recalc, model=model,
                    next_page=next_page or '', _request_timeout=30)
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)        # экспоненциальный бэкофф
        rows.extend(_row(it) for it in resp.prices)
        next_page = getattr(resp, 'next_page', None)
        if not next_page:
            break
        time.sleep(pause)                       # rate-limit
    df = pd.DataFrame(rows)
    if len(df):
        df['quote_date'] = pd.to_datetime(date)
        df['expiration'] = pd.to_datetime(df['expiration'])
        df['dte'] = (df['expiration'] - df['quote_date']).dt.days
    return df


def fetch_range(symbol, dates, api=None, **kw):
    """Качает список дат с кешем+resume (parquet/день). dates — iterable 'YYYY-MM-DD'."""
    api = api or get_api()
    outdir = os.path.join(CACHE_ROOT, symbol)
    os.makedirs(outdir, exist_ok=True)
    for d in dates:
        ds = str(d)[:10]
        fp = os.path.join(outdir, f'{ds}.parquet')
        mk = os.path.join(outdir, f'{ds}.empty')
        if os.path.exists(fp) or os.path.exists(mk):
            continue                            # resume: уже скачано / помечено пустым
        try:
            df = fetch_day(symbol, ds, api=api, **kw)
        except Exception as e:
            print(f'[skip] {ds}: {e}')
            continue
        if len(df):
            df.to_parquet(fp)
            print(f'[ok] {ds}: {len(df)} контрактов')
        else:
            open(mk, 'w').close()               # маркер пустого дня — не перекачивать
            print(f'[empty] {ds}')


def load_cached(symbol):
    """Склеивает кеш в один DataFrame. symbol: str или список (напр. ['SPX','SPXW']
       → полная цепочка: SPX месячные + SPXW дневные/недельные)."""
    syms = [symbol] if isinstance(symbol, str) else list(symbol)
    dfs = []
    for sym in syms:
        outdir = os.path.join(CACHE_ROOT, sym)
        if not os.path.isdir(outdir):
            continue
        for f in sorted(os.listdir(outdir)):
            if f.endswith('.parquet'):
                dfs.append(pd.read_parquet(os.path.join(outdir, f)))
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


# ─────────────────────────────────────────────────────────────
# Дневные фичи: VRP / IV-surface  (нужен spot — передаём извне)
# ─────────────────────────────────────────────────────────────
def _interp_atm_iv(chain, spot, target_dte):
    """ATM IV (ближайший к деньгам страйк), интерполированная к target_dte по двум экспирациям."""
    c = chain.dropna(subset=['iv', 'dte', 'strike'])
    c = c[(c['iv'] > 0) & (c['dte'] > 0)]
    if c.empty:
        return np.nan
    # ATM IV по каждой экспирации = среднее call/put IV у ближайшего страйка
    atm = []
    for dte, g in c.groupby('dte'):
        k = g.iloc[(g['strike'] - spot).abs().argsort()[:2]]   # 2 ближайших страйка
        atm.append((dte, k['iv'].mean()))
    atm = sorted(atm)
    dtes = np.array([a[0] for a in atm]); ivs = np.array([a[1] for a in atm])
    if target_dte <= dtes.min() or target_dte >= dtes.max():
        return float(ivs[np.abs(dtes - target_dte).argmin()])
    return float(np.interp(target_dte, dtes, ivs))


def iv_surface_features(chain, spot):
    """ATM IV 30/60d, term-slope, 25-delta skew, put/call IV — на один день."""
    f = {}
    f['atm_iv_30'] = _interp_atm_iv(chain, spot, 30)
    f['atm_iv_60'] = _interp_atm_iv(chain, spot, 60)
    f['iv_term_slope'] = f['atm_iv_60'] - f['atm_iv_30']
    # 25-delta skew: IV пута(delta≈-0.25) − IV колла(delta≈0.25) у ~30d
    near = chain[(chain['dte'] >= 20) & (chain['dte'] <= 45)].dropna(subset=['iv', 'delta'])
    puts, calls = near[near['type'] == 'put'], near[near['type'] == 'call']
    def iv_at_delta(g, tgt):
        if g.empty: return np.nan
        return g.iloc[(g['delta'] - tgt).abs().argsort()[:1]]['iv'].mean()
    f['skew_25d'] = iv_at_delta(puts, -0.25) - iv_at_delta(calls, 0.25)
    return f


# ─────────────────────────────────────────────────────────────
# GEX (dealer gamma exposure) — нужен OI (есть в Intrinio)
# Конвенция: дилеры long calls / short puts → знак (call_gamma − put_gamma).
# GEX = Σ gamma · OI · 100 · spot²·0.01  (в $/1% движения). Знак настраиваемый.
# ─────────────────────────────────────────────────────────────
def gex(chain, spot, dte_max=None):
    c = chain.dropna(subset=['gamma', 'open_interest', 'type'])
    if dte_max is not None:
        c = c[c['dte'] <= dte_max]
    if c.empty:
        return np.nan
    sign = np.where(c['type'] == 'call', 1.0, -1.0)
    notional = c['gamma'] * c['open_interest'] * 100 * (spot ** 2) * 0.01
    return float((sign * notional).sum())


# ─────────────────────────────────────────────────────────────
def gex_by_dte(chain, spot, buckets=((0, 7), (7, 30), (30, 90))):
    """GEX в разбивке по горизонтам DTE — near-term гамма vs среднесрочная."""
    out = {}
    for lo, hi in buckets:
        sub = chain[(chain['dte'] > lo) & (chain['dte'] <= hi)]
        out[f'gex_{lo}_{hi}'] = gex(sub, spot) if len(sub) else np.nan
    return out


def positioning_features(chain, spot, dte_max=90):
    """OI-карта позиционирования (Layer 1) на горизонте ≤dte_max:
       put/call OI, call/put-стены (макс OI), концентрация OI."""
    c = chain[(chain['dte'] > 0) & (chain['dte'] <= dte_max)].dropna(
        subset=['open_interest', 'strike', 'type'])
    if c.empty:
        return {}
    calls = c[c['type'] == 'call']; puts = c[c['type'] == 'put']
    coi = calls['open_interest'].sum(); poi = puts['open_interest'].sum()
    f = {'put_call_oi': poi / coi if coi > 0 else np.nan}
    ca = calls[calls['strike'] >= spot]; pb = puts[puts['strike'] <= spot]
    if len(ca):
        f['call_wall_dist'] = (ca.groupby('strike')['open_interest'].sum().idxmax() - spot) / spot
    if len(pb):
        f['put_wall_dist'] = (pb.groupby('strike')['open_interest'].sum().idxmax() - spot) / spot
    oi_strike = c.groupby('strike')['open_interest'].sum().sort_values(ascending=False)
    tot = oi_strike.sum()
    f['oi_concentration'] = oi_strike.head(5).sum() / tot if tot > 0 else np.nan
    f['net_oi_90d'] = (coi - poi)
    return f


def _bs_iv(price, S, K, T, r, is_call, n_iter=60):
    """Векторная BS implied vol из цены (Newton). Обходит битую вендорскую IV."""
    from scipy.stats import norm
    sigma = np.full(len(price), 0.3)
    for _ in range(n_iter):
        sq = sigma * np.sqrt(T)
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / sq
        d2 = d1 - sq
        model = np.where(is_call,
                         S * norm.cdf(d1) - K * np.exp(-r*T) * norm.cdf(d2),
                         K * np.exp(-r*T) * norm.cdf(-d2) - S * norm.cdf(-d1))
        vega = S * norm.pdf(d1) * np.sqrt(T)
        sigma = np.clip(sigma - (model - price) / np.where(vega < 1e-8, 1e-8, vega), 1e-3, 5.0)
    return sigma


def _bs_gamma(S, K, T, r, sigma):
    from scipy.stats import norm
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))


def _recompute_iv_gamma(chain, spot, rate=0.04):
    """Пересчёт iv+gamma из марок (для near-money ±25%); дальние страйки gamma≈0."""
    c = chain.copy()
    m = (c['mark'] > 0.05) & (c['dte'] > 0) & ((c['strike']/spot - 1).abs() < 0.25)
    sub = c[m]
    if sub.empty:
        return c
    from scipy.stats import norm
    T = sub['dte'].values / 365.0; K = sub['strike'].values
    iscall = (sub['type'] == 'call').values
    iv = _bs_iv(sub['mark'].values, spot, K, T, rate, iscall)
    d1 = (np.log(spot / K) + (rate + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
    c.loc[m, 'iv'] = iv
    c.loc[m, 'gamma'] = norm.pdf(d1) / (spot * iv * np.sqrt(T))
    c.loc[m, 'delta'] = np.where(iscall, norm.cdf(d1), norm.cdf(d1) - 1)
    c.loc[~m, 'gamma'] = 0.0
    return c


def infer_spot(chain):
    """Spot из цепочки по put-call parity (страйк min|call_mark−put_mark| на ближнем DTE).
       Для индексов (SPX/NDX), где securities-spot недоступен."""
    c = chain.dropna(subset=['mark', 'strike', 'type', 'dte'])
    c = c[(c['dte'] > 0) & (c['mark'] > 0.05)]   # только реально котируемые (без нулевых марок)
    if c.empty:
        return np.nan
    near = c[c['dte'] == c['dte'].min()]
    piv = near.pivot_table(index='strike', columns='type', values='mark', aggfunc='first')
    if 'call' in piv and 'put' in piv:
        diff = (piv['call'] - piv['put']).abs()
        if diff.notna().any():
            return float(diff.idxmin())
    calls = c[c['type'] == 'call'].dropna(subset=['delta'])
    if len(calls):
        return float(calls.iloc[(calls['delta'] - 0.5).abs().values.argmin()]['strike'])
    return np.nan


def atm_straddle_cost(chain, spot, target_dte=30):
    """Round-trip транзакционный кост short ATM-straddle = (ask−bid)/mark
       (call+put у ближайшего к spot страйка, экспирация ближе к target_dte).
       Доля от премии — заменяет выдуманный COST_FRAC реальным спредом."""
    c = chain.dropna(subset=['bid', 'ask', 'mark', 'strike', 'dte', 'type'])
    c = c[(c['dte'] > 0) & (c['mark'] > 0.05)]
    if c.empty:
        return np.nan
    dte = c['dte'].iloc[(c['dte'] - target_dte).abs().values.argmin()]
    g = c[c['dte'] == dte]
    k = g['strike'].iloc[(g['strike'] - spot).abs().values.argmin()]
    leg = g[g['strike'] == k]
    call = leg[leg['type'] == 'call']; put = leg[leg['type'] == 'put']
    if call.empty or put.empty:
        return np.nan
    spread = (call['ask'].iloc[0] - call['bid'].iloc[0]) + (put['ask'].iloc[0] - put['bid'].iloc[0])
    mark = call['mark'].iloc[0] + put['mark'].iloc[0]
    return float(spread / mark) if mark > 0 else np.nan


def daily_features(symbol, spot_series=None, recompute=False, rate=0.04):
    """Склеивает кеш → дневные фичи (iv-surface + gex). spot_series: Series date->spot
       (если None — infer_spot). recompute=True → iv+gamma пересчитываются из марок
       (обязательно для SPX/NDX: вендорская IV/greeks битые)."""
    raw = load_cached(symbol)
    if raw.empty:
        return pd.DataFrame()
    out = []
    for qd, chain in raw.groupby('quote_date'):
        spot = None if spot_series is None else spot_series.get(pd.Timestamp(qd))
        if spot is None or (isinstance(spot, float) and np.isnan(spot)):
            spot = infer_spot(chain)
        if spot is None or np.isnan(spot):
            continue
        if recompute:
            chain = _recompute_iv_gamma(chain, spot, rate)
        row = {'date': pd.Timestamp(qd), 'spot': spot}
        row.update(iv_surface_features(chain, spot))
        row['gex'] = gex(chain, spot)
        row['gex_0dte'] = gex(chain, spot, dte_max=1)
        row.update(gex_by_dte(chain, spot))          # gex_0_7 / 7_30 / 30_90
        row.update(positioning_features(chain, spot)) # OI-карта (Layer 1)
        row['straddle_spread'] = atm_straddle_cost(chain, spot)  # реальный round-trip кост
        out.append(row)
    return pd.DataFrame(out).set_index('date').sort_index()


# ─────────────────────────────────────────────────────────────
# Spot (underlying) — из Securities API; RV считаем сами
# ─────────────────────────────────────────────────────────────
def fetch_spot(symbol, start_date, end_date, api_key=None, page_size=10000):
    """EOD close базового актива (напр. SPY) → Series date->close (adj_close тоже)."""
    import intrinio_sdk as intrinio
    key = api_key or os.environ.get('INTRINIO_API_KEY')
    if not key:
        raise RuntimeError('Нет ключа INTRINIO_API_KEY')
    intrinio.ApiClient().set_api_key(key); intrinio.ApiClient().allow_retries(True)
    sec = intrinio.SecurityApi()
    rows, nxt = [], ''
    while True:
        r = sec.get_security_stock_prices(symbol, start_date=start_date, end_date=end_date,
                                          frequency='daily', page_size=page_size, next_page=nxt or '')
        rows.extend({'date': p.date, 'close': p.close,
                     'adj_close': getattr(p, 'adj_close', p.close)} for p in r.stock_prices)
        nxt = getattr(r, 'next_page', None)
        if not nxt:
            break
    s = pd.DataFrame(rows); s['date'] = pd.to_datetime(s['date'])
    s = s.set_index('date').sort_index()
    return s.loc[(s.index >= pd.Timestamp(start_date)) & (s.index <= pd.Timestamp(end_date))]


def realized_vol(close, window=21):
    """Annualized realized vol из дневных log-returns базового."""
    lr = np.log(close / close.shift(1))
    return lr.rolling(window).std() * np.sqrt(252)


if __name__ == '__main__':
    # Smoke-test: python intrinio_options.py SPY 2024-01-03
    sym = sys.argv[1] if len(sys.argv) > 1 else 'SPY'
    dt  = sys.argv[2] if len(sys.argv) > 2 else '2024-01-03'
    df = fetch_day(sym, dt)
    print(f'{sym} {dt}: {len(df)} контрактов, экспираций {df["expiration"].nunique() if len(df) else 0}')
    if len(df):
        print(df.head().to_string())
        print('OI sum:', df['open_interest'].sum(), '| IV непустых:', df['iv'].notna().sum())
