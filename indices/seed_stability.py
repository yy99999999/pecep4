"""
seed_stability.py — are our unsupervised taxonomies reproducible, or artefacts of seed=7?

WHY
  Sinha et al. (EBioMedicine 2021) compared nine clustering algorithms on three ARDS
  RCTs and found that re-running with a different random seed frequently destroyed the
  finding: significant results survived in 1-3 of 10 runs for several algorithms, and the
  Adjusted Rand Index between runs was low — i.e. the CLUSTER MEMBERSHIP itself moved.
  Every taxonomy in this track was built with a single fixed seed (7) and never tested.

TWO LAYERS, because we have a learned representation upstream of the clustering
  A. clustering seed only : fix the autoencoder, vary the GMM seed
  B. full pipeline seed   : retrain the autoencoder too — the latent itself is random-init
  The paper only tests A; B is the honest test for us.

AND THE POINT THAT ACTUALLY MATTERS (the paper's real lesson)
  Not "do the labels move" but "does the CONCLUSION survive". So we also re-estimate the
  headline result — IB structure -> post-IB volatility — under every seed.
  Note in advance: that headline uses the RAW features and the continuous latent, never
  the discrete clusters, so if the "continuous beats discrete" lesson is right it should
  be far more seed-robust than the archetypes are.

READING THE ARI
  1.0 = identical partitions, 0.0 = no better than chance agreement.
  Sinha et al. treat persistently low ARI as grounds to distrust the clusters.

USAGE  ./vbt-env/bin/python seed_stability.py [--seeds 10]
"""
import os, argparse, importlib.util, logging
import numpy as np
import pandas as pd

import session
import torch
from sklearn.preprocessing import StandardScaler
from sklearn.mixture import GaussianMixture
from sklearn.linear_model import Ridge
from sklearn.metrics import adjusted_rand_score, r2_score
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache')
TEST_FROM = pd.Timestamp('2020-01-01')
NBINS, WINDOW, KMAX = 64, 60, 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('seed')


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def bic_k(Z, kmax=KMAX, seed=7):
    best, bk = np.inf, 2
    for k in range(1, kmax + 1):
        b = GaussianMixture(k, covariance_type='full', n_init=5, reg_covar=1e-4,
                            random_state=seed).fit(Z).bic(Z)
        if b < best:
            best, bk = b, k
    return max(2, bk)


def pairwise_ari(labels):
    v = [adjusted_rand_score(labels[i], labels[j])
         for i in range(len(labels)) for j in range(i + 1, len(labels))]
    return float(np.mean(v)), float(np.min(v)), float(np.max(v))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--seeds', type=int, default=10)
    args = ap.parse_args()
    SEEDS = list(range(1, args.seeds + 1))

    shape_m = _load('shape_ae', os.path.join(ROOT, 'day_shape_autoencoder.py'))
    open_m  = _load('open_ae',  os.path.join(ROOT, 'open_type_autoencoder.py'))
    ib_m    = _load('ib_ae',    os.path.join(ROOT, 'ib_type_autoencoder.py'))

    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    rth = session.get_rth(es)
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet')); days.index = pd.to_datetime(days.index)

    # ── deterministic inputs (no randomness before the AE) ──
    log.info('building deterministic inputs …')
    prof  = shape_m.build_profiles(rth, NBINS)
    paths, _ = open_m.build_open_paths(rth, WINDOW)
    Fib = ib_m.build_ib_features(rth, days, bins=24).dropna(subset=ib_m.FEATURES)
    tri = Fib.index < TEST_FROM
    Xib = StandardScaler().fit(Fib.loc[tri, ib_m.FEATURES]).transform(Fib[ib_m.FEATURES]).astype(np.float32)

    TAX = {
        'day-shape': dict(X=prof.values.astype(np.float32), idx=prof.index, mod=shape_m,
                          n_in=NBINS, latent=8, epochs=80),
        'opening':   dict(X=paths.values.astype(np.float32), idx=paths.index, mod=open_m,
                          n_in=WINDOW, latent=8, epochs=80),
        'IB':        dict(X=Xib, idx=Fib.index, mod=ib_m,
                          n_in=Xib.shape[1], latent=4, epochs=120),
    }

    rows = []
    ib_latents = {}
    for name, cfg in TAX.items():
        X, idx, mod = cfg['X'], cfg['idx'], cfg['mod']
        tr = idx < TEST_FROM

        # ── A: fix the AE, vary only the clustering seed ──
        torch.manual_seed(7); np.random.seed(7)
        ae = mod.train_ae(X[tr], cfg['n_in'], cfg['latent'], cfg['epochs'])
        Z0 = mod.encode(ae, X)
        k0 = bic_k(Z0[tr])
        labs_A = [GaussianMixture(k0, covariance_type='full', n_init=25, reg_covar=1e-4,
                                  random_state=s).fit(Z0[tr]).predict(Z0) for s in SEEDS]
        ariA = pairwise_ari(labs_A)

        # ── B: retrain the AE per seed too (the honest test) ──
        labs_B, ks = [], []
        for s in SEEDS:
            torch.manual_seed(s); np.random.seed(s)
            ae_s = mod.train_ae(X[tr], cfg['n_in'], cfg['latent'], cfg['epochs'])
            Zs = mod.encode(ae_s, X)
            ks_ = bic_k(Zs[tr], seed=s)
            ks.append(ks_)
            labs_B.append(GaussianMixture(ks_, covariance_type='full', n_init=25,
                                          reg_covar=1e-4, random_state=s).fit(Zs[tr]).predict(Zs))
            if name == 'IB':
                ib_latents[s] = pd.DataFrame(Zs, index=idx)
        # ARI across B only meaningful where k matches; report anyway (ARI handles differing k)
        ariB = pairwise_ari(labs_B)

        log.info('[%-9s] k(seed7)=%d  k across seeds %s', name, k0, sorted(set(ks)))
        log.info('    A clustering-seed only : ARI mean %.3f  (min %.3f, max %.3f)', *ariA)
        log.info('    B full pipeline        : ARI mean %.3f  (min %.3f, max %.3f)', *ariB)
        rows.append(dict(taxonomy=name, k_seed7=k0, k_modal=int(pd.Series(ks).mode()[0]),
                         k_range=f'{min(ks)}-{max(ks)}', ari_clust=ariA[0], ari_full=ariB[0],
                         ari_full_min=ariB[1]))

    S = pd.DataFrame(rows).set_index('taxonomy')

    # ── C: does the HEADLINE CONCLUSION survive? ──
    log.info('══ C · headline result (IB structure → post-IB vol) under every seed ══')
    rth2 = rth.copy(); rth2['date'] = rth2.index.normalize()
    orow = {}
    for date, g in rth2.groupby('date'):
        if len(g) < 120:
            continue
        post = g.iloc[60:]
        lr = np.diff(np.log(post['close'].values))
        if len(lr) < 30:
            continue
        orow[date] = float(np.std(lr) * np.sqrt(len(lr)))
    post_rv = pd.Series(orow)
    dvol_prev = (days['rv20'].shift(1) / np.sqrt(252)).replace(0, np.nan)
    y = np.log(post_rv / dvol_prev.reindex(post_rv.index)).dropna()

    vix = pd.read_parquet(os.path.join(CACHE, 'vix_daily.parquet')); vix.index = pd.to_datetime(vix.index)
    v = vix['vix_close'].reindex(days.index).ffill()
    T = pd.DataFrame({'log_rv20_prev': np.log(days['rv20'].shift(1).replace(0, np.nan)),
                      'log_vix_prev': np.log(v.shift(1)),
                      'vix_chg5': v.shift(1) - v.shift(6)})

    def r2_for(block, tag):
        D = pd.concat([y.rename('y'), block, T], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
        tr_, te_ = D.index < TEST_FROM, D.index >= TEST_FROM
        cols = [c for c in D.columns if c != 'y']
        Xs = StandardScaler().fit(D.loc[tr_, cols]).transform(D[cols])
        p = Ridge(alpha=10.0).fit(Xs[tr_], D['y'][tr_]).predict(Xs[te_])
        return r2_score(D['y'][te_], p)

    raw_r2 = r2_for(Fib[ib_m.FEATURES], 'raw')          # deterministic — no AE involved
    lat_r2 = [r2_for(ib_latents[s].add_prefix('z'), f'latent s{s}') for s in SEEDS]
    log.info('  RAW IB features (no AE, deterministic): R² = %.4f', raw_r2)
    log.info('  IB LATENT across %d seeds            : mean %.4f  sd %.4f  min %.4f  max %.4f',
             len(SEEDS), np.mean(lat_r2), np.std(lat_r2), np.min(lat_r2), np.max(lat_r2))

    # ── figure ──
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
    fig.suptitle('Seed stability — are the taxonomies reproducible? (method after Sinha et al. 2021)',
                 fontsize=12, weight='bold')
    x = np.arange(len(S)); w = .35
    ax[0].bar(x - w/2, S['ari_clust'], w, label='clustering seed only', alpha=.85)
    ax[0].bar(x + w/2, S['ari_full'], w, label='full pipeline (AE too)', alpha=.85, color='C3')
    ax[0].axhline(1.0, color='k', ls=':', lw=1)
    ax[0].set_xticks(x); ax[0].set_xticklabels(S.index); ax[0].set_ylim(0, 1.05)
    ax[0].set_ylabel('mean pairwise ARI'); ax[0].legend(fontsize=8)
    ax[0].set_title('Cluster-membership stability', fontsize=10)

    ax[1].bar(x, [int(k.split('-')[1]) - int(k.split('-')[0]) for k in S['k_range']],
              color='C1', alpha=.85)
    ax[1].set_xticks(x); ax[1].set_xticklabels(S.index)
    ax[1].set_ylabel('spread of BIC-argmin k across seeds')
    ax[1].set_title('Does the chosen k move?', fontsize=10)

    ax[2].axhline(raw_r2, color='C2', lw=2, label=f'raw features {raw_r2:.3f} (deterministic)')
    ax[2].plot(SEEDS, lat_r2, 'o-', color='C0', label='latent per seed')
    ax[2].set_xlabel('seed'); ax[2].set_ylabel('OOS R²')
    ax[2].legend(fontsize=8); ax[2].set_title('Does the CONCLUSION survive?', fontsize=10)

    fig.tight_layout(rect=[0, 0, 1, 0.92])
    out = os.path.join(ROOT, 'seed_stability.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)

    print('\n' + '=' * 78)
    print('SEED STABILITY (10 seeds, ARI: 1=identical partitions, 0=chance)')
    print('=' * 78)
    print(S.round(3).to_string())
    print(f'\nheadline vol result:  raw features R²={raw_r2:.4f} (no AE, deterministic)')
    print(f'                      latent R² across seeds {np.mean(lat_r2):.4f} ± {np.std(lat_r2):.4f}'
          f'  [{np.min(lat_r2):.4f}, {np.max(lat_r2):.4f}]')
    print('=' * 78)


if __name__ == '__main__':
    main()
