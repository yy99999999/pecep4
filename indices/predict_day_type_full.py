"""
predict_day_type_full.py — TRACK ITEM 1 (extended):
  can the type of the CURRENT day be predicted at IB close from
    · the opening type      (unsupervised archetype)
    · the IB type           (unsupervised)
    · the position of the open inside YESTERDAY's profile
    · YESTERDAY's day type  (both unsupervised archetype and Dalton rule)

  Every taxonomy is chosen by BIC ARGMIN on a GaussianMixture fitted on TRAIN years.

THREE TARGETS, AND WHY
  The first hour is physically PART of the day's volume profile, so predicting the
  full-day shape from IB structure is partly tautological. We therefore report:
    T1  dalton_day_type   — the rule label (overlap limited to ib_width_cat)
    T2  unsup_day_shape   — unsupervised full-day archetype  [MECHANICAL OVERLAP:
                            the IB contributes ~15% of the day's volume — read with care]
    T3  unsup_postIB      — unsupervised archetype of the POST-IB profile (minutes
                            60-390) — fully DISJOINT from every predictor, and the
                            version that actually matters ("how will the rest of the
                            day develop?")
  T3 is the honest headline; T1/T2 are context.

TIMING
  All predictors are known by minute 60; all targets complete at the close, so this is
  a genuine forecast made at IB close.

CARRIED-FORWARD LESSON
  Discrete labels lose signal (confirmed 3× in this track), so each block is run in a
  discrete form (types, as asked) and a continuous form (latents) as the upper bound.

USAGE  ./vbt-env/bin/python predict_day_type_full.py [--kmax 10]
"""
import os, argparse, importlib.util, logging
import numpy as np
import pandas as pd

import session               # DST-aware cash session (see session.py)

import torch
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.mixture import GaussianMixture
from sklearn.metrics import accuracy_score, f1_score, log_loss
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT      = os.path.dirname(os.path.abspath(__file__))
CACHE     = os.path.join(ROOT, 'cache')
SEED      = 7
TEST_FROM = pd.Timestamp('2020-01-01')
NBINS     = 64
WINDOW    = 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('day-pred')
np.random.seed(SEED); torch.manual_seed(SEED)

POS_FEATS = ['open_rel_prior_range', 'dist_from_prior_mid', 'dist_from_prior_poc',
             'abs_gap_vol', 'pctile_extremity', 'outside_range']


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def bh_fdr(pvals, q=0.10):
    p = np.asarray(pvals, float); n = len(p); order = np.argsort(p)
    passed = p[order] <= q * np.arange(1, n + 1) / n
    out = np.zeros(n, bool)
    if passed.any():
        out[order[:np.max(np.where(passed)[0]) + 1]] = True
    qv = np.empty(n); run = 1.0
    for i in range(n - 1, -1, -1):
        run = min(run, p[order[i]] * n / (i + 1)); qv[order[i]] = run
    return out, qv


def bic_argmin(Ztr, kmax, tag):
    rows = []
    for kk in range(1, kmax + 1):
        gm = GaussianMixture(kk, covariance_type='full', n_init=5, reg_covar=1e-4,
                             random_state=SEED).fit(Ztr)
        rows.append((kk, gm.bic(Ztr), gm.aic(Ztr)))
    sel = pd.DataFrame(rows, columns=['k', 'BIC', 'AIC'])
    k = int(sel.loc[sel['BIC'].idxmin(), 'k'])
    log.info('[%-22s] BIC argmin k=%d', tag, k)
    return k, sel


def post_ib_profiles(rth, n_bins, skip=WINDOW):
    """volume-by-price profile of the POST-IB session (minutes `skip`..close),
    range-normalised and summing to 1 — disjoint from every IB-close predictor."""
    rth = rth.copy(); rth['date'] = rth.index.normalize()
    out = {}
    for date, g in rth.groupby('date'):
        g = g.iloc[skip:]
        if len(g) < 60:
            continue
        lo, hi = g['low'].min(), g['high'].max()
        if hi - lo <= 0:
            continue
        tp = (g['high'].values + g['low'].values + g['close'].values) / 3.0
        idx = np.clip(((tp - lo) / (hi - lo) * n_bins).astype(int), 0, n_bins - 1)
        pr = np.bincount(idx, weights=g['volume'].values.astype(float), minlength=n_bins)
        if pr.sum() <= 0:
            continue
        out[date] = pr / pr.sum()
    return pd.DataFrame(out).T.sort_index()


# ───────────────────────── build ─────────────────────────
def build(kmax):
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    rth = session.get_rth(es)
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet')); days.index = pd.to_datetime(days.index)

    shape_m = _load('shape_ae', os.path.join(ROOT, 'day_shape_autoencoder.py'))
    open_m  = _load('open_ae',  os.path.join(ROOT, 'open_type_autoencoder.py'))
    ib_m    = _load('ib_ae',    os.path.join(ROOT, 'ib_type_autoencoder.py'))

    def latent(X, index, n_in, latent_dim, epochs, mod):
        trm = index < TEST_FROM
        ae = mod.train_ae(X[trm], n_in, latent_dim, epochs)
        return pd.DataFrame(mod.encode(ae, X), index=index)

    log.info('full-day profiles …')
    prof = shape_m.build_profiles(rth, NBINS)
    Zday = latent(prof.values.astype(np.float32), prof.index, NBINS, 8, 80, shape_m)

    log.info('post-IB profiles (minutes 60-close) …')
    pprof = post_ib_profiles(rth, NBINS)
    Zpost = latent(pprof.values.astype(np.float32), pprof.index, NBINS, 8, 80, shape_m)

    log.info('opening paths …')
    paths, _ = open_m.build_open_paths(rth, WINDOW)
    Zopen = latent(paths.values.astype(np.float32), paths.index, WINDOW, 8, 80, open_m)

    log.info('IB descriptors …')
    Fib = ib_m.build_ib_features(rth, days, bins=24).dropna(subset=ib_m.FEATURES)
    tri = Fib.index < TEST_FROM
    Xi = StandardScaler().fit(Fib.loc[tri, ib_m.FEATURES]).transform(Fib[ib_m.FEATURES]).astype(np.float32)
    Zib = latent(Xi, Fib.index, Xi.shape[1], 4, 120, ib_m)

    # position of the open inside yesterday's profile
    D = days.copy()
    prior_prof = prof.reindex(D.index).shift(1)
    prev_close = D['close_px'].shift(1)
    prng = (D['prev_high'] - D['prev_low']).replace(0, np.nan)
    rel  = (D['open_px'] - D['prev_low']) / prng
    relc = rel.clip(0, 1)
    bidx = (relc * NBINS).astype('float').fillna(0).astype(int).clip(0, NBINS - 1)
    pv = prior_prof.values
    cum = np.full(len(D), np.nan)
    for i in range(len(D)):
        if not np.all(np.isnan(pv[i])) and not np.isnan(relc.iloc[i]):
            cum[i] = np.nansum(pv[i][:bidx.iloc[i] + 1])
    dvol = (D['rv20'] / np.sqrt(252)).replace(0, np.nan)

    A = pd.DataFrame(index=D.index)
    A['open_rel_prior_range'] = rel
    A['dist_from_prior_mid']  = (rel - 0.5).abs()
    A['dist_from_prior_poc']  = (D['open_px'] - D['prev_poc']).abs() / prng
    A['abs_gap_vol']          = ((D['open_px'] - prev_close) / prev_close).abs() / dvol
    A['pctile_extremity']     = np.abs(cum - 0.5)
    A['outside_range']        = ((rel < 0) | (rel > 1)).astype(float)
    A['dalton_day']           = D['day_type'].astype(str)
    A['dalton_day_prev']      = D['day_type'].astype(str).shift(1)

    A = (A.join(Zday.add_prefix('dy'), how='inner')
           .join(Zday.reindex(D.index).shift(1).add_prefix('pd'))     # PRIOR day shape
           .join(Zpost.add_prefix('po'), how='inner')
           .join(Zopen.add_prefix('op'), how='inner')
           .join(Zib.add_prefix('ib'), how='inner'))
    A = A.replace([np.inf, -np.inf], np.nan).dropna()
    A = A[(A['dalton_day'] != 'unknown') & (A['dalton_day_prev'] != 'unknown')]
    return A, kmax


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kmax', type=int, default=10)
    args = ap.parse_args()

    A, _ = build(args.kmax)
    tr = A.index < TEST_FROM
    te = ~tr
    log.info('dataset: %d days (train %d / test %d)', len(A), tr.sum(), te.sum())

    cols = lambda p: [c for c in A.columns if c.startswith(p) and c[2:].isdigit()]
    Zday, Zpd = A[cols('dy')].values, A[cols('pd')].values
    Zpost, Zop, Zib = A[cols('po')].values, A[cols('op')].values, A[cols('ib')].values

    # ── taxonomies: BIC argmin on train ──
    k_day, sel_day   = bic_argmin(Zday[tr],  args.kmax, 'full-day shape')
    k_post, sel_post = bic_argmin(Zpost[tr], args.kmax, 'post-IB shape')
    k_op, _          = bic_argmin(Zop[tr],   args.kmax, 'opening')
    k_ib, _          = bic_argmin(Zib[tr],   args.kmax, 'IB')
    fit = lambda Z, k: GaussianMixture(k, covariance_type='full', n_init=25,
                                       reg_covar=1e-4, random_state=SEED).fit(Z[tr])
    gm_day = fit(Zday, k_day)
    A['y_day']    = gm_day.predict(Zday)
    A['y_post']   = fit(Zpost, k_post).predict(Zpost)
    A['open_arch'] = fit(Zop, k_op).predict(Zop)
    A['ib_type']   = fit(Zib, k_ib).predict(Zib)
    A['prior_arch'] = gm_day.predict(Zpd)          # SAME taxonomy, applied to prior day
    log.info('k: day=%d  postIB=%d  opening=%d  IB=%d', k_day, k_post, k_op, k_ib)

    # ── predictor blocks (all known at IB close) ──
    scale = lambda c: pd.DataFrame(StandardScaler().fit(A.loc[tr, c]).transform(A[c]),
                                   index=A.index, columns=c)
    B = {
        'position':        scale(POS_FEATS),
        'prior_day_type':  pd.concat([pd.get_dummies(A['prior_arch'], prefix='pa'),
                                      pd.get_dummies(A['dalton_day_prev'], prefix='pdt')], axis=1),
        'open_type':       pd.get_dummies(A['open_arch'], prefix='oa'),
        'ib_type':         pd.get_dummies(A['ib_type'], prefix='ib'),
    }
    B['ALL types']    = pd.concat([B['position'], B['prior_day_type'],
                                   B['open_type'], B['ib_type']], axis=1)
    B['ALL latents']  = pd.concat([B['position'], scale(cols('pd')),
                                   scale(cols('op')), scale(cols('ib'))], axis=1)

    TARGETS = [('T1 dalton_day_type', A['dalton_day'].values, 'rule label'),
               ('T2 unsup_day_shape', A['y_day'].values, 'MECHANICAL OVERLAP'),
               ('T3 unsup_postIB', A['y_post'].values, 'DISJOINT — headline')]

    results = {}
    for tname, y, note in TARGETS:
        log.info('══ %s  (%s) ══', tname, note)
        res = {}
        for bname, X in B.items():
            c = LogisticRegression(max_iter=4000, C=1.0).fit(X.values[tr], y[tr])
            pred = c.predict(X.values[te])
            acc = accuracy_score(y[te], pred)
            f1m = f1_score(y[te], pred, average='macro', zero_division=0)
            ll = log_loss(y[te], c.predict_proba(X.values[te]), labels=c.classes_)
            maj = pd.Series(y[tr]).value_counts().idxmax()
            base = (y[te] == maj).mean()
            prior = pd.Series(y[tr]).value_counts(normalize=True).reindex(c.classes_).fillna(1e-9).values
            ll0 = log_loss(y[te], np.tile(prior, (te.sum(), 1)), labels=c.classes_)
            log.info('  [%-16s] acc=%.4f (base %.4f)  F1=%.3f  ll=%.4f (prior %.4f)  Δll=%+.4f',
                     bname, acc, base, f1m, ll, ll0, ll - ll0)
            res[bname] = dict(acc=acc, base=base, f1=f1m, ll=ll, ll0=ll0, dll=ll - ll0)
        results[tname] = res

    # ── persistence: does the day type repeat? ──
    log.info('══ day-type PERSISTENCE (does yesterday repeat?) ══')
    pers = {}
    for name, cur, prv in [('unsup day archetype', A['y_day'], A['prior_arch']),
                           ('Dalton day_type', A['dalton_day'], A['dalton_day_prev'])]:
        cnt = pd.crosstab(prv, cur)
        pct = pd.crosstab(prv, cur, normalize='index').mul(100).round(1)
        chi2, p, dof, _ = stats.chi2_contingency(cnt.values)
        base = cur.value_counts(normalize=True)
        ps, cells = [], []
        for r_ in cnt.index:
            n = cnt.loc[r_].sum()
            for cc in cnt.columns:
                p1, p0 = cnt.loc[r_, cc] / n, base[cc]
                se = np.sqrt(p0 * (1 - p0) / n)
                ps.append(2 * (1 - stats.norm.cdf(abs(p1 - p0) / se)) if se > 0 else 1.0)
                cells.append((r_, cc, n, p1 * 100, p0 * 100))
        sig, qv = bh_fdr(ps)
        log.info('  [%s] chi2=%.1f dof=%d p=%.3g  FDR-significant %d/%d',
                 name, chi2, dof, p, sig.sum(), len(sig))
        pers[name] = (pct, p, int(sig.sum()), len(sig))

    # ── figure ──
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle('Extended track item 1 — current-day type from opening, IB, open position, prior day',
                 fontsize=13, weight='bold')
    bn = list(B.keys())

    for i, (tname, _, note) in enumerate(TARGETS):
        ax = fig.add_subplot(2, 3, i + 1)
        accs = [results[tname][b]['acc'] for b in bn]
        base = results[tname][bn[0]]['base']
        ax.bar(range(len(bn)), accs, color=['C0'] * 4 + ['C2', 'C4'], alpha=.85)
        ax.axhline(base, color='r', ls='--', lw=1.2, label=f'majority {base:.3f}')
        ax.set_xticks(range(len(bn))); ax.set_xticklabels(bn, rotation=35, fontsize=6.5, ha='right')
        ax.set_title(f'{tname}\n({note})', fontsize=9); ax.legend(fontsize=6)

    ax = fig.add_subplot(2, 3, 4)
    w = 0.27
    for j, (tname, _, _) in enumerate(TARGETS):
        d = [results[tname][b]['dll'] for b in bn]
        ax.bar(np.arange(len(bn)) + (j - 1) * w, d, w, label=tname.split()[0], alpha=.85)
    ax.axhline(0, color='k', lw=1)
    ax.set_xticks(range(len(bn))); ax.set_xticklabels(bn, rotation=35, fontsize=6.5, ha='right')
    ax.set_title('Δ log-loss vs prior (negative = real skill)', fontsize=9); ax.legend(fontsize=6)

    ax = fig.add_subplot(2, 3, 5)
    pct, p, s, n = pers['unsup day archetype']
    im = ax.imshow(pct.values, cmap='RdBu_r', aspect='auto')
    ax.set_xticks(range(pct.shape[1])); ax.set_xticklabels(pct.columns, fontsize=6)
    ax.set_yticks(range(pct.shape[0])); ax.set_yticklabels(pct.index, fontsize=6)
    ax.set_title(f'P(day archetype | YESTERDAY) %\nchi2 p={p:.2g}, FDR {s}/{n}', fontsize=9)
    for a_ in range(pct.shape[0]):
        for b_ in range(pct.shape[1]):
            ax.text(b_, a_, f'{pct.values[a_,b_]:.0f}', ha='center', va='center', fontsize=5)

    ax = fig.add_subplot(2, 3, 6); ax.axis('off')
    lines = [f'days={len(A)}   k: day={k_day} postIB={k_post} open={k_op} IB={k_ib}', '']
    for tname, _, note in TARGETS:
        r = results[tname]
        lines.append(f'{tname}  (base {r[bn[0]]["base"]:.4f})')
        for b in bn:
            lines.append(f'   {b:<15} acc {r[b]["acc"]:.4f}  Δll {r[b]["dll"]:+.4f}')
        lines.append('')
    for k_, (pct_, p_, s_, n_) in pers.items():
        lines.append(f'persistence {k_}: p={p_:.2g}, FDR {s_}/{n_}')
    ax.text(0, 1, '\n'.join(lines), va='top', ha='left', fontsize=7.5, family='monospace')

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(ROOT, 'predict_day_type_full.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)

    print('\n' + '=' * 78)
    print('EXTENDED TRACK 1 — current-day type from opening + IB + open position + prior day')
    print('=' * 78)
    for tname, _, note in TARGETS:
        r = results[tname]
        print(f'\n{tname}  ({note})   base={r[bn[0]]["base"]:.4f}')
        for b in bn:
            print(f'  {b:<15} acc {r[b]["acc"]:.4f}   Δlogloss {r[b]["dll"]:+.4f}')
    print('\npersistence:', {k_: f'p={v[1]:.2g}, FDR {v[2]}/{v[3]}' for k_, v in pers.items()})
    print('=' * 78)


if __name__ == '__main__':
    main()
