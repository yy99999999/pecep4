"""
xasset_vrp.py — does the volatility risk premium exist OUTSIDE equity indices,
and are the sleeves genuinely uncorrelated — especially on the tails?

WHY THIS IS THE PROJECT'S PRIMARY BREADTH IDEA
  The organizing theory is IR = IC x sqrt(breadth): more weakly-correlated sleeves beat
  one strong one. The short-vol engine works on equity indices (SPY/SPX, QQQ/NDX), but
  those are one risk. TLT / IEF / GLD / USO are bonds, rates, metals and energy — if the
  same VRP structure holds there, the sleeves are genuinely diversifying. The chains are
  already cached (1219-1226 days each, 2021-09 -> 2026-06) and have never been used.

THREE QUESTIONS, IN ORDER
  1. Does the premium EXIST? Measured as actually earned, not as a signal:
        vrp_earned(t) = atm_iv_30(t) - RV_forward(t -> t+21)
     (the project's `vrp` feature is IV - TRAILING RV — that is a sizing signal, not the
     premium a seller collects. Different object, easy to conflate.)
  2. Does it SURVIVE COSTS? `straddle_spread` from the pipeline is the real ATM round-trip
     cost per instrument. Premium in vol points is meaningless until compared with it.
  3. Are the sleeves uncorrelated ON THE TAILS? Average correlation is the easy question
     and the wrong one — sleeves that look independent in calm periods can collapse into
     one trade in a crisis. That is what actually decides whether breadth is real.

STATISTICS
  vrp_earned uses a 21-day forward window, so consecutive days overlap by 20/21 and are
  massively autocorrelated. Headline stats therefore use NON-OVERLAPPING samples (every
  21st day); the daily series is kept only for correlation shape.

USAGE  ./vbt-env/bin/python xasset_vrp.py [--symbols SPY QQQ TLT IEF GLD USO] [--rebuild]
"""
import os, argparse, importlib.util, logging
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache')
WIN   = 21          # trading days ~ the 30-calendar-day tenor of atm_iv_30
SEED  = 7

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('xvrp')


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def features(sym, iopt, rebuild=False):
    """per-symbol daily features, cached (recompute=True → self-computed IV, vendor-independent)"""
    p = os.path.join(CACHE, f'xasset_feat_{sym}.parquet')
    if os.path.exists(p) and not rebuild:
        return pd.read_parquet(p)
    log.info('  building %s (self-greeks, ~1-2 min) …', sym)
    f = iopt.daily_features(sym, None, recompute=True)
    if f.empty:
        log.warning('  %s: no data', sym); return f
    f.to_parquet(p)
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', nargs='+', default=['SPY', 'QQQ', 'TLT', 'IEF', 'GLD', 'USO'])
    ap.add_argument('--rebuild', action='store_true')
    args = ap.parse_args()

    iopt = _load('intrinio_options', os.path.join(ROOT, 'intrinio_options.py'))
    D = {}
    for s in args.symbols:
        f = features(s, iopt, args.rebuild)
        if f.empty:
            continue
        f = f.copy()
        f['rv_fwd'] = iopt.realized_vol(f['spot'], WIN).shift(-WIN)   # realised over (t, t+WIN]
        f['vrp_earned'] = f['atm_iv_30'] - f['rv_fwd']
        f['gex_z'] = ((f['gex'] - f['gex'].rolling(60).mean()) /
                      f['gex'].rolling(60).std()).shift(1)            # PIT: OI publishes late
        D[s] = f
        log.info('%s: %d days  %s → %s', s, len(f), f.index.min().date(), f.index.max().date())

    syms = list(D)

    # ── 1 + 2: does the premium exist, and does it beat the instrument's own cost? ──
    rows = []
    for s in syms:
        f = D[s]
        nov = f['vrp_earned'].dropna().iloc[::WIN]          # NON-OVERLAPPING
        if len(nov) < 10:
            continue
        t, p = stats.ttest_1samp(nov.values, 0.0)
        cost = f['straddle_spread'].median() if 'straddle_spread' in f else np.nan
        rows.append(dict(sym=s, n_nonov=len(nov), vrp_mean=nov.mean() * 100,
                         vrp_med=nov.median() * 100, pos_pct=(nov > 0).mean() * 100,
                         t=t, p=p, iv_med=f['atm_iv_30'].median() * 100,
                         cost_pct=cost * 100 if np.isfinite(cost) else np.nan))
    R = pd.DataFrame(rows).set_index('sym')
    R['vrp_over_cost'] = R['vrp_mean'] / R['cost_pct']
    log.info('══ 1+2 · premium earned (vol points, annualised) vs the instrument cost ══\n%s',
             R.round(2).to_string())

    # ── 3: correlation, and the one that matters — on the tails ──
    V = pd.DataFrame({s: D[s]['vrp_earned'] for s in syms}).dropna(how='all')
    Vn = V.iloc[::WIN].dropna()                                     # non-overlapping
    C = Vn.corr()
    log.info('══ 3 · correlation of earned VRP (non-overlapping, n=%d) ══\n%s',
             len(Vn), C.round(2).to_string())

    ref = 'SPY' if 'SPY' in syms else syms[0]
    q = Vn[ref].quantile(0.10)
    tail = Vn[Vn[ref] <= q]                                          # equity vol-seller's worst
    log.info('══ TAIL TEST · %s worst decile (n=%d) ══', ref, len(tail))
    tl = pd.DataFrame({'all_mean': Vn.mean() * 100, 'tail_mean': tail.mean() * 100})
    tl['damage'] = tl['tail_mean'] - tl['all_mean']
    tl['still_pos_%'] = [(tail[s] > 0).mean() * 100 for s in Vn.columns]
    log.info('\n%s', tl.round(2).to_string())
    off = [s for s in syms if s != ref]
    log.info('mean corr with %s: all-sample %.2f  |  in %s tail %.2f',
             ref, C.loc[ref, off].mean(), ref,
             tail.corr().loc[ref, off].mean() if len(tail) > 3 else np.nan)

    # ── does the GEX gate transfer outside equities? ──
    log.info('══ GEX gate transfer (mean earned VRP, vol pts) ══')
    g_rows = []
    for s in syms:
        f = D[s].dropna(subset=['vrp_earned', 'gex_z'])
        nov = f.iloc[::WIN]
        if len(nov) < 20:
            continue
        hi = nov.loc[nov['gex_z'] >= 0, 'vrp_earned'] * 100
        lo = nov.loc[nov['gex_z'] < 0, 'vrp_earned'] * 100
        g_rows.append(dict(sym=s, n_hi=len(hi), gex_pos=hi.mean(),
                           n_lo=len(lo), gex_neg=lo.mean(), gate_lift=hi.mean() - lo.mean()))
    G = pd.DataFrame(g_rows).set_index('sym')
    log.info('\n%s', G.round(2).to_string())

    # ── figure ──
    fig = plt.figure(figsize=(15, 9))
    fig.suptitle('Cross-asset volatility risk premium — does breadth actually exist?',
                 fontsize=13, weight='bold')

    ax = fig.add_subplot(2, 3, 1)
    ax.bar(R.index, R['vrp_mean'], color='C0', alpha=.85, label='earned VRP')
    ax.plot(R.index, R['cost_pct'], 'rv', ms=9, label='round-trip cost')
    ax.axhline(0, color='k', lw=1); ax.legend(fontsize=8)
    ax.set_ylabel('vol points'); ax.set_title('Premium vs cost', fontsize=10)

    ax = fig.add_subplot(2, 3, 2)
    im = ax.imshow(C.values, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(len(C))); ax.set_xticklabels(C.columns, rotation=45, fontsize=8)
    ax.set_yticks(range(len(C))); ax.set_yticklabels(C.index, fontsize=8)
    for i in range(len(C)):
        for j in range(len(C)):
            ax.text(j, i, f'{C.values[i,j]:.2f}', ha='center', va='center', fontsize=7)
    ax.set_title('Corr of earned VRP (all sample)', fontsize=10)

    ax = fig.add_subplot(2, 3, 3)
    if len(tail) > 3:
        Ct = tail.corr()
        im = ax.imshow(Ct.values, cmap='RdBu_r', vmin=-1, vmax=1)
        ax.set_xticks(range(len(Ct))); ax.set_xticklabels(Ct.columns, rotation=45, fontsize=8)
        ax.set_yticks(range(len(Ct))); ax.set_yticklabels(Ct.index, fontsize=8)
        for i in range(len(Ct)):
            for j in range(len(Ct)):
                ax.text(j, i, f'{Ct.values[i,j]:.2f}', ha='center', va='center', fontsize=7)
    ax.set_title(f'Corr in the {ref} TAIL — the real test', fontsize=10)

    ax = fig.add_subplot(2, 3, 4)
    x = np.arange(len(tl))
    ax.bar(x - .2, tl['all_mean'], .4, label='all days', alpha=.85)
    ax.bar(x + .2, tl['tail_mean'], .4, label=f'{ref} worst decile', alpha=.85, color='C3')
    ax.axhline(0, color='k', lw=1)
    ax.set_xticks(x); ax.set_xticklabels(tl.index, fontsize=8); ax.legend(fontsize=8)
    ax.set_ylabel('vol points'); ax.set_title('Does the sleeve survive the equity tail?', fontsize=10)

    ax = fig.add_subplot(2, 3, 5)
    ax.bar(G.index, G['gate_lift'], color='C2', alpha=.85)
    ax.axhline(0, color='k', lw=1)
    ax.set_ylabel('vol pts (gex_z>=0 minus <0)')
    ax.set_title('Does the GEX gate transfer?', fontsize=10)

    ax = fig.add_subplot(2, 3, 6); ax.axis('off')
    L = ['earned VRP = atm_iv_30(t) − realised vol(t→t+21), non-overlapping', '']
    for s in R.index:
        r = R.loc[s]
        L.append(f'  {s:<4} {r.vrp_mean:+6.2f} vol pts  t={r.t:+5.2f}  '
                 f'{r.pos_pct:4.0f}% pos  cost {r.cost_pct:4.1f}  x{r.vrp_over_cost:.1f}')
    L += ['', f'mean corr with {ref}: all {C.loc[ref, off].mean():+.2f}'
              f'  tail {tail.corr().loc[ref, off].mean():+.2f}' if len(tail) > 3 else '']
    ax.text(0, 1, '\n'.join(L), va='top', ha='left', fontsize=8.5, family='monospace')

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(ROOT, 'xasset_vrp.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)

    print('\n' + '=' * 78)
    print('CROSS-ASSET VRP — premium, cost, and tail correlation')
    print('=' * 78)
    print(R.round(2).to_string())
    print('\ntail behaviour (in the %s worst decile):' % ref)
    print(tl.round(2).to_string())
    print('=' * 78)


if __name__ == '__main__':
    main()
