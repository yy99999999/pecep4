# indices/ — index tests (Market Profile + intermarket regime)

Honest-methodology tests on the equity index itself (ES/NQ futures, intermarket/macro).

| File | Role |
|------|------|
| `amt_classify.py` | Market Profile / Dalton primitives — value area, POC, HVN/LVN, day-type |
| `intermarket_lab.py` | Intermarket & macro regime engine (GMM) + vol-term/credit features (FRED). Also reused by the `options/` track. |
| `amt_stats.ipynb` | Market Profile statistical test suite on ES (2010–2026) |
| `intermarket_regime.ipynb` | Intermarket/macro regime as a forward volatility predictor |

### Neural structure models (PyTorch autoencoders)
Unsupervised embeddings of intraday structure, each `AE → latent → clustering`, all on
ES 2010–2026 with an honest time split (train ≤2019 / test ≥2020).

| File | What it learns |
|------|----------------|
| `day_shape_autoencoder.py` | Day **profile shape** (volume-by-price, range-normalised). Latent compresses 64→8 with almost no loss of day-type information (macro-F1 0.48 vs 0.49 raw); archetypes separate double-distribution from normal-variation. |
| `open_type_autoencoder.py` | **Opening trajectory** (first 60 min, direction-invariant) + `open_location` context. Rediscovers drive / auction / reversal geometry unsupervised. |
| `ib_type_autoencoder.py` | **Initial-Balance types** (10 causal structural features). BIC/AIC selection over the latent. |
| `predict_day_type.py` | Track item 1 — can `day_type` be predicted at IB close from `open_type` × `ib_type`? Probabilities-first (contingency, χ², BH-FDR, Wilson LB), then models under an incrementality gate. |

**Findings:** MP gives **no tradeable directional edge** (even intraday; the one
FDR-surviving segment signal decomposed into sub-cost overnight-gap mean-reversion).
The intermarket regime engine **is** a real forward *volatility* predictor — kept, and
reused by the options macro-filter. Direction: no edge anywhere; vol/tails are the
predictable targets.

From the neural models:
- **IB structure is a continuum, not discrete types.** BIC has only a shallow, non-robust
  minimum on a flat plateau (AIC diverges); the elbow sits at k=3 → *directional /
  reversal / wide-expansion*. No robust post-IB directional edge (only a weak
  anti-continuation lean in the reversal type, sub-cost).
- **`day_type` genuinely depends on `open_type` × `ib_type`** (χ² p=1.7e-30, 14/36 cells
  FDR-significant; e.g. `open_drive|reversal-IB` → P(double_distribution) 53% vs 40% base).
  But **discretising the IB is lossy**: raw continuous IB features predict day_type far
  better OOS (3-class acc 0.437) than the 3 discrete types (0.399) over a 0.377 baseline —
  and the probabilistic edge rarely flips the hard argmax.
- `open_type` (as defined in `amt_classify`) is purely *open position within the IB*, so
  `open_location` is an **orthogonal second axis**, not a refinement of it.

Launch Jupyter from inside this folder so the notebooks' `./module.py` paths resolve.
Replace the `YOUR_FRED_API_KEY` placeholder with your own free FRED key. Market data is
licensed and not included (see root README).
