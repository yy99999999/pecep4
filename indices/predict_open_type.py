"""
predict_open_type.py — TRACK ITEM 3 (fully unsupervised version):
  predict the UNSUPERVISED OPENING archetype of day t from
    (a) where the open sits inside the UNSUPERVISED profile of day t−1, and
    (b) the market regime — all known at/just before the open.

WHY THIS IS THE CLEANEST FORECAST OF THE TRACK
  Every predictor is point-in-time at the open: yesterday's finished volume profile,
  today's opening price relative to it, and yesterday's regime/VIX. The target — the
  shape of the first 60 minutes — has not happened yet. Nothing here is definitional
  (unlike day_type/open_type, which are rules over the same window they describe).

LESSON FROM TRACK ITEM 1 APPLIED
  Discretising a continuum throws away signal. So we predict BOTH
    · the discrete opening archetype (multinomial logistic), and
    · the continuous opening LATENT vector (ridge, multi-output OOS R²).
  The latent regression is the honest measure of "how much of the opening is
  forecastable at all".

SYMMETRY
  The opening archetype is direction-invariant (paths are canonicalised by the sign of
  the early move), so the position features are mainly |·| / extremity forms — a gap up
  and a gap down of equal size are the same situation for SHAPE purposes.

USAGE  ./vbt-env/bin/python predict_open_type.py [--kopen 0]   (0 = BIC elbow)
"""
import os, argparse, importlib.util, logging
import numpy as np
import pandas as pd

import torch
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.mixture import GaussianMixture
from sklearn.metrics import accuracy_score, f1_score, r2_score, log_loss
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT      = os.path.dirname(os.path.abspath(__file__))
CACHE     = os.path.join(ROOT, 'cache')
RTH_START = 14 * 60 + 30
RTH_END   = 21 * 60 + 0
SEED      = 7
TEST_FROM = pd.Timestamp('2020-01-01')
NBINS     = 64
WINDOW    = 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('open-pred')
np.random.seed(SEED); torch.manual_seed(SEED)

POS_FEATS = ['open_rel_prior_range', 'dist_from_prior_mid', 'dist_from_prior_poc',
             'abs_gap_vol', 'pctile_extremity', 'outside_range']
REG_FEATS = ['vix_prev', 'vix_chg5', 'vix_pctile252', 'rv20_prev', 'regime_conf_prev']


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


def pick_elbow(ks, bic):
    """smallest k whose marginal BIC gain falls below 10% of the largest gain."""
    gains = -np.diff(bic)
    if len(gains) == 0 or gains.max() <= 0:
        return int(ks[0])
    thr = 0.10 * gains.max()
    for i, g in enumerate(gains):
        if g < thr:
            return int(ks[i])
    return int(ks[-1])


# ───────────────────────── build everything ─────────────────────────
def build():
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    t = es.index.hour * 60 + es.index.minute
    rth = es[(t >= RTH_START) & (t < RTH_END)].copy()
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet')); days.index = pd.to_datetime(days.index)

    shape_m = _load('shape_ae', os.path.join(ROOT, 'day_shape_autoencoder.py'))
    open_m  = _load('open_ae',  os.path.join(ROOT, 'open_type_autoencoder.py'))

    # ── TARGET: unsupervised opening archetype + latent ──
    log.info('building opening paths + opening latent …')
    paths, _ = open_m.build_open_paths(rth, WINDOW)
    Xp = paths.values.astype(np.float32)
    tr_p = paths.index < TEST_FROM
    ae_o = open_m.train_ae(Xp[tr_p], WINDOW, latent=8, epochs=80)
    Zopen = pd.DataFrame(open_m.encode(ae_o, Xp), index=paths.index)

    # ── PREDICTOR A: yesterday's unsupervised profile shape latent ──
    log.info('building day profiles + shape latent …')
    prof = shape_m.build_profiles(rth, NBINS)
    Xs = prof.values.astype(np.float32)
    tr_s = prof.index < TEST_FROM
    ae_s = shape_m.train_ae(Xs[tr_s], NBINS, latent=8, epochs=80)
    Zshape = pd.DataFrame(shape_m.encode(ae_s, Xs), index=prof.index,
                          columns=[f'sh{i}' for i in range(8)])

    # ── PREDICTOR B: position of today's open inside yesterday's profile ──
    D = days.copy()
    prof_al = prof.reindex(D.index)
    prior_prof = prof_al.shift(1)                       # yesterday's profile
    prev_close = D['close_px'].shift(1)
    prng = (D['prev_high'] - D['prev_low']).replace(0, np.nan)
    rel = (D['open_px'] - D['prev_low']) / prng          # <0 or >1 ⇒ gap outside range
    # volume percentile of the open inside yesterday's profile
    relc = rel.clip(0, 1)
    bidx = (relc * NBINS).astype('float').fillna(0).astype(int).clip(0, NBINS - 1)
    cum = np.full(len(D), np.nan)
    pv = prior_prof.values
    for i in range(len(D)):
        row = pv[i]
        if np.all(np.isnan(row)) or np.isnan(relc.iloc[i]):
            continue
        cum[i] = np.nansum(row[:bidx.iloc[i] + 1])
    dvol = (D['rv20'] / np.sqrt(252)).replace(0, np.nan)

    P = pd.DataFrame(index=D.index)
    P['open_rel_prior_range'] = rel
    P['dist_from_prior_mid']  = (rel - 0.5).abs()
    P['dist_from_prior_poc']  = (D['open_px'] - D['prev_poc']).abs() / prng
    P['abs_gap_vol']          = ((D['open_px'] - prev_close) / prev_close).abs() / dvol
    P['pctile_extremity']     = np.abs(cum - 0.5)
    P['outside_range']        = ((rel < 0) | (rel > 1)).astype(float)

    # ── PREDICTOR C: market regime, strictly lagged to the prior close ──
    vix = pd.read_parquet(os.path.join(CACHE, 'vix_daily.parquet'))
    vix.index = pd.to_datetime(vix.index)
    v = vix['vix_close'].reindex(D.index).ffill()
    R = pd.DataFrame(index=D.index)
    R['vix_prev']      = v.shift(1)
    R['vix_chg5']      = v.shift(1) - v.shift(6)
    R['vix_pctile252'] = v.shift(1).rolling(252).rank(pct=True)
    R['rv20_prev']     = D['rv20'].shift(1)
    try:
        reg = pd.read_parquet(os.path.join(CACHE, 'intermarket_regime_wf.parquet'))
        reg.index = pd.to_datetime(reg.index)
        R['regime_prev']      = reg['regime'].reindex(D.index).shift(1)
        R['regime_conf_prev'] = reg['regime_conf'].reindex(D.index).shift(1).fillna(0.0)
    except Exception as e:
        log.warning('regime cache unavailable (%s)', e)
        R['regime_prev'] = np.nan; R['regime_conf_prev'] = 0.0
    R['regime_prev'] = R['regime_prev'].fillna(-1).astype(int).astype(str)

    S = Zshape.reindex(D.index).shift(1)                 # yesterday's shape latent
    S.columns = [f'sh{i}' for i in range(8)]

    A = pd.concat([P, R, S], axis=1)
    A = A.join(Zopen.add_prefix('z'), how='inner')
    A = A.replace([np.inf, -np.inf], np.nan).dropna(subset=POS_FEATS + REG_FEATS +
                                                    list(S.columns))
    return A, Zopen, paths


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kopen', type=int, default=0, help='0 = BIC argmin')
    ap.add_argument('--kmax', type=int, default=10)
    args = ap.parse_args()

    A, Zopen, paths = build()
    zcols = [c for c in A.columns if c.startswith('z') and c[1:].isdigit()]
    Z = A[zcols].values
    tr = A.index < TEST_FROM
    te = ~tr
    log.info('dataset: %d days  (train %d ≤2019 / test %d ≥2020)', len(A), tr.sum(), te.sum())

    # ── target archetypes: BIC sweep + elbow ──
    rows = []
    for kk in range(1, args.kmax + 1):
        gm = GaussianMixture(kk, covariance_type='full', n_init=5, reg_covar=1e-4,
                             random_state=SEED).fit(Z[tr])
        rows.append((kk, gm.bic(Z[tr]), gm.aic(Z[tr])))
    sel = pd.DataFrame(rows, columns=['k', 'BIC', 'AIC'])
    k_elbow = pick_elbow(sel['k'].values, sel['BIC'].values)
    k_min   = int(sel.loc[sel['BIC'].idxmin(), 'k'])
    K = args.kopen if args.kopen > 0 else k_min          # BIC argmin drives
    log.info('opening-latent model selection:\n%s', sel.round(0).to_string(index=False))
    log.info('BIC argmin k=%d, elbow k=%d → using K=%d', k_min, k_elbow, K)

    gm = GaussianMixture(K, covariance_type='full', n_init=25, reg_covar=1e-4,
                         random_state=SEED).fit(Z[tr])
    y = gm.predict(Z)
    A['arch'] = y
    log.info('archetype sizes: %s', dict(pd.Series(y).value_counts().sort_index()))

    # ── feature blocks ──
    def blk(cols):
        return pd.DataFrame(StandardScaler().fit(A.loc[tr, cols]).transform(A[cols]),
                            index=A.index, columns=cols)
    Xpos = blk(POS_FEATS)
    Xreg = pd.concat([blk(REG_FEATS), pd.get_dummies(A['regime_prev'], prefix='rg')], axis=1)
    Xsha = blk([f'sh{i}' for i in range(8)])

    # ═══ classification: predict the discrete archetype ═══
    def clf_eval(X, tag):
        c = LogisticRegression(max_iter=4000, C=1.0)
        c.fit(X.values[tr], y[tr])
        pred = c.predict(X.values[te])
        acc = accuracy_score(y[te], pred)
        f1m = f1_score(y[te], pred, average='macro', zero_division=0)
        ll  = log_loss(y[te], c.predict_proba(X.values[te]), labels=c.classes_)
        maj = pd.Series(y[tr]).value_counts().idxmax()
        base = (y[te] == maj).mean()
        prior = pd.Series(y[tr]).value_counts(normalize=True).reindex(c.classes_).fillna(1e-9).values
        ll0 = log_loss(y[te], np.tile(prior, (te.sum(), 1)), labels=c.classes_)
        log.info('[%-28s] acc=%.4f (base %.4f)  macroF1=%.3f  logloss=%.4f (prior %.4f)',
                 tag, acc, base, f1m, ll, ll0)
        return dict(tag=tag, acc=acc, base=base, f1=f1m, ll=ll, ll0=ll0)

    log.info('── classification: discrete opening archetype ──')
    c_pos = clf_eval(Xpos, 'position only')
    c_reg = clf_eval(Xreg, 'regime only')
    c_sha = clf_eval(Xsha, 'prior-shape latent only')
    c_ps  = clf_eval(pd.concat([Xpos, Xsha], axis=1), 'position + prior-shape')
    c_all = clf_eval(pd.concat([Xpos, Xsha, Xreg], axis=1), 'position + shape + regime')

    # ═══ regression: predict the continuous opening latent ═══
    def reg_eval(X, tag):
        r = Ridge(alpha=10.0).fit(X.values[tr], Z[tr])
        pred = r.predict(X.values[te])
        r2_all = r2_score(Z[te], pred, multioutput='variance_weighted')
        r2_dim = r2_score(Z[te], pred, multioutput='raw_values')
        log.info('[%-28s] OOS R²(var-weighted)=%+.4f   best dim=%+.4f',
                 tag, r2_all, np.nanmax(r2_dim))
        return dict(tag=tag, r2=r2_all, r2_dim=r2_dim)

    log.info('── regression: continuous opening latent (OOS R²; 0 = no skill) ──')
    g_pos = reg_eval(Xpos, 'position only')
    g_reg = reg_eval(Xreg, 'regime only')
    g_sha = reg_eval(Xsha, 'prior-shape latent only')
    g_all = reg_eval(pd.concat([Xpos, Xsha, Xreg], axis=1), 'position + shape + regime')

    # ═══ probabilities-first: archetype vs quintile of the key position feature ═══
    A['q_gap'] = pd.qcut(A['abs_gap_vol'], 5, labels=[f'Q{i+1}' for i in range(5)], duplicates='drop')
    ct = pd.crosstab(A['q_gap'], A['arch'], normalize='index').mul(100).round(1)
    cnt = pd.crosstab(A['q_gap'], A['arch'])
    chi2, pchi, dof, _ = stats.chi2_contingency(cnt.values)
    log.info('P(archetype | |gap| quintile) [%%]:\n%s', ct.to_string())
    log.info('chi2=%.1f dof=%d p=%.3g', chi2, dof, pchi)

    base_rate = pd.Series(y).value_counts(normalize=True).sort_index()
    ps, cells = [], []
    for qi in cnt.index:
        n = cnt.loc[qi].sum()
        for a in cnt.columns:
            k = cnt.loc[qi, a]
            p1, p0 = k / n, base_rate[a]
            se = np.sqrt(p0 * (1 - p0) / n)
            ps.append(2 * (1 - stats.norm.cdf(abs(p1 - p0) / se)) if se > 0 else 1.0)
            cells.append((qi, a, n, p1 * 100, p0 * 100))
    sig, qv = bh_fdr(ps)
    H = pd.DataFrame(cells, columns=['gap_q', 'arch', 'n', 'P%', 'base%'])
    H['q'] = qv; H['sig'] = sig; H['lift'] = H['P%'] - H['base%']
    hits = H[H['sig']].sort_values('q')
    log.info('FDR-significant cells: %d/%d\n%s', len(hits), len(H),
             hits.round(2).to_string(index=False) if len(hits) else '')

    # ═══ figure ═══
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle('Track item 3 — forecasting the UNSUPERVISED opening archetype from '
                 'prior-day profile position + regime', fontsize=13, weight='bold')

    axA = fig.add_subplot(2, 3, 1)
    for c in range(K):
        axA.plot(paths.reindex(A.index).values[y == c].mean(0), label=f'A{c} (n={(y==c).sum()})')
    axA.axhline(0, color='k', lw=.6, ls=':')
    axA.set_title(f'Target: {K} opening archetypes (mean path)')
    axA.set_xlabel('minutes from open'); axA.legend(fontsize=7)

    axB = fig.add_subplot(2, 3, 2)
    axB.plot(sel['k'], sel['BIC'], 'o-', color='C3', label='BIC')
    axB.plot(sel['k'], sel['AIC'], 's-', color='C0', label='AIC')
    axB.axvline(K, color='k', ls=':', lw=1.2)
    axB.set_title(f'Opening-latent selection (argmin {k_min}, elbow {k_elbow})')
    axB.set_xlabel('k'); axB.legend(fontsize=8)

    axC = fig.add_subplot(2, 3, 3)
    names = ['pos', 'regime', 'shape', 'pos+shape', 'all']
    accs = [c_pos['acc'], c_reg['acc'], c_sha['acc'], c_ps['acc'], c_all['acc']]
    axC.bar(names, accs, color='C0', alpha=.85)
    axC.axhline(c_pos['base'], color='r', ls='--', label=f"majority {c_pos['base']:.3f}")
    axC.set_title('OOS accuracy — discrete archetype'); axC.legend(fontsize=7)
    axC.tick_params(axis='x', rotation=25)

    axD = fig.add_subplot(2, 3, 4)
    r2s = [g_pos['r2'], g_reg['r2'], g_sha['r2'], g_all['r2']]
    axD.bar(['pos', 'regime', 'shape', 'all'], r2s,
            color=['C2' if v > 0 else 'C3' for v in r2s], alpha=.85)
    axD.axhline(0, color='k', lw=1)
    axD.set_title('OOS R² — continuous opening latent'); axD.set_ylabel('R²')

    axE = fig.add_subplot(2, 3, 5)
    im = axE.imshow(ct.values, cmap='RdBu_r', vmin=ct.values.min(), vmax=ct.values.max(), aspect='auto')
    axE.set_xticks(range(ct.shape[1])); axE.set_xticklabels([f'A{c}' for c in ct.columns], fontsize=7)
    axE.set_yticks(range(ct.shape[0])); axE.set_yticklabels(ct.index, fontsize=7)
    axE.set_title(f'P(archetype | |gap| quintile) %\nchi2 p={pchi:.2g}, FDR hits={len(hits)}')
    for i in range(ct.shape[0]):
        for j in range(ct.shape[1]):
            axE.text(j, i, f'{ct.values[i,j]:.0f}', ha='center', va='center', fontsize=6)

    axF = fig.add_subplot(2, 3, 6); axF.axis('off')
    txt = (f'days={len(A)}  K={K} archetypes\n\n'
           f'CLASSIFICATION (OOS acc, base {c_pos["base"]:.4f})\n'
           f'  position only      : {c_pos["acc"]:.4f}   ll {c_pos["ll"]:.4f}\n'
           f'  regime only        : {c_reg["acc"]:.4f}   ll {c_reg["ll"]:.4f}\n'
           f'  prior-shape latent : {c_sha["acc"]:.4f}   ll {c_sha["ll"]:.4f}\n'
           f'  position + shape   : {c_ps["acc"]:.4f}   ll {c_ps["ll"]:.4f}\n'
           f'  all                : {c_all["acc"]:.4f}   ll {c_all["ll"]:.4f}\n'
           f'  (prior logloss     : {c_pos["ll0"]:.4f})\n\n'
           f'REGRESSION (OOS R², 0 = no skill)\n'
           f'  position only      : {g_pos["r2"]:+.4f}\n'
           f'  regime only        : {g_reg["r2"]:+.4f}\n'
           f'  prior-shape latent : {g_sha["r2"]:+.4f}\n'
           f'  all                : {g_all["r2"]:+.4f}\n\n'
           f'chi2 P(arch | |gap|) p = {pchi:.2g}\n'
           f'FDR-significant cells: {len(hits)}/{len(H)}')
    axF.text(0, 1, txt, va='top', ha='left', fontsize=9, family='monospace')

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = os.path.join(ROOT, 'predict_open_type.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)

    print('\n' + '=' * 74)
    print('TRACK 3 — unsupervised opening archetype from prior-profile position + regime')
    print('=' * 74)
    print(f'days={len(A)}  K={K}  (BIC argmin {k_min}, elbow {k_elbow})')
    print(f'classification OOS acc : base {c_pos["base"]:.4f} | pos {c_pos["acc"]:.4f} | '
          f'regime {c_reg["acc"]:.4f} | shape {c_sha["acc"]:.4f} | all {c_all["acc"]:.4f}')
    print(f'latent regression OOS R²: pos {g_pos["r2"]:+.4f} | regime {g_reg["r2"]:+.4f} | '
          f'shape {g_sha["r2"]:+.4f} | all {g_all["r2"]:+.4f}')
    print(f'chi2 P(arch | |gap|) p={pchi:.3g}   FDR cells {len(hits)}/{len(H)}')
    print('=' * 74)


if __name__ == '__main__':
    main()
