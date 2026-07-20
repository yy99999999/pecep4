"""
intermarket_lab — чистый intermarket/macro feature + regime engine (без Market Profile).
Заменяет amt_classify для пивота: никакой value-area / day-type логики Далтона.

Содержит:
  build_daily            — дневной OHLC из intraday RTH-баров
  build_features         — causal intermarket/macro фичи на дневной сетке + target
  fit_regime_model / build_reference / canonical_map / assign_regimes — движок режимов
  wilson_lb / bh_fdr / two_prop_p — статистика для оценки эджа
"""
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler

# Итоговый стационарный intermarket/macro набор (даёт vol R²~0.22 в honest-WF)
INTERMARKET_FEATURES = [
    'vix_percentile_252d', 'vix_change_5d', 'vol_ratio_5_20', 'vol_of_vol_20d',
    'yield_slope', 'yield_slope_change_10d',
    'zn_mom_10d', 'cl_mom_20d', 'dx_mom_20d',
    'er_20d', 'autocorr_lag1_20d', 'hurst_100d', 'trend_r2_20d',
    'cl_es_corr_20d', 'zn_es_corr_20d', 'es_nq_corr_20d',
    'ret_skew_20d', 'range_pct_20d',
]


# ─────────────────────────────────────────────────────────────
# FRED: vol term-structure + credit (бесплатно, глубоко) → vol-режим/кризис-контекст
# ─────────────────────────────────────────────────────────────
FRED_VOL_CREDIT = {
    'vix':   'VIXCLS',        # VIX 30d
    'vix3m': 'VXVCLS',        # VIX 3-month (93d)
    'vxn':   'VXNCLS',        # Nasdaq-100 vol 30d
    'hy_oas':'BAMLH0A0HYM2',  # High-Yield OAS
    'ig_oas':'BAMLC0A0CM',    # Investment-Grade OAS
}

def fetch_fred_series(codes, start, end, api_key):
    from fredapi import Fred
    fred = Fred(api_key=api_key)
    out = {}
    for name, code in codes.items():
        try:
            out[name] = fred.get_series(code, observation_start=start, observation_end=end)
        except Exception as e:
            print(f'FRED {code} ERR {e}')
    df = pd.DataFrame(out); df.index = pd.to_datetime(df.index)
    return df.sort_index()

def vol_credit_features(start, end, api_key):
    """Стационарные vol-term + credit фичи (causal): наклон/инверсия кривой VIX,
       перцентили, HY-IG спред и его изменения. Кризис/vol-режим контекст."""
    raw = fetch_fred_series(FRED_VOL_CREDIT, start, end, api_key).ffill()
    f = pd.DataFrame(index=raw.index)
    f['vix_term_slope']    = raw['vix'] - raw['vix3m']        # >0 = backwardation (стресс)
    f['vix_term_ratio']    = raw['vix'] / raw['vix3m']
    f['vxn_pctile_252']    = raw['vxn'].rolling(252).rank(pct=True)
    f['hy_ig_spread']      = raw['hy_oas'] - raw['ig_oas']
    f['hy_oas_chg_5']      = raw['hy_oas'].diff(5)
    f['hy_oas_pctile_252'] = raw['hy_oas'].rolling(252).rank(pct=True)
    return f


# ─────────────────────────────────────────────────────────────
# Дневной OHLC
# ─────────────────────────────────────────────────────────────
def build_daily(rth_bars):
    """Дневной OHLCV из intraday RTH-баров (open=first, close=last)."""
    g = rth_bars.groupby(rth_bars.index.normalize())
    daily = g.agg(open=('open', 'first'), high=('high', 'max'),
                  low=('low', 'min'), close=('close', 'last'),
                  volume=('volume', 'sum'))
    daily.index = pd.to_datetime(daily.index)
    return daily


# ─────────────────────────────────────────────────────────────
# Структурные хелперы (тренд vs mean-reversion)
# ─────────────────────────────────────────────────────────────
def _hurst(series, window=100, max_lag=20):
    def calc(data):
        if np.isnan(data).any():
            return np.nan
        lags = range(2, max_lag)
        tau = [np.std(np.subtract(data[lag:], data[:-lag])) for lag in lags]
        if any(t == 0 for t in tau):
            return np.nan
        try:
            return np.polyfit(np.log(list(lags)), np.log(tau), 1)[0]
        except Exception:
            return np.nan
    return series.rolling(window).apply(calc, raw=True)


def _efficiency_ratio(s, window=20):
    direction  = (s - s.shift(window)).abs()
    volatility = s.diff().abs().rolling(window).sum()
    return direction / volatility.replace(0, np.nan)


def _rolling_r2(s, window=20):
    def calc(y):
        if np.isnan(y).any():
            return np.nan
        x = np.arange(len(y))
        c = np.corrcoef(x, y)[0, 1]
        return c * c
    return s.rolling(window).apply(calc, raw=True)


# ─────────────────────────────────────────────────────────────
# Построение фич
# ─────────────────────────────────────────────────────────────
def build_features(es_rth, nq_rth, vix, macro, zn, cl):
    """Дневной фрейм: OHLC ES + causal intermarket/macro фичи + target fwd_ret.
       Все фичи стационарны и используют только прошлое (rolling)."""
    es = build_daily(es_rth)
    nq = build_daily(nq_rth)
    logret = np.log(es['close'] / es['close'].shift(1))

    f = pd.DataFrame(index=es.index)
    f['open_px']  = es['open']
    f['close_px'] = es['close']

    # ── ES realized vol (Garman-Klass) ──
    gk = (0.5 * np.log(es['high'] / es['low'])**2
          - (2*np.log(2) - 1) * np.log(es['close'] / es['open'])**2)
    gkv20 = np.sqrt(gk.rolling(20).mean() * 252)
    gkv5  = np.sqrt(gk.rolling(5).mean()  * 252)
    f['gk_vol_20d']     = gkv20
    f['vol_ratio_5_20'] = gkv5 / gkv20
    f['vol_of_vol_20d'] = gkv20.rolling(20).std()

    # ── ES структура ──
    f['hurst_100d']        = _hurst(es['close'])
    f['er_20d']            = _efficiency_ratio(es['close'], 20)
    f['trend_r2_20d']      = _rolling_r2(es['close'], 20)
    f['autocorr_lag1_20d'] = logret.rolling(20).apply(
        lambda x: pd.Series(x).autocorr(lag=1), raw=False)
    f['ret_skew_20d']      = logret.rolling(20).skew()
    f['ret_kurt_20d']      = logret.rolling(20).kurt()
    f['range_pct_20d']     = ((es['high'] - es['low']) / es['open']).rolling(20).rank(pct=True)

    # ── VIX ──
    v = vix['vix_close'].reindex(es.index).ffill()
    f['vix_percentile_252d'] = v.rolling(252).rank(pct=True)
    f['vix_change_5d']       = v.pct_change(5, fill_method=None)

    # ── Ставки / интермаркет импульсы ──
    f['yield_slope']            = macro['yield_slope'].reindex(es.index).ffill()
    f['yield_slope_change_10d'] = macro['yield_slope'].diff(10).reindex(es.index)
    f['zn_mom_10d'] = zn['close'].pct_change(10, fill_method=None).reindex(es.index)
    f['cl_mom_20d'] = cl['close'].pct_change(20, fill_method=None).reindex(es.index)
    f['dx_mom_20d'] = macro['dx_close'].pct_change(20, fill_method=None).reindex(es.index)

    # ── Кросс-корреляции (20d) ──
    znr = np.log(zn['close'] / zn['close'].shift(1)).reindex(es.index)
    clr = np.log(cl['close'] / cl['close'].shift(1)).reindex(es.index)
    nqr = np.log(nq['close'] / nq['close'].shift(1)).reindex(es.index)
    f['cl_es_corr_20d'] = clr.rolling(20).corr(logret)
    f['zn_es_corr_20d'] = znr.rolling(20).corr(logret)
    f['es_nq_corr_20d'] = nqr.rolling(20).corr(logret)

    # ── Target: дневной open→close (лаг на m+1 делается в WF) ──
    f['fwd_ret'] = (es['close'] - es['open']) / es['open']
    return f


# ─────────────────────────────────────────────────────────────
# Движок режимов (expanding fit, каноникализация по центроидам)
# ─────────────────────────────────────────────────────────────
def fit_regime_model(train_df, features, k, seed=42, n_init=10, cov_type='diag'):
    X = train_df[features].dropna()
    scaler = RobustScaler().fit(X)
    gmm = GaussianMixture(n_components=k, covariance_type=cov_type,
                          random_state=seed, n_init=n_init, reg_covar=1e-6)
    gmm.fit(scaler.transform(X))
    return scaler, gmm


def _centroids(scaler, gmm):
    return scaler.inverse_transform(gmm.means_)


def build_reference(discovery_df, features, k):
    """Эталонные центроиды режимов (фиксируем смысл один раз на discovery)."""
    scaler, gmm = fit_regime_model(discovery_df, features, k)
    return _centroids(scaler, gmm)


def canonical_map(scaler, gmm, ref_centroids):
    """comp_id -> canonical regime: венгерский матчинг по расстоянию центроидов."""
    C   = _centroids(scaler, gmm)
    std = ref_centroids.std(axis=0) + 1e-9
    D   = np.linalg.norm((C[:, None, :] - ref_centroids[None, :, :]) / std, axis=2)
    rows, cols = linear_sum_assignment(D)
    return {int(r): int(c) for r, c in zip(rows, cols)}


def assign_regimes(df, scaler, gmm, cmap, features):
    """(regime, confidence) по строкам df с полными фичами."""
    X     = df[features]
    valid = X.dropna().index
    Z     = scaler.transform(X.loc[valid])
    regime = pd.Series(np.nan, index=df.index, name='regime')
    conf   = pd.Series(np.nan, index=df.index, name='regime_confidence')
    regime.loc[valid] = [cmap[int(c)] for c in gmm.predict(Z)]
    conf.loc[valid]   = gmm.predict_proba(Z).max(axis=1)
    return regime, conf


# ─────────────────────────────────────────────────────────────
# Статистика оценки эджа
# ─────────────────────────────────────────────────────────────
def wilson_lb(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    denom = 1 + z*z/n
    centre = p + z*z/(2*n)
    margin = z * np.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (centre - margin) / denom


def bh_fdr(pvals):
    p = np.asarray(pvals, float); n = len(p)
    order = np.argsort(p); q = np.empty(n); prev = 1.0
    for rank, idx in enumerate(order[::-1]):
        r = n - rank
        prev = min(prev, p[idx] * n / r); q[idx] = prev
    return q


def two_prop_p(k1, n1, k2, n2):
    from scipy.stats import norm
    if n1 == 0 or n2 == 0:
        return 1.0
    pp = (k1 + k2) / (n1 + n2)
    se = np.sqrt(pp*(1-pp)*(1/n1 + 1/n2))
    if se == 0:
        return 1.0
    return 2 * (1 - norm.cdf(abs((k1/n1 - k2/n2) / se)))


print('intermarket_lab OK')
