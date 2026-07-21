"""
day_shape_autoencoder.py — PyTorch autoencoder for the ES daily Market-Profile SHAPE,
with unsupervised archetype discovery + a supervised Dalton day-type classifier.

WHAT IT DOES
  1. Build a per-day volume-by-price profile from RTH 1-min bars, range-normalised to
     [0,1] and volume-normalised to sum=1  → a pure SHAPE vector (level/size removed).
     Captures the Dalton forms: b / P / D (normal) / double-distribution / trend.
  2. Train a dense autoencoder (profile → latent → profile) on the TRAIN years only.
  3. Unsupervised: KMeans over the latent → shape archetypes; show the mean real
     profile of each archetype and cross-tab it against the rule-based day_type.
  4. Supervised: classify day_type from the latent embedding, honest TIME split
     (train ≤ 2019, test ≥ 2020). Baselines: majority class + logistic on the RAW
     profile. Tells us how much of "day_type" is actually shape.
  5. CAUSAL detector: repeat the classifier using ONLY the first-60-min (IB) profile
     → an early, non-circular "which day-type is forming" forecast.
  6. Save a 6-panel figure (archetypes / latent PCA / confusions / recon) + print metrics.

USAGE
  ./vbt-env/bin/python day_shape_autoencoder.py
  ./vbt-env/bin/python day_shape_autoencoder.py --bins 64 --latent 8 --epochs 80 --k 6

Data-independent: reads cache/es_continuous.parquet + cache/es_days.parquet (both exist).
Research/characterisation only — Market Profile carries no proven directional edge here.
"""
import os, argparse, logging
import numpy as np
import pandas as pd

import torch
import torch.nn as nn
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT      = os.path.dirname(os.path.abspath(__file__))
CACHE     = os.path.join(ROOT, 'cache')
RTH_START = 14 * 60 + 30
RTH_END   = 21 * 60 + 0
TICK      = 0.25
SEED      = 7
TEST_FROM = pd.Timestamp('2020-01-01')   # honest out-of-sample cutoff

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('ae')
np.random.seed(SEED); torch.manual_seed(SEED)


# ───────────────────────── data → shape profiles ─────────────────────────
def load_rth():
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    t = es.index.hour * 60 + es.index.minute
    return es[(t >= RTH_START) & (t < RTH_END)].copy()


def build_profiles(rth, n_bins, ib_minutes=None):
    """date → shape vector (len n_bins, range-normalised, sums to 1).
    ib_minutes: if set, use only the first N minutes (causal IB profile)."""
    rth = rth.copy()
    rth['date'] = rth.index.normalize()
    out = {}
    for date, g in rth.groupby('date'):
        if ib_minutes is not None:
            g = g.iloc[:ib_minutes]
        if len(g) < 30:
            continue
        lo, hi = g['low'].min(), g['high'].max()
        if hi - lo < TICK:
            continue
        tp  = (g['high'].values + g['low'].values + g['close'].values) / 3.0
        rel = (tp - lo) / (hi - lo)
        idx = np.clip((rel * n_bins).astype(int), 0, n_bins - 1)
        prof = np.bincount(idx, weights=g['volume'].values.astype(float), minlength=n_bins)
        s = prof.sum()
        if s <= 0:
            continue
        out[date] = prof / s
    return pd.DataFrame(out).T.sort_index()   # index=date, cols=0..n_bins-1


# ───────────────────────── autoencoder ─────────────────────────
class AE(nn.Module):
    def __init__(self, n_in, latent):
        super().__init__()
        self.enc = nn.Sequential(
            nn.Linear(n_in, 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(),
            nn.Linear(32, latent))
        self.dec = nn.Sequential(
            nn.Linear(latent, 32), nn.ReLU(),
            nn.Linear(32, 64), nn.ReLU(),
            nn.Linear(64, n_in), nn.Softmax(dim=1))   # output is a valid distribution

    def forward(self, x):
        z = self.enc(x)
        return self.dec(z), z


def train_ae(Xtr, n_in, latent, epochs, lr=1e-3, batch=128):
    model = AE(n_in, latent)
    opt   = torch.optim.Adam(model.parameters(), lr=lr)
    lossf = nn.MSELoss()
    Xt    = torch.tensor(Xtr, dtype=torch.float32)
    n     = len(Xt)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, batch):
            b = Xt[perm[i:i + batch]]
            opt.zero_grad()
            xr, _ = model(b)
            loss = lossf(xr, b)
            loss.backward(); opt.step()
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


# ───────────────────────── classifier eval ─────────────────────────
def clf_report(Ztr, ytr, Zte, yte, classes, tag):
    sc = StandardScaler().fit(Ztr)
    clf = LogisticRegression(max_iter=2000, class_weight='balanced', C=1.0)
    clf.fit(sc.transform(Ztr), ytr)
    pred = clf.predict(sc.transform(Zte))
    acc  = accuracy_score(yte, pred)
    f1m  = f1_score(yte, pred, average='macro', labels=classes, zero_division=0)
    maj  = pd.Series(ytr).value_counts().idxmax()
    base = (yte == maj).mean()
    log.info('[%s] OOS acc=%.3f  macro-F1=%.3f  (majority-class baseline=%.3f)',
             tag, acc, f1m, base)
    return pred, acc, f1m, base


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bins', type=int, default=64)
    ap.add_argument('--latent', type=int, default=8)
    ap.add_argument('--epochs', type=int, default=80)
    ap.add_argument('--k', type=int, default=6, help='archetype clusters')
    ap.add_argument('--out', default=os.path.join(ROOT, 'day_shape_ae.png'))
    args = ap.parse_args()

    log.info('loading RTH bars …')
    rth = load_rth()
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet'))
    days.index = pd.to_datetime(days.index)

    log.info('building full-day shape profiles (bins=%d) …', args.bins)
    prof = build_profiles(rth, args.bins)
    log.info('building causal IB-60m shape profiles …')
    prof_ib = build_profiles(rth, args.bins, ib_minutes=60)

    # align profiles ↔ labels
    common = prof.index.intersection(days.index)
    prof   = prof.loc[common]
    y      = days.loc[common, 'day_type'].astype(str)
    keep   = y.notna() & (y != 'nan')
    prof, y = prof.loc[keep], y.loc[keep]
    X   = prof.values.astype(np.float32)
    idx = prof.index
    log.info('dataset: %d days × %d bins  | day_type classes: %s',
             *X.shape, dict(y.value_counts()))

    # honest time split
    tr = idx < TEST_FROM
    te = ~tr
    Xtr, Xte = X[tr], X[te]
    ytr, yte = y[tr].values, y[te].values
    classes = sorted(y.unique())
    log.info('train %d (≤2019)  |  test %d (≥2020)', tr.sum(), te.sum())

    # 1) autoencoder on TRAIN shapes only
    log.info('training autoencoder  (latent=%d, epochs=%d) …', args.latent, args.epochs)
    model = train_ae(Xtr, args.bins, args.latent, args.epochs)
    Ztr, Zte = encode(model, Xtr), encode(model, Xte)
    Zall = encode(model, X)
    mse_tr = float(((recon(model, Xtr) - Xtr) ** 2).mean())
    mse_te = float(((recon(model, Xte) - Xte) ** 2).mean())
    log.info('recon MSE  train=%.3e  test=%.3e', mse_tr, mse_te)

    # 2) archetypes (unsupervised) on latent
    km = KMeans(n_clusters=args.k, n_init=10, random_state=SEED).fit(Ztr)
    arch = km.predict(Zall)
    cross = pd.crosstab(pd.Series(arch, index=idx, name='archetype'),
                        y, normalize='index').mul(100).round(1)
    log.info('archetype → day_type mix (%%):\n%s', cross.to_string())

    # 3) supervised: latent → day_type (OOS)
    pred_lat, acc_lat, f1_lat, base = clf_report(Ztr, ytr, Zte, yte, classes,
                                                 'latent(full-day)→day_type[6-class]')
    # baseline: logistic on RAW profile
    _, acc_raw, f1_raw, _ = clf_report(Xtr, ytr, Xte, yte, classes,
                                       'raw-profile→day_type[6-class]')

    # 3b) fair test on the 3 dominant SHAPE classes (96% of days; the rare
    #     trend/normal/nontrend have too few samples for any shape model)
    MAJORS = ['double_distribution', 'normal_variation', 'neutral']
    mj  = np.isin(y.values, MAJORS)
    mtr, mte = mj & tr, mj & te
    pred3, acc3, f13, base3 = clf_report(Zall[mtr], y.values[mtr], Zall[mte], y.values[mte],
                                         MAJORS, 'latent(full-day)→day_type[3-major]')
    _, acc3r, f13r, _ = clf_report(X[mtr], y.values[mtr], X[mte], y.values[mte],
                                   MAJORS, 'raw-profile→day_type[3-major]')

    # 4) CAUSAL: IB-only latent → full-day day_type
    pib = prof_ib.reindex(idx).dropna()
    ci  = pib.index
    Xib = pib.values.astype(np.float32)
    ytr_ib = y.loc[ci][ci < TEST_FROM].values
    yte_ib = y.loc[ci][ci >= TEST_FROM].values
    model_ib = train_ae(Xib[ci < TEST_FROM], args.bins, args.latent, args.epochs)
    Zib_tr = encode(model_ib, Xib[ci < TEST_FROM])
    Zib_te = encode(model_ib, Xib[ci >= TEST_FROM])
    pred_ib, acc_ib, f1_ib, base_ib = clf_report(Zib_tr, ytr_ib, Zib_te, yte_ib,
                                                 classes, 'latent(IB-60m)→day_type')

    # ───────────────── figure ─────────────────
    fig = plt.figure(figsize=(16, 10)); fig.suptitle(
        'ES daily Market-Profile shape autoencoder — archetypes & day-type detection',
        fontsize=13, weight='bold')
    rel = np.linspace(0, 1, args.bins)

    # panel A: archetype mean profiles
    axA = fig.add_subplot(2, 3, 1)
    for c in range(args.k):
        axA.plot(km.cluster_centers_[c] if False else X[arch == c].mean(0), rel,
                 label=f'A{c} (n={int((arch==c).sum())})')
    axA.set_title('Shape archetypes (mean real profile)')
    axA.set_xlabel('vol share'); axA.set_ylabel('relative price (0=low,1=high)')
    axA.legend(fontsize=7)

    # panel B: latent PCA coloured by day_type
    axB = fig.add_subplot(2, 3, 2)
    P2 = PCA(2, random_state=SEED).fit_transform(Zall)
    for cl in classes:
        m = (y.values == cl)
        axB.scatter(P2[m, 0], P2[m, 1], s=6, alpha=.4, label=cl)
    axB.set_title('Latent space (PCA-2) by day_type'); axB.legend(fontsize=6)

    # panel C: latent PCA coloured by archetype
    axC = fig.add_subplot(2, 3, 3)
    sc = axC.scatter(P2[:, 0], P2[:, 1], c=arch, s=6, alpha=.5, cmap='tab10')
    axC.set_title('Latent space (PCA-2) by archetype')

    # panel D: confusion latent full-day
    def conf_panel(ax, yt, yp, title):
        cm = confusion_matrix(yt, yp, labels=classes, normalize='true')
        im = ax.imshow(cm, cmap='Blues', vmin=0, vmax=1)
        ax.set_xticks(range(len(classes))); ax.set_yticks(range(len(classes)))
        ax.set_xticklabels(classes, rotation=90, fontsize=6)
        ax.set_yticklabels(classes, fontsize=6)
        ax.set_title(title, fontsize=9); ax.set_ylabel('true'); ax.set_xlabel('pred')
        for i in range(len(classes)):
            for j in range(len(classes)):
                ax.text(j, i, f'{cm[i,j]:.2f}', ha='center', va='center',
                        fontsize=5, color='white' if cm[i, j] > .5 else 'black')
    conf_panel(fig.add_subplot(2, 3, 4), yte, pred_lat,
               f'Confusion: latent full-day\nacc={acc_lat:.2f} F1={f1_lat:.2f} base={base:.2f}')
    conf_panel(fig.add_subplot(2, 3, 5), yte_ib, pred_ib,
               f'Confusion: causal IB-60m\nacc={acc_ib:.2f} F1={f1_ib:.2f} base={base_ib:.2f}')

    # panel F: reconstruction examples
    axF = fig.add_subplot(2, 3, 6)
    ex = np.random.RandomState(SEED).choice(len(Xte), 3, replace=False)
    R = recon(model, Xte[ex])
    for k, e in enumerate(ex):
        axF.plot(Xte[e], rel, color=f'C{k}', lw=1.5, label='real' if k == 0 else None)
        axF.plot(R[k], rel, color=f'C{k}', ls='--', lw=1.2, label='recon' if k == 0 else None)
    axF.set_title(f'Reconstruction (test)  MSE={mse_te:.2e}'); axF.legend(fontsize=7)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(args.out, dpi=110)
    log.info('saved figure → %s', args.out)

    # summary
    print('\n' + '=' * 68)
    print('SUMMARY')
    print('=' * 68)
    print(f'days={len(X)}  bins={args.bins}  latent={args.latent}  archetypes={args.k}')
    print(f'AE recon MSE  train={mse_tr:.2e}  test={mse_te:.2e}')
    print('-- 6-class (all day_types, severe imbalance) --')
    print(f'  full-day shape (latent) : acc={acc_lat:.3f}  F1={f1_lat:.3f}')
    print(f'  full-day shape (raw)    : acc={acc_raw:.3f}  F1={f1_raw:.3f}')
    print(f'  causal IB-60m (latent)  : acc={acc_ib:.3f}  F1={f1_ib:.3f}')
    print(f'  majority baseline       : acc={base:.3f}')
    print('-- 3 dominant shape classes (double_dist / normal_var / neutral, 96% of days) --')
    print(f'  full-day shape (latent) : acc={acc3:.3f}  F1={f13:.3f}')
    print(f'  full-day shape (raw)    : acc={acc3r:.3f}  F1={f13r:.3f}')
    print(f'  majority baseline       : acc={base3:.3f}')
    print('=' * 68)


if __name__ == '__main__':
    main()
