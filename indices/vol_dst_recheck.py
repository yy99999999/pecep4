"""
vol_dst_recheck.py — does the headline result survive a DST-CORRECT session?

THE BUG
  amt_classify sets RTH_START/RTH_END as fixed UTC minutes (14:30-21:00). That is the
  US cash session only in WINTER (EST). In summer (EDT) the real session is 13:30-20:00
  UTC, so the fixed filter silently captured 10:30-17:00 ET:
     · "open"   = the 10:30 price, not the session open
     · "IB"     = the SECOND hour (10:30-11:30)
     · session  = one hour PAST the 16:00 close
  65% of all trading days (3248/4961) are EDT ⇒ were measured on the wrong window.
  No exception was ever raised: the window still contains ~390 one-minute bars.

WHAT THIS SCRIPT DOES
  Recomputes the headline finding (IB structure → post-IB realised vol) TWICE —
  once with the legacy fixed-UTC window, once with a DST-correct 09:30-16:00 ET
  session — and prints them side by side. Self-contained: it derives trailing vol and
  prior-day levels from the bars itself, so it does not depend on the es_days /
  es_va caches (which were themselves built with the buggy window).

USAGE  ./vbt-env/bin/python vol_dst_recheck.py
"""
import os, importlib.util, logging
import numpy as np
import pandas as pd

from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from scipy import stats

ROOT  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache')
SEED  = 7
TEST_FROM = pd.Timestamp('2020-01-01')
IBW   = 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('dst')
np.random.seed(SEED)


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def get_rth(es, mode):
    """mode='legacy'  → fixed 14:30-21:00 UTC (the bug)
       mode='correct' → true 09:30-16:00 America/New_York (DST-aware)"""
    if mode == 'legacy':
        t = es.index.hour * 60 + es.index.minute
        return es[(t >= 870) & (t < 1260)].copy()
    ny = es.index.tz_localize('UTC').tz_convert('America/New_York')
    m = ny.hour * 60 + ny.minute
    out = es[(m >= 570) & (m < 960)].copy()          # 09:30 .. 16:00 ET
    out.index = ny[(m >= 570) & (m < 960)].tz_localize(None)   # naive NY time
    return out


def session_frame(rth):
    """per-day: post-IB realised vol, IB range %, daily close, prior levels."""
    r = rth.copy(); r['date'] = r.index.normalize()
    rows = {}
    for date, g in r.groupby('date'):
        if len(g) < IBW + 60:
            continue
        post = g.iloc[IBW:]
        lr = np.diff(np.log(post['close'].values))
        if len(lr) < 30:
            continue
        rows[date] = dict(
            post_rv=float(np.std(lr) * np.sqrt(len(lr))),
            ib_range_pct=float((g.iloc[:IBW]['high'].max() - g.iloc[:IBW]['low'].min()) / g['open'].iloc[0]),
            close_px=float(g['close'].iloc[-1]),
            day_high=float(g['high'].max()), day_low=float(g['low'].min()),
            open_px=float(g['open'].iloc[0]), n_bars=len(g))
    S = pd.DataFrame(rows).T.sort_index()
    lr_d = np.log(S['close_px'] / S['close_px'].shift(1))
    S['rv20'] = lr_d.rolling(20).std() * np.sqrt(252)      # trailing, needs .shift(1) to be safe
    return S


def run(mode, es, ib_m, vix):
    rth = get_rth(es, mode)
    S = session_frame(rth)
    log.info('[%s] sessions=%d  median bars/day=%.0f  (RTH span check)',
             mode, len(S), S['n_bars'].median())

    rv20_prev = S['rv20'].shift(1)
    dvol_prev = (rv20_prev / np.sqrt(252)).replace(0, np.nan)
    y = np.log(S['post_rv'] / dvol_prev)

    # IB structural descriptor on THIS session definition, lag-safe width
    days_stub = pd.DataFrame({'ib_rv_ratio': np.nan}, index=S.index)
    F = ib_m.build_ib_features(rth, days_stub, bins=24)
    F['width'] = S['ib_range_pct'].reindex(F.index) / dvol_prev.reindex(F.index)
    F = F.dropna(subset=ib_m.FEATURES)

    v = vix['vix_close'].reindex(S.index).ffill()
    T = pd.DataFrame(index=S.index)
    T['log_rv20_prev'] = np.log(rv20_prev.replace(0, np.nan))
    T['log_vix_prev']  = np.log(v.shift(1))
    T['vix_chg5']      = v.shift(1) - v.shift(6)

    D = pd.concat([y.rename('y'), F[ib_m.FEATURES], T], axis=1)
    D = D.replace([np.inf, -np.inf], np.nan).dropna()
    tr = D.index < TEST_FROM; te = ~tr
    sc = lambda c: pd.DataFrame(StandardScaler().fit(D.loc[tr, c]).transform(D[c]),
                                index=D.index, columns=c)
    TRAIL = ['log_rv20_prev', 'log_vix_prev', 'vix_chg5']
    blocks = {
        'trailing (baseline)': sc(TRAIL),
        'trail + IB width':    pd.concat([sc(TRAIL), sc(['width'])], axis=1),
        'trail + IB raw':      pd.concat([sc(TRAIL), sc(ib_m.FEATURES)], axis=1),
    }
    yv = D['y'].values
    out = {}
    for name, X in blocks.items():
        m = Ridge(alpha=10.0).fit(X.values[tr], yv[tr])
        p = m.predict(X.values[te])
        out[name] = (r2_score(yv[te], p), stats.spearmanr(p, yv[te]).correlation)
    out['_n'] = (len(D), int(te.sum()))
    return out


def main():
    es = pd.read_parquet(os.path.join(CACHE, 'es_continuous.parquet'))
    es.index = pd.to_datetime(es.index)
    vix = pd.read_parquet(os.path.join(CACHE, 'vix_daily.parquet')); vix.index = pd.to_datetime(vix.index)
    ib_m = _load('ib_ae', os.path.join(ROOT, 'ib_type_autoencoder.py'))

    res = {m: run(m, es, ib_m, vix) for m in ['legacy', 'correct']}

    print('\n' + '=' * 74)
    print('DST RE-CHECK — IB structure → post-IB realised vol  (OOS ≥2020)')
    print('=' * 74)
    print(f'{"block":<24} {"legacy (buggy)":>18} {"DST-correct":>18}')
    for b in ['trailing (baseline)', 'trail + IB width', 'trail + IB raw']:
        l, c = res['legacy'][b], res['correct'][b]
        print(f'{b:<24} {l[0]:>+10.4f} (ρ{l[1]:+.2f}) {c[0]:>+10.4f} (ρ{c[1]:+.2f})')
    for m in ['legacy', 'correct']:
        base = res[m]['trailing (baseline)'][0]
        print(f'\n{m}: n={res[m]["_n"][0]} (test {res[m]["_n"][1]})   '
              f'ΔR²(IB width)={res[m]["trail + IB width"][0]-base:+.4f}   '
              f'ΔR²(IB raw)={res[m]["trail + IB raw"][0]-base:+.4f}')
    print('=' * 74)


if __name__ == '__main__':
    main()
