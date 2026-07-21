"""
iv_smoke_test.py — THE tradeability question, in smoke-test form:
  is the IB (first-hour) information ALREADY PRICED into 0DTE implied vol at 10:30 ET?

WHY IT MATTERS
  We showed IB structure forecasts post-IB realised vol (OOS R2 0.52). But every market
  participant sees the same first hour. If the 10:30 option price already embeds it, that
  R2 is worth nothing. Our earlier incrementality test only beat YESTERDAY's EOD options
  — never the contemporaneous price. This closes that gap.

DATA PROBLEM AND THE WORKAROUND
  The ES bars end 2026-06-02 and the option files start 2026-06-05 — zero overlap, so
  realised vol cannot come from ES. Instead the underlying path is RECONSTRUCTED from the
  options themselves by put-call parity, S_t = C_t - P_t + K, taking the median over all
  0DTE strikes quoted in that minute (~19/min). Probe on one day: 405 minutes of full
  session, 1-min |ret| median 0.97bp, lag-1 autocorrelation +0.02 — i.e. microstructure
  noise does NOT dominate (bid-ask bounce would give strongly negative autocorrelation).

THE TEST (self-contained, no ES needed, no trailing-vol normaliser needed)
  implied  = ATM 0DTE straddle at 10:30  ->  sigma of the REMAINING session
             (ATM straddle ~ S*sigma*sqrt(2/pi)  =>  sigma = straddle/S * sqrt(pi/2))
  realised = std(1-min log returns 10:30->16:00) * sqrt(n)
  y  = log(realised / implied)              the vol SURPRISE versus what was priced
  x  = log(ib_range / implied)              first-hour width RELATIVE to the priced move
       (+ dimensionless IB shape features)

  If x explains y  -> the first hour carries information the option price has NOT
  absorbed, and the forecast is monetisable.
  If x is flat     -> it is already in the price, and R2=0.52 is worth zero.

  Normalising by implied is deliberate: it removes the need for a trailing-vol
  normaliser (unavailable here) AND makes the benchmark the market price itself.

POWER WARNING
  30 trading days (2026-06-05..07-20), one regime. Detectable only if the effect is
  large (|rho| > ~0.36 for p<0.05). This is a smell test, not a verdict.

USAGE  ./vbt-env/bin/python iv_smoke_test.py
"""
import os, glob, logging
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
TZ   = 'America/New_York'
SNAP = 10 * 60 + 30        # 10:30 ET — end of the initial balance
OPEN = 9 * 60 + 30
CLOSE = 16 * 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('iv')


def load_chain(sym):
    fs = sorted(glob.glob(os.path.join(DATA, f'options_{sym}_1m*.parquet')))
    d = pd.concat([pd.read_parquet(f, columns=['ts', 'expiry', 'opt_type', 'strike', 'close'])
                   for f in fs], ignore_index=True)
    d = d.drop_duplicates(subset=['ts', 'expiry', 'opt_type', 'strike'])
    ny = d['ts'].dt.tz_convert(TZ)
    d['date'] = ny.dt.normalize().dt.tz_localize(None)
    d['min']  = ny.dt.hour * 60 + ny.dt.minute
    d['expiry'] = pd.to_datetime(d['expiry'])
    d = d[d['expiry'] == d['date']]                      # 0DTE only
    log.info('%s: %s 0DTE rows over %d days (%s → %s)', sym, f'{len(d):,}', d['date'].nunique(),
             d['date'].min().date(), d['date'].max().date())
    return d


def parity_spot(g):
    """median put-call-parity spot per minute from all strikes quoted that minute"""
    piv = g.pivot_table(index='min', columns=['opt_type', 'strike'], values='close', aggfunc='last')
    if 'C' not in piv.columns.get_level_values(0) or 'P' not in piv.columns.get_level_values(0):
        return None
    C, P = piv['C'], piv['P']
    k = C.columns.intersection(P.columns)
    if len(k) < 4:
        return None
    S = (C[k] - P[k] + pd.Series(k, index=k)).median(axis=1).dropna()
    return S.sort_index()


def day_metrics(g):
    S = parity_spot(g)
    if S is None or len(S) < 200:
        return None
    ib   = S[(S.index >= OPEN) & (S.index < SNAP)]
    post = S[(S.index >= SNAP) & (S.index <= CLOSE)]
    if len(ib) < 40 or len(post) < 120:
        return None

    # implied: ATM 0DTE straddle at the 10:30 snapshot
    snap = g[g['min'] == SNAP]
    piv = snap.pivot_table(index='strike', columns='opt_type', values='close', aggfunc='last')
    if not {'C', 'P'} <= set(piv.columns):
        return None
    piv = piv.dropna()
    if len(piv) < 4:
        return None
    S0 = float(post.iloc[0])
    atm = piv.index[np.argmin(np.abs(piv.index.values - S0))]
    straddle = float(piv.loc[atm, 'C'] + piv.loc[atm, 'P'])
    implied = straddle / S0 * np.sqrt(np.pi / 2)          # sigma over the remaining session
    if not np.isfinite(implied) or implied <= 0:
        return None

    lr = np.diff(np.log(post.values))
    realised = float(np.std(lr) * np.sqrt(len(lr)))

    ibh, ibl, ib_o, ib_c = ib.max(), ib.min(), ib.iloc[0], ib.iloc[-1]
    rng = (ibh - ibl) / S0
    if rng <= 0:
        return None
    s = np.sign(ib_c - ib_o) or 1.0
    op_pos = np.clip((ib_o - ibl) / (ibh - ibl), 0, 1)
    cl_pos = np.clip((ib_c - ibl) / (ibh - ibl), 0, 1)
    half = len(ib) // 2
    return dict(
        implied=implied, realised=realised, ib_range=rng,
        one_sided=abs(ib_c - ib_o) / (ibh - ibl),
        open_run=op_pos if s > 0 else 1 - op_pos,
        close_run=cl_pos if s > 0 else 1 - cl_pos,
        run_ext_t=(np.argmax(ib.values) if s > 0 else np.argmin(ib.values)) / len(ib),
        range_build=((ib.iloc[half:].max() - ib.iloc[half:].min()) /
                     (ib.iloc[:half].max() - ib.iloc[:half].min() + 1e-9)))


def build(sym):
    d = load_chain(sym)
    rows = {}
    for date, g in d.groupby('date'):
        m = day_metrics(g)
        if m:
            rows[date] = m
    F = pd.DataFrame(rows).T.sort_index().astype(float)
    F['y']  = np.log(F['realised'] / F['implied'])        # vol surprise vs priced
    F['x']  = np.log(F['ib_range'] / F['implied'])        # IB width vs priced
    return F


def analyse(sym, F):
    n = len(F)
    log.info('══ %s ══  usable days = %d', sym, n)
    log.info('   implied  median %.4f   realised median %.4f   realised/implied median %.2f',
             F['implied'].median(), F['realised'].median(),
             (F['realised'] / F['implied']).median())

    out = {}
    r1 = stats.spearmanr(F['implied'], F['realised'])
    r2 = stats.spearmanr(F['ib_range'], F['realised'])
    r3 = stats.spearmanr(F['x'], F['y'])
    log.info('   Spearman implied → realised   : %+.3f (p=%.3f)   [does the market price it]', r1.correlation, r1.pvalue)
    log.info('   Spearman ib_range → realised  : %+.3f (p=%.3f)', r2.correlation, r2.pvalue)
    log.info('   Spearman x → y  (THE TEST)    : %+.3f (p=%.3f)   [IB info NOT in the price]',
             r3.correlation, r3.pvalue)
    out.update(rho_iv=r1.correlation, rho_ib=r2.correlation, rho_test=r3.correlation, p_test=r3.pvalue)

    # OLS slope of the surprise on relative IB width
    sl = stats.linregress(F['x'], F['y'])
    log.info('   OLS  y = a + b·x :  b=%+.3f (t=%+.2f, p=%.3f)  R²=%.3f',
             sl.slope, sl.slope / sl.stderr, sl.pvalue, sl.rvalue**2)
    out.update(b=sl.slope, t=sl.slope / sl.stderr, p_b=sl.pvalue, r2=sl.rvalue**2)

    # sign test: when the IB is wide relative to what is priced, does realised beat implied?
    hi = F[F['x'] > F['x'].median()]
    k = int((hi['y'] > 0).sum()); m = len(hi)
    pb = stats.binomtest(k, m, 0.5).pvalue if m else np.nan
    log.info('   sign test | wide-IB days: realised>implied on %d/%d (%.0f%%)  p=%.3f',
             k, m, 100 * k / max(m, 1), pb)
    out.update(sign_k=k, sign_n=m, sign_p=pb)
    return out


def main():
    res, frames = {}, {}
    for sym in ['SPY', 'QQQ']:
        F = build(sym)
        frames[sym] = F
        res[sym] = analyse(sym, F)

    fig = plt.figure(figsize=(14, 8))
    fig.suptitle('Smoke test — is the first hour already priced into 0DTE implied vol at 10:30 ET?',
                 fontsize=13, weight='bold')
    for i, sym in enumerate(['SPY', 'QQQ']):
        F = frames[sym]
        ax = fig.add_subplot(2, 3, 1 + i * 3)
        ax.scatter(F['implied'], F['realised'], s=28, alpha=.75)
        lim = [0, max(F['implied'].max(), F['realised'].max()) * 1.1]
        ax.plot(lim, lim, 'k--', lw=1)
        ax.set_xlabel('implied (10:30 straddle)'); ax.set_ylabel('realised post-IB')
        ax.set_title(f'{sym}: priced vs realised  ρ={res[sym]["rho_iv"]:+.2f}', fontsize=10)

        ax = fig.add_subplot(2, 3, 2 + i * 3)
        ax.scatter(F['x'], F['y'], s=28, alpha=.75, color='C1')
        xs = np.linspace(F['x'].min(), F['x'].max(), 20)
        ax.plot(xs, res[sym]['b'] * xs + (F['y'].mean() - res[sym]['b'] * F['x'].mean()), 'r-', lw=1.5)
        ax.axhline(0, color='k', lw=.8); ax.axvline(F['x'].median(), color='k', ls=':', lw=.8)
        ax.set_xlabel('log(IB range / implied)'); ax.set_ylabel('log(realised / implied)')
        ax.set_title(f'{sym}: THE TEST  b={res[sym]["b"]:+.2f} (t={res[sym]["t"]:+.2f})', fontsize=10)

        ax = fig.add_subplot(2, 3, 3 + i * 3)
        ratio = (F['realised'] / F['implied']).sort_values()
        ax.bar(range(len(ratio)), ratio.values - 1,
               color=['C2' if v > 1 else 'C3' for v in ratio.values], alpha=.85)
        ax.axhline(0, color='k', lw=1)
        ax.set_title(f'{sym}: realised/implied − 1  (n={len(F)})', fontsize=10)
        ax.set_xlabel('days sorted')

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = os.path.join(ROOT, 'iv_smoke_test.png')
    fig.savefig(out, dpi=110); log.info('saved figure → %s', out)

    print('\n' + '=' * 76)
    print('IV SMOKE TEST — is the first hour already in the 10:30 option price?')
    print('=' * 76)
    for sym in ['SPY', 'QQQ']:
        r = res[sym]
        print(f'\n{sym}  (n={len(frames[sym])} days)')
        print(f'  implied→realised   rho {r["rho_iv"]:+.3f}')
        print(f'  ib_range→realised  rho {r["rho_ib"]:+.3f}')
        print(f'  THE TEST  x→y      rho {r["rho_test"]:+.3f} (p={r["p_test"]:.3f})   '
              f'slope b={r["b"]:+.3f}  t={r["t"]:+.2f}  R²={r["r2"]:.3f}')
        print(f'  sign test wide-IB  {r["sign_k"]}/{r["sign_n"]} realised>implied  p={r["sign_p"]:.3f}')
    print('\nPOWER: ~30 days, one regime — smell test only.')
    print('=' * 76)


if __name__ == '__main__':
    main()
