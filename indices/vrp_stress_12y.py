"""
vrp_stress_12y.py — how does the short-vol premium behave in a REAL crisis?

WHY THIS COULD NOT BE ASKED BEFORE
  The options cache starts 2021-09. That sample contains no genuine vol crisis: no
  Aug-2015, no Feb-2018 Volmageddon, no Mar-2020. Every short-vol conclusion in this
  project was therefore drawn from a calm regime. The project's own notes list
  "deep history -> crisis stress-test, the real survival test" as wanted but gated behind
  a paid Intrinio add-on. The new daily trade files (2014-06 -> 2022-07) close that gap.

DATA AND THE SPLICE
  · 2014-06 .. 2021-09  : ATM IV computed from TRADE prices (this project's own BS solver)
  · 2021-09 .. 2026-06  : ATM IV from the Intrinio cache (marks, self-computed greeks)
  Calibrated on 159 genuinely overlapping days at the real seam:
      bias (trade - intrinio) mean -0.05 vol pts, median -0.32, corr 0.94, sd 1.83
  So the LEVEL is safe to splice (bias ~0 vs a ~0.9 vp premium) but a single day is noisy
  — which is exactly why everything here is aggregate, never a daily signal.
  Spot comes from put-call parity on the same chains, so IV and realised vol are measured
  on one internally consistent underlying.

WHAT IS MEASURED
  vrp_earned(t) = ATM_IV(t) - realised vol(t -> t+21), in annualised vol points:
  what a seller actually collects, not the IV-minus-trailing-RV *signal*.
  Overlapping windows are 20/21 redundant, so all statistics use NON-OVERLAPPING samples.

WHAT THIS CANNOT SAY
  The trade files carry no bid/ask and no open interest, so costs and the GEX gate cannot
  be extended. This is a statement about the raw premium and its tail, not about a
  tradeable strategy.

USAGE  ./vbt-env/bin/python vrp_stress_12y.py [--rebuild]
"""
import os, glob, argparse, importlib.util, logging
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache')
DATA  = os.path.join(ROOT, 'data')
WIN   = 21
SEAM  = pd.Timestamp('2021-09-27')

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('stress')

CRISES = {
    'Aug-2015 devaluation': ('2015-08-01', '2015-09-30'),
    'Feb-2018 Volmageddon': ('2018-01-25', '2018-03-15'),
    'Q4-2018 selloff':      ('2018-10-01', '2018-12-31'),
    'Mar-2020 COVID':       ('2020-02-15', '2020-04-15'),
    '2022 bear':            ('2022-01-01', '2022-07-19'),
}


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def trade_series(iopt, rebuild=False):
    """daily parity spot + robust ATM IV from the trade files"""
    p = os.path.join(CACHE, 'spy_trade_ivspot.parquet')
    if os.path.exists(p) and not rebuild:
        return pd.read_parquet(p)
    log.info('building ATM IV + parity spot from trade files …')
    d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(DATA, 'options_SPY_1d*.parquet')))],
                  ignore_index=True).drop_duplicates(subset=['ts', 'osi'])
    d['date'] = pd.to_datetime(d['ts'], utc=True).dt.tz_convert('America/New_York').dt.normalize().dt.tz_localize(None)
    d['expiry'] = pd.to_datetime(d['expiry'])
    d['dte'] = (d['expiry'] - d['date']).dt.days
    d = d[(d['dte'] >= 20) & (d['dte'] <= 45) & (d['close'] > 0) & (d['volume'] > 0)]

    rows = {}
    for dt, g in d.groupby('date'):
        exp = g.groupby('expiry')['volume'].sum().idxmax()
        c = g[(g['expiry'] == exp) & (g['opt_type'] == 'C')].set_index('strike')['close']
        p_ = g[(g['expiry'] == exp) & (g['opt_type'] == 'P')].set_index('strike')['close']
        k = c.index.intersection(p_.index)
        if len(k) < 5:
            continue
        S = float((c[k] - p_[k] + pd.Series(k, index=k)).median())
        T = max((exp - dt).days, 1) / 365.0
        near = sorted(k, key=lambda x: abs(x - S))[:6]
        px = np.array([c[x] for x in near] + [p_[x] for x in near])
        K = np.array(list(near) * 2)
        isc = np.array([True] * len(near) + [False] * len(near))
        iv = iopt._bs_iv(px, S, K, T, 0.04, isc)
        iv = iv[(iv > 0.02) & (iv < 2.0)]
        if len(iv) >= 4:
            rows[dt] = {'spot': S, 'atm_iv_30': float(np.median(iv))}
    F = pd.DataFrame(rows).T.sort_index()
    F.to_parquet(p)
    return F


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--rebuild', action='store_true')
    args = ap.parse_args()
    iopt = _load('intrinio_options', os.path.join(ROOT, 'intrinio_options.py'))

    T = trade_series(iopt, args.rebuild)
    I = pd.read_parquet(os.path.join(CACHE, 'xasset_feat_SPY.parquet'))[['spot', 'atm_iv_30']]
    log.info('trade series %s → %s (%d d) | intrinio %s → %s (%d d)',
             T.index.min().date(), T.index.max().date(), len(T),
             I.index.min().date(), I.index.max().date(), len(I))

    # splice: trade data before the seam, Intrinio (marks) after
    F = pd.concat([T[T.index < SEAM], I[I.index >= SEAM]]).sort_index()
    F['src'] = np.where(F.index < SEAM, 'trade', 'intrinio')
    log.info('spliced: %d days  %s → %s', len(F), F.index.min().date(), F.index.max().date())

    lr = np.log(F['spot'] / F['spot'].shift(1))
    F['rv_fwd'] = (lr.rolling(WIN).std() * np.sqrt(252)).shift(-WIN)
    F['vrp'] = F['atm_iv_30'] - F['rv_fwd']
    V = F.dropna(subset=['vrp'])

    nov = V.iloc[::WIN]
    log.info('non-overlapping samples: %d', len(nov))

    def desc(x, tag):
        if len(x) < 5:
            return
        t, p = stats.ttest_1samp(x.values, 0.0)
        log.info('  %-26s n=%3d  mean %+6.2f vp  med %+6.2f  %5.1f%% pos  t=%+5.2f p=%.3f  worst %+7.2f',
                 tag, len(x), x.mean()*100, x.median()*100, (x > 0).mean()*100, t, p, x.min()*100)

    log.info('══ premium, full 12 years vs the calm-only sample ══')
    desc(nov['vrp'], 'FULL 2014-2026')
    desc(nov.loc[nov.index < SEAM, 'vrp'], '  2014-2021 (trade src)')
    desc(nov.loc[nov.index >= SEAM, 'vrp'], '  2021-2026 (intrinio)')
    desc(nov.loc[nov.index >= '2021-09-27', 'vrp'], '  the sample used so far')

    log.info('══ crisis windows (DAILY vrp, overlapping — descriptive) ══')
    crows = []
    for name, (a, b) in CRISES.items():
        w = V.loc[a:b, 'vrp']
        if len(w) < 5:
            continue
        crows.append(dict(crisis=name, n=len(w), mean_vp=w.mean()*100,
                          worst_vp=w.min()*100, pct_neg=(w < 0).mean()*100))
        log.info('  %-22s n=%3d  mean %+7.2f vp  worst %+8.2f vp  negative %.0f%% of days',
                 name, len(w), w.mean()*100, w.min()*100, (w < 0).mean()*100)
    C = pd.DataFrame(crows).set_index('crisis')

    log.info('══ concentration of losses ══')
    x = nov['vrp'].sort_values()
    tot = nov['vrp'].sum()
    for q in [0.05, 0.10, 0.20]:
        k = max(1, int(len(x) * q))
        log.info('  worst %2.0f%% of periods (n=%2d) give back %+.2f vp = %.0f%% of the total %+.2f vp',
                 q*100, k, x.iloc[:k].sum()*100, 100*abs(x.iloc[:k].sum()/tot) if tot else np.nan, tot*100)

    log.info('══ worst single 21-day windows ever ══')
    worst = V['vrp'].nsmallest(8)
    for dt, v in worst.items():
        log.info('  %s   %+7.2f vp   (IV %.1f  vs realised %.1f)',
                 dt.date(), v*100, V.loc[dt, 'atm_iv_30']*100, V.loc[dt, 'rv_fwd']*100)

    by_year = V.groupby(V.index.year)['vrp'].agg(['mean', 'min', 'count'])
    by_year[['mean', 'min']] *= 100
    log.info('══ by year (vol points) ══\n%s', by_year.round(2).to_string())

    # ── figure ──
    fig = plt.figure(figsize=(16, 9))
    fig.suptitle('Short-vol premium across 12 years — including the crises the recent sample lacks',
                 fontsize=13, weight='bold')

    ax = fig.add_subplot(2, 2, 1)
    ax.plot(V.index, V['atm_iv_30']*100, lw=.8, label='ATM IV (30d)')
    ax.plot(V.index, V['rv_fwd']*100, lw=.8, label='realised vol (next 21d)', alpha=.8)
    ax.axvline(SEAM, color='k', ls=':', lw=1)
    ax.text(SEAM, ax.get_ylim()[1]*0.95, ' splice', fontsize=7)
    ax.legend(fontsize=8); ax.set_ylabel('vol points'); ax.set_title('What was sold vs what arrived', fontsize=10)

    ax = fig.add_subplot(2, 2, 2)
    ax.plot(V.index, (V['vrp']*100).cumsum()/WIN, lw=1, color='C2')
    ax.axhline(0, color='k', lw=.8)
    for a, b in CRISES.values():
        ax.axvspan(pd.Timestamp(a), pd.Timestamp(b), color='C3', alpha=.15)
    ax.set_title('Cumulative premium (vol pts, crises shaded)', fontsize=10)

    ax = fig.add_subplot(2, 2, 3)
    cols = ['C3' if v < 0 else 'C0' for v in by_year['mean']]
    ax.bar(by_year.index.astype(str), by_year['mean'], color=cols, alpha=.85)
    ax.axhline(0, color='k', lw=1); ax.tick_params(axis='x', rotation=45)
    ax.set_ylabel('mean vrp (vol pts)'); ax.set_title('Premium by year', fontsize=10)

    ax = fig.add_subplot(2, 2, 4)
    ax.hist(nov['vrp']*100, bins=30, color='C0', alpha=.8)
    ax.axvline(0, color='k', lw=1)
    ax.axvline(nov['vrp'].mean()*100, color='C2', lw=1.5, label='mean')
    ax.set_title('Distribution of earned premium (non-overlapping)', fontsize=10)
    ax.set_xlabel('vol points'); ax.legend(fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(ROOT, 'vrp_stress_12y.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)

    print('\n' + '=' * 76)
    print('12-YEAR SHORT-VOL PREMIUM STRESS TEST')
    print('=' * 76)
    print(C.round(2).to_string())
    print('\nby year:\n', by_year.round(2).to_string())
    print('=' * 76)


if __name__ == '__main__':
    main()
