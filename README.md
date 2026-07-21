# Index Vol & Flow Research

Honest-methodology backtests of systematic strategies on equity **indices** (ES/NQ
futures, SPX/NDX options), plus a full **Market Profile** (Dalton) test suite.

The organizing idea is **flow-counterparty alpha**: earn premium by being the
counterparty to participants who trade *not by choice* — forced hedging, vol-target
and risk-parity rebalancing, dealer gamma hedging, and biased retail flow. Edge is
sought in **volatility / risk-premium / relative-value**, not outright direction.

Everything here is run under a strict methodology: expanding walk-forward, train-only
fitting, point-in-time features, FDR correction on every multi-hypothesis search, an
incrementality gate (a new signal must beat the existing stack out-of-sample or it is
dropped), and real execution costs. Negative results are kept, not hidden.

> ⚠️ **Research code, not investment advice.** No market data is included — the inputs
> are licensed (Databento, Intrinio) and must be sourced separately (see *Data*).

---

## Layout

The repo is split into two tracks, each self-contained in its own folder:

```
options/   — options volatility strategy (GEX-gated short-vol engine)
indices/   — index tests: Market Profile (Dalton) + intermarket regime
docs/      — research notes, project map, idea backlog
```

### `options/` — options vol strategy
| File | What it does |
|------|--------------|
| [`intrinio_options.py`](options/intrinio_options.py) | EOD options-chain fetcher (cache + resume), **self-computed IV/greeks** (vendor-independent), and VRP / IV-surface / **GEX** / positioning features. |
| [`backtest.py`](options/backtest.py) | Consolidated point-in-time backtest of the short-vol engine (1DTE iron condor, GEX+macro gate, inverse-IV sizing). Honest marks, held-to-expiry. |
| [`live_signal.py`](options/live_signal.py) | Daily live signal for the same engine — same code path backtest ↔ live. |
| [`options_vrp_gex.ipynb`](options/options_vrp_gex.ipynb) | **Main options study** — VRP premium, GEX→vol, nested incrementality, direction (FDR), matched-horizon, subperiod, P&L, cost-sweep, dealer-vs-retail positioning, stress episodes. |

### `indices/` — index tests
Full write-up in [`indices/README.md`](indices/README.md).

| File | What it does |
|------|--------------|
| [`session.py`](indices/session.py) | **DST-aware cash session — the single source of truth.** The old fixed-UTC window was EST-only, so 65% of days were silently measured on 10:30–17:00 ET. |
| [`amt_classify.py`](indices/amt_classify.py) | **Market Profile / Dalton** primitives — value area, POC, HVN/LVN, day-type classification. |
| [`intermarket_lab.py`](indices/intermarket_lab.py) | Intermarket & macro **regime engine** (GMM), plus vol-term / credit crisis-filter features from FRED. No Market Profile. |
| [`amt_stats.ipynb`](indices/amt_stats.ipynb) | Market Profile statistical test suite on ES (2010–2026) — 25 cells, runs clean end-to-end. |
| [`intermarket_regime.ipynb`](indices/intermarket_regime.ipynb) | Intermarket/macro regime model as a forward volatility predictor. |
| `*_autoencoder.py` | Unsupervised PyTorch embeddings of day shape, opening trajectory and Initial-Balance structure; taxonomy size by BIC argmin. |
| `predict_*.py` | Can one structure predict another (day / IB / opening type)? **All null** — the apparent day-type skill is label mechanics. |
| `*_vol*.py`, `iv_smoke_test.py` | IB structure → post-IB volatility (**OOS R² 0.52, ΔR² +0.34**), plus the three monetisation tests that closed it. |

> **Cross-track dependency:** the options engine reuses `indices/intermarket_lab.py`
> for its macro crisis-filter (vol-term / credit). `backtest.py`, `live_signal.py` and
> `options_vrp_gex.ipynb` load it from `../indices/`, so keep both folders side by side.

### Research notes (`docs/`)
Design docs, the running project map, and the idea backlog — including the honest
write-ups of what was **dropped and why** (`PROJECT.md`, `RESEARCH.md`,
`indices_execution_priorities.md`, and the liquidity/L3 idea files).

---

## Findings (honest summary)

- ❌ **Market Profile / Dalton — no directional alpha.** A full honest rebuild
  (expanding-WF, train-only clustering, FDR, incrementality) found no tradeable
  direction edge from MP, even intraday. One intraday-segment signal survived FDR but
  decomposed into overnight-gap mean-reversion, sub-cost and year-unstable. Kept as a
  reference test suite; **not** a live sleeve.
- ✅ **GEX-gated short-vol — validated 2021–2026, cross-instrument (SPY/SPX, QQQ/NDX).**
  VRP as a *size* multiplier + GEX(0–7d→all-DTE) gate + vol-term/credit macro filter.
  Forward inverse-IV sizing `size=(REF_IV/IV)²` is the key risk fix; all backward-looking
  controls (vol-target, DD-cap, equity-kill) were net-negative. Wings (iron condor) cap
  an otherwise irreducible single-day gap tail (Monte-Carlo jump-diffusion: naked ruin
  ~3.5% → 0%).
- ⚖️ **Intraday: the first hour forecasts the day's volatility — but it is not tradeable.**
  IB structure predicts post-IB realised vol strongly (OOS R² 0.174 → **0.516**, ΔR² +0.342,
  Q5/Q1 ×2.66). Three independent monetisation tests all fail: no directional edge
  (Spearman with trade P&L −0.017), nothing to size without a base edge, and against the
  contemporaneous 10:30 0DTE price the increment is ~zero on both SPY and QQQ. A useful
  **risk-normalisation** input, not alpha.
- ❌ **Direction** — no edge found anywhere, consistent across all work. **Vol and tails**
  are the predictable targets.

See `docs/PROJECT.md` for the full alive-vs-dead ledger and methodology principles.

---

## Data (not included — bring your own)

The code and notebooks expect local data that is **licensed and gitignored**:

| Source | Used for | Expected local layout |
|--------|----------|-----------------------|
| **Databento** GLBX (`.dbn`, OHLCV 1m/1d) | ES/NQ/ZN/CL/ZT/DX futures | `data/GLBX-*/*.dbn`, `data/IFUS-*/*.dbn` |
| **Databento** OPRA | VIX daily | `data/OPRA-*/` |
| **Intrinio** (Individual plan) | EOD options chains (SPY/QQQ/SPX/SPXW/NDX/NDXP, 2021-09→2026-06) | `cache/intrinio/<SYM>/*.parquet` |
| **FRED** (free) | VIX/VIX3M/VXN term + HY/IG credit | fetched at runtime |

Derived feature caches land under `cache/` and are regenerated by the code.

### API keys (via environment, never hardcoded)
```bash
export INTRINIO_API_KEY=...     # or write it to ~/.intrinio_key
export FRED_API_KEY=...         # free from https://fred.stlouisfed.org/docs/api/api_key.html
```
`live_signal.py` reads the Intrinio key in order: `INTRINIO_API_KEY` env → `~/.intrinio_key`
→ `<repo>/.intrinio_key` (gitignored). Replace the `YOUR_FRED_API_KEY` placeholder in the
code/notebooks with your own free FRED key (or wire it to `FRED_API_KEY`).

---

## Setup & running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# backtest the short-vol engine (caches features on first run)
python options/backtest.py --ref-iv 0.14 --base 1

# emit today's live signal (falls back to latest cached EOD if today unpublished)
python options/live_signal.py --use-cache
```

Notebooks run under Jupyter once the data above is in place. Launch Jupyter from
inside the notebook's own folder (`options/` or `indices/`) so the relative module
paths resolve.

---

## Disclaimer

For research and educational purposes only. Nothing here is financial advice or a
solicitation to trade. Backtests are hypothetical, carry look-ahead/overfit risk despite
best efforts, and past performance does not indicate future results. Market data is the
property of its respective vendors and is not distributed with this repository.
