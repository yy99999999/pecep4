"""
ib_type_autoencoder.py — UNSUPERVISED discovery of INITIAL-BALANCE types (user's own
theory; NOT a Dalton taxonomy) via a PyTorch autoencoder, same principle as the
day-shape / opening-type models.

IDEA
  An "IB type" is a compact description of the STRUCTURE of the first 60 minutes:
  how wide it is, where price opened & closed within it, how one-sided it was, WHEN
  the extremes formed, whether it kept expanding, and how the IB volume is skewed.
  All features are direction-invariant (canonicalised by the sign of the IB move, so a
  one-sided-up and one-sided-down IB are the same TYPE) and causal (known at IB close).

  The autoencoder compresses this structural descriptor → a latent; KMeans finds the
  natural IB archetypes. We then CHARACTERISE each type and — the payoff — test whether
  it predicts the POST-IB move IN THE IB'S OWN DIRECTION (continuation vs reversal),
  honest OOS. That is the tradeable content of the theory.

USAGE
  ./vbt-env/bin/python ib_type_autoencoder.py [--k 5] [--latent 4] [--bins 24] [--epochs 120]

Reads cache/es_continuous.parquet + cache/es_days.parquet.
"""
import os, argparse, logging
import numpy as np
import pandas as pd

import session               # DST-aware cash session (see session.py)

import torch
import torch.nn as nn
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT      = os.path.dirname(os.path.abspath(__file__))
CACHE     = os.path.join(ROOT, 'cache')
SEED      = 7
TEST_FROM = pd.Timestamp('2020-01-01')
IBW       = 60          # initial-balance window (minutes)

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('ib-ae')
np.random.seed(SEED); torch.manual_seed(SEED)

FEATURES = ['width', 'open_run_side', 'close_run_side', 'one_sided',
            'run_ext_time', 'ctr_ext_time', 'range_build', 'vol_skew_dir',
            'vol_conc', 'ib_vol_z']


# ───────────────────────── IB structural descriptor ─────────────────────────
def build_ib_features(rth, days, bins):
    rth = rth.copy(); rth['date'] = rth.index.normalize()
    rows = {}
    for date, g in rth.groupby('date'):
        if len(g) < IBW:
            continue
        g = g.iloc[:IBW]
        hi = g['high'].values; lo = g['low'].values; cl = g['close'].values
        vol = g['volume'].values.astype(float)
        op  = g['open'].iloc[0]; c60 = cl[-1]
        ibh, ibl = hi.max(), lo.min(); ibr = ibh - ibl
        if ibr <= 0:
            continue
        s = np.sign(c60 - op) or 1.0                       # IB move direction
        # positions on the "run side" (1 = far end of the move)
        open_pos  = np.clip((op  - ibl) / ibr, 0, 1)
        close_pos = np.clip((c60 - ibl) / ibr, 0, 1)
        open_run  = open_pos  if s > 0 else 1 - open_pos
        close_run = close_pos if s > 0 else 1 - close_pos
        one_sided = abs(c60 - op) / ibr
        # timing of extremes (0=start,1=end of IB), by move direction
        hi_t = int(np.argmax(hi)) / IBW
        lo_t = int(np.argmin(lo)) / IBW
        run_ext_time = hi_t if s > 0 else lo_t             # when the run extreme printed
        ctr_ext_time = lo_t if s > 0 else hi_t             # when the counter extreme printed
        # expansion: 2nd-half range vs 1st-half range
        r1 = hi[:30].max() - lo[:30].min()
        r2 = hi[30:].max() - lo[30:].min()
        range_build = r2 / (r1 + 1e-9)
        # IB volume profile → skew toward the run end + concentration
        tp = (hi + lo + cl) / 3.0
        idx = np.clip(((tp - ibl) / ibr * bins).astype(int), 0, bins - 1)
        prof = np.bincount(idx, weights=vol, minlength=bins).astype(float)
        prof = prof / prof.sum()
        centers = (np.arange(bins) + 0.5) / bins
        com = float((centers * prof).sum())
        vol_skew_dir = s * (com - 0.5) * 2.0               # >0: volume built toward the run
        vol_conc = float(prof.max())                       # peakiness (balanced vs single node)
        rows[date] = dict(width=np.nan, open_run_side=open_run, close_run_side=close_run,
                          one_sided=one_sided, run_ext_time=run_ext_time,
                          ctr_ext_time=ctr_ext_time, range_build=range_build,
                          vol_skew_dir=vol_skew_dir, vol_conc=vol_conc,
                          ib_vol=float(vol.sum()), sign=s, close60=c60)
    F = pd.DataFrame(rows).T.sort_index()
    # width from the trailing-vol-normalised IB range (causal); IB-volume z-score
    F['width']    = days.reindex(F.index)['ib_rv_ratio'].astype(float).values
    lv            = np.log(F['ib_vol'].astype(float))
    F['ib_vol_z'] = ((lv - lv.rolling(60, min_periods=20).mean()) /
                     lv.rolling(60, min_periods=20).std()).values
    return F


# ───────────────────────── autoencoder ─────────────────────────
class AE(nn.Module):
    def __init__(self, n_in, latent):
        super().__init__()
        self.enc = nn.Sequential(nn.Linear(n_in, 24), nn.ReLU(),
                                 nn.Linear(24, 12), nn.ReLU(), nn.Linear(12, latent))
        self.dec = nn.Sequential(nn.Linear(latent, 12), nn.ReLU(),
                                 nn.Linear(12, 24), nn.ReLU(), nn.Linear(24, n_in))

    def forward(self, x):
        z = self.enc(x); return self.dec(z), z


def train_ae(Xtr, n_in, latent, epochs, lr=1e-3, batch=128):
    m = AE(n_in, latent); opt = torch.optim.Adam(m.parameters(), lr=lr)
    lf = nn.MSELoss(); Xt = torch.tensor(Xtr, dtype=torch.float32); n = len(Xt)
    for ep in range(epochs):
        m.train(); perm = torch.randperm(n); tot = 0.0
        for i in range(0, n, batch):
            b = Xt[perm[i:i + batch]]; opt.zero_grad()
            xr, _ = m(b); loss = lf(xr, b); loss.backward(); opt.step()
            tot += loss.item() * len(b)
        if (ep + 1) % 40 == 0 or ep == 0:
            log.info('  epoch %3d/%d  recon-MSE=%.3e', ep + 1, epochs, tot / n)
    return m


def encode(m, X):
    m.eval()
    with torch.no_grad():
        _, z = m(torch.tensor(X, dtype=torch.float32))
    return z.numpy()


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--k', type=int, default=0, help='0 = auto (min BIC); else force k')
    ap.add_argument('--kmax', type=int, default=10, help='max components in BIC/AIC sweep')
    ap.add_argument('--latent', type=int, default=4)
    ap.add_argument('--bins', type=int, default=24)
    ap.add_argument('--epochs', type=int, default=120)
    ap.add_argument('--out', default=os.path.join(ROOT, 'ib_type_ae.png'))
    args = ap.parse_args()

    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    rth = session.get_rth(es)
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet')); days.index = pd.to_datetime(days.index)

    log.info('building IB structural descriptors …')
    F = build_ib_features(rth, days, args.bins)
    F = F.join(days[['day_type', 'open_type', 'close_px']], how='left')
    # forward outcome: post-IB move IN the IB's own direction (continuation>0)
    F['fwd_in_dir'] = F['sign'] * (F['close_px'] - F['close60']) / F['close60']
    F = F.dropna(subset=FEATURES + ['fwd_in_dir'])
    idx = F.index
    X = StandardScaler().fit(F.loc[idx < TEST_FROM, FEATURES]).transform(F[FEATURES]).astype(np.float32)
    log.info('dataset: %d days × %d IB features', *X.shape)

    tr = idx < TEST_FROM
    log.info('training IB autoencoder (latent=%d) …', args.latent)
    model = train_ae(X[tr], X.shape[1], args.latent, args.epochs)
    Z = encode(model, X)

    # ── choose the number of IB types by BIC / AIC (GaussianMixture on the latent) ──
    log.info('BIC/AIC model selection (GMM on latent, k=1..%d) …', args.kmax)
    rows = []
    for kk in range(1, args.kmax + 1):
        gm = GaussianMixture(kk, covariance_type='full', n_init=5,
                             reg_covar=1e-4, random_state=SEED).fit(Z)
        sil = silhouette_score(Z, gm.predict(Z)) if kk > 1 else np.nan
        rows.append((kk, gm.bic(Z), gm.aic(Z), sil))
    sel = pd.DataFrame(rows, columns=['k', 'BIC', 'AIC', 'silhouette'])
    best_bic = int(sel.loc[sel['BIC'].idxmin(), 'k'])
    best_aic = int(sel.loc[sel['AIC'].idxmin(), 'k'])
    log.info('model selection:\n%s', sel.round(1).to_string(index=False))
    log.info('optimal components:  BIC → k=%d   AIC → k=%d', best_bic, best_aic)

    K = args.k if args.k > 0 else best_bic          # BIC drives unless forced
    K = max(2, K)
    log.info('using K=%d IB types (%s)', K, 'forced' if args.k > 0 else 'min-BIC')
    args.k = K
    gm  = GaussianMixture(K, covariance_type='full', n_init=25,
                          reg_covar=1e-4, random_state=SEED).fit(Z)
    lab = gm.predict(Z)
    F['ib_type'] = lab

    # ── characterise each IB type (standardised feature means = signature) ──
    sig = pd.DataFrame(X, index=idx, columns=FEATURES).groupby(lab).mean()
    log.info('IB-type signatures (standardised feature means):\n%s', sig.round(2).to_string())

    # ── forward predictiveness (the payoff), honest OOS ──
    def fwd_stats(mask_period, name):
        rows = []
        for c in range(args.k):
            v = F.loc[mask_period & (F['ib_type'] == c), 'fwd_in_dir'].values * 1e4  # bps
            if len(v) < 10:
                rows.append((c, len(v), np.nan, np.nan, np.nan)); continue
            t_, p_ = stats.ttest_1samp(v, 0.0)
            rows.append((c, len(v), v.mean(), (v > 0).mean() * 100, t_))
        r = pd.DataFrame(rows, columns=['ib_type', 'n', 'fwd_bps', 'cont_WR%', 't'])
        log.info('[%s] forward move in IB direction by type:\n%s', name, r.round(2).to_string(index=False))
        return r

    te = ~tr
    r_all = fwd_stats(pd.Series(True, index=idx), 'FULL 2010-2026')
    r_oos = fwd_stats(pd.Series(te, index=idx),  'OOS 2020-2026')

    # cross-tab with Dalton day_type (context, not ground truth)
    ct = pd.crosstab(F['ib_type'], F['day_type'], normalize='index').mul(100).round(0)
    log.info('IB-type → day_type mix (%%):\n%s', ct.to_string())

    # ───────────────── figure ─────────────────
    fig = plt.figure(figsize=(16, 10)); fig.suptitle(
        'Unsupervised Initial-Balance types (autoencoder) — structure & forward edge',
        fontsize=13, weight='bold')

    # A: signature heatmap
    axA = fig.add_subplot(2, 3, 1)
    im = axA.imshow(sig.values, cmap='RdBu_r', vmin=-1.2, vmax=1.2, aspect='auto')
    axA.set_xticks(range(len(FEATURES))); axA.set_xticklabels(FEATURES, rotation=90, fontsize=7)
    axA.set_yticks(range(args.k)); axA.set_yticklabels([f'IB{c}' for c in range(args.k)])
    axA.set_title('IB-type signatures (σ from mean)')
    for i in range(args.k):
        for j in range(len(FEATURES)):
            axA.text(j, i, f'{sig.values[i,j]:.1f}', ha='center', va='center', fontsize=6)

    # B: latent PCA by IB type
    axB = fig.add_subplot(2, 3, 2)
    P2 = PCA(2, random_state=SEED).fit_transform(Z)
    axB.scatter(P2[:, 0], P2[:, 1], c=lab, s=6, alpha=.5, cmap='tab10')
    axB.set_title(f'IB latent (PCA-2)  silhouette={silhouette_score(Z, lab):.2f}')

    # C: forward edge by type (OOS) with 95% CI
    axC = fig.add_subplot(2, 3, 3)
    xs = np.arange(args.k)
    means = r_oos['fwd_bps'].values
    ns = r_oos['n'].values.astype(float)
    sds = np.array([F.loc[te & (F['ib_type'] == c), 'fwd_in_dir'].std() * 1e4 for c in xs])
    ci = 1.96 * sds / np.sqrt(np.where(ns > 0, ns, np.nan))
    axC.bar(xs, means, yerr=ci, color=['C%d' % c for c in xs], alpha=.8, capsize=3)
    axC.axhline(0, color='k', lw=.8)
    axC.set_xticks(xs); axC.set_xticklabels([f'IB{c}' for c in xs])
    axC.set_title('Forward post-IB move IN IB direction\n(bps, OOS 2020-26, 95% CI)')
    axC.set_ylabel('bps')

    # D: IB-type → day_type
    axD = fig.add_subplot(2, 3, 4)
    im2 = axD.imshow(ct.values, cmap='Blues', vmin=0, vmax=100, aspect='auto')
    axD.set_xticks(range(len(ct.columns))); axD.set_xticklabels(ct.columns, rotation=90, fontsize=7)
    axD.set_yticks(range(args.k)); axD.set_yticklabels([f'IB{c}' for c in range(args.k)])
    axD.set_title('IB-type → day_type (row %)')
    for i in range(ct.shape[0]):
        for j in range(ct.shape[1]):
            axD.text(j, i, f'{ct.values[i,j]:.0f}', ha='center', va='center', fontsize=6,
                     color='white' if ct.values[i, j] > 50 else 'black')

    # E: sizes + continuation WR (OOS)
    axE = fig.add_subplot(2, 3, 5)
    axE.bar(xs, r_oos['cont_WR%'].values, color=['C%d' % c for c in xs], alpha=.8)
    axE.axhline(50, color='k', lw=.8, ls=':')
    axE.set_xticks(xs); axE.set_xticklabels([f'IB{c}\nn={int(n)}' for c, n in zip(xs, r_oos['n'])], fontsize=7)
    axE.set_ylim(40, 60); axE.set_title('Continuation win-rate (OOS)'); axE.set_ylabel('% days fwd>0 in IB dir')

    # F: BIC / AIC model selection curve
    axF = fig.add_subplot(2, 3, 6)
    axF.plot(sel['k'], sel['BIC'], 'o-', label='BIC', color='C3')
    axF.plot(sel['k'], sel['AIC'], 's-', label='AIC', color='C0')
    axF.axvline(best_bic, color='C3', ls=':', lw=1.2)
    axF.axvline(best_aic, color='C0', ls=':', lw=1.2)
    axF.scatter([best_bic], [float(sel.loc[sel.k == best_bic, 'BIC'].iloc[0])], s=120,
                facecolors='none', edgecolors='C3', linewidths=2, zorder=5)
    axF.set_xlabel('number of IB types (k)'); axF.set_ylabel('information criterion')
    axF.set_title(f'Model selection — BIC→k={best_bic}, AIC→k={best_aic}  (used K={args.k})')
    axF.legend(fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(args.out, dpi=110)
    log.info('saved figure → %s', args.out)

    print('\n' + '=' * 70)
    print('SUMMARY — unsupervised Initial-Balance types')
    print('=' * 70)
    print(f'days={len(X)}  k={args.k}  latent={args.latent}')
    print('per-type forward move in IB direction (bps) — FULL vs OOS:')
    m = r_all.merge(r_oos, on='ib_type', suffixes=('_full', '_oos'))
    print(m[['ib_type', 'n_full', 'fwd_bps_full', 't_full', 'n_oos', 'fwd_bps_oos', 't_oos']]
          .round(2).to_string(index=False))
    print('=' * 70)


if __name__ == '__main__':
    main()
