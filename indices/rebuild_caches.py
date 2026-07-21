"""
rebuild_caches.py — rebuild the Market-Profile caches on the DST-CORRECT session.

The old caches (es_va, es_days, nq_*) were built with a fixed 14:30-21:00 UTC window,
which is the US cash session only under EST. 65% of the history is EDT, where that
window is actually 10:30-17:00 ET — wrong "open", the SECOND hour as the "IB", and an
hour past the close. Everything downstream inherited that. This script reproduces the
notebook's cache-building steps linearly, using session.get_rth (see session.py).

Rebuilds, for ES and NQ:
    cache/<sym>_va.parquet      value-area / POC / HVN-LVN database
    cache/<sym>_days.parquet    classified days + RV-20 / volume-z / IB-RV normalisations

Old files are backed up to cache/legacy_dst_bug/ rather than overwritten in place, so
the pre-fix numbers stay reproducible for comparison.

USAGE  ./vbt-env/bin/python rebuild_caches.py [--symbols ES NQ]
"""
import os, shutil, argparse, importlib.util, logging
import numpy as np
import pandas as pd

import session

ROOT   = os.path.dirname(os.path.abspath(__file__))
CACHE  = os.path.join(ROOT, 'cache')
BACKUP = os.path.join(CACHE, 'legacy_dst_bug')

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger('rebuild')


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def prep_va(va_db):
    """restore hvn/lvn lists from parquet round-trips (strings or already lists)"""
    va = va_db.copy()
    for col in ['hvn_levels', 'lvn_levels']:
        if col not in va.columns:
            va[col] = [[] for _ in range(len(va))]
            continue
        va[col] = va[col].apply(
            lambda x: x if isinstance(x, list) else
            [] if str(x) in ('[]', 'nan', '') else
            [float(v) for v in str(x).strip('[]').split(',') if v.strip()])
    return va


def add_normalizations(days_df, rth):
    """RV-20, volume z-score, IB/RV ratio and IB size buckets (notebook cell #11)."""
    r = rth.copy(); r['date'] = r.index.normalize()
    daily_close = r.groupby('date')['close'].last()
    daily_vol   = r.groupby('date')['volume'].sum()

    log_ret = np.log(daily_close / daily_close.shift(1))
    rv20    = log_ret.rolling(20).std() * np.sqrt(252)
    vol_z   = ((daily_vol - daily_vol.rolling(60).mean()) /
               daily_vol.rolling(60).std().replace(0, np.nan))

    df = days_df.copy()
    df.index = pd.to_datetime(df.index)
    df['rv20']        = rv20.reindex(df.index)
    df['vol_zscore']  = vol_z.reindex(df.index)
    df['ib_pct']      = df['ib_range'] / df['open_px']
    df['ib_rv_ratio'] = df['ib_pct'] / (df['rv20'] / np.sqrt(252))
    df['ib_size']     = pd.qcut(df['ib_rv_ratio'].dropna(), q=3,
                                labels=['narrow', 'normal', 'wide'], duplicates='drop')
    return df


def backup(path):
    if os.path.exists(path):
        os.makedirs(BACKUP, exist_ok=True)
        dst = os.path.join(BACKUP, os.path.basename(path))
        if not os.path.exists(dst):
            shutil.copy2(path, dst)
            log.info('  backed up %s → legacy_dst_bug/', os.path.basename(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', nargs='+', default=['es', 'nq'])
    args = ap.parse_args()

    mod = _load('amt_classify', os.path.join(ROOT, 'amt_classify.py'))

    for sym in [s.lower() for s in args.symbols]:
        cont = os.path.join(CACHE, f'{sym}_continuous.parquet')
        if not os.path.exists(cont):
            log.warning('%s: no continuous cache, skipping', sym.upper()); continue

        df = pd.read_parquet(cont); df.index = pd.to_datetime(df.index)
        rth = session.get_rth(df)
        ndays = rth.index.normalize().nunique()
        log.info('%s: %s RTH bars over %d sessions (DST-correct 09:30-16:00 ET)',
                 sym.upper(), f'{len(rth):,}', ndays)

        va_path   = os.path.join(CACHE, f'{sym}_va.parquet')
        days_path = os.path.join(CACHE, f'{sym}_days.parquet')
        backup(va_path); backup(days_path)

        log.info('%s: building value-area database …', sym.upper())
        va = mod.build_va_database(rth)
        save = va.copy()
        for c in ['hvn_levels', 'lvn_levels']:
            if c in save.columns:
                save[c] = save[c].apply(str)
        save.to_parquet(va_path)
        log.info('%s: VA database %d days → %s', sym.upper(), len(va), os.path.basename(va_path))

        log.info('%s: classifying days …', sym.upper())
        irv = mod.calc_intraday_rv(rth, window=20)
        irv_dict = {d.date(): v for d, v in irv.items() if not np.isnan(v)}
        days = mod.classify_days(rth, prep_va(va), irv_dict=irv_dict)
        days = add_normalizations(days, rth)
        days.to_parquet(days_path)
        log.info('%s: days %d rows, %d cols → %s',
                 sym.upper(), len(days), len(days.columns), os.path.basename(days_path))
        for col in ['day_type', 'open_type']:
            if col in days.columns:
                log.info('%s %s:\n%s', sym.upper(), col,
                         days[col].value_counts().to_string())

    log.info('done — legacy caches preserved in %s', BACKUP)


if __name__ == '__main__':
    main()
