# indices/ — Market Profile & intraday structure on ES/NQ

Honest-methodology research on the equity index itself: expanding walk-forward,
train-only fitting, point-in-time features, BH-FDR on every multi-cell search, and an
incrementality gate that a signal must pass or be dropped. Negative results are kept.

```
session.py           DST-aware cash session — the single source of truth
rebuild_caches.py    regenerates the MP caches linearly (ES + NQ)
core/                Dalton Market Profile + intermarket regime engine
autoencoders/        unsupervised embeddings of intraday structure (PyTorch)
structure_tests/     can one structure predict another?  (all null)
vol_tests/           does IB structure predict volatility, and is it tradeable?
```

Everything is run on ES 2010–2026 with an honest time split (train ≤2019 / test ≥2020),
except where the options overlap forces a later split.

---

## session.py — read this first

The pipeline used to hardcode the session as fixed UTC minutes (14:30–21:00), which is
the US cash session **only under EST**. On EDT days the real session is 13:30–20:00 UTC,
so the old filter silently captured 10:30–17:00 ET: the "open" was the 10:30 price, the
"IB" was the **second** hour, and the session ran an hour past the close. **3248 of 4961
days (65%) were measured on the wrong window** — silently, because the wrong window still
holds ~390 one-minute bars. Confirmed from the volume profile (open/close volume spikes
land at 13:30 / 19:59–20:00 UTC in summer, 14:30 / 20:59–21:00 in winter).

All results here are on the corrected session. `vol_tests/vol_dst_recheck.py` recomputes
the headline both ways — the finding survives and is slightly stronger on the true session.

## core/ — Market Profile + regime engine

| File | Role |
|------|------|
| `amt_classify.py` | Dalton primitives: value area, POC, HVN/LVN, day type, opening type |
| `intermarket_lab.py` | intermarket/macro GMM regime engine + vol-term/credit features (also used by the `options/` track) |
| `amt_stats.ipynb` | 25-cell pipeline: caches → causal feature layer → L0–L3 regime/shape architecture → the decisive Dalton test |
| `intermarket_regime.ipynb` | intermarket regime as a forward volatility predictor |

`amt_stats.ipynb` is the notebook of record. Its own results: direction — nothing
survives FDR (all q ≥ 0.44); volatility magnitude — strongly significant (q to 2.4e-05);
decisive post-IB Dalton test — all q = 0.90.

## autoencoders/ — unsupervised structure

Each is `AE → latent → clustering`, taxonomy size chosen by **BIC argmin** on train.

| File | What it learns |
|------|----------------|
| `day_shape_autoencoder.py` | day profile shape (volume-by-price, range-normalised) |
| `open_type_autoencoder.py` | opening trajectory, direction-invariant, + `open_location` context |
| `ib_type_autoencoder.py` | Initial-Balance types from 10 causal structural features |

Findings: the latent is a faithful shape embedding (64→8 with almost no loss of
day-type information); archetypes rediscover the Dalton geometry unsupervised
(auction vs directional vs reversal); but IB structure is a **continuum, not discrete
types** — BIC has only a shallow minimum on a flat plateau and AIC diverges.

## structure_tests/ — can one structure predict another?

| File | Question | Answer |
|------|----------|--------|
| `predict_day_type.py` | day type from opening × IB type | dependence is real (χ² p=1.7e-30, 14/36 FDR cells) but rarely flips the argmax |
| `predict_day_type_full.py` | + open position + prior day | **the apparent skill is label mechanics** — on the disjoint post-IB target all of it vanishes |
| `predict_ib_type.py` | IB type from opening, prior profile, open position | prior profile is a complete null (χ² p=0.94); the opening explains a lot but that is **same-window overlap, not forecast** |
| `predict_open_type.py` | opening archetype from prior profile + regime | null, including the continuous latent (OOS R² negative) |

Across the board: inside one hour structure is tightly linked; **across the day boundary
almost nothing transfers.** Also confirmed 5× — discretising a continuum destroys signal,
so use types for interpretation and continuous features for modelling.

## vol_tests/ — the one positive result, and why it is not tradeable

| File | Role |
|------|------|
| `predict_post_ib_vol.py` | IB structure → post-IB realised vol / range |
| `vol_incrementality.py` | two-way gate against the existing options vol stack |
| `delta_one_ib_vol.py` | can the forecast be monetised on ES alone? |
| `iv_smoke_test.py` | is the first hour already priced into 0DTE IV at 10:30? |
| `vol_dst_recheck.py` | headline recomputed under the legacy vs corrected session |

**The forecast is real.** Over a trailing-vol baseline, OOS: post-IB realised vol
R² 0.174 → **0.516** (ΔR² +0.342), post-IB range 0.192 → 0.446; Spearman +0.72;
predicted quintiles monotone, Q5/Q1 = **×2.66** in vol terms. IB *shape* adds ~+0.12 R²
beyond IB *width* alone.

**But it is not monetisable**, on three independent counts:
- *direction* — IB-breakout-to-close conditioned on predicted vol: 0/5 quintiles survive
  FDR, unconditional −1.32bp (t=−0.67), Spearman(forecast, trade P&L) = −0.017. The
  quintile spread is cost-invariant, so this is an absence of signal, not costs.
- *sizing* — moot: scaling needs a base edge, and there is none.
- *volatility itself* — against the contemporaneous 0DTE price the increment is ~zero:
  on SPY and QQQ (30 days each) IB range → realised ρ≈0.47 (our signal replicates), but
  implied → realised ρ≈0.79, and conditional on the 10:30 price the IB adds nothing
  (ρ −0.02 / +0.08, R²≈0), independently on both instruments.

⚠️ **Walk-back worth stating plainly:** the incrementality gate beat *yesterday's* EOD
option stack, not *today's* price. R²=0.52 measured how much better the first hour is
than yesterday's vol — not than the market. By 10:30 dealers have repriced 0DTE to the
actual IB. Power caveat: 30 days excludes a *large* edge, not a small one.

**Standing use:** the first hour is a vol-regime sensor for **risk normalisation, not
alpha** — position size and stop width scaled to the expected post-IB range. Reopening
the alpha question needs long intraday OPRA history (hundreds of days, not 30) plus a
multivariate test on the full IB shape.

---

## Running

Scripts resolve `session.py` and the cached data from the `indices/` root, so run them
from anywhere:

```bash
python vol_tests/predict_post_ib_vol.py
python autoencoders/ib_type_autoencoder.py --k 3
python rebuild_caches.py --symbols es nq       # after any session/pipeline change
```

Figures are written next to the script that produces them. Launch Jupyter from `core/`
so the notebook's relative paths resolve. Market data is licensed and not included —
see the root README for the expected layout; replace the `YOUR_FRED_API_KEY` placeholder
with your own free FRED key.
