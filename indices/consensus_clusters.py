"""
consensus_clusters.py — seed-independent taxonomies via CONSENSUS CLUSTERING.

WHY NOT JUST PICK A GOOD SEED
  seed_stability.py showed the clustering itself is reproducible (ARI 0.90-1.00 with the
  autoencoder fixed) but the AUTOENCODER's initialisation is not: retraining per seed
  gives ARI 0.26-0.56, and the BIC-argmin k itself moves (IB: 5..8). The tempting fix is
  to hunt for the seed whose archetypes look best — that is selection on the outcome, the
  same sin as picking a threshold after seeing the result, and it does not transfer to new
  data. Instead we average OVER seeds.

METHOD (as in Sinha et al. 2021, ConsensusClusterPlus)
  1. train N autoencoders with N different seeds -> N latents
  2. for each candidate k: cluster every latent at that k and accumulate a CO-ASSOCIATION
     matrix M[i,j] = fraction of runs in which days i and j land in the same cluster
  3. PAC (proportion of ambiguous clustering) = share of pairs with 0.1 < M < 0.9.
     Low PAC = the partition is agreed on. Pick k = argmin PAC — a stability criterion,
     not a likelihood one, and therefore not seed-dependent the way BIC-argmin was.
  4. final labels = average-linkage agglomerative clustering on the distance 1 - M
  5. per-day CONFIDENCE = mean co-association with its own consensus cluster. Days with
     low confidence are genuinely borderline and should be reported as such rather than
     silently assigned to a type.

USAGE  ./vbt-env/bin/python consensus_clusters.py [--runs 30] [--kmax 8]
"""
import os, argparse, importlib.util, logging
import numpy as np
import pandas as pd

import session
import torch
from sklearn.preprocessing import StandardScaler
from sklearn.mixture import GaussianMixture
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache')
TEST_FROM = pd.Timestamp('2020-01-01')
NBINS, WINDOW = 64, 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('consensus')


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def consensus_matrix(latents, k, n):
    """M[i,j] = fraction of runs where i and j share a cluster (float32, n x n)"""
    M = np.zeros((n, n), dtype=np.float32)
    for s, Z in latents.items():
        lab = GaussianMixture(k, covariance_type='full', n_init=10, reg_covar=1e-4,
                              random_state=s).fit(Z).predict(Z)
        M += (lab[:, None] == lab[None, :]).astype(np.float32)
    M /= len(latents)
    return M


def pac(M, lo=0.1, hi=0.9):
    iu = np.triu_indices_from(M, k=1)
    v = M[iu]
    return float(((v > lo) & (v < hi)).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', type=int, default=30)
    ap.add_argument('--kmax', type=int, default=8)
    args = ap.parse_args()
    SEEDS = list(range(1, args.runs + 1))

    shape_m = _load('shape_ae', os.path.join(ROOT, 'day_shape_autoencoder.py'))
    open_m  = _load('open_ae',  os.path.join(ROOT, 'open_type_autoencoder.py'))
    ib_m    = _load('ib_ae',    os.path.join(ROOT, 'ib_type_autoencoder.py'))

    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    rth = session.get_rth(es)
    days = pd.read_parquet(os.path.join(CACHE, 'es_days.parquet')); days.index = pd.to_datetime(days.index)

    prof = shape_m.build_profiles(rth, NBINS)
    paths, _ = open_m.build_open_paths(rth, WINDOW)
    Fib = ib_m.build_ib_features(rth, days, bins=24).dropna(subset=ib_m.FEATURES)
    tri = Fib.index < TEST_FROM
    Xib = StandardScaler().fit(Fib.loc[tri, ib_m.FEATURES]).transform(Fib[ib_m.FEATURES]).astype(np.float32)

    TAX = {
        'day-shape': dict(X=prof.values.astype(np.float32), idx=prof.index, mod=shape_m,
                          n_in=NBINS, latent=8, epochs=80),
        'opening':   dict(X=paths.values.astype(np.float32), idx=paths.index, mod=open_m,
                          n_in=WINDOW, latent=8, epochs=80),
        'IB':        dict(X=Xib, idx=Fib.index, mod=ib_m, n_in=Xib.shape[1],
                          latent=4, epochs=120),
    }

    summary, store, pacs = [], {}, {}
    for name, cfg in TAX.items():
        X, idx, mod = cfg['X'], cfg['idx'], cfg['mod']
        tr = idx < TEST_FROM
        log.info('[%s] training %d autoencoders …', name, len(SEEDS))
        latents = {}
        for s in SEEDS:
            torch.manual_seed(s); np.random.seed(s)
            ae = mod.train_ae(X[tr], cfg['n_in'], cfg['latent'], cfg['epochs'])
            latents[s] = mod.encode(ae, X)
        n = len(X)

        best_k, best_pac, best_M = None, np.inf, None
        row_pac = {}
        for k in range(2, args.kmax + 1):
            M = consensus_matrix(latents, k, n)
            p = pac(M)
            row_pac[k] = p
            if p < best_pac:
                best_k, best_pac, best_M = k, p, M
        pacs[name] = row_pac
        log.info('[%s] PAC by k: %s', name, {k: round(v, 3) for k, v in row_pac.items()})
        log.info('[%s] consensus k = %d  (PAC %.3f — lower is more agreed)', name, best_k, best_pac)

        lab = AgglomerativeClustering(n_clusters=best_k, metric='precomputed',
                                      linkage='average').fit_predict(1.0 - best_M)
        conf = np.array([best_M[i, lab == lab[i]].mean() for i in range(n)])

        # how much does a single-seed run agree with the consensus?
        single = [adjusted_rand_score(lab,
                  GaussianMixture(best_k, covariance_type='full', n_init=10, reg_covar=1e-4,
                                  random_state=s).fit(latents[s]).predict(latents[s]))
                  for s in SEEDS]
        log.info('[%s] ARI(single seed vs consensus): mean %.3f  min %.3f  max %.3f',
                 name, np.mean(single), np.min(single), np.max(single))
        log.info('[%s] per-day confidence: median %.2f   below 0.5 on %.0f%% of days',
                 name, np.median(conf), 100 * (conf < 0.5).mean())
        store[name] = pd.DataFrame({'cluster': lab, 'confidence': conf}, index=idx)
        summary.append(dict(taxonomy=name, k_consensus=best_k, PAC=best_pac,
                            ari_single_vs_consensus=float(np.mean(single)),
                            conf_median=float(np.median(conf)),
                            pct_low_conf=float(100 * (conf < 0.5).mean()),
                            sizes=str(dict(pd.Series(lab).value_counts().sort_index()))))

    S = pd.DataFrame(summary).set_index('taxonomy')
    out_p = os.path.join(CACHE, 'consensus_labels.parquet')
    pd.concat({k: v for k, v in store.items()}, axis=0).to_parquet(out_p)
    log.info('consensus labels → %s', out_p)

    fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
    fig.suptitle('Consensus clustering — a seed-independent taxonomy (30 autoencoder seeds)',
                 fontsize=12, weight='bold')
    for name, row in pacs.items():
        ax[0].plot(list(row), list(row.values()), 'o-', label=name)
    ax[0].set_xlabel('k'); ax[0].set_ylabel('PAC (lower = more agreement)')
    ax[0].legend(fontsize=8); ax[0].set_title('k chosen by stability, not likelihood', fontsize=10)

    x = np.arange(len(S))
    ax[1].bar(x, S['ari_single_vs_consensus'], color='C1', alpha=.85)
    ax[1].set_xticks(x); ax[1].set_xticklabels(S.index); ax[1].set_ylim(0, 1)
    ax[1].set_ylabel('ARI'); ax[1].set_title('One seed vs the consensus', fontsize=10)

    for i, name in enumerate(store):
        ax[2].hist(store[name]['confidence'], bins=25, alpha=.55, label=name)
    ax[2].axvline(0.5, color='k', ls=':', lw=1)
    ax[2].set_xlabel('per-day confidence'); ax[2].legend(fontsize=8)
    ax[2].set_title('How firmly does each day belong?', fontsize=10)

    fig.tight_layout(rect=[0, 0, 1, 0.92])
    p = os.path.join(ROOT, 'consensus_clusters.png')
    fig.savefig(p, dpi=110); log.info('saved figure → %s', p)

    print('\n' + '=' * 82)
    print('CONSENSUS CLUSTERING — seed-independent by construction')
    print('=' * 82)
    print(S.round(3).to_string())
    print('=' * 82)


if __name__ == '__main__':
    main()
