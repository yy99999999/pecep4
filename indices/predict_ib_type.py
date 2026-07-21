"""
predict_ib_type.py — TRACK ITEM 2 (extended):
  P(unsupervised IB type)  given
    (a) the opening type          — Dalton rule `open_type` AND the unsupervised
                                    opening archetype,
    (b) the type of YESTERDAY's profile (unsupervised day-shape archetype),
    (c) the position of today's open inside yesterday's profile.

TWO KINDS OF PREDICTOR — DO NOT MIX THEM
  · CAUSAL block (known at/just before the open): prior-day profile type + the open's
    position inside it. Anything these explain is a genuine FORECAST of IB structure.
  · CONTEMPORANEOUS block (measured in the SAME first 60 minutes as the IB): the
    opening type. Whatever this explains is OVERLAP/redundancy between two
    descriptors of one window — informative, but it is not prediction.

  Reporting them separately is the whole point: it splits "how much of the initial
  balance is already set at the open" from "how much the opening merely re-describes".

MODEL SELECTION
  Every unsupervised taxonomy here (IB types, opening archetypes, prior-profile types)
  is chosen by BIC argmin over a GaussianMixture fitted on TRAIN years only.

LESSON CARRIED FORWARD
  Discrete labels lose information, so besides classifying the discrete IB type we also
  regress the CONTINUOUS IB latent (OOS R²) — a k-invariant measure of real skill.

USAGE  ./vbt-env/bin/python predict_ib_type.py
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
log = logging.getLogger('ib-pred')
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
    log.info('[%s] BIC argmin k=%d\n%s', tag, k, sel.round(0).to_string(index=False))
    return k, sel


# ───────────────────────── build ─────────────────────────
def build(kmax):
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    t = es.index.hour * 60 + es.index.minute
    rth = es[(t >= RTH_START) & (t < RTH_END)].copy()
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet')); days.index = pd.to_datetime(days.index)

    shape_m = _load('shape_ae', os.path.join(ROOT, 'day_shape_autoencoder.py'))
    open_m  = _load('open_ae',  os.path.join(ROOT, 'open_type_autoencoder.py'))
    ib_m    = _load('ib_ae',    os.path.join(ROOT, 'ib_type_autoencoder.py'))

    # ── TARGET: unsupervised IB type + continuous IB latent ──
    log.info('building IB descriptors …')
    Fib = ib_m.build_ib_features(rth, days, bins=24).dropna(subset=ib_m.FEATURES)
    tr_i = Fib.index < TEST_FROM
    Xi = StandardScaler().fit(Fib.loc[tr_i, ib_m.FEATURES]).transform(Fib[ib_m.FEATURES]).astype(np.float32)
    ae_i = ib_m.train_ae(Xi[tr_i], Xi.shape[1], latent=4, epochs=120)
    Zib = pd.DataFrame(ib_m.encode(ae_i, Xi), index=Fib.index)

    # ── opening: rule type + unsupervised archetype (contemporaneous) ──
    log.info('building opening paths …')
    paths, _ = open_m.build_open_paths(rth, WINDOW)
    Xp = paths.values.astype(np.float32)
    tr_p = paths.index < TEST_FROM
    ae_o = open_m.train_ae(Xp[tr_p], WINDOW, latent=8, epochs=80)
    Zopen = pd.DataFrame(open_m.encode(ae_o, Xp), index=paths.index)

    # ── prior-day profile: unsupervised shape archetype (causal, lagged) ──
    log.info('building day profiles …')
    prof = shape_m.build_profiles(rth, NBINS)
    Xs = prof.values.astype(np.float32)
    tr_s = prof.index < TEST_FROM
    ae_s = shape_m.train_ae(Xs[tr_s], NBINS, latent=8, epochs=80)
    Zshape = pd.DataFrame(shape_m.encode(ae_s, Xs), index=prof.index)

    # ── position of the open inside yesterday's profile (causal) ──
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

    P = pd.DataFrame(index=D.index)
    P['open_rel_prior_range'] = rel
    P['dist_from_prior_mid']  = (rel - 0.5).abs()
    P['dist_from_prior_poc']  = (D['open_px'] - D['prev_poc']).abs() / prng
    P['abs_gap_vol']          = ((D['open_px'] - prev_close) / prev_close).abs() / dvol
    P['pctile_extremity']     = np.abs(cum - 0.5)
    P['outside_range']        = ((rel < 0) | (rel > 1)).astype(float)

    A = P.join(D[['open_type']], how='left')
    A = A.join(Zib.add_prefix('ib'), how='inner')
    A = A.join(Zopen.add_prefix('op'), how='inner')
    A = A.join(Zshape.reindex(D.index).shift(1).add_prefix('ps'), how='inner')  # PRIOR day
    A = A.replace([np.inf, -np.inf], np.nan).dropna()
    A = A[A['open_type'].astype(str) != 'unknown']
    return A, kmax


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kmax', type=int, default=10)
    args = ap.parse_args()

    A, _ = build(args.kmax)
    tr = A.index < TEST_FROM
    te = ~tr
    log.info('dataset: %d days (train %d ≤2019 / test %d ≥2020)', len(A), tr.sum(), te.sum())

    # latent columns are <prefix><digit>; guard against e.g. 'open_type' matching 'op'
    ibc = [c for c in A.columns if c.startswith('ib') and c[2:].isdigit()]
    opc = [c for c in A.columns if c.startswith('op') and c[2:].isdigit()]
    psc = [c for c in A.columns if c.startswith('ps') and c[2:].isdigit()]
    Zib, Zop, Zps = A[ibc].values, A[opc].values, A[psc].values

    # ── taxonomies, all BIC-argmin on TRAIN ──
    k_ib, sel_ib = bic_argmin(Zib[tr], args.kmax, 'IB types (target)')
    k_op, _      = bic_argmin(Zop[tr], args.kmax, 'opening archetypes')
    k_ps, _      = bic_argmin(Zps[tr], args.kmax, 'prior-profile types')
    y      = GaussianMixture(k_ib, covariance_type='full', n_init=25, reg_covar=1e-4,
                             random_state=SEED).fit(Zib[tr]).predict(Zib)
    a_open = GaussianMixture(k_op, covariance_type='full', n_init=25, reg_covar=1e-4,
                             random_state=SEED).fit(Zop[tr]).predict(Zop)
    a_ps   = GaussianMixture(k_ps, covariance_type='full', n_init=25, reg_covar=1e-4,
                             random_state=SEED).fit(Zps[tr]).predict(Zps)
    A['ib_type'], A['open_arch'], A['prior_type'] = y, a_open, a_ps
    log.info('k: IB=%d  opening=%d  prior-profile=%d | IB sizes %s',
             k_ib, k_op, k_ps, dict(pd.Series(y).value_counts().sort_index()))

    # ── feature blocks ──
    scale = lambda cols: pd.DataFrame(
        StandardScaler().fit(A.loc[tr, cols]).transform(A[cols]), index=A.index, columns=cols)
    X_pos  = scale(POS_FEATS)                                             # causal
    X_ptyp = pd.get_dummies(A['prior_type'], prefix='pt')                 # causal
    X_plat = scale(psc)                                                   # causal (continuous)
    X_odal = pd.get_dummies(A['open_type'].astype(str), prefix='od')      # contemporaneous
    X_oarc = pd.get_dummies(A['open_arch'], prefix='oa')                  # contemporaneous
    X_olat = scale(opc)                                                   # contemporaneous (cont.)

    def clf(X, tag):
        c = LogisticRegression(max_iter=4000, C=1.0).fit(X.values[tr], y[tr])
        pred = c.predict(X.values[te])
        acc = accuracy_score(y[te], pred)
        f1m = f1_score(y[te], pred, average='macro', zero_division=0)
        ll = log_loss(y[te], c.predict_proba(X.values[te]), labels=c.classes_)
        maj = pd.Series(y[tr]).value_counts().idxmax()
        base = (y[te] == maj).mean()
        prior = pd.Series(y[tr]).value_counts(normalize=True).reindex(c.classes_).fillna(1e-9).values
        ll0 = log_loss(y[te], np.tile(prior, (te.sum(), 1)), labels=c.classes_)
        log.info('[%-34s] acc=%.4f (base %.4f)  macroF1=%.3f  ll=%.4f (prior %.4f)',
                 tag, acc, base, f1m, ll, ll0)
        return dict(tag=tag, acc=acc, base=base, f1=f1m, ll=ll, ll0=ll0)

    def reg(X, tag):
        r = Ridge(alpha=10.0).fit(X.values[tr], Zib[tr])
        r2 = r2_score(Zib[te], r.predict(X.values[te]), multioutput='variance_weighted')
        log.info('[%-34s] OOS R²(IB latent)=%+.4f', tag, r2)
        return r2

    log.info('══ CAUSAL block — genuine forecast (known at the open) ══')
    c_pos  = clf(X_pos, 'position in prior profile')
    c_pt   = clf(X_ptyp, 'prior-profile TYPE')
    c_pl   = clf(X_plat, 'prior-profile latent (cont.)')
    c_caus = clf(pd.concat([X_pos, X_ptyp], axis=1), 'CAUSAL: position + prior type')
    c_causl= clf(pd.concat([X_pos, X_plat], axis=1), 'CAUSAL: position + prior latent')

    log.info('══ CONTEMPORANEOUS block — overlap, NOT a forecast ══')
    c_od   = clf(X_odal, 'open_type (Dalton rule)')
    c_oa   = clf(X_oarc, 'opening archetype (unsup.)')
    c_ol   = clf(X_olat, 'opening latent (cont.)')
    c_all  = clf(pd.concat([X_pos, X_ptyp, X_odal, X_oarc], axis=1), 'ALL (causal + contemporaneous)')

    log.info('══ continuous IB latent, OOS R² (k-invariant) ══')
    r_pos  = reg(X_pos, 'position in prior profile')
    r_pt   = reg(X_ptyp, 'prior-profile TYPE')
    r_caus = reg(pd.concat([X_pos, X_plat], axis=1), 'CAUSAL: position + prior latent')
    r_oa   = reg(X_oarc, 'opening archetype (unsup.)')
    r_ol   = reg(X_olat, 'opening latent (cont.)')
    r_all  = reg(pd.concat([X_pos, X_plat, X_olat], axis=1), 'ALL')

    # ── probabilities-first: P(IB type | opening archetype) and | prior type ──
    def contingency(col, name):
        cnt = pd.crosstab(A[col], A['ib_type'])
        pct = pd.crosstab(A[col], A['ib_type'], normalize='index').mul(100).round(1)
        chi2, p, dof, _ = stats.chi2_contingency(cnt.values)
        log.info('P(ib_type | %s) [%%]  chi2=%.1f dof=%d p=%.3g:\n%s', name, chi2, dof, p, pct.to_string())
        base = pd.Series(y).value_counts(normalize=True).sort_index()
        ps, cells = [], []
        for r_ in cnt.index:
            n = cnt.loc[r_].sum()
            for cc in cnt.columns:
                p1, p0 = cnt.loc[r_, cc] / n, base[cc]
                se = np.sqrt(p0 * (1 - p0) / n)
                ps.append(2 * (1 - stats.norm.cdf(abs(p1 - p0) / se)) if se > 0 else 1.0)
                cells.append((r_, cc, n, p1 * 100, p0 * 100))
        sig, qv = bh_fdr(ps)
        H = pd.DataFrame(cells, columns=[name, 'ib_type', 'n', 'P%', 'base%'])
        H['q'] = qv; H['sig'] = sig; H['lift'] = H['P%'] - H['base%']
        log.info('  FDR-significant: %d/%d', H['sig'].sum(), len(H))
        return pct, p, H

    pct_o, p_o, H_o = contingency('open_arch', 'opening archetype')
    pct_p, p_p, H_p = contingency('prior_type', 'prior-profile type')

    # ── figure ──
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle('Track item 2 — P(unsupervised IB type | opening type, prior profile, open position)',
                 fontsize=13, weight='bold')

    axA = fig.add_subplot(2, 3, 1)
    axA.plot(sel_ib['k'], sel_ib['BIC'], 'o-', color='C3', label='BIC')
    axA.plot(sel_ib['k'], sel_ib['AIC'], 's-', color='C0', label='AIC')
    axA.axvline(k_ib, color='k', ls=':')
    axA.set_title(f'IB-type selection — BIC argmin k={k_ib}'); axA.set_xlabel('k'); axA.legend(fontsize=8)

    axB = fig.add_subplot(2, 3, 2)
    im = axB.imshow(pct_o.values, cmap='RdBu_r', aspect='auto')
    axB.set_xticks(range(pct_o.shape[1])); axB.set_xticklabels([f'IB{c}' for c in pct_o.columns], fontsize=6)
    axB.set_yticks(range(pct_o.shape[0])); axB.set_yticklabels([f'A{r}' for r in pct_o.index], fontsize=7)
    axB.set_title(f'P(IB type | opening archetype) %\nchi2 p={p_o:.2g}, FDR {H_o["sig"].sum()}/{len(H_o)}')
    for i in range(pct_o.shape[0]):
        for j in range(pct_o.shape[1]):
            axB.text(j, i, f'{pct_o.values[i,j]:.0f}', ha='center', va='center', fontsize=5)

    axC = fig.add_subplot(2, 3, 3)
    im = axC.imshow(pct_p.values, cmap='RdBu_r', aspect='auto')
    axC.set_xticks(range(pct_p.shape[1])); axC.set_xticklabels([f'IB{c}' for c in pct_p.columns], fontsize=6)
    axC.set_yticks(range(pct_p.shape[0])); axC.set_yticklabels([f'P{r}' for r in pct_p.index], fontsize=7)
    axC.set_title(f'P(IB type | prior-profile type) %\nchi2 p={p_p:.2g}, FDR {H_p["sig"].sum()}/{len(H_p)}')
    for i in range(pct_p.shape[0]):
        for j in range(pct_p.shape[1]):
            axC.text(j, i, f'{pct_p.values[i,j]:.0f}', ha='center', va='center', fontsize=5)

    axD = fig.add_subplot(2, 3, 4)
    names = ['pos', 'priorType', 'CAUSAL', 'openDalton', 'openArch', 'ALL']
    accs  = [c_pos['acc'], c_pt['acc'], c_caus['acc'], c_od['acc'], c_oa['acc'], c_all['acc']]
    cols  = ['C0', 'C0', 'C0', 'C1', 'C1', 'C2']
    axD.bar(names, accs, color=cols, alpha=.85)
    axD.axhline(c_pos['base'], color='r', ls='--', label=f"majority {c_pos['base']:.3f}")
    axD.set_title('OOS accuracy (blue=causal, orange=contemporaneous)')
    axD.tick_params(axis='x', rotation=30); axD.legend(fontsize=7)

    axE = fig.add_subplot(2, 3, 5)
    rn = ['pos', 'priorType', 'CAUSAL', 'openArch', 'openLatent', 'ALL']
    rv = [r_pos, r_pt, r_caus, r_oa, r_ol, r_all]
    axE.bar(rn, rv, color=['C0', 'C0', 'C0', 'C1', 'C1', 'C2'], alpha=.85)
    axE.axhline(0, color='k', lw=1)
    axE.set_title('OOS R² — continuous IB latent'); axE.tick_params(axis='x', rotation=30)

    axF = fig.add_subplot(2, 3, 6); axF.axis('off')
    txt = (f'days={len(A)}   k: IB={k_ib}, opening={k_op}, prior={k_ps}\n\n'
           f'CAUSAL (forecast; base {c_pos["base"]:.4f})\n'
           f'  position           acc {c_pos["acc"]:.4f}  ll {c_pos["ll"]:.4f}\n'
           f'  prior-profile TYPE acc {c_pt["acc"]:.4f}  ll {c_pt["ll"]:.4f}\n'
           f'  prior latent       acc {c_pl["acc"]:.4f}  ll {c_pl["ll"]:.4f}\n'
           f'  position+priorType acc {c_caus["acc"]:.4f}  ll {c_caus["ll"]:.4f}\n'
           f'  (prior logloss     {c_pos["ll0"]:.4f})\n\n'
           f'CONTEMPORANEOUS (overlap, NOT forecast)\n'
           f'  open_type (rule)   acc {c_od["acc"]:.4f}  ll {c_od["ll"]:.4f}\n'
           f'  opening archetype  acc {c_oa["acc"]:.4f}  ll {c_oa["ll"]:.4f}\n'
           f'  opening latent     acc {c_ol["acc"]:.4f}  ll {c_ol["ll"]:.4f}\n'
           f'  ALL                acc {c_all["acc"]:.4f}  ll {c_all["ll"]:.4f}\n\n'
           f'OOS R² (continuous IB latent)\n'
           f'  causal   pos {r_pos:+.4f}  pos+priorLat {r_caus:+.4f}\n'
           f'  contemp. arch {r_oa:+.4f}  openLatent {r_ol:+.4f}\n'
           f'  ALL {r_all:+.4f}')
    axF.text(0, 1, txt, va='top', ha='left', fontsize=8.5, family='monospace')

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = os.path.join(ROOT, 'predict_ib_type.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)

    print('\n' + '=' * 76)
    print('TRACK 2 — P(unsupervised IB type | opening, prior profile, open position)')
    print('=' * 76)
    print(f'days={len(A)}  k: IB={k_ib}, opening={k_op}, prior-profile={k_ps}  base={c_pos["base"]:.4f}')
    print(f'CAUSAL (forecast)        : pos {c_pos["acc"]:.4f} | priorType {c_pt["acc"]:.4f} | '
          f'both {c_caus["acc"]:.4f}   | OOS R² {r_caus:+.4f}')
    print(f'CONTEMPORANEOUS (overlap): openRule {c_od["acc"]:.4f} | openArch {c_oa["acc"]:.4f} | '
          f'openLatent {c_ol["acc"]:.4f} | OOS R² {r_ol:+.4f}')
    print(f'chi2  P(IB|opening) p={p_o:.3g} (FDR {H_o["sig"].sum()}/{len(H_o)})   '
          f'P(IB|prior) p={p_p:.3g} (FDR {H_p["sig"].sum()}/{len(H_p)})')
    print('=' * 76)


if __name__ == '__main__':
    main()
