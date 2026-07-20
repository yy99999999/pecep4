# indices/ — index tests (Market Profile + intermarket regime)

Honest-methodology tests on the equity index itself (ES/NQ futures, intermarket/macro).

| File | Role |
|------|------|
| `amt_classify.py` | Market Profile / Dalton primitives — value area, POC, HVN/LVN, day-type |
| `intermarket_lab.py` | Intermarket & macro regime engine (GMM) + vol-term/credit features (FRED). Also reused by the `options/` track. |
| `amt_stats.ipynb` | Market Profile statistical test suite on ES (2010–2026) |
| `intermarket_regime.ipynb` | Intermarket/macro regime as a forward volatility predictor |

**Findings:** Market Profile gives **no tradeable directional edge** (even intraday; the
one FDR-surviving segment signal decomposed into sub-cost overnight-gap mean-reversion).
The intermarket regime engine **is** a real forward *volatility* predictor — kept, and
reused by the options macro-filter. Direction: no edge anywhere; vol/tails are the
predictable targets.

Launch Jupyter from inside this folder so the notebooks' `./module.py` paths resolve.
Replace the `YOUR_FRED_API_KEY` placeholder with your own free FRED key. Market data is
licensed and not included (see root README).
