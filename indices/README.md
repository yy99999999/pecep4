# indices/ — index tests (Market Profile + intermarket regime)

Honest-methodology tests on the equity index itself (ES/NQ futures, intermarket/macro):
expanding walk-forward, train-only fitting, point-in-time features, BH-FDR on every
multi-cell search, and an incrementality gate a signal must pass or be dropped.
Negative results are kept, not hidden.

## Read this first — the session

| File | Role |
|------|------|
| `session.py` | **DST-aware cash session (09:30–16:00 America/New_York) — the single source of truth.** Import it; never hardcode UTC minutes. |
| `rebuild_caches.py` | Regenerates the MP caches (ES + NQ) linearly. Legacy caches are preserved rather than overwritten. |

The pipeline used to define the session as fixed UTC minutes (14:30–21:00), which is the
US cash session **only under EST**. On EDT days the real session is 13:30–20:00 UTC, so
that filter silently captured 10:30–17:00 ET: the "open" was the 10:30 price, the "IB"
was the **second** hour, and the day ran an hour past the close. **3248 of 4961 trading
days (65%) were measured on the wrong window** — silently, because the wrong window still
holds ~390 one-minute bars. Confirmed from the volume profile (open/close volume spikes
land at 13:30 / 19:59–20:00 UTC in summer, 14:30 / 20:59–21:00 in winter).

Everything below is on the corrected session. `vol_dst_recheck.py` recomputes the
headline under both definitions — it survives the fix and is slightly stronger on the
true session (R² 0.484 → 0.512).

## Core

| File | Role |
|------|------|
| `amt_classify.py` | Market Profile / Dalton primitives — value area, POC, HVN/LVN, day-type |
| `intermarket_lab.py` | Intermarket & macro regime engine (GMM) + vol-term/credit features (FRED). Also reused by the `options/` track. |
| `amt_stats.ipynb` | 25-cell pipeline: caches → causal feature layer → L0–L3 regime/shape architecture → the decisive Dalton test |
| `intermarket_regime.ipynb` | Intermarket/macro regime as a forward volatility predictor |

`amt_stats.ipynb` is the notebook of record and runs clean end-to-end. Its own results:
direction — nothing survives FDR (all q ≥ 0.44); volatility magnitude — strongly
significant (q down to 2.4e-05); decisive post-IB Dalton test — all q = 0.90.

## Neural structure models (PyTorch autoencoders)

Unsupervised embeddings of intraday structure, each `AE → latent → clustering`, on
ES 2010–2026 with an honest time split (train ≤2019 / test ≥2020). Taxonomy size is
chosen by **BIC argmin** on train.

| File | What it learns |
|------|----------------|
| `day_shape_autoencoder.py` | Day **profile shape** (volume-by-price, range-normalised). Latent compresses 64→8 with almost no loss of day-type information; archetypes separate double-distribution from normal-variation. |
| `open_type_autoencoder.py` | **Opening trajectory** (first 60 min, direction-invariant) + `open_location` context. Rediscovers drive / auction / reversal geometry unsupervised. |
| `ib_type_autoencoder.py` | **Initial-Balance types** from 10 causal structural features. BIC/AIC selection over the latent. |

**IB structure is a continuum, not discrete types.** BIC has only a shallow, non-robust
minimum on a flat plateau while AIC diverges; the elbow sits at k=3 → *directional /
reversal / wide-expansion*. No robust post-IB directional edge (only a weak
anti-continuation lean in the reversal type, sub-cost).

## Structure tests — can one structure predict another?

| File | Question | Answer |
|------|----------|--------|
| `predict_day_type.py` | day type from `open_type` × `ib_type` | dependence is statistically real (χ² p=1.7e-30, 14/36 cells FDR-significant) but the probabilistic edge rarely flips the hard argmax |
| `predict_day_type_full.py` | + open position + prior day type | **the apparent skill is label mechanics** — see below |
| `predict_ib_type.py` | IB type from opening, prior profile, open position | prior profile is a complete null (χ² p=0.94, 0/24 FDR); the opening explains a lot, but that is **same-window overlap, not forecast** |
| `predict_open_type.py` | opening archetype from prior-profile position + regime | null, including the continuous latent (OOS R² negative — so not a discretisation artefact) |

⚠️ **`day_type` predictability is label mechanics, not forecastability.** `classify_day_type`
is largely a function of IB quantities (`ib_width_cat`, `ib_range/day_range`, `broken_dir`),
so IB structure predicts the **label**. Target the *disjoint* post-IB profile instead and
all of it vanishes: every block sits at or below the majority baseline with positive
Δlog-loss. Prior-day type adds ~nothing anywhere, and day-type persistence exists only in
the rule labels (χ² p=5e-4, 3/36 cells) — not in the unsupervised archetypes.

**Across the board:** inside one hour structure is tightly linked; **across the day
boundary almost nothing transfers.** Also confirmed 5× — discretising a continuum
destroys signal, so use types for interpretation and continuous features for modelling.

## Volatility tests — the one positive result, and why it is not tradeable

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
beyond IB *width* alone — that is the genuinely new content from the autoencoder work.

**But it is not monetisable**, on three independent counts:

- **direction** — IB-breakout-to-close conditioned on predicted vol: 0/5 quintiles survive
  FDR, unconditional −1.32bp (t=−0.67), Spearman(forecast, trade P&L) = **−0.017**. The
  quintile spread is cost-invariant, so this is an absence of signal, not a cost problem.
- **sizing** — moot: scaling needs a base edge, and there is none.
- **volatility itself** — against the contemporaneous 0DTE price the increment is ~zero.
  On SPY and QQQ (30 days each, underlying path reconstructed from the options by
  put-call parity): IB range → realised ρ≈0.47 (our signal replicates out-of-sample and
  out-of-instrument), but implied → realised ρ≈0.79, and conditional on the 10:30 price
  the IB adds nothing (ρ −0.02 / +0.08, R²≈0) — independently on both instruments.

⚠️ **Walk-back worth stating plainly:** the incrementality gate beat *yesterday's* EOD
option stack, not *today's* price. R²=0.52 measured how much better the first hour is
than yesterday's vol — not than the market. By 10:30 dealers have already repriced 0DTE
to the actual IB. Power caveat: 30 days excludes a *large* edge, not a small one.

## Findings

- ❌ **Market Profile / Dalton — no directional alpha.** Confirmed across the rule-based
  suite, the unsupervised archetypes, and the decisive post-IB test (all q = 0.90).
- ❌ **Structure → structure** — nothing transfers across the day boundary.
- ✅ **Structure → volatility** — the first hour genuinely forecasts the volatility of the
  rest of the day. Strong, monotone, cross-validated.
- ❌ **…but not tradeable** — no directional edge, nothing to size, and already in the
  0DTE quote by 10:30.
- ✅ The intermarket regime engine **is** a real forward *volatility* predictor — kept, and
  reused by the options macro-filter.

**Standing use:** treat the first hour as a vol-regime sensor for **risk normalisation,
not alpha** — position size and stop width scaled to the expected post-IB range for
whatever strategy you already run. Reopening the alpha question needs long intraday OPRA
history (hundreds of days, not 30) plus a multivariate test on the full IB shape.

---

Launch Jupyter from inside this folder so the notebooks' `./module.py` paths resolve.
Replace the `YOUR_FRED_API_KEY` placeholder with your own free FRED key. Market data is
licensed and not included (see root README). Run `rebuild_caches.py` after any change to
the session or the classifier.
