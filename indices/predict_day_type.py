"""
predict_day_type.py — TRACK ITEM 1:
  can the Dalton DAY TYPE be predicted at the END OF THE FIRST HOUR from
  (a) the OPENING type and (b) the unsupervised IB type?

WHY THIS IS A REAL FORECAST, NOT A TAUTOLOGY
  classify_day_type() is driven mostly by POST-IB information: whether/which way the
  IB gets broken, the full-day range (ib_range/day_range), the day POC position
  (poc_bias) and day-profile bimodality — none of which is known at IB close.
  The only overlapping input is ib_width_cat, and it only gates the two rare classes
  (nontrend n=18, normal n=73). So predicting day_type from open_type + ib_type at
  minute 60 is a genuine forward question.

METHOD (project house-style)
  · predictors known at minute 60:  open_type (Dalton rule, 4 cats)
                                    ib_type   (unsupervised AE+GMM, 3 cats)
  · honest TIME split: train ≤2019, test ≥2020 (no shuffling)
  · PROBABILITIES FIRST: full P(day_type | open_type × ib_type) contingency,
    chi-square independence test, then per-cell two-proportion tests with BH-FDR
    and Wilson lower bounds — only then models.
  · INCREMENTALITY GATE: ib_type must beat open_type alone OOS or it is dropped.
  · baselines: majority class + prior; rare classes reported but not chased.

USAGE  ./vbt-env/bin/python predict_day_type.py
"""
import os, importlib.util, logging
import numpy as np
import pandas as pd

import session               # DST-aware cash session (see session.py)

import torch
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.mixture import GaussianMixture
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, log_loss
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT      = os.path.dirname(os.path.abspath(__file__))
CACHE     = os.path.join(ROOT, 'cache')
SEED      = 7
TEST_FROM = pd.Timestamp('2020-01-01')
K_IB      = 3          # BIC-elbow number of IB types
MAJORS    = ['normal_variation', 'double_distribution', 'neutral']   # 96% of days

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('daytype')
np.random.seed(SEED); torch.manual_seed(SEED)


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


# ───────────────────────── stats helpers (project house-style) ─────────────────────────
def wilson_lb(k, n, z=1.96):
    if n == 0:
        return np.nan
    p = k / n
    d = 1 + z**2 / n
    c = p + z**2 / (2 * n)
    m = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (c - m) / d


def two_prop_p(k1, n1, k2, n2):
    if min(n1, n2) == 0:
        return 1.0
    p1, p2 = k1 / n1, k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    return 2 * (1 - stats.norm.cdf(abs(p1 - p2) / se))


def bh_fdr(pvals, q=0.10):
    p = np.asarray(pvals, float)
    n = len(p)
    order = np.argsort(p)
    thresh = q * (np.arange(1, n + 1)) / n
    passed = p[order] <= thresh
    out = np.zeros(n, bool)
    if passed.any():
        cut = np.max(np.where(passed)[0])
        out[order[:cut + 1]] = True
    # BH-adjusted q-values
    qv = np.empty(n); running = 1.0
    for i in range(n - 1, -1, -1):
        running = min(running, p[order[i]] * n / (i + 1))
        qv[order[i]] = running
    return out, qv


# ───────────────────────── build the three variables ─────────────────────────
def build_dataset():
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    rth = session.get_rth(es)
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet'))
    days.index = pd.to_datetime(days.index)

    ib = _load('ib_ae', os.path.join(ROOT, 'ib_type_autoencoder.py'))
    log.info('rebuilding IB structural descriptors + IB types (k=%d) …', K_IB)
    F = ib.build_ib_features(rth, days, bins=24)
    F = F.dropna(subset=ib.FEATURES)
    tr = F.index < TEST_FROM
    Xs = StandardScaler().fit(F.loc[tr, ib.FEATURES]).transform(F[ib.FEATURES]).astype(np.float32)
    model = ib.train_ae(Xs[tr], Xs.shape[1], latent=4, epochs=120)
    Z = ib.encode(model, Xs)
    gm = GaussianMixture(K_IB, covariance_type='full', n_init=25,
                         reg_covar=1e-4, random_state=SEED).fit(Z)
    F['ib_type'] = gm.predict(Z)

    D = F[['ib_type']].join(days[['open_type', 'day_type']], how='inner')
    D = D[D['open_type'].notna() & D['day_type'].notna()]
    D = D[(D['open_type'].astype(str) != 'unknown') & (D['day_type'].astype(str) != 'unknown')]
    D['ib_type'] = D['ib_type'].astype(int)
    # keep the raw IB features too (for the "continuous upper bound" model)
    D = D.join(F[ib.FEATURES])
    return D, ib.FEATURES


# ───────────────────────── main ─────────────────────────
def main():
    D, IBFEATS = build_dataset()
    log.info('dataset: %d days | open_type=%d cats, ib_type=%d cats, day_type=%d cats',
             len(D), D['open_type'].nunique(), D['ib_type'].nunique(), D['day_type'].nunique())

    tr = D.index < TEST_FROM
    te = ~tr
    log.info('train %d (≤2019)  test %d (≥2020)', tr.sum(), te.sum())

    # ═══════════ 1. PROBABILITIES FIRST ═══════════
    D['cell'] = D['open_type'].astype(str) + ' | IB' + D['ib_type'].astype(str)
    ct_cnt = pd.crosstab(D['cell'], D['day_type'])
    ct_pct = pd.crosstab(D['cell'], D['day_type'], normalize='index').mul(100).round(1)
    log.info('P(day_type | open_type × ib_type)  [%%]:\n%s', ct_pct.to_string())

    chi2, pchi, dof, _ = stats.chi2_contingency(ct_cnt.values)
    log.info('chi-square independence: chi2=%.1f  dof=%d  p=%.3g', chi2, dof, pchi)

    # per-cell tests vs the overall base rate, for the dominant classes, BH-FDR
    base = D['day_type'].value_counts(normalize=True)
    rows = []
    for cell in ct_cnt.index:
        n = int(ct_cnt.loc[cell].sum())
        for cls in MAJORS:
            k = int(ct_cnt.loc[cell, cls]) if cls in ct_cnt.columns else 0
            k_rest = int(D[D['day_type'] == cls].shape[0]) - k
            n_rest = len(D) - n
            p = two_prop_p(k, n, k_rest, n_rest)
            rows.append((cell, cls, n, k / n * 100, base[cls] * 100,
                         wilson_lb(k, n) * 100, p))
    R = pd.DataFrame(rows, columns=['cell', 'day_type', 'n', 'P%', 'base%', 'wilson_lb%', 'p'])
    sig, qv = bh_fdr(R['p'].values, q=0.10)
    R['q'] = qv; R['sig_FDR10'] = sig
    R['lift'] = R['P%'] - R['base%']
    hits = R[R['sig_FDR10']].sort_values('q')
    log.info('FDR-significant cells (q<0.10): %d of %d tests', len(hits), len(R))
    if len(hits):
        log.info('\n%s', hits[['cell', 'day_type', 'n', 'P%', 'base%', 'lift', 'wilson_lb%', 'q']]
                 .round(2).to_string(index=False))

    # ═══════════ 2. MODELS (incrementality gate) ═══════════
    ohe = lambda s, pre: pd.get_dummies(s.astype(str), prefix=pre)
    Xopen = ohe(D['open_type'], 'op')
    Xib   = ohe(D['ib_type'], 'ib')
    Xint  = ohe(D['cell'], 'cell')                       # full interaction cells
    Xcont = pd.DataFrame(StandardScaler().fit(D.loc[tr, IBFEATS]).transform(D[IBFEATS]),
                         index=D.index, columns=IBFEATS)
    y = D['day_type'].astype(str).values

    def evaluate(X, tag, mask_cls=None):
        m = np.ones(len(D), bool) if mask_cls is None else np.isin(y, mask_cls)
        Xtr, ytr = X.values[tr & m], y[tr & m]
        Xte, yte = X.values[te & m], y[te & m]
        clf = LogisticRegression(max_iter=3000, C=1.0)   # multinomial by default
        clf.fit(Xtr, ytr)
        pred = clf.predict(Xte)
        acc = accuracy_score(yte, pred)
        f1m = f1_score(yte, pred, average='macro', zero_division=0)
        maj = pd.Series(ytr).value_counts().idxmax()
        basel = (yte == maj).mean()
        try:
            ll = log_loss(yte, clf.predict_proba(Xte), labels=clf.classes_)
            ll0 = log_loss(yte, np.tile(pd.Series(ytr).value_counts(normalize=True)
                                        .reindex(clf.classes_).fillna(1e-9).values,
                                        (len(yte), 1)), labels=clf.classes_)
        except Exception:
            ll = ll0 = np.nan
        log.info('[%-34s] OOS acc=%.4f  macroF1=%.3f  logloss=%.4f (prior %.4f)  base=%.4f',
                 tag, acc, f1m, ll, ll0, basel)
        return dict(tag=tag, acc=acc, f1=f1m, ll=ll, ll0=ll0, base=basel, pred=pred, yte=yte)

    log.info('── 6-class ──')
    r_op   = evaluate(Xopen, 'open_type only')
    r_ib   = evaluate(Xib,   'ib_type only')
    r_both = evaluate(pd.concat([Xopen, Xib], axis=1), 'open_type + ib_type')
    r_int  = evaluate(Xint,  'interaction cells (4×3)')
    r_cont = evaluate(pd.concat([Xopen, Xcont], axis=1), 'open_type + RAW IB features')

    log.info('── 3 dominant classes (96%% of days) ──')
    m3_op   = evaluate(Xopen, 'open_type only [3-class]', MAJORS)
    m3_ib   = evaluate(Xib,   'ib_type only [3-class]', MAJORS)
    m3_both = evaluate(pd.concat([Xopen, Xib], axis=1), 'open+ib [3-class]', MAJORS)
    m3_cont = evaluate(pd.concat([Xopen, Xcont], axis=1), 'open+RAW IB [3-class]', MAJORS)

    # incrementality verdict
    inc = m3_both['acc'] - m3_op['acc']
    log.info('INCREMENTALITY (3-class): open→open+ib  Δacc=%+.4f  Δlogloss=%+.4f',
             inc, m3_both['ll'] - m3_op['ll'])

    # ═══════════ 3. figure ═══════════
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle('Track item 1 — predicting Dalton DAY TYPE at IB close from open_type × ib_type',
                 fontsize=13, weight='bold')

    axA = fig.add_subplot(2, 3, 1)
    im = axA.imshow(ct_pct.values, cmap='Blues', vmin=0, vmax=60, aspect='auto')
    axA.set_xticks(range(len(ct_pct.columns))); axA.set_xticklabels(ct_pct.columns, rotation=90, fontsize=6)
    axA.set_yticks(range(len(ct_pct.index)));   axA.set_yticklabels(ct_pct.index, fontsize=6)
    axA.set_title('P(day_type | open_type × ib_type)  %')
    for i in range(ct_pct.shape[0]):
        for j in range(ct_pct.shape[1]):
            axA.text(j, i, f'{ct_pct.values[i,j]:.0f}', ha='center', va='center', fontsize=5,
                     color='white' if ct_pct.values[i, j] > 35 else 'black')

    axB = fig.add_subplot(2, 3, 2)
    lifts = R.pivot(index='cell', columns='day_type', values='lift')
    im2 = axB.imshow(lifts.values, cmap='RdBu_r', vmin=-15, vmax=15, aspect='auto')
    axB.set_xticks(range(lifts.shape[1])); axB.set_xticklabels(lifts.columns, rotation=90, fontsize=6)
    axB.set_yticks(range(lifts.shape[0])); axB.set_yticklabels(lifts.index, fontsize=6)
    axB.set_title(f'lift vs base rate (pp)\nchi2 p={pchi:.2g}, FDR hits={len(hits)}')
    for i in range(lifts.shape[0]):
        for j in range(lifts.shape[1]):
            v = lifts.values[i, j]
            axB.text(j, i, f'{v:+.0f}', ha='center', va='center', fontsize=5)

    axC = fig.add_subplot(2, 3, 3)
    names = ['open', 'ib', 'open+ib', 'cells', 'open+rawIB']
    accs  = [r_op['acc'], r_ib['acc'], r_both['acc'], r_int['acc'], r_cont['acc']]
    axC.bar(names, accs, color='C0', alpha=.85)
    axC.axhline(r_op['base'], color='r', ls='--', lw=1.2, label=f"majority {r_op['base']:.3f}")
    axC.set_title('OOS accuracy — 6-class'); axC.legend(fontsize=7)
    axC.tick_params(axis='x', rotation=30); axC.set_ylim(0, max(accs + [r_op['base']]) * 1.25)

    axD = fig.add_subplot(2, 3, 4)
    names3 = ['open', 'ib', 'open+ib', 'open+rawIB']
    accs3  = [m3_op['acc'], m3_ib['acc'], m3_both['acc'], m3_cont['acc']]
    axD.bar(names3, accs3, color='C2', alpha=.85)
    axD.axhline(m3_op['base'], color='r', ls='--', lw=1.2, label=f"majority {m3_op['base']:.3f}")
    axD.set_title('OOS accuracy — 3 dominant classes'); axD.legend(fontsize=7)
    axD.tick_params(axis='x', rotation=30); axD.set_ylim(0, max(accs3 + [m3_op['base']]) * 1.25)

    axE = fig.add_subplot(2, 3, 5)
    cls3 = sorted(set(m3_both['yte']))
    cm = confusion_matrix(m3_both['yte'], m3_both['pred'], labels=cls3, normalize='true')
    axE.imshow(cm, cmap='Blues', vmin=0, vmax=1)
    axE.set_xticks(range(len(cls3))); axE.set_xticklabels(cls3, rotation=90, fontsize=6)
    axE.set_yticks(range(len(cls3))); axE.set_yticklabels(cls3, fontsize=6)
    axE.set_title('Confusion: open+ib (3-class, OOS)')
    for i in range(len(cls3)):
        for j in range(len(cls3)):
            axE.text(j, i, f'{cm[i,j]:.2f}', ha='center', va='center', fontsize=6,
                     color='white' if cm[i, j] > .5 else 'black')

    axF = fig.add_subplot(2, 3, 6); axF.axis('off')
    verdict = (
        f'chi-square independence : p = {pchi:.2g}\n'
        f'FDR-significant cells   : {len(hits)} / {len(R)}\n\n'
        f'6-class OOS accuracy\n'
        f'  majority baseline : {r_op["base"]:.4f}\n'
        f'  open_type         : {r_op["acc"]:.4f}\n'
        f'  ib_type           : {r_ib["acc"]:.4f}\n'
        f'  open + ib         : {r_both["acc"]:.4f}\n'
        f'  open + RAW IB     : {r_cont["acc"]:.4f}\n\n'
        f'3-class OOS accuracy\n'
        f'  majority baseline : {m3_op["base"]:.4f}\n'
        f'  open_type         : {m3_op["acc"]:.4f}\n'
        f'  open + ib         : {m3_both["acc"]:.4f}\n'
        f'  open + RAW IB     : {m3_cont["acc"]:.4f}\n\n'
        f'INCREMENTALITY (3-class)\n'
        f'  open → open+ib  Δacc = {inc:+.4f}\n'
        f'  Δlogloss = {m3_both["ll"] - m3_op["ll"]:+.4f}\n'
    )
    axF.text(0, 1, verdict, va='top', ha='left', fontsize=9, family='monospace')

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = os.path.join(ROOT, 'predict_day_type.png')
    fig.savefig(out, dpi=110)
    log.info('saved figure → %s', out)

    print('\n' + '=' * 72)
    print('TRACK 1 — day_type from open_type × ib_type (OOS 2020-2026)')
    print('=' * 72)
    print(f'chi2 independence p={pchi:.3g}   FDR-significant cells: {len(hits)}/{len(R)}')
    print(f'6-class : base {r_op["base"]:.4f} | open {r_op["acc"]:.4f} | ib {r_ib["acc"]:.4f} '
          f'| open+ib {r_both["acc"]:.4f} | open+rawIB {r_cont["acc"]:.4f}')
    print(f'3-class : base {m3_op["base"]:.4f} | open {m3_op["acc"]:.4f} | ib {m3_ib["acc"]:.4f} '
          f'| open+ib {m3_both["acc"]:.4f} | open+rawIB {m3_cont["acc"]:.4f}')
    print(f'incrementality open→open+ib (3-class): Δacc={inc:+.4f}  '
          f'Δlogloss={m3_both["ll"] - m3_op["ll"]:+.4f}')
    print('=' * 72)


if __name__ == '__main__':
    main()
