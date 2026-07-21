"""
fill_feasibility.py — can the parked 1DTE iron condor actually be FILLED?

THE BLOCKER THIS ATTACKS
  The short-vol engine is validated (Sharpe ~1 realistic) but parked for one reason:
  "fragile to real 4-leg-condor fills". Everything so far assumed marks. This measures
  what the tape actually says.

WHY 30 DAYS OF 1-MIN DATA IS THE RIGHT SIZE HERE
  Signal research needs long history (30 days told us almost nothing about vol edges).
  A FILL study is a microstructure question — it needs intraday depth, not years. 30 days
  x ~390 minutes x a full chain is plenty to see whether the legs trade at all.

WHAT THIS CAN AND CANNOT SEE
  The files hold TRADE bars (OHLCV), not quotes. So:
    · CAN measure: whether each leg prints at all near the decision time, how often, and
      the dispersion of prints inside a minute (a LOWER BOUND on the effective spread —
      it understates the true bid/ask when all prints hit the same side).
    · CANNOT measure: the actual bid/ask you would cross. That needs NBBO quotes.
  The point of this script is to size the problem and make the data request precise.

THE ENGINE'S LEGS (live_signal.py): 1DTE, entered at the close of T
    short put   S*(1-0.012)      short call  S*(1+0.012)
    long put    S*(1-0.05)       long call   S*(1+0.05)
  The ±5% wings on a 1DTE are nearly worthless — that is exactly where fills should be
  worst, and where a 0.01-0.05 print tax is enormous relative to the premium collected.

USAGE  ./vbt-env/bin/python fill_feasibility.py [--sym SPY]
"""
import os, glob, argparse, logging
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
TZ   = 'America/New_York'
OTM_PCT, WING_PCT = 0.012, 0.05
CLOSE_MIN = 16 * 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('fill')


def load(sym):
    fs = sorted(glob.glob(os.path.join(DATA, f'options_{sym}_1m*.parquet')))
    d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    d = d.drop_duplicates(subset=['ts', 'expiry', 'opt_type', 'strike'])
    ny = d['ts'].dt.tz_convert(TZ)
    d['date'] = ny.dt.normalize().dt.tz_localize(None)
    d['min']  = ny.dt.hour * 60 + ny.dt.minute
    d['expiry'] = pd.to_datetime(d['expiry'])
    return d


def parity_spot(g, minute):
    piv = g[g['min'] == minute].pivot_table(index='strike', columns='opt_type',
                                            values='close', aggfunc='last')
    if not {'C', 'P'} <= set(piv.columns):
        return np.nan
    piv = piv.dropna()
    if len(piv) < 4:
        return np.nan
    return float((piv['C'] - piv['P'] + piv.index.to_series()).median())


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--sym', default='SPY')
    ap.add_argument('--window', type=int, default=10, help='minutes before the close')
    args = ap.parse_args()

    d = load(args.sym)
    dates = sorted(d['date'].unique())
    log.info('%s: %d days %s → %s', args.sym, len(dates),
             pd.Timestamp(dates[0]).date(), pd.Timestamp(dates[-1]).date())

    rows = []
    for i, day in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        g = d[(d['date'] == day) & (d['expiry'] == nxt)]     # 1DTE as of the close of `day`
        if g.empty:
            continue
        # spot from the 0DTE chain of the same day (denser), fall back to the 1DTE chain
        same = d[(d['date'] == day) & (d['expiry'] == day)]
        S = parity_spot(same if not same.empty else g, CLOSE_MIN - 1)
        if not np.isfinite(S):
            continue

        win = g[(g['min'] >= CLOSE_MIN - args.window) & (g['min'] < CLOSE_MIN)]
        legs = {'short_put':  ('P', S * (1 - OTM_PCT)),  'short_call': ('C', S * (1 + OTM_PCT)),
                'long_put':   ('P', S * (1 - WING_PCT)), 'long_call':  ('C', S * (1 + WING_PCT))}
        rec = {'date': day, 'spot': S}
        for name, (typ, target) in legs.items():
            side = win[win['opt_type'] == typ]
            if side.empty:
                rec[f'{name}_prints'] = 0; rec[f'{name}_px'] = np.nan
                rec[f'{name}_disp'] = np.nan; continue
            k = side['strike'].iloc[(side['strike'] - target).abs().argsort().iloc[0]]
            leg = side[side['strike'] == k]
            px = float(leg['close'].iloc[-1])
            # within-minute high-low = LOWER BOUND on the effective spread
            disp = float((leg['high'] - leg['low']).mean())
            rec[f'{name}_prints'] = int(len(leg))
            rec[f'{name}_px'] = px
            rec[f'{name}_disp'] = disp
            rec[f'{name}_strike'] = float(k)
        rows.append(rec)

    F = pd.DataFrame(rows).set_index('date')
    legs = ['short_put', 'short_call', 'long_put', 'long_call']

    log.info('══ leg availability in the last %d minutes (1DTE, at the close) ══', args.window)
    for l in legs:
        pr = F[f'{l}_prints']
        log.info('  %-11s traded on %2d/%2d days  median prints/day %4.1f  median px %.3f',
                 l, int((pr > 0).sum()), len(F), pr.median(), F[f'{l}_px'].median())

    F['credit'] = F['short_put_px'] + F['short_call_px'] - F['long_put_px'] - F['long_call_px']
    F['disp_total'] = F[[f'{l}_disp' for l in legs]].sum(axis=1)
    F['all_traded'] = (F[[f'{l}_prints' for l in legs]] > 0).all(axis=1)

    ok = F[F['all_traded'] & F['credit'].notna() & (F['credit'] > 0)]
    log.info('══ the 4-leg package ══')
    log.info('  all four legs printed on %d/%d days (%.0f%%)',
             int(F['all_traded'].sum()), len(F), 100 * F['all_traded'].mean())
    if len(ok):
        log.info('  median net credit          %.3f  (%.1f bp of spot)',
                 ok['credit'].median(), 1e4 * ok['credit'].median() / ok['spot'].median())
        log.info('  median summed print-disp   %.3f  = %.0f%% of the credit  ← LOWER BOUND on cost',
                 ok['disp_total'].median(), 100 * ok['disp_total'].median() / ok['credit'].median())
        log.info('  days where disp > credit   %d/%d', int((ok['disp_total'] > ok['credit']).sum()), len(ok))

    log.info('══ per-leg cost share (lower bound) ══')
    for l in legs:
        s = (F[f'{l}_disp'] / F['credit']).replace([np.inf, -np.inf], np.nan).dropna()
        if len(s):
            log.info('  %-11s median disp = %5.1f%% of credit', l, 100 * s.median())

    print('\n' + '=' * 72)
    print(f'FILL FEASIBILITY — {args.sym} 1DTE iron condor at the close (n={len(F)} days)')
    print('=' * 72)
    print(F[[f'{l}_prints' for l in legs] + ['credit', 'disp_total']].describe().round(3).to_string())
    print('=' * 72)
    print('NOTE: dispersion of trade prints is a LOWER BOUND on the spread you would cross.')
    print('      A real answer needs NBBO quotes, not trade bars.')


if __name__ == '__main__':
    main()
