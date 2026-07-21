"""
session.py — single source of truth for the US cash session (DST-AWARE).

WHY THIS MODULE EXISTS
  The pipeline used to hardcode the session as fixed UTC minutes (14:30-21:00), which
  is the US cash session only under EST. On EDT days the real session is 13:30-20:00
  UTC, so the fixed filter silently captured 10:30-17:00 ET:
      · "open"  = the 10:30 price, not the session open
      · "IB"    = the SECOND hour (10:30-11:30), not the initial balance
      · session = one hour PAST the 16:00 equity close
  3248 of 4961 trading days (65%) are EDT, so most of the history was measured on the
  wrong window — silently, because the wrong window still holds ~390 one-minute bars.
  Verified from the volume profile: the open/close volume spikes land at 13:30 and
  19:59-20:00 UTC in summer, and at 14:30 and 20:59-21:00 UTC in winter.

USAGE
  import session
  rth = session.get_rth(es_continuous)     # tz-naive UTC bars in → cash-session bars out

  The returned frame is indexed by NAIVE New-York time, so `.normalize()` yields the
  correct trading date and all downstream date joins keep working unchanged.
"""
import pandas as pd

TZ           = 'America/New_York'
RTH_OPEN_ET  = 9 * 60 + 30      # 09:30 ET
RTH_CLOSE_ET = 16 * 60          # 16:00 ET (exclusive)


def to_ny(index):
    """DatetimeIndex (naive = UTC, or tz-aware) → tz-aware New-York index."""
    idx = pd.DatetimeIndex(index)
    return (idx.tz_localize('UTC') if idx.tz is None else idx).tz_convert(TZ)


def get_rth(df, open_et=RTH_OPEN_ET, close_et=RTH_CLOSE_ET):
    """Filter intraday bars to the US cash session, DST-aware.

    Returns a copy indexed by naive New-York time. Half-days (early 13:00 ET closes)
    simply yield fewer bars — callers already guard on bar counts.
    """
    ny = to_ny(df.index)
    m = ny.hour * 60 + ny.minute
    mask = (m >= open_et) & (m < close_et)
    out = df[mask].copy()
    out.index = ny[mask].tz_localize(None)
    return out


def is_dst(index):
    """True where the timestamp falls in EDT (summer) — the days the old filter broke."""
    ny = to_ny(index)
    return pd.Series([bool(x.dst()) for x in ny], index=pd.DatetimeIndex(index))
