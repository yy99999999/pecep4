"""
open_type_autoencoder.py — UNSUPERVISED discovery of Dalton OPENING types via a
PyTorch autoencoder on the opening price PATH (same principle as day_shape_autoencoder).

WHY A PATH, NOT A PROFILE
  A day's *shape* is a volume-by-price profile. An *opening type* is a TRAJECTORY:
    · open_drive           — one-directional thrust from the open, no retrace
    · open_test_drive      — probe one way, reverse, then drive the other
    · open_rejection_rev   — push one way, get rejected, reverse back through the open
    · open_auction         — rotational / balanced, wanders around the open
  So the input is the first-60-min price path (minute close − open), made
  DIRECTION-INVARIANT (canonicalised by the sign of the early move, because a drive
  up and a drive down are the same *type*) and scaled by the opening range so drives
  and auctions are comparable across days.

PIPELINE  (mirrors the day-shape model)
  1. build canonical opening-path vectors (len = WINDOW minutes).
  2. train a dense autoencoder path → latent → path (train years only).
  3. UNSUPERVISED: KMeans over the latent → opening archetypes.
  4. measure how well the archetypes rediscover the rule-based open_type
     (NMI / ARI + crosstab + majority mapping).  Purely unsupervised — labels are
     used ONLY for scoring, never for fitting.
  5. save a 6-panel figure (archetype mean paths / latent PCA / crosstab / recon).

USAGE
  ./vbt-env/bin/python open_type_autoencoder.py [--window 60] [--latent 8] [--k 4] [--epochs 80]

Reads cache/es_continuous.parquet + cache/es_days.parquet. Characterisation only.
"""
import os, argparse, logging
import numpy as np
import pandas as pd

import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import session               # DST-aware cash session (indices/session.py)

import torch
import torch.nn as nn
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (normalized_mutual_info_score, adjusted_rand_score,
                             silhouette_score)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # indices/ root
HERE      = os.path.dirname(os.path.abspath(__file__))   # this script's folder
CACHE     = os.path.join(ROOT, 'cache')
SEED      = 7
TEST_FROM = pd.Timestamp('2020-01-01')

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('open-ae')
np.random.seed(SEED); torch.manual_seed(SEED)


# ───────────────────────── data → opening paths ─────────────────────────
def load_rth():
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    return session.get_rth(es)


def build_open_paths(rth, window, sign_at=10):
    """date → canonical range-scaled opening path (len window) + sign used.
    path(t) = sign * (close_t − open) / opening_range ; sign = direction of the
    first `sign_at` minutes (→ drive-up and drive-down collapse to one type).
    Returns (paths_df, sign_series) — sign lets us canonicalise the context too."""
    rth = rth.copy()
    rth['date'] = rth.index.normalize()
    out, signs = {}, {}
    for date, g in rth.groupby('date'):
        if len(g) < window:
            continue
        g = g.iloc[:window]
        op   = g['open'].iloc[0]
        path = g['close'].values - op                      # level vs open
        rng  = g['high'].iloc[:window].max() - g['low'].iloc[:window].min()
        if rng <= 0:
            continue
        s = np.sign(path[min(sign_at, window - 1)])
        if s == 0:
            s = np.sign(path[-1]) or 1.0
        out[date]   = (s * path) / rng                     # direction-invariant, scaled
        signs[date] = s
    return pd.DataFrame(out).T.sort_index(), pd.Series(signs).sort_index()


# open_location ordinal along the below→above-prior-value axis (signed)
LOC_ORD = {'outside_range_below': -3, 'outside_va_below_poc': -2, 'inside_va_below_poc': -1,
           'inside_va_above_poc':  1, 'outside_va_above_poc':  2, 'outside_range_above':  3}


def build_context(days, sign, idx):
    """Canonical open-location context, aligned to idx.
    loc_ord is flipped by the early-move sign → 'extension in the direction of the
    move' vs 'against it' (this is the prior-value info a bare path cannot see)."""
    d = days.reindex(idx)
    s = sign.reindex(idx).values
    loc = d['open_location'].map(LOC_ORD).values.astype(float)
    loc_canon = s * loc                                    # signed by move direction
    poc_dist  = d['open_poc_dist'].values.astype(float)    # unsigned extension magnitude
    ctx = np.column_stack([loc_canon, poc_dist])
    return np.nan_to_num(ctx, nan=0.0)


# ───────────────────────── autoencoder ─────────────────────────
class AE(nn.Module):
    def __init__(self, n_in, latent):
        super().__init__()
        self.enc = nn.Sequential(nn.Linear(n_in, 64), nn.ReLU(),
                                 nn.Linear(64, 32), nn.ReLU(),
                                 nn.Linear(32, latent))
        self.dec = nn.Sequential(nn.Linear(latent, 32), nn.ReLU(),
                                 nn.Linear(32, 64), nn.ReLU(),
                                 nn.Linear(64, n_in))       # linear output (path, not a distribution)

    def forward(self, x):
        z = self.enc(x)
        return self.dec(z), z


def train_ae(Xtr, n_in, latent, epochs, lr=1e-3, batch=128):
    model = AE(n_in, latent); opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossf = nn.MSELoss(); Xt = torch.tensor(Xtr, dtype=torch.float32); n = len(Xt)
    for ep in range(epochs):
        model.train(); perm = torch.randperm(n); tot = 0.0
        for i in range(0, n, batch):
            b = Xt[perm[i:i + batch]]; opt.zero_grad()
            xr, _ = model(b); loss = lossf(xr, b); loss.backward(); opt.step()
            tot += loss.item() * len(b)
        if (ep + 1) % 20 == 0 or ep == 0:
            log.info('  epoch %3d/%d  recon-MSE=%.3e', ep + 1, epochs, tot / n)
    return model


def encode(model, X):
    model.eval()
    with torch.no_grad():
        _, z = model(torch.tensor(X, dtype=torch.float32))
    return z.numpy()


def recon(model, X):
    model.eval()
    with torch.no_grad():
        xr, _ = model(torch.tensor(X, dtype=torch.float32))
    return xr.numpy()


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--window', type=int, default=60, help='opening minutes')
    ap.add_argument('--latent', type=int, default=8)
    ap.add_argument('--k', type=int, default=4, help='archetypes (Dalton has 4 open types)')
    ap.add_argument('--epochs', type=int, default=80)
    ap.add_argument('--out', default=os.path.join(HERE, 'open_type_ae.png'))
    args = ap.parse_args()

    log.info('loading RTH bars …')
    rth  = load_rth()
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet'))
    days.index = pd.to_datetime(days.index)

    log.info('building canonical opening paths (window=%dm) …', args.window)
    paths, sign = build_open_paths(rth, args.window)

    common = paths.index.intersection(days.index)
    paths  = paths.loc[common]
    lbl    = days.loc[common, 'open_type'].astype(str)
    keep   = lbl.notna() & (lbl != 'nan')
    paths, lbl = paths.loc[keep], lbl.loc[keep]
    Xpath = paths.values.astype(np.float32)                # raw canonical path (for plots)
    idx = paths.index
    labels_true = lbl.values
    open_types  = sorted(lbl.unique())
    log.info('dataset: %d days × %d min  | rule open_type: %s',
             *Xpath.shape, dict(lbl.value_counts()))

    # context: canonical open_location (+ POC-distance) — the prior-value info
    ctx = build_context(days, sign, idx)
    log.info('added open_location context: loc_ord∈[-3,3] canonical + open_poc_dist')

    tr = idx < TEST_FROM
    log.info('AE trained on %d days (≤2019); clustering scored on all', tr.sum())

    # 1) path autoencoder on the range-scaled path (representation of the TRAJECTORY)
    log.info('training opening-path autoencoder (latent=%d) …', args.latent)
    model = train_ae(Xpath[tr], args.window, args.latent, args.epochs)
    Zpath = encode(model, Xpath)
    mse   = float(((recon(model, Xpath) - Xpath) ** 2).mean())

    # 2) clustering feature sets: latent alone  vs  latent + open_location context.
    #    open_location is a SEPARATE, orthogonal axis (where the open sat vs prior
    #    value) — fusing it makes a 2-axis taxonomy (trajectory × location).
    CTX_W = 1.5
    zZ = StandardScaler().fit(Zpath[tr]).transform(Zpath)
    zC = StandardScaler().fit(ctx[tr]).transform(ctx)
    F_path = zZ
    F_loc  = np.hstack([zZ, zC * CTX_W])

    def cluster(F, tag):
        a = KMeans(n_clusters=args.k, n_init=20, random_state=SEED).fit_predict(F)
        nmi, ari = (normalized_mutual_info_score(labels_true, a),
                    adjusted_rand_score(labels_true, a))
        log.info('[%s] NMI(vs open_type)=%.3f  ARI=%.3f', tag, nmi, ari)
        return a, nmi, ari

    arch_raw = KMeans(n_clusters=args.k, n_init=20, random_state=SEED).fit_predict(Xpath)
    nmi_raw  = normalized_mutual_info_score(labels_true, arch_raw)
    log.info('[raw-path (no AE)] NMI=%.3f', nmi_raw)
    _,    nmi_path, _   = cluster(F_path, 'path-only AE')
    arch, nmi, ari      = cluster(F_loc,  'path + open_location')

    X   = Xpath                                            # plots use the raw path
    Z   = F_loc
    sil = silhouette_score(F_loc, arch)

    cross = pd.crosstab(pd.Series(arch, name='archetype'),
                        pd.Series(labels_true, name='open_type'),
                        normalize='index').mul(100).round(1)
    majmap = cross.idxmax(axis=1).to_dict()
    # second axis: what open_LOCATION does each archetype carry?
    loc_lbl = days.reindex(idx)['open_location'].astype(str).values
    cross_loc = pd.crosstab(pd.Series(arch, name='archetype'),
                            pd.Series(loc_lbl, name='open_location'),
                            normalize='index').mul(100).round(0)
    log.info('archetype → open_location mix (%%):\n%s', cross_loc.to_string())
    log.info('silhouette=%.3f  NMI(vs open_type)=%.3f  ARI=%.3f  | raw-path NMI=%.3f',
             sil, nmi, ari, nmi_raw)
    log.info('archetype → open_type mix (%%):\n%s', cross.to_string())
    log.info('archetype → majority open_type: %s',
             {a: f'{v} ({int((arch==a).sum())}d)' for a, v in majmap.items()})

    # ───────────────── figure ─────────────────
    fig = plt.figure(figsize=(16, 10)); fig.suptitle(
        'Unsupervised Dalton opening-type autoencoder — opening-path archetypes',
        fontsize=13, weight='bold')
    tmin = np.arange(args.window)

    # A: archetype mean canonical path
    axA = fig.add_subplot(2, 3, 1)
    for c in range(args.k):
        axA.plot(tmin, X[arch == c].mean(0),
                 label=f'A{c}≈{majmap[c]} (n={int((arch==c).sum())})')
    axA.axhline(0, color='k', lw=.6, ls=':')
    axA.set_title('Opening archetypes (mean canonical path)')
    axA.set_xlabel('minutes from open'); axA.set_ylabel('signed move / opening-range')
    axA.legend(fontsize=7)

    # B: latent PCA by rule open_type
    axB = fig.add_subplot(2, 3, 2)
    P2 = PCA(2, random_state=SEED).fit_transform(Z)
    for ot in open_types:
        m = labels_true == ot
        axB.scatter(P2[m, 0], P2[m, 1], s=6, alpha=.4, label=ot)
    axB.set_title(f'Latent (PCA-2) by rule open_type\nNMI={nmi:.3f} ARI={ari:.3f}')
    axB.legend(fontsize=6)

    # C: latent PCA by archetype
    axC = fig.add_subplot(2, 3, 3)
    axC.scatter(P2[:, 0], P2[:, 1], c=arch, s=6, alpha=.5, cmap='tab10')
    axC.set_title(f'Latent (PCA-2) by archetype  silhouette={sil:.2f}')

    # D: crosstab heatmap
    axD = fig.add_subplot(2, 3, 4)
    im = axD.imshow(cross.values, cmap='Blues', vmin=0, vmax=100, aspect='auto')
    axD.set_xticks(range(len(cross.columns))); axD.set_xticklabels(cross.columns, rotation=90, fontsize=7)
    axD.set_yticks(range(len(cross.index)));   axD.set_yticklabels([f'A{i}' for i in cross.index], fontsize=8)
    axD.set_title('archetype → open_type  (row %)')
    for i in range(cross.shape[0]):
        for j in range(cross.shape[1]):
            axD.text(j, i, f'{cross.values[i,j]:.0f}', ha='center', va='center',
                     fontsize=7, color='white' if cross.values[i, j] > 50 else 'black')

    # E: example paths per archetype (thin) + mean (thick)
    axE = fig.add_subplot(2, 3, 5)
    rng = np.random.RandomState(SEED)
    for c in range(args.k):
        members = np.where(arch == c)[0]
        for e in rng.choice(members, min(15, len(members)), replace=False):
            axE.plot(tmin, X[e], color=f'C{c}', alpha=.12, lw=.7)
        axE.plot(tmin, X[arch == c].mean(0), color=f'C{c}', lw=2.2)
    axE.axhline(0, color='k', lw=.6, ls=':')
    axE.set_title('Sample paths by archetype'); axE.set_xlabel('minutes from open')

    # F: reconstruction examples
    axF = fig.add_subplot(2, 3, 6)
    ex = rng.choice(len(X), 3, replace=False); R = recon(model, X[ex])
    for k, e in enumerate(ex):
        axF.plot(tmin, X[e], color=f'C{k}', lw=1.6, label='real' if k == 0 else None)
        axF.plot(tmin, R[k], color=f'C{k}', ls='--', lw=1.2, label='recon' if k == 0 else None)
    axF.axhline(0, color='k', lw=.6, ls=':')
    axF.set_title(f'Reconstruction  MSE={mse:.2e}'); axF.legend(fontsize=7)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(args.out, dpi=110)
    log.info('saved figure → %s', args.out)

    print('\n' + '=' * 68)
    print('SUMMARY — unsupervised opening types')
    print('=' * 68)
    print(f'days={len(X)}  window={args.window}m  latent={args.latent}  archetypes={args.k}')
    print(f'AE recon MSE={mse:.2e}   silhouette={sil:.3f}')
    print('alignment with rule open_type (NMI) — effect of adding open_location:')
    print(f'  raw path (no AE)        : {nmi_raw:.3f}')
    print(f'  path-only AE            : {nmi_path:.3f}')
    print(f'  path + open_location AE : {nmi:.3f}   (ARI={ari:.3f})')
    print('archetype → majority open_type:')
    for a in sorted(majmap):
        print(f'  A{a}: {majmap[a]:24s} n={int((arch==a).sum())}  purity={cross.loc[a].max():.0f}%')
    print('=' * 68)


if __name__ == '__main__':
    main()
