# options/ — options volatility strategy

GEX-gated short-vol engine on index options (SPY/QQQ/SPX/SPXW/NDX/NDXP).
**VRP** as a size multiplier + **GEX**(0–7d→all-DTE) gate + vol-term/credit macro
filter; forward inverse-IV sizing `size=(REF_IV/IV)²`; 1DTE iron condor to cap the
single-day gap tail. Validated 2021–2026, cross-instrument.

| File | Role |
|------|------|
| `intrinio_options.py` | EOD chain fetcher + self-computed IV/greeks + VRP/GEX/positioning features |
| `backtest.py` | Point-in-time backtest (honest marks, held-to-expiry) |
| `live_signal.py` | Daily live signal — same code path as the backtest |
| `options_vrp_gex.ipynb` | Full study: VRP, GEX→vol, incrementality, direction (FDR), P&L, cost-sweep, stress |

**Run** (from repo root):
```bash
python options/backtest.py --ref-iv 0.14 --base 1
python options/live_signal.py --use-cache
```

**Dependency:** loads `../indices/intermarket_lab.py` for the macro crisis-filter —
keep the `indices/` folder alongside. Keys via env (`INTRINIO_API_KEY`, `FRED_API_KEY`)
or `~/.intrinio_key`; data is licensed and not included (see root README).
