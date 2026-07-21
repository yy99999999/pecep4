"""
audit_vol_benchmark.py — METHODOLOGY AUDIT (track item 3):
  every "we predict volatility" claim in this project was benchmarked against TRAILING
  REALISED vol. None was benchmarked against the market's own forecast of the same
  quantity — the implied vol. Does the daily vol skill survive that?

WHY THIS AUDIT EXISTS
  The IV smoke test on the IB result taught the lesson the hard way: IB structure beat a
  trailing-vol baseline by dR2 +0.34, but against the contemporaneous 0DTE price the
  increment was ~zero. "Better than yesterday's information" is not "better than the
  price". The notebook's L3-vol/L3-inc layer uses
      naive = abs_ret.ewm(halflife=10).mean().shift(1)
  i.e. trailing realised vol — VIX never enters as a BENCHMARK (only as a feature).
  So the same trap may be sitting in the daily-horizon claim.

WHAT WAS ALREADY VERIFIED CLEAN (first audit axis — look-ahead)
  The notebook lags both predictor blocks explicitly:
      wf['fwd_ret'] = (close_px - open_px)/open_px      # day t move
      mp      = es_days[MP_FEATURES].shift(1)           # completed day t-1
      NMP_BLK = es_days[NONMP_FEATURES].shift(1)
  Features from the completed prior day predict today's move — correct timing, no leak.
  (The one real leak found in this project, rv20 including today's close, is fixed and
  everything here uses rv20.shift(1).)

THE TEST
  target : log|open→close| of day t
  blocks : EWMA naive (trailing realised) | VIX(t-1) | both | + MP | + intermarket | all
  the number that matters: dR2 of our features OVER (naive + VIX), not over naive alone.

USAGE  ./vbt-env/bin/python audit_vol_benchmark.py
"""
import os, logging
import numpy as np
import pandas as pd

from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache')
TEST_FROM = pd.Timestamp('2020-01-01')
SEED = 7

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('audit')
np.random.seed(SEED)

MP    = ['ib_norm', 'prof_norm', 'ib_profile_ratio', 'poc_bias', 'open_poc_dist', 'bimodality']
NONMP = ['vix_pctile_252', 'vix_chg5', 'vol_ratio_5_20', 'log_rv20', 'ret_skew_20', 'range_pct_20']


def build():
    d = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet'))
    d.index = pd.to_datetime(d.index)
    v = pd.read_parquet(os.path.join(CACHE, 'vix_daily.parquet'))
    v.index = pd.to_datetime(v.index)
    vix = v['vix_close'].reindex(d.index).ffill()

    F = pd.DataFrame(index=d.index)
    # TARGET: today's open→close move (the notebook's abs_ret)
    abs_ret = ((d['close_px'] - d['open_px']) / d['open_px']).abs()
    F['y'] = np.log(abs_ret.replace(0, np.nan))

    # lag-safe daily vol scale (rv20 includes today's close → shift)
    dvol_prev = (d['rv20'].shift(1) / np.sqrt(252)).replace(0, np.nan)

    # ── BENCHMARK 1: trailing realised (the notebook's naive) ──
    F['ewma_abs'] = np.log(abs_ret.ewm(halflife=10).mean().shift(1))

    # ── BENCHMARK 2: the MARKET's forecast of the same quantity ──
    # VIX(t-1) → expected |daily move| = sigma * sqrt(2/pi)
    F['vix_fc'] = np.log(vix.shift(1) / 100 / np.sqrt(252) * np.sqrt(2 / np.pi))

    # ── our MP block (structure of the completed prior day) ──
    F['ib_norm']          = d['ib_range'] / (dvol_prev * d['open_px'])
    F['prof_norm']        = d['day_range'] / (dvol_prev * d['open_px'])
    for c in ['ib_profile_ratio', 'poc_bias', 'open_poc_dist', 'bimodality']:
        F[c] = d[c]

    # ── our intermarket / vol-state block ──
    gk = (0.5 * np.log(d['day_high'] / d['day_low'])**2 -
          (2 * np.log(2) - 1) * np.log(d['close_px'] / d['open_px'])**2)
    F['vol_ratio_5_20']  = np.sqrt(gk.rolling(5).mean()) / np.sqrt(gk.rolling(20).mean())
    F['vix_pctile_252']  = vix.rolling(252).rank(pct=True)
    F['vix_chg5']        = vix.pct_change(5)
    F['log_rv20']        = np.log(d['rv20'].replace(0, np.nan))
    lr = np.log(d['close_px'] / d['close_px'].shift(1))
    F['ret_skew_20']     = lr.rolling(20).skew()
    F['range_pct_20']    = ((d['day_high'] - d['day_low']) / d['open_px']).rolling(20).rank(pct=True)

    # EVERY predictor is from the completed prior day
    pred = MP + NONMP
    F[pred] = F[pred].shift(1)
    return F.replace([np.inf, -np.inf], np.nan).dropna()


def main():
    F = build()
    tr, te = F.index < TEST_FROM, F.index >= TEST_FROM
    log.info('days=%d (train %d / test %d)', len(F), tr.sum(), te.sum())
    y = F['y'].values

    def fit(cols, tag):
        X = StandardScaler().fit(F.loc[tr, cols]).transform(F[cols])
        p = Ridge(alpha=10.0).fit(X[tr], y[tr]).predict(X[te])
        r2 = r2_score(y[te], p)
        rho = stats.spearmanr(p, y[te]).correlation
        log.info('  [%-34s] OOS R²=%+.4f  ρ=%+.3f', tag, r2, rho)
        return r2

    log.info('══ benchmarks ══')
    r_naive = fit(['ewma_abs'], 'naive: trailing realised (EWMA)')
    r_vix   = fit(['vix_fc'], 'market: VIX(t-1) forecast')
    r_bench = fit(['ewma_abs', 'vix_fc'], 'naive + VIX  ← honest baseline')

    log.info('══ our features on top ══')
    r_mp_n   = fit(['ewma_abs'] + MP, 'naive + MP')
    r_mp_b   = fit(['ewma_abs', 'vix_fc'] + MP, 'naive + VIX + MP')
    r_nmp_b  = fit(['ewma_abs', 'vix_fc'] + NONMP, 'naive + VIX + intermarket')
    r_all_n  = fit(['ewma_abs'] + MP + NONMP, 'naive + ALL  (no VIX benchmark)')
    r_all_b  = fit(['ewma_abs', 'vix_fc'] + MP + NONMP, 'naive + VIX + ALL')

    print('\n' + '=' * 74)
    print('AUDIT — does daily vol skill survive a MARKET benchmark (VIX), not just trailing?')
    print('=' * 74)
    print(f'  naive (trailing realised)      R² {r_naive:+.4f}')
    print(f'  VIX(t-1) alone                 R² {r_vix:+.4f}')
    print(f'  naive + VIX  (honest baseline) R² {r_bench:+.4f}')
    print()
    print(f'  ΔR² of VIX over naive alone            {r_bench - r_naive:+.4f}')
    print(f'  ΔR² of MP     over naive ONLY          {r_mp_n  - r_naive:+.4f}   <- the old way')
    print(f'  ΔR² of MP     over naive+VIX           {r_mp_b  - r_bench:+.4f}   <- the honest way')
    print(f'  ΔR² of intermarket over naive+VIX      {r_nmp_b - r_bench:+.4f}')
    print(f'  ΔR² of ALL    over naive ONLY          {r_all_n - r_naive:+.4f}   <- the old way')
    print(f'  ΔR² of ALL    over naive+VIX           {r_all_b - r_bench:+.4f}   <- the honest way')
    print('=' * 74)

    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle('Audit — trailing-vol benchmark vs the market\'s own forecast (VIX)',
                 fontsize=12, weight='bold')
    names = ['naive', 'VIX', 'naive+VIX', '+MP', '+intermarket', '+ALL']
    vals  = [r_naive, r_vix, r_bench, r_mp_b, r_nmp_b, r_all_b]
    ax[0].bar(names, vals, color=['C7', 'C1', 'C0', 'C2', 'C2', 'C2'], alpha=.85)
    ax[0].axhline(r_bench, color='r', ls='--', lw=1, label='honest baseline')
    ax[0].set_ylabel('OOS R²'); ax[0].tick_params(axis='x', rotation=25); ax[0].legend(fontsize=8)
    ax[0].set_title('OOS R² by block', fontsize=10)

    inc = {'MP': (r_mp_n - r_naive, r_mp_b - r_bench),
           'ALL': (r_all_n - r_naive, r_all_b - r_bench)}
    x = np.arange(len(inc)); w = .35
    ax[1].bar(x - w/2, [v[0] for v in inc.values()], w, label='over naive only (old)', color='C3', alpha=.85)
    ax[1].bar(x + w/2, [v[1] for v in inc.values()], w, label='over naive+VIX (honest)', color='C0', alpha=.85)
    ax[1].axhline(0, color='k', lw=1)
    ax[1].set_xticks(x); ax[1].set_xticklabels(inc.keys())
    ax[1].set_ylabel('ΔR²'); ax[1].legend(fontsize=8)
    ax[1].set_title('Incremental value, old benchmark vs honest one', fontsize=10)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out = os.path.join(ROOT, 'audit_vol_benchmark.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)


if __name__ == '__main__':
    main()
