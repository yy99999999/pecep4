"""
predict_post_ib_vol.py — the one hypothesis with a prior chance:
  does the IB STRUCTURE (continuous latent) predict POST-IB VOLATILITY / RANGE
  EXPANSION — i.e. how big the rest of the day will be?

WHY THIS ONE IS DIFFERENT FROM EVERYTHING BEFORE IT
  · The target is a market OUTCOME (realised vol / range of minutes 60→close), not a
    rule label — so it cannot be won by label mechanics.
  · It is physically DISJOINT from every predictor (all predictors close at minute 60).
  · Volatility is the quantity this project has repeatedly found to be predictable,
    while direction never was.

TWO LEAKS THAT WOULD FAKE A RESULT — BOTH CLOSED HERE
  1. `rv20` in es_days is computed from daily closes INCLUDING today's close. Using it
     (or `ib_rv_ratio`, which divides by it) to predict today's vol is lookahead.
     → everything uses rv20.shift(1); the IB `width` feature is RECOMPUTED lag-safely.
  2. Normalising the target by the IB range would put a predictor in the denominator
     and manufacture a mechanical relationship.
     → targets are normalised by TRAILING vol only.

THE REAL TEST — INCREMENTALITY
  Vol is autocorrelated, so any block containing trailing vol scores R²>0 trivially.
  The question is ΔR² of IB structure ON TOP of a trailing-vol baseline.

USAGE  ./vbt-env/bin/python predict_post_ib_vol.py
"""
import os, argparse, importlib.util, logging
import numpy as np
import pandas as pd

import session               # DST-aware cash session (see session.py)

import torch
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.mixture import GaussianMixture
from sklearn.metrics import r2_score
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT      = os.path.dirname(os.path.abspath(__file__))
CACHE     = os.path.join(ROOT, 'cache')
SEED      = 7
TEST_FROM = pd.Timestamp('2020-01-01')
IBW       = 60
WINDOW    = 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('ibvol')
np.random.seed(SEED); torch.manual_seed(SEED)

POS_FEATS = ['open_rel_prior_range', 'dist_from_prior_mid', 'abs_gap_vol', 'outside_range']


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def build():
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    rth = session.get_rth(es)
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet')); days.index = pd.to_datetime(days.index)

    ib_m   = _load('ib_ae',   os.path.join(ROOT, 'ib_type_autoencoder.py'))
    open_m = _load('open_ae', os.path.join(ROOT, 'open_type_autoencoder.py'))

    # ── TARGETS: post-IB realised vol & range, normalised by TRAILING vol ──
    log.info('building post-IB outcomes …')
    rth2 = rth.copy(); rth2['date'] = rth2.index.normalize()
    rows = {}
    for date, g in rth2.groupby('date'):
        if len(g) < IBW + 60:
            continue
        post = g.iloc[IBW:]
        lr = np.diff(np.log(post['close'].values))
        if len(lr) < 30:
            continue
        rows[date] = dict(
            post_rv=float(np.std(lr) * np.sqrt(len(lr))),                       # session-scale move
            post_range=float((post['high'].max() - post['low'].min()) / post['open'].iloc[0]),
            ib_range_pct=float((g.iloc[:IBW]['high'].max() - g.iloc[:IBW]['low'].min())
                               / g['open'].iloc[0]))
    O = pd.DataFrame(rows).T.sort_index()

    rv20_prev = days['rv20'].shift(1)                    # LAG-SAFE (rv20 includes today's close)
    dvol_prev = (rv20_prev / np.sqrt(252)).replace(0, np.nan)
    O = O.join(dvol_prev.rename('dvol_prev'), how='inner').dropna()
    O['y_rv']    = np.log(O['post_rv'] / O['dvol_prev'])
    O['y_range'] = np.log(O['post_range'] / O['dvol_prev'])

    # ── IB features, with a LAG-SAFE width ──
    log.info('building IB descriptors (lag-safe width) …')
    F = ib_m.build_ib_features(rth, days, bins=24)
    F['width'] = (O['ib_range_pct'].reindex(F.index) / dvol_prev.reindex(F.index))
    F = F.dropna(subset=ib_m.FEATURES)
    tri = F.index < TEST_FROM
    Xi = StandardScaler().fit(F.loc[tri, ib_m.FEATURES]).transform(F[ib_m.FEATURES]).astype(np.float32)
    ae = ib_m.train_ae(Xi[tri], Xi.shape[1], latent=4, epochs=120)
    Zib = pd.DataFrame(ib_m.encode(ae, Xi), index=F.index, columns=[f'ibz{i}' for i in range(4)])

    # ── opening latent (extra block) ──
    paths, _ = open_m.build_open_paths(rth, WINDOW)
    trp = paths.index < TEST_FROM
    ae_o = open_m.train_ae(paths.values.astype(np.float32)[trp], WINDOW, 8, 80)
    Zop = pd.DataFrame(open_m.encode(ae_o, paths.values.astype(np.float32)), index=paths.index,
                       columns=[f'opz{i}' for i in range(8)])

    # ── trailing-vol baseline + position ──
    vix = pd.read_parquet(os.path.join(CACHE, 'vix_daily.parquet'))
    vix.index = pd.to_datetime(vix.index)
    v = vix['vix_close'].reindex(days.index).ffill()
    T = pd.DataFrame(index=days.index)
    T['log_rv20_prev'] = np.log(rv20_prev.replace(0, np.nan))
    T['log_vix_prev']  = np.log(v.shift(1))
    T['vix_chg5']      = v.shift(1) - v.shift(6)

    prng = (days['prev_high'] - days['prev_low']).replace(0, np.nan)
    rel = (days['open_px'] - days['prev_low']) / prng
    P = pd.DataFrame(index=days.index)
    P['open_rel_prior_range'] = rel
    P['dist_from_prior_mid']  = (rel - 0.5).abs()
    P['abs_gap_vol'] = ((days['open_px'] - days['close_px'].shift(1)) /
                        days['close_px'].shift(1)).abs() / dvol_prev
    P['outside_range'] = ((rel < 0) | (rel > 1)).astype(float)

    A = (O[['y_rv', 'y_range']]
         .join(F[ib_m.FEATURES], how='inner')
         .join(Zib, how='inner').join(Zop, how='inner')
         .join(T, how='inner').join(P, how='inner'))
    A = A.replace([np.inf, -np.inf], np.nan).dropna()
    return A, ib_m.FEATURES


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--kmax', type=int, default=10)
    args = ap.parse_args()
    A, IBFEATS = build()
    tr = A.index < TEST_FROM; te = ~tr
    log.info('dataset: %d days (train %d / test %d)', len(A), tr.sum(), te.sum())

    ibz = [f'ibz{i}' for i in range(4)]
    opz = [f'opz{i}' for i in range(8)]
    TRAIL = ['log_rv20_prev', 'log_vix_prev', 'vix_chg5']

    # discrete IB type (BIC argmin) for the discrete-vs-continuous comparison
    Z = A[ibz].values
    best = min(range(1, args.kmax + 1),
               key=lambda k: GaussianMixture(k, covariance_type='full', n_init=5,
                                             reg_covar=1e-4, random_state=SEED).fit(Z[tr]).bic(Z[tr]))
    A['ib_type'] = GaussianMixture(best, covariance_type='full', n_init=25, reg_covar=1e-4,
                                   random_state=SEED).fit(Z[tr]).predict(Z)
    log.info('IB types: BIC argmin k=%d', best)

    sc = lambda c: pd.DataFrame(StandardScaler().fit(A.loc[tr, c]).transform(A[c]),
                                index=A.index, columns=c)
    blocks = {
        'trailing vol (baseline)': sc(TRAIL),
        'IB width only':           sc(['width']),
        'IB type (discrete)':      pd.get_dummies(A['ib_type'], prefix='ibt'),
        'IB latent (4D)':          sc(ibz),
        'IB raw (10)':             sc(IBFEATS),
        'trail + IB width':        pd.concat([sc(TRAIL), sc(['width'])], axis=1),
        'trail + IB type':         pd.concat([sc(TRAIL), pd.get_dummies(A['ib_type'], prefix='ibt')], axis=1),
        'trail + IB latent':       pd.concat([sc(TRAIL), sc(ibz)], axis=1),
        'trail + IB raw':          pd.concat([sc(TRAIL), sc(IBFEATS)], axis=1),
        'trail + IB raw + open + pos': pd.concat([sc(TRAIL), sc(IBFEATS), sc(opz), sc(POS_FEATS)], axis=1),
    }

    out = {}
    for tgt in ['y_rv', 'y_range']:
        y = A[tgt].values
        log.info('══ target: %s ══', tgt)
        res = {}
        for name, X in blocks.items():
            m = Ridge(alpha=10.0).fit(X.values[tr], y[tr])
            p = m.predict(X.values[te])
            r2 = r2_score(y[te], p)
            rho = stats.spearmanr(p, y[te]).correlation
            res[name] = dict(r2=r2, rho=rho, pred=p)
            log.info('  [%-28s] OOS R²=%+.4f  Spearman=%+.3f', name, r2, rho)
        base = res['trailing vol (baseline)']['r2']
        for name in ['trail + IB width', 'trail + IB type', 'trail + IB latent', 'trail + IB raw',
                     'trail + IB raw + open + pos']:
            log.info('  INCREMENTAL %-28s ΔR² = %+.4f', name, res[name]['r2'] - base)
        out[tgt] = res

    # quintile monotonicity on the best model (y_rv)
    y = A['y_rv'].values[te]
    pred = out['y_rv']['trail + IB raw']['pred']
    qs = pd.qcut(pd.Series(pred), 5, labels=[f'Q{i+1}' for i in range(5)])
    qt = pd.DataFrame({'pred_q': qs.values, 'realised': y}).groupby('pred_q', observed=True)['realised'].agg(['mean', 'count'])
    log.info('realised log-vol ratio by predicted quintile (OOS):\n%s', qt.round(3).to_string())
    spread = qt['mean'].iloc[-1] - qt['mean'].iloc[0]
    log.info('Q5−Q1 spread = %.3f log units  (×%.2f in vol terms)', spread, np.exp(spread))

    # ── figure ──
    fig = plt.figure(figsize=(16, 9))
    fig.suptitle('IB structure → POST-IB volatility / range expansion (the vol hypothesis)',
                 fontsize=13, weight='bold')
    names = list(blocks.keys())

    for i, tgt in enumerate(['y_rv', 'y_range']):
        ax = fig.add_subplot(2, 3, i + 1)
        vals = [out[tgt][n]['r2'] for n in names]
        cols = ['C7' if 'baseline' in n else ('C2' if n.startswith('trail +') else 'C0') for n in names]
        ax.barh(range(len(names)), vals, color=cols, alpha=.85)
        ax.set_yticks(range(len(names))); ax.set_yticklabels(names, fontsize=6.5)
        ax.axvline(0, color='k', lw=1)
        ax.axvline(out[tgt]['trailing vol (baseline)']['r2'], color='r', ls='--', lw=1)
        ax.set_title(f'OOS R² — {"post-IB realised vol" if tgt=="y_rv" else "post-IB range"}', fontsize=10)
        ax.invert_yaxis()

    ax = fig.add_subplot(2, 3, 3)
    inc = ['trail + IB width', 'trail + IB type', 'trail + IB latent', 'trail + IB raw',
           'trail + IB raw + open + pos']
    w = .38
    for j, tgt in enumerate(['y_rv', 'y_range']):
        b = out[tgt]['trailing vol (baseline)']['r2']
        ax.bar(np.arange(len(inc)) + (j - .5) * w, [out[tgt][n]['r2'] - b for n in inc], w,
               label='post-IB vol' if tgt == 'y_rv' else 'post-IB range', alpha=.85)
    ax.axhline(0, color='k', lw=1)
    ax.set_xticks(range(len(inc))); ax.set_xticklabels([n.replace('trail + ', '') for n in inc],
                                                       rotation=30, fontsize=6.5, ha='right')
    ax.set_title('INCREMENTAL ΔR² over trailing-vol baseline', fontsize=10); ax.legend(fontsize=7)

    ax = fig.add_subplot(2, 3, 4)
    ax.bar(range(len(qt)), qt['mean'].values, color='C2', alpha=.85)
    ax.set_xticks(range(len(qt))); ax.set_xticklabels(qt.index, fontsize=8)
    ax.set_title(f'Realised post-IB vol by predicted quintile (OOS)\nQ5−Q1 = ×{np.exp(spread):.2f}',
                 fontsize=10); ax.set_ylabel('log(post-IB vol / trailing vol)')

    ax = fig.add_subplot(2, 3, 5)
    ax.scatter(pred, y, s=5, alpha=.25)
    ax.set_xlabel('predicted'); ax.set_ylabel('realised')
    ax.set_title(f'trail + IB raw (OOS)\nR²={out["y_rv"]["trail + IB raw"]["r2"]:.3f}  '
                 f'ρ={out["y_rv"]["trail + IB raw"]["rho"]:.3f}', fontsize=10)

    ax = fig.add_subplot(2, 3, 6); ax.axis('off')
    L = [f'days={len(A)}  test={te.sum()}  IB types k={best}', '',
         'OOS R²           post-IB vol | post-IB range']
    for n in names:
        L.append(f'  {n:<26} {out["y_rv"][n]["r2"]:+.4f} | {out["y_range"][n]["r2"]:+.4f}')
    L += ['', 'INCREMENTAL ΔR² over trailing baseline']
    for n in inc:
        L.append(f'  {n.replace("trail + ",""):<24} {out["y_rv"][n]["r2"]-out["y_rv"]["trailing vol (baseline)"]["r2"]:+.4f} | '
                 f'{out["y_range"][n]["r2"]-out["y_range"]["trailing vol (baseline)"]["r2"]:+.4f}')
    L += ['', f'Q5-Q1 realised vol ratio: x{np.exp(spread):.2f}']
    ax.text(0, 1, '\n'.join(L), va='top', ha='left', fontsize=7.5, family='monospace')

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    p = os.path.join(ROOT, 'predict_post_ib_vol.png')
    fig.savefig(p, dpi=110); log.info('saved figure → %s', p)

    print('\n' + '=' * 76)
    print('IB STRUCTURE → POST-IB VOLATILITY (OOS 2020-2026)')
    print('=' * 76)
    for tgt, lab in [('y_rv', 'post-IB realised vol'), ('y_range', 'post-IB range')]:
        b = out[tgt]['trailing vol (baseline)']['r2']
        print(f'\n{lab}:  trailing-vol baseline R² = {b:+.4f}')
        for n in inc:
            print(f'  +{n.replace("trail + ",""):<24} R² {out[tgt][n]["r2"]:+.4f}   ΔR² {out[tgt][n]["r2"]-b:+.4f}')
    print(f'\nQ5-Q1 realised post-IB vol: x{np.exp(spread):.2f}')
    print('=' * 76)


if __name__ == '__main__':
    main()
