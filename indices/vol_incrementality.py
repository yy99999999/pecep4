"""
vol_incrementality.py — the project's incrementality gate applied to the new result:
  does the intraday IB-structure vol nowcast add anything to the EXISTING options
  vol stack (VRP + GEX + IV + vol-term/credit), or is it redundant?

  This is the same gate that killed MP-for-direction and the 90DTE positioning sleeve:
  a new signal must beat the existing stack OUT-OF-SAMPLE or it is dropped.

TESTED BOTH WAYS AND ON BOTH HOME TURFS
  Target A — TODAY's post-IB realised vol (minutes 60→close).   IB nowcast's home turf.
             Decision at minute 60 of T ⇒ options features lagged to T−1.
  Target B — TOMORROW's full-session realised vol.               Options stack's home turf,
             and what the parked 1DTE engine actually needs.
             Decision at the close of T ⇒ options features at T (they publish T+1 AM),
             IB structure from T.

  For each target:
      ΔR²(IB | trailing+options)  — does the intraday structure ADD to the stack?
      ΔR²(options | trailing+IB)  — does the stack add to the intraday structure?
  Both numbers are needed: only reporting the first would hide redundancy.

SAMPLE
  Options cache is 2021-09→2026-06, so the honest split here is train <2024, test ≥2024
  (the ≤2019 split used elsewhere is impossible — no options data before 2021).

LEAKS CLOSED (same as predict_post_ib_vol.py)
  rv20 includes today's close → rv20.shift(1) for the Target-A normaliser and features;
  the IB `width` feature recomputed lag-safely; targets never normalised by IB range.

USAGE  ./vbt-env/bin/python vol_incrementality.py
"""
import os, importlib.util, logging
import numpy as np
import pandas as pd

import session               # DST-aware cash session (see session.py)

from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT      = os.path.dirname(os.path.abspath(__file__))
CACHE     = os.path.join(ROOT, 'cache')
SEED      = 7
SPLIT     = pd.Timestamp('2024-01-01')      # options data starts 2021-09
IBW       = 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('incr')
np.random.seed(SEED)

OPT = ['atm_iv_30', 'vrp', 'gex_z', 'vix_term_slope']
TRAIL = ['log_rv20_prev', 'log_vix_prev', 'vix_chg5']


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def build():
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    rth = session.get_rth(es)
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet')); days.index = pd.to_datetime(days.index)
    ib_m = _load('ib_ae', os.path.join(ROOT, 'ib_type_autoencoder.py'))

    # realised vols
    rth2 = rth.copy(); rth2['date'] = rth2.index.normalize()
    rows = {}
    for date, g in rth2.groupby('date'):
        if len(g) < IBW + 60:
            continue
        post = g.iloc[IBW:]
        lr_p = np.diff(np.log(post['close'].values))
        lr_f = np.diff(np.log(g['close'].values))
        if len(lr_p) < 30:
            continue
        rows[date] = dict(post_rv=float(np.std(lr_p) * np.sqrt(len(lr_p))),
                          full_rv=float(np.std(lr_f) * np.sqrt(len(lr_f))),
                          ib_range_pct=float((g.iloc[:IBW]['high'].max() -
                                              g.iloc[:IBW]['low'].min()) / g['open'].iloc[0]))
    O = pd.DataFrame(rows).T.sort_index()

    rv20_prev = days['rv20'].shift(1)
    dvol_prev = (rv20_prev / np.sqrt(252)).replace(0, np.nan)      # known before day T
    dvol_T    = (days['rv20'] / np.sqrt(252)).replace(0, np.nan)   # known at close of T
    O = O.join(dvol_prev.rename('dvol_prev')).join(dvol_T.rename('dvol_T')).dropna()

    # Target A: today's post-IB vol, normalised by vol known BEFORE today
    O['yA'] = np.log(O['post_rv'] / O['dvol_prev'])
    # Target B: TOMORROW's full-session vol, normalised by vol known at close of T
    O['yB'] = np.log(O['full_rv'].shift(-1) / O['dvol_T'])

    # IB structural descriptor with lag-safe width
    F = ib_m.build_ib_features(rth, days, bins=24)
    F['width'] = O['ib_range_pct'].reindex(F.index) / dvol_prev.reindex(F.index)
    F = F.dropna(subset=ib_m.FEATURES)

    # trailing-vol baseline
    vix = pd.read_parquet(os.path.join(CACHE, 'vix_daily.parquet')); vix.index = pd.to_datetime(vix.index)
    v = vix['vix_close'].reindex(days.index).ffill()
    T = pd.DataFrame(index=days.index)
    T['log_rv20_prev'] = np.log(rv20_prev.replace(0, np.nan))
    T['log_vix_prev']  = np.log(v.shift(1))
    T['vix_chg5']      = v.shift(1) - v.shift(6)

    # options stack (existing)
    P = pd.read_parquet(os.path.join(CACHE, 'bt_features_SPX_SPXW.parquet'))
    P.index = pd.to_datetime(P.index)
    P = P[OPT].reindex(days.index)
    optA = P.shift(1).add_suffix('_A')     # for Target A: decision at minute 60 of T
    optB = P.add_suffix('_B')              # for Target B: decision at close of T

    A = (O[['yA', 'yB']].join(F[ib_m.FEATURES], how='inner')
         .join(T, how='inner').join(optA, how='inner').join(optB, how='inner'))
    A = A.replace([np.inf, -np.inf], np.nan)
    return A, ib_m.FEATURES


def main():
    A, IBFEATS = build()

    results = {}
    for tgt, osuf, label in [('yA', '_A', "TODAY's post-IB vol (IB nowcast home turf)"),
                             ('yB', '_B', "TOMORROW's full-day vol (options stack home turf)")]:
        cols = IBFEATS + TRAIL + [c + osuf for c in OPT] + [tgt]
        D = A[cols].dropna()
        tr = D.index < SPLIT; te = ~tr
        log.info('══ %s ══  n=%d (train %d / test %d, %s→%s)', label, len(D), tr.sum(), te.sum(),
                 D.index.min().date(), D.index.max().date())
        y = D[tgt].values
        sc = lambda c: pd.DataFrame(StandardScaler().fit(D.loc[tr, c]).transform(D[c]),
                                    index=D.index, columns=c)
        OPTC = [c + osuf for c in OPT]
        blocks = {
            'trailing (baseline)':        sc(TRAIL),
            'options stack only':         sc(OPTC),
            'IB structure only':          sc(IBFEATS),
            'trailing + options':         pd.concat([sc(TRAIL), sc(OPTC)], axis=1),
            'trailing + IB':              pd.concat([sc(TRAIL), sc(IBFEATS)], axis=1),
            'trailing + options + IB':    pd.concat([sc(TRAIL), sc(OPTC), sc(IBFEATS)], axis=1),
        }
        res = {}
        for name, X in blocks.items():
            m = Ridge(alpha=10.0).fit(X.values[tr], y[tr])
            p = m.predict(X.values[te])
            res[name] = dict(r2=r2_score(y[te], p),
                             rho=stats.spearmanr(p, y[te]).correlation, pred=p)
            log.info('  [%-26s] OOS R²=%+.4f  ρ=%+.3f', name, res[name]['r2'], res[name]['rho'])
        full = res['trailing + options + IB']['r2']
        res['dIB']  = full - res['trailing + options']['r2']
        res['dOPT'] = full - res['trailing + IB']['r2']
        log.info('  → ΔR²(IB  | trailing+options) = %+.4f   %s', res['dIB'],
                 'IB ADDS' if res['dIB'] > 0.01 else 'redundant')
        log.info('  → ΔR²(opt | trailing+IB)      = %+.4f   %s', res['dOPT'],
                 'options ADD' if res['dOPT'] > 0.01 else 'redundant')
        res['y_te'] = y[te]; res['idx_te'] = D.index[te]
        results[tgt] = res

    # ── figure ──
    fig = plt.figure(figsize=(15, 8))
    fig.suptitle('Incrementality gate — intraday IB vol nowcast vs the existing options vol stack',
                 fontsize=13, weight='bold')
    names = ['trailing (baseline)', 'options stack only', 'IB structure only',
             'trailing + options', 'trailing + IB', 'trailing + options + IB']
    titles = {'yA': "TODAY's post-IB vol", 'yB': "TOMORROW's full-day vol"}

    for i, tgt in enumerate(['yA', 'yB']):
        ax = fig.add_subplot(2, 3, i + 1)
        vals = [results[tgt][n]['r2'] for n in names]
        cols = ['C7', 'C1', 'C0', 'C1', 'C0', 'C2']
        ax.barh(range(len(names)), vals, color=cols, alpha=.85)
        ax.set_yticks(range(len(names))); ax.set_yticklabels(names, fontsize=7)
        ax.axvline(0, color='k', lw=1); ax.invert_yaxis()
        ax.set_title(f'OOS R² — {titles[tgt]}', fontsize=10)

    ax = fig.add_subplot(2, 3, 3)
    w = .38
    for j, tgt in enumerate(['yA', 'yB']):
        ax.bar([0 + (j - .5) * w, 1 + (j - .5) * w],
               [results[tgt]['dIB'], results[tgt]['dOPT']], w,
               label=titles[tgt], alpha=.85)
    ax.axhline(0, color='k', lw=1)
    ax.set_xticks([0, 1]); ax.set_xticklabels(['ΔR² IB | trail+opt', 'ΔR² opt | trail+IB'], fontsize=8)
    ax.set_title('Two-way incrementality', fontsize=10); ax.legend(fontsize=7)

    for i, tgt in enumerate(['yA', 'yB']):
        ax = fig.add_subplot(2, 3, 4 + i)
        p = results[tgt]['trailing + options + IB']['pred']; yv = results[tgt]['y_te']
        ax.scatter(p, yv, s=6, alpha=.3)
        ax.set_title(f'{titles[tgt]} — full model\nR²={results[tgt]["trailing + options + IB"]["r2"]:.3f}',
                     fontsize=9)
        ax.set_xlabel('predicted'); ax.set_ylabel('realised')

    ax = fig.add_subplot(2, 3, 6); ax.axis('off')
    L = ['OOS R²                     today | tomorrow']
    for n in names:
        L.append(f'  {n:<24} {results["yA"][n]["r2"]:+.4f} | {results["yB"][n]["r2"]:+.4f}')
    L += ['', 'INCREMENTALITY',
          f'  ΔR²(IB  | trail+options)  {results["yA"]["dIB"]:+.4f} | {results["yB"]["dIB"]:+.4f}',
          f'  ΔR²(opt | trail+IB)       {results["yA"]["dOPT"]:+.4f} | {results["yB"]["dOPT"]:+.4f}',
          '', f'split: train <{SPLIT.date()}, test ≥{SPLIT.date()}']
    ax.text(0, 1, '\n'.join(L), va='top', ha='left', fontsize=8, family='monospace')

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = os.path.join(ROOT, 'vol_incrementality.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)

    print('\n' + '=' * 78)
    print('INCREMENTALITY GATE — IB vol nowcast vs options vol stack')
    print('=' * 78)
    for tgt, lab in [('yA', "TODAY's post-IB vol"), ('yB', "TOMORROW's full-day vol")]:
        print(f'\n{lab}:')
        for n in names:
            print(f'  {n:<26} R² {results[tgt][n]["r2"]:+.4f}')
        print(f'  ΔR²(IB  | trailing+options) = {results[tgt]["dIB"]:+.4f}')
        print(f'  ΔR²(opt | trailing+IB)      = {results[tgt]["dOPT"]:+.4f}')
    print('=' * 78)


if __name__ == '__main__':
    main()
