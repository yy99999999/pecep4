# Quant research — project map & plan

_Last updated: 2026-06-22_

## ⚫ CLOSED THREAD (2026-07-02) — Market Profile intraday-segment (DONE, no tradeable edge)
MP was dropped for WHOLE-DAY direction (no edge). REVIVED at intraday-segment granularity, one signal found (open>VAH→S1-down, q=0.016). Deepened at full power → **CLOSED: the signal is repackaged overnight-gap mean-reversion (OLS β_gap t=−5.07, VAH dummy t=+0.40=zero incremental), ~1bp sub-cost (net −1.05bps/trade = loses), year-unstable.** MP×GEX combo also dead (regime-confound). No tradeable intraday ES direction from MP in sign or magnitude. Scripts: `/tmp/mp_seg.py`, `/tmp/mp_gex_combo.py`, `/tmp/mp_deep.py`. See memory `mp-intraday-segments`. **Do NOT revive MP.** Original thread notes retained below for reference:
### (archived) MP intraday-segment detail
Predict INTRADAY SEGMENT direction relative to PRIOR-DAY Market Profile (Value Area / POC) + VWAP, conditioned on zone-tests. **Probabilities-FIRST, strategy only after.**
- **Segments (clock-aligned):** S1=0-15m · S2=15-60m · S3=60-120m · S4=last-hour. Direction = sign(seg_close−seg_open).
- **Prior-day MP** = volume profile (POC=max-vol bin; VAH/VAL=70% value area). **Contexts:** 4-zone open-location (open vs VAH/POC/VAL, POC=divider); zone-test flags (S1 touched VAH/POC/VAL); VWAP position. Stats: P(seg up | context) + two-prop + BH-FDR. Data: `es_continuous` 1-min RTH 2010-26 (n=4105). Script: `/tmp/mp_seg.py`.
- **FINDING (one robust signal, rest noise):** 🎯 **open above prior VAH → first-15min (S1) fades DOWN, P(up)=46.8% vs 49.6% base (Δ−2.8, q=0.016 FDR)** = classic MP rejection of value-area extension; info concentrated in first 15m, dissipates by day-end (MP theory). 28 cells tested, ~2.8 FP expected → only q=0.016 trusted (theory-backed).
- 🔴 **MP × GEX COMBO — TESTED & DEAD (2026-07-02, `/tmp/mp_gex_combo.py`).** Overlaid option-structure (GEX regime / zero-gamma flip / gamma walls, self-recomputed IV, T-1→T lag) on MP segments. Intersection caps n~1158 (2021-26). Combo cell above_VAH|−gamma = biggest point effect (P(up)=41.4%, −1.74bps) BUT p=0.17, sub-cost (<2bp), and **subperiod-KILLER: whole effect in 2022 bear/−gamma yr; sign flips positive 2024-25** = regime-confound, not gamma×MP interaction. MP-only on 2021-26 also loses sig (q=0.59, n/4). Gamma overlay does NOT rescue MP. See memory `mp-intraday-segments`.
- **NEXT (if revisited):** MP-only deepening on FULL 2010-26 (has power): magnitude-vs-cost, gap-gradation, VWAP, acceptance/rejection; mirror open<VAL→S1-up. But full-sample magnitude ~1bp < cost → likely characterization-only, not a tradeable sleeve.

## 🅿️ PARKED — GEX/options engine (live-timing fragility)
Deployed 1DTE iron-condor (`live_signal.py`, `backtest.py`) but **realistic live timing collapses the edge:** GEX built from OI (publishes T+1) → gex_z lagged 1 day → Sharpe 1.04→0.31. Confidence-buffer (`gex_z(T-1)≥0.5`) recovers ~0.97 realistic (all years positive) BUT fragile to real 4-leg-condor fills → **paper-trade is the true test.** No clean real-time OI data → parked. Artifacts kept. See memory `vol-engine-deployment`.

## Organizing theory
**Flow-counterparty alpha**: earn premium by being counterparty to participants who trade NOT by choice — forced (margin/vol-target/dealer-hedging/rebalancing), systematically biased (hedgers pay vol premium = VRP; retail), info-disadvantaged, structurally constrained. Edge lives in **volatility / risk-premium / relative-value**, NOT outright direction. Power-first; breadth (IR=IC·√breadth) over rare setups.

## Status (what's alive vs dead)
- ❌ **Market Profile / Dalton (DROPPED).** Honest-methodology rebuild (expanding-WF, train-only clustering, FDR, incrementality) showed quantified MP gives NO directional alpha even intraday post-IB. Only vol predictable, and via intermarket/macro not MP. Legacy: `amt_classify.py`, `jupyter strats/amt_stats.ipynb`, `intermarket_regime.ipynb` (+ `intermarket_lab.py` engine, still used for vol-term/credit).
- ✅ **Vol-engine (VALIDATED on 2021-2026, cross-instrument):**
  **VRP (size) + GEX(0-7→all-DTE gate/tail) + vol-term/credit (macro crisis-filter).**
  - GEX-gated short-vol: Sharpe ~0.80@10% cost on SPY AND SPX; worst day −18bp vs −94 naive.
  - VRP_only loses; VRP best as size multiplier, not gate. naive short-vol loses.
  - macro-filter (VIX backwardation / credit) adds: 0.80→0.85.
  - direction: no edge anywhere (consistent across all work).
  - 90DTE OI-positioning: tested clean (non-overlap blocks, 4 instruments) → NOT a dealer-specific edge (SPX≠NDX, signs flip, n=54 noise) → dropped.
  - ✅ **REAL execution costs (deploy #1 CLOSED):** actual ATM-straddle round-trip spread SPY 0.56% / SPX 1.38% (vs assumed 10%) → cost-insensitive (×3 spread barely moves Sharpe). SPX BEATS SPY despite wider spread.
  - ✅ **RISK/SIZING (deploy #2 CLOSED):** **forward inverse-IV sizing** `sz=(REF_IV/IV)²` is the fix for short-vol (Sharpe 0.92→~2.1, Calmar →1.2-1.33). ALL backward-looking controls (realized-vol target, DD-cap, equity-kill, DD-floor) net-NEGATIVE — drawdowns are single-day gaps; reactive control fires late & chokes recovery. **VRP-weight dropped → combat = flat GEX+macro gate + forward IV-sizing.** REF_IV = risk-dial (Sharpe-invariant; sets maxDD); recommend 0.13-0.14 (maxDD −15/−17%, annRet 18-21%). Crisis-off = forward gates only.

## Data (Intrinio Individual plan)
- Options EOD via `get_options_prices_eod_by_ticker`: **2021-09 → 2026-06** only (deep history capped on Individual).
- Cached (`cache/intrinio/<SYM>/*.parquet`, ~1126-1181 days each): **SPY, QQQ, SPX, SPXW, NDX, NDXP**. SPX=monthly + SPXW=daily/weekly → full DTE (need BOTH; same NDX+NDXP). Combine via list: `daily_features(['SPX','SPXW'], recompute=True)`.
- 🔴 **Vendor IV/greeks BROKEN for SPX (~2.7× inflated); marks are clean** → we **self-compute IV+delta+gamma from marks** (`recompute=True`, `_recompute_iv_gamma`). Vendor-independent. SPY vendor IV was fine.
- Spot: SPY/QQQ from cache or inference; SPX/NDX via `infer_spot` (put-call parity) — accurate.
- FRED (free, key in code): VIX/VIX3M/VXN + HY/IG OAS → `intermarket_lab.vol_credit_features` (vol-term slope, credit).
- ⛔ **Add-on gated (trial did NOT unlock):** deep history 2008+ (500), bulk downloads (0 files), dark pool (403, needs access_codes). = paid bundle, price unquoted, $300+ deferred (cost-sensitive). UA = recent-only (no history). Constituents = current snapshot only (survivorship).

## Key files
- `intrinio_options.py` — fetcher (fetch_day/fetch_range, cache+resume+timeout), self-greeks (`_recompute_iv_gamma`, `_bs_iv/_bs_gamma`), features (`daily_features`, `iv_surface_features`, `gex`, `gex_by_dte`, `positioning_features`, `infer_spot`, `fetch_spot`, `realized_vol`), stats (`wilson_lb/bh_fdr/two_prop_p`).
- `intermarket_lab.py` — intermarket/macro regime engine + `vol_credit_features` (FRED).
- `jupyter strats/options_vrp_gex.ipynb` — MAIN options notebook. Cells: 1 imports, 2 features(+vc merge), 3 VRP premium, 4 GEX→vol, 5 nested incrementality, 6 direction(FDR), 7 matched-horizon (7a GEX-tail / 7b positioning non-overlap blocks), 8 subperiod GEX, 9 P&L, 10 variants×cost-sweep, 11 dealer-vs-retail positioning, 12 stress-episodes. `SYMBOL` switch: 'SPY'/'QQQ' or ['SPX','SPXW']/['NDX','NDXP'].
- Backups: `*.claude-edits.ipynb`. Git: branch `honest-pipeline-dalton-verdict`.

## Methodology principles (hard-won)
1. Honest WF, no lookahead; train-only fitting; point-in-time.
2. **FDR** (BH) on every multi-cell search; rank by CI lower-bound not point WR.
3. **Incrementality gate**: new signal/data must beat existing stack OOS or it's dropped (killed MP, positioning).
4. Power-aware: daily σ~1% vs tiny edges → need big n / less-noisy targets (vol/tails > mean direction).
5. Breadth > rare setups. Costs always in. Self-compute greeks (vendor-independent).

## Plan / next steps
1. ✅ DONE — stress-episode test (cell 12): gate flat 67% of worst days, Aug-2024 100% flat, Apr-2025 flat.
2. ✅ DONE — real execution costs (cell 8/9): spread SPY 0.56%/SPX 1.38%, cost-insensitive. Combat variant `VRPsz×GEX×macro`.
3. ✅ DONE — risk/sizing (cell 13): forward inverse-IV sizing on flat GEX+macro gate; backward-looking controls rejected; VRP-weight dropped. Sharpe ~2.1, REF_IV risk-dial.
4. ✅ DONE — intermarket-regime integration TESTED & DROPPED: GMM regime (2012-26 WF, `cache/intermarket_regime_wf.parquet`) is a real forward vol predictor but REDUNDANT with GEX+macro (gate already flattens 87% of danger regime-3 days; adding it: Sharpe 2.10→1.97). Two independent detectors agree = robustness confirmation, no combinable alpha. intermarket engine kept for deep-history stress-test + futures Track 2.
5. ✅ DONE — **DEPLOYED**: `live_signal.py` (gate `gex_z>=0 & vix_term_slope<=0` + inverse-IV sizing; gex_z>=0 fixed point-in-time threshold beats backtest's full-sample gate, Sharpe 2.28). Daily signal → `signals_log.csv`, recommends ~30-DTE ATM straddle. Key via env/`~/.intrinio_key`; `.gitignore` added. Verified end-to-end (cache mode). User TODO: create `~/.intrinio_key`, add cron, re-verify live key (SPY had 401). See [[vol-engine-deployment]].
6. **If budget allows:** add-on bundle → deep history 2008+ (crisis stress-test of GEX gate — the real survival test) + dark pool (incrementality). Ask support for price.
7. Later: contextual-bandit meta-allocation over PROVEN legs (not discovery); deployment (ALFRED PIT data, same code WF↔live).

## Operational notes (live deployment)
- **Run:** `python live_signal.py` (fetches trailing window of recent EOD + emits signal) · `--use-cache` (no fetch) · `--ref-iv 0.13|0.16` (risk-dial) · `--base N` (# straddles at normal IV = capital decision). Audit trail → `signals_log.csv`.
- **Cron (each trading morning, picks up prior-day EOD once published):** `30 8 * * 1-5 cd <repo> && ./vbt-env/bin/python live_signal.py >> cron_signal.log 2>&1`.
- **Timing:** Intrinio publishes day-T EOD options after close (often T+1 AM). "Today" returns 403 until then → script falls back to latest complete cached EOD. The trailing fetch-window backfills any missing recent day (already caught a missing SPX-monthly 06-15).
- **Key:** never hardcode. Read order env `INTRINIO_API_KEY` → `~/.intrinio_key` → `<repo>/.intrinio_key` (gitignored). Re-verify key periodically (a stale key gave SPY 401s).
- **Perf:** `daily_features(recompute=True)` recomputes self-greeks over full history (~90s/run) — fine daily; optimize to incremental if it ever matters.
- ✅ **TAIL-RISK (RESOLVED 2026-06-18: switched to iron condor).** Monte-Carlo (jump-diffusion crash-gaps): naked 1DTE strangle P(ruin>50%DD/5y)=3.5%, worst-day −64%, maxDD median −14% (backtest −3% understated 4.6×); ±5% wings → 0% ruin, worst-day −16.6%. live_signal.py now iron condor (OTM_PCT=0.012 short / WING_PCT=0.05 long). Original note below:
- 🔴 **(superseded) TAIL-RISK MITIGATION.** Live config = **naked short ATM straddle** → residual single-day GAP risk is irreducible (worst day −7.6%@REF0.13 .. −18%@REF0.20; the gate/IV-sizer are forward and can't stop a surprise gap). Two levers, in order of cost:
  1. **Lower REF_IV** (smaller base size) — free, just scales risk down linearly.
  2. **Buy wings → iron condor / short strangle with long tails** instead of naked straddle: cap the gap loss at a known max. Costs premium (lower carry / Sharpe) but converts unbounded tail into a fixed debit — likely worth it for an own-account short-vol sleeve. NOT yet backtested; needs the wing strikes priced from the chain (have bid/ask) and a re-run of cell 13 P&L with the capped payoff. **Do before scaling `--base` up.**
- **Other pending:** deep-history 2008+ crisis stress-test (paid add-on); execution is manual from the signal (no broker API wired).

## Future execution tracks (after current options deploy)
- **TRACK 2 — PRIORITY (prop-tradeable futures): intraday gamma-levels → ES/MES direction.** Same signal layer. SPX EOD OI + self-gamma → net GEX(K), zero-gamma flip, put/call walls, GEX ratio. spot>flip(+γ)→MR/fade-to-walls; spot<flip(−γ)→trend/breakout. Execute ES/MES intraday (data we have: EOD SPX options + ES 1-min `es_continuous`). = regime→execution layer over vol-engine (VRP+GEX+macro = risk/crisis-off). Caveats: crowding/decay (subperiod stability), intraday overfit DoF (strict OOS), ES costs. Revives intraday direction (daily had none).
- **TRACK 1 — secondary (BLOCKED: prop can't trade VIX): VX-futures short-vol execution.** Port straddle→short VX1 / VX calendar (alpha same, cleaner, carry=VRP). Needs VX futures (CBOE) + VVIX. ES alone = no edge.

## BREADTH PHASE (2026-06-24 — daily plan in `CHECKLIST.md`)
Pivot to **breadth: IR = IC·√breadth.** New principle — a sleeve is judged by **Sharpe × (1−corr-to-portfolio) on TAIL days**, not standalone Sharpe (corr→1 in crises; full-sample corr lies). Three tracks: **options breadth / L3 / prediction-markets**. See `CHECKLIST.md` + memory [[cross-asset-vrp-breadth]], [[kalshi-prediction-markets]].

🔴 **DEAD SLEEVES (2026-06-23, `/tmp/sleeves.py`, n=1117):** three `new_logic_liq.md` daily-feature ideas failed the gauntlet — **basis (ES−SPX) stress** = in-sample mirage (TRAIN mono −0.95 → TEST mono +0.02, full IC −0.063); **credit-vol composite** & **cascade flag** real but REDUNDANT with VIX/vix_term we already use (composite test IC +0.39 ≈ VIX +0.40; cascade worst-DD capture 20% < naive VIX-hi 26%). Lesson: easy daily macro/liquidity signals on SPX/ES are perimolot or sit inside VIX → independence must come from other assets / other time-mechanism / other data structure. **Do NOT build the basis/cascade modules from `new_logic_liq.md`.**

## Next frontiers (2026-06-17 — index-vol & futures-direction EXHAUSTED)
Status: deployed product = 1DTE ±1.2% strangle (honest ~1.3, real-marks). Everything that extends it failed incrementality; ALL futures-direction (daily/intraday/MR/trend/carry/bandit) = no robust net-of-cost edge. Futures gives only equity BETA (~0.8, can't improve). Genuinely-NEW structural premia remain, options-executable, NOT re-treads:

### A. Dispersion / correlation premium (NEW edge, not VRP)
- Mechanism: hedgers buy INDEX puts (cheap broad protection) → index IV inflated vs component IV. Index var < Σ component var (corr<1). Structural = index-hedging demand → **correlation risk premium**.
- Trade: **short index vol + long single-stock vol = short correlation** (delta/vega-balanced). Distinct from VRP (it's the corr premium, not the vol premium).
- Implied correlation: `ρ_imp = (σ²_index − Σ wᵢ²σᵢ²) / (Σ_{i≠j} wᵢwⱼσᵢσⱼ)`. Signal = ρ_imp high (index rich) → short corr; realized-vs-implied corr spread = the premium.
- Data: SPY/SPX index IV (have) + top-N component options (AAPL/MSFT/NVDA/AMZN/GOOG/META… via Intrinio by_ticker). ⚠️ survivorship (use current top holdings, caveat). Simplified v1: short SPY straddle + long top-5 component straddles (vega-weighted).
- Gauntlet: does implied−realized corr spread exist & is it harvestable after costs (many legs!)? FDR/incrementality/subperiods. Capital-intensive, many legs = main practical risk.
- Priority: the one genuinely-different OPTIONS edge untested. Moderate prior (documented prop strategy, structural).

### B. Cross-asset VRP — ✅ PRIMARY / ACTIVE (diversification, same edge / new markets)
- Same short-vol VRP+GEX+macro engine on **GLD / USO / TLT / IEF** — different asset classes → potentially UNCORRELATED VRP = real portfolio diversification (unlike 0DTE corr-0.80 / index-only). Bond-vol (rates) vs equity-vol (risk-appetite) = different drivers.
- GEX may not apply (different dealer structure) but VRP+vol-term-macro might. Test each: does the 1DTE-strangle engine hold per-underlying? **THE metric = P&L corr vs SPX on tail days.**
- **Data (2026-06-24):** GLD + USO ready; **TLT + IEF fetched** (`/tmp/fetch_bonds.py`, resumable, 1226-day calendar = USO's). **TY-futures options NOT on by_ticker (like CL) → IEF = 10yr/belly proxy, TLT = long end.** TODO: completeness check → run gauntlet per-asset.

### D. Convex / long-vol overlay (the elegant turbocharger)
- The ONLY thing that doesn't fall with short-vol = opposite sign. Buy cheap tails when skew/GEX signal crash-risk. Standalone Sharpe LOW (long-vol bleeds) but **negative corr raises PORTFOLIO Sharpe** even at low own-Sharpe — "turbocharge", not "1.5 alone".
- Kill the bleed via ex-ante timing of WHEN to hold: candidate = **L3 idea #4 liquidity-vacuum** (thin ES book → buy long-tail only then). Also the natural fix for unsolved −5.3% condor days → links options ↔ L3 tracks.

### E. Prediction markets (Kalshi) — small uncorrelated sleeve
- Event resolution ⟂ market beta = genuinely uncorrelated. Best angles play from our options strength: **Kalshi binary ↔ SPX options digital** (binary = digital option, price from IV surface, trade divergence); **Kalshi Fed ↔ CME FedWatch** divergence. Caveats: tiny capacity, fees, settlement risk → small sleeve not main engine. Also usable as live macro-prob filter (NOT backtested — history too short). See [[kalshi-prediction-markets]].

### C. Time-based STRUCTURAL on futures (user intuition — different angle)
- We applied options-vol-logic & direction-logic to futures; NEVER the TIME-STRUCTURE of returns. **Overnight vs intraday decomposition** (Lou-Polk-Skouras): equity premium accrues OVERNIGHT (close→open); RTH (open→close) ≈ flat/negative. STRUCTURAL time-of-day effect, NOT direction-prediction. Futures-native (ES ~23h). Test: is ES premium concentrated overnight? Does "long overnight / flat intraday" beat 24h-long risk-adjusted? Buildable from es_continuous. Plus event/calendar time-structure (OPEX, FOMC/CPI liquidity days) — the only live thread from liquidity_center_ideas.md (its bias-signals = already-killed direction).

## TAIL-CUT roadmap (the binding Sharpe constraint — потенциал 3+)
Tail days (~7-15 catastrophic −5% sessions that slip through the gate) inflate downside variance → cap Sharpe and prevent sizing up. Cutting them = the highest-leverage improvement. Candidates, by backtestability:
1. **Tighter wings** (short ±1.2% + long ±2-3% instead of ±5%) — STRUCTURAL cap, fully backtestable (no intraday data), directly shrinks max-loss → lower tail variance → higher Sharpe IF residual premium covers. Test wing-width sweep. STRONGEST.
2. **Higher buffer margin** (gex_z(T-1)≥1.0 vs 0.5) — already a tail-cut (margin 1.0 → maxDD −2% vs 0.5's −5.9%); ex-ante avoidance, backtestable, overfit-watch.
3. **Event-day skip** (FOMC/CPI/OPEX) — calendar-known ex-ante; tail days cluster on macro events; no prediction needed, backtestable.
4. **Intraday STOP-LOSS** — TESTED (`/tmp/stoploss.py`, ES-1min re-pricing approx): stop-2% Sharpe 1.51→2.02, worst −5.3%→−2.0%, BUT triggers only 7/270 days, **57% are FALSE (recover by close — +gamma MR)**, and flat-IV approx OVERSTATES benefit (real selloffs spike IV → worse). Fragile, can't validate without intraday option marks → PAPER-OBSERVE candidate, NOT added to engine. See [[vol-engine-deployment]].
5. **Trade the FLIPS** (alt): on flip-to-short-gamma days (gex_z crossing <0), go LONG vol (cheap straddle) instead of short — GEX short-gamma quintile = 28.5% big-move prob. Separate strategy; flip-detection has the same lag problem; direction=0 caveat.

## Memory (auto-loaded)
See `~/.claude/projects/-Users-lol-dev-tools-quant/memory/`: project-direction, options-vrp-gex-findings, vol-engine-deployment, track2-gamma-intraday, futures-execution-tracks, amt-research-findings, amt-stats-reproducibility.
