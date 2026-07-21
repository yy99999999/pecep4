"""
delta_one_ib_vol.py — does the post-IB VOL FORECAST convert into money on ES alone?

THE IDEA
  We proved the IB structure forecasts post-IB volatility (OOS R² 0.52, dR² +0.34 over a
  trailing-vol baseline). Volatility is not directly tradeable with futures, so we use it
  as a REGIME SWITCH for a delta-one rule whose direction comes from the market:

      IB BREAKOUT: after minute 60, the first touch of the IB high (long) or IB low
      (short); hold to the cash close.
      Fade is the exact mirror (-1 x breakout), so the real question is not "breakout or
      fade" but: does the SIGN / SIZE of the breakout-continuation edge depend on the
      predicted post-IB vol?

  Hypothesis (Dalton + vol logic): on high predicted-vol days breaks continue (trend
  days); on low predicted-vol days breaks fail (balance/rotation).

WHY THIS SIDESTEPS "IS IT ALREADY PRICED?"
  We never sell volatility to the options market, so it does not matter whether 0DTE IV
  at 10:30 already embeds the IB range. We only ask whether the vol forecast conditions
  the profitability of a futures entry style.

HONEST CONSTRUCTION
  · vol model fitted on TRAIN ONLY (<=2019); quintile thresholds also taken from TRAIN
    and applied to TEST — no lookahead in the bucketing.
  · entry filled at the breakout level plus one tick of adverse slippage; costs swept.
  · BH-FDR across the quintile x direction search; year-by-year stability for survivors.
  · session is DST-correct (session.py).

USAGE  ./vbt-env/bin/python delta_one_ib_vol.py [--cost-bp 1.0]
"""
import os, argparse, importlib.util, logging
import numpy as np
import pandas as pd

import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import session               # DST-aware cash session (indices/session.py)

from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # indices/ root
HERE      = os.path.dirname(os.path.abspath(__file__))   # this script's folder
CACHE = os.path.join(ROOT, 'cache')
SEED  = 7
TEST_FROM = pd.Timestamp('2020-01-01')
IBW   = 60
TICK  = 0.25

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('d1')
np.random.seed(SEED)


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def bh_fdr(p, q=0.10):
    p = np.asarray(p, float); n = len(p); o = np.argsort(p)
    ok = p[o] <= q * np.arange(1, n + 1) / n
    out = np.zeros(n, bool)
    if ok.any():
        out[o[:np.max(np.where(ok)[0]) + 1]] = True
    qv = np.empty(n); run = 1.0
    for i in range(n - 1, -1, -1):
        run = min(run, p[o[i]] * n / (i + 1)); qv[o[i]] = run
    return out, qv


def build():
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    rth = session.get_rth(es)
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet')); days.index = pd.to_datetime(days.index)
    ib_m = _load('ib_ae', os.path.join(ROOT, 'autoencoders', 'ib_type_autoencoder.py'))

    rth2 = rth.copy(); rth2['date'] = rth2.index.normalize()
    rows = {}
    for date, g in rth2.groupby('date'):
        if len(g) < IBW + 60:
            continue
        ib, post = g.iloc[:IBW], g.iloc[IBW:]
        ibh, ibl = ib['high'].max(), ib['low'].min()
        lr = np.diff(np.log(post['close'].values))
        if len(lr) < 30 or ibh <= ibl:
            continue
        close_px = post['close'].iloc[-1]

        # first breakout of the IB after minute 60
        up = np.where(post['high'].values > ibh)[0]
        dn = np.where(post['low'].values < ibl)[0]
        iu = up[0] if len(up) else np.inf
        idn = dn[0] if len(dn) else np.inf
        if iu == np.inf and idn == np.inf:
            side, entry = 0, np.nan
        elif iu <= idn:
            side, entry = +1, ibh + TICK          # one tick of adverse slippage
        else:
            side, entry = -1, ibl - TICK
        bo_ret = np.nan if side == 0 else side * (close_px - entry) / entry

        rows[date] = dict(
            post_rv=float(np.std(lr) * np.sqrt(len(lr))),
            ib_range_pct=float((ibh - ibl) / g['open'].iloc[0]),
            side=side, bo_ret=bo_ret,
            post_ret=float((close_px - post['open'].iloc[0]) / post['open'].iloc[0]))
    O = pd.DataFrame(rows).T.sort_index()

    rv20_prev = days['rv20'].shift(1)
    dvol_prev = (rv20_prev / np.sqrt(252)).replace(0, np.nan)
    O = O.join(dvol_prev.rename('dvol_prev'), how='inner')
    O['y_rv'] = np.log(O['post_rv'] / O['dvol_prev'])

    F = ib_m.build_ib_features(rth, days, bins=24)
    F['width'] = O['ib_range_pct'].reindex(F.index) / dvol_prev.reindex(F.index)
    F = F.dropna(subset=ib_m.FEATURES)

    vix = pd.read_parquet(os.path.join(CACHE, 'vix_daily.parquet')); vix.index = pd.to_datetime(vix.index)
    v = vix['vix_close'].reindex(days.index).ffill()
    T = pd.DataFrame(index=days.index)
    T['log_rv20_prev'] = np.log(rv20_prev.replace(0, np.nan))
    T['log_vix_prev']  = np.log(v.shift(1))
    T['vix_chg5']      = v.shift(1) - v.shift(6)

    A = O.join(F[ib_m.FEATURES], how='inner').join(T, how='inner')
    return A.replace([np.inf, -np.inf], np.nan), ib_m.FEATURES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cost-bp', type=float, default=1.0, help='round-trip cost in bps')
    args = ap.parse_args()

    A, IBFEATS = build()
    FEATS = IBFEATS + ['log_rv20_prev', 'log_vix_prev', 'vix_chg5']
    D = A.dropna(subset=FEATS + ['y_rv']).copy()
    tr, te = D.index < TEST_FROM, D.index >= TEST_FROM
    log.info('days=%d (train %d / test %d)', len(D), tr.sum(), te.sum())

    # ── vol forecast, fitted on TRAIN only ──
    sc = StandardScaler().fit(D.loc[tr, FEATS])
    X = sc.transform(D[FEATS])
    mdl = Ridge(alpha=10.0).fit(X[tr], D.loc[tr, 'y_rv'].values)
    D['vol_hat'] = mdl.predict(X)
    log.info('vol model OOS R²=%.4f', 1 - ((D.loc[te, 'y_rv'] - D.loc[te, 'vol_hat'])**2).sum()
             / ((D.loc[te, 'y_rv'] - D.loc[tr, 'y_rv'].mean())**2).sum())

    # ── quintiles from TRAIN thresholds, applied to TEST (no lookahead) ──
    qs = D.loc[tr, 'vol_hat'].quantile([.2, .4, .6, .8]).values
    D['vq'] = np.digitize(D['vol_hat'], qs) + 1

    trades = D[te & D['side'].ne(0) & D['bo_ret'].notna()].copy()
    cost = args.cost_bp / 1e4
    trades['net'] = trades['bo_ret'] - cost
    log.info('OOS breakout trades: %d of %d test days (%.0f%% had an IB break)',
             len(trades), int(te.sum()), 100 * len(trades) / te.sum())

    # ── per-quintile stats, BH-FDR over the 5-cell search ──
    rows = []
    for q in range(1, 6):
        v = trades.loc[trades['vq'] == q, 'net'].values * 1e4
        if len(v) < 20:
            rows.append((q, len(v), np.nan, np.nan, np.nan, np.nan)); continue
        t_, p_ = stats.ttest_1samp(v, 0.0)
        rows.append((q, len(v), v.mean(), (v > 0).mean() * 100, t_, p_))
    R = pd.DataFrame(rows, columns=['vol_q', 'n', 'mean_bps', 'WR%', 't', 'p'])
    sig, qv = bh_fdr(R['p'].fillna(1).values)
    R['q_fdr'] = qv; R['sig'] = sig
    log.info('IB-breakout → close, by PREDICTED post-IB vol quintile (OOS, net %.1fbp):\n%s',
             args.cost_bp, R.round(2).to_string(index=False))

    allv = trades['net'].values * 1e4
    t_all, p_all = stats.ttest_1samp(allv, 0.0)
    log.info('unconditional breakout: n=%d mean=%.2fbp WR=%.1f%% t=%.2f p=%.3f',
             len(allv), allv.mean(), (allv > 0).mean() * 100, t_all, p_all)

    # ── cost sweep on the extreme quintiles ──
    log.info('cost sweep (mean bps):')
    for c in [0.0, 0.5, 1.0, 2.0, 3.0]:
        q1 = (trades.loc[trades['vq'] == 1, 'bo_ret'].mean() - c / 1e4) * 1e4
        q5 = (trades.loc[trades['vq'] == 5, 'bo_ret'].mean() - c / 1e4) * 1e4
        log.info('   cost %.1fbp → Q1 %+.2f   Q5 %+.2f   spread %+.2f', c, q1, q5, q5 - q1)

    # ── year stability ──
    trades['yr'] = trades.index.year
    yr = trades.pivot_table(index='yr', columns='vq', values='net', aggfunc='mean').mul(1e4).round(1)
    log.info('mean net bps by year × vol quintile:\n%s', yr.to_string())

    # ── figure ──
    fig = plt.figure(figsize=(15, 8))
    fig.suptitle('Delta-one on ES — does the post-IB vol forecast switch the IB-breakout edge?',
                 fontsize=13, weight='bold')

    ax = fig.add_subplot(2, 3, 1)
    m = R['mean_bps'].values
    se = np.array([trades.loc[trades['vq'] == q, 'net'].std() * 1e4 /
                   np.sqrt(max(1, (trades['vq'] == q).sum())) for q in range(1, 6)])
    ax.bar(R['vol_q'], m, yerr=1.96 * se, capsize=3,
           color=['C3' if x < 0 else 'C2' for x in np.nan_to_num(m)], alpha=.85)
    ax.axhline(0, color='k', lw=1)
    ax.set_xlabel('predicted post-IB vol quintile'); ax.set_ylabel('net bps / trade')
    ax.set_title(f'Breakout→close by vol quintile (net {args.cost_bp}bp)', fontsize=10)

    ax = fig.add_subplot(2, 3, 2)
    ax.bar(R['vol_q'], R['WR%'], color='C0', alpha=.85)
    ax.axhline(50, color='k', ls=':', lw=1)
    ax.set_ylim(35, 65); ax.set_title('Win rate by vol quintile', fontsize=10)
    ax.set_xlabel('vol quintile')

    ax = fig.add_subplot(2, 3, 3)
    for q in [1, 5]:
        s = trades.loc[trades['vq'] == q, 'net'].sort_index().cumsum() * 1e4
        ax.plot(s.index, s.values, label=f'Q{q} (n={len(s)})')
    ax.axhline(0, color='k', lw=.8); ax.legend(fontsize=8)
    ax.set_title('Cumulative net bps — extreme quintiles', fontsize=10)

    ax = fig.add_subplot(2, 3, 4)
    im = ax.imshow(yr.values, cmap='RdBu_r', vmin=-np.nanmax(np.abs(yr.values)),
                   vmax=np.nanmax(np.abs(yr.values)), aspect='auto')
    ax.set_xticks(range(yr.shape[1])); ax.set_xticklabels([f'Q{c}' for c in yr.columns], fontsize=8)
    ax.set_yticks(range(yr.shape[0])); ax.set_yticklabels(yr.index, fontsize=8)
    ax.set_title('Year × quintile, mean net bps', fontsize=10)
    for i in range(yr.shape[0]):
        for j in range(yr.shape[1]):
            val = yr.values[i, j]
            if not np.isnan(val):
                ax.text(j, i, f'{val:.0f}', ha='center', va='center', fontsize=6)

    ax = fig.add_subplot(2, 3, 5)
    ax.scatter(trades['vol_hat'], trades['net'] * 1e4, s=5, alpha=.2)
    ax.axhline(0, color='k', lw=.8)
    ax.set_xlabel('predicted post-IB vol'); ax.set_ylabel('net bps')
    rho = stats.spearmanr(trades['vol_hat'], trades['net']).correlation
    ax.set_title(f'Trade P&L vs vol forecast  ρ={rho:+.3f}', fontsize=10)

    ax = fig.add_subplot(2, 3, 6); ax.axis('off')
    L = [f'OOS test days       : {int(te.sum())}',
         f'breakout trades     : {len(trades)} ({100*len(trades)/te.sum():.0f}% of days)',
         f'cost assumed        : {args.cost_bp:.1f} bp round trip', '',
         'net bps by predicted-vol quintile:']
    for _, r in R.iterrows():
        L.append(f'   Q{int(r.vol_q)}  n={int(r.n):>4}  {r.mean_bps:+6.2f}bp  '
                 f'WR {r["WR%"]:.1f}%  t={r.t:+.2f}  q={r.q_fdr:.3f}'
                 f'{"  *" if r.sig else ""}')
    L += ['', f'unconditional: {allv.mean():+.2f}bp  t={t_all:+.2f}  p={p_all:.3f}',
          f'Spearman(vol_hat, P&L) = {rho:+.3f}',
          '', 'FDR-significant cells: %d/5' % int(R['sig'].sum())]
    ax.text(0, 1, '\n'.join(L), va='top', ha='left', fontsize=8.5, family='monospace')

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(HERE, 'delta_one_ib_vol.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)

    print('\n' + '=' * 74)
    print(f'DELTA-ONE ES — IB breakout conditioned on predicted post-IB vol (net {args.cost_bp}bp)')
    print('=' * 74)
    print(R.round(2).to_string(index=False))
    print(f'\nunconditional: {allv.mean():+.2f} bp  t={t_all:+.2f}  p={p_all:.3f}   '
          f'Spearman(vol_hat,P&L)={rho:+.3f}')
    print(f'FDR-significant: {int(R["sig"].sum())}/5')
    print('=' * 74)


if __name__ == '__main__':
    main()
