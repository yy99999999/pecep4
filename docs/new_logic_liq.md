Ниже — **ready-to-build backlog** под твою новую архитектуру:

- **Liquidity-centered = bias**
- **Option-adjusted = execution**
- **VVIX / events / cascade = veto/risk**
- **CTA / vanna/charm = only phase 2**

Я делаю это максимально прикладно:  
для каждого блока даю

- **Feature to compute**
- **Function/module**
- **Notebook cell**
- **Expected dataframe columns**
- **First plot/table to inspect**
- **Done / accept criteria**

---

# 0. Целевая структура проекта

## Новые / обновляемые файлы

### Новый модуль
**`indices_flow_lab.py`**
Зачем:
- не перегружать `intermarket_lab.py`
- держать в одном месте:
  - liquidity bias features
  - ES daily/intraday helpers
  - execution regime tagging
  - simple backtest utilities

### Обновить
**`intrinio_options.py`**
Добавить:
- `gex_profile(...)`
- `daily_gex_panel(...)`
- `opex_features(...)`
- позже: `vanna_charm_profile(...)`

### Новый ноутбук
**`jupyter strats/indices_liquidity_execution.ipynb`**

---

# 1. Целевая схема датафреймов

Это важно зафиксировать заранее.

---

## A. `bias_daily_df`
Одна строка = один торговый день.

Индекс:
- `date`

Колонки:
- `es_close`
- `spx_close`
- `rv_5d`
- `rv_20d`
- `rv_shock`
- `vol_target_alloc`
- `alloc_delta_5d`
- `hy_oas`
- `ig_oas`
- `hy_oas_delta_5d`
- `vix`
- `vix3m`
- `vix_vix3m_ratio`
- `term_slope`
- `credit_vol_composite`
- `basis`
- `fair_basis`
- `basis_vs_fair`
- `basis_zscore_60d`
- `fed_bs`
- `tga`
- `rrp`
- `net_liquidity_1w`
- `net_liquidity_4w`
- forward targets:
  - `fwd_ret_5d`
  - `fwd_ret_10d`
  - `fwd_ret_20d`
  - `fwd_rv_5d`
  - `fwd_rv_10d`
  - `fwd_dd_5d`
  - `fwd_dd_10d`

---

## B. `exec_daily_df`
Одна строка = один день, опционный execution context.

Индекс:
- `date`

Колонки:
- `spot`
- `total_gex`
- `gex_ratio`
- `gex_norm_60d`
- `zero_gamma_level`
- `call_wall`
- `put_wall`
- `wall_width_pct`
- `spot_vs_zero_gamma_pct`
- `gex_regime`
- `days_to_monthly_opex`
- `days_to_weekly_opex`
- `is_monthly_opex_week`
- `expiring_oi_pct`
- `post_opex_flag`
- `vix`
- `vvix`
- `vvix_pctl_60d`
- event flags:
  - `is_fomc_day`
  - `is_cpi_day`
  - `is_nfp_day`
  - `event_severity`

Также можно сюда позже добавить:
- `net_vanna`
- `net_charm`

---

## C. `es_intraday_df`
Индекс:
- `datetime`

Колонки:
- `session_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `rth_flag`
- `minute_ret`
- `cum_rth_ret`
- `rv_30m`
- `session_vwap`
- `dist_to_vwap`
- `ib_high`
- `ib_low`
- `ib_range_pct`
- `gap_pct`
- `break_ib_high`
- `break_ib_low`

---

## D. `master_daily_df`
Финальный merge:
- `bias_daily_df`
- `exec_daily_df`
- aggregated next-day intraday targets

Колонки:
всё из A + B + execution targets:
- `next_rth_range_pct`
- `next_intraday_rv`
- `next_breakout_day_flag`
- `next_mr_day_flag`
- `next_close_minus_open_pct`

---

# 2. Notebook skeleton

## Предлагаемые ячейки в `indices_liquidity_execution.ipynb`

1. **Imports / config**
2. **Load ES + SPX/SPXW + macro**
3. **Build bias_daily_df**
4. **Bias test: vol-target**
5. **Bias test: credit + term**
6. **Bias test: basis**
7. **Bias test: net liquidity**
8. **Bias composite**
9. **Build exec_daily_df (GEX + OPEX + VVIX + events)**
10. **Build intraday ES targets**
11. **Execution regime tests**
12. **+Gamma MR backtest**
13. **-Gamma breakout vs flat**
14. **OPEX modifier**
15. **VVIX / event / cascade overlays**
16. **Bias as veto**
17. **Bias as side filter**
18. **Bias as size scaling**
19. **Subperiod + cost sweep**
20. **Final candidate summary**

---

# 3. Ready-to-build backlog

Ниже — в рабочем порядке.

---

---
## BACKLOG 01 — Create `indices_flow_lab.py`
### Feature to compute
Базовый каркас для:
- realized vol
- forward targets
- basis
- volatility-target features
- event flags
- intraday session features
- simple walk-forward helper

### Function/module
**New file:** `indices_flow_lab.py`

Минимальные функции:
```python
realized_vol(series, window, annualize=True)
forward_return(series, horizon)
forward_realized_vol(series, horizon)
forward_max_drawdown(series, horizon)
es_spx_basis(es_series, spx_series, dte_to_front=None, rate_series=None)
vol_target_features(price_series, rv_short=5, rv_long=20, target_vol=0.10)
economic_event_flags(dates, source='manual_csv_or_fred')
build_rth_session_features(es_1m_df)
expanding_wf_splits(index, min_train, test_size, step)
quintile_bins_train_only(train_series, test_series, q=5)
```

### Notebook cell
**Cell 1** imports  
**Cell 2** smoke test on sample dates

### Expected dataframe columns
None yet; just function outputs

### First plot/table to inspect
- Table: one row per function, with sample output
- Plot: `rv_5d`, `rv_20d` over time
- Plot: `basis_vs_fair`

### Done / accept criteria
- Functions import without error
- Can compute on ES daily series and return aligned index
- No NaN explosion beyond warmup windows

---

## BACKLOG 02 — Build `bias_daily_df`
### Feature to compute
Daily master dataframe for liquidity bias research

### Function/module
**`indices_flow_lab.py`**
```python
build_bias_daily_df(es_daily, spx_daily, fred_df, rate_df=None)
```

### Internal features
- ES close / SPX close
- RV metrics
- vol-target metrics
- credit metrics
- VIX term metrics
- basis metrics
- net liquidity metrics
- forward targets

### Notebook cell
**Cell 3**

### Expected dataframe columns
Minimum required:
```python
[
 'es_close','spx_close',
 'rv_5d','rv_20d','rv_shock',
 'vol_target_alloc','alloc_delta_5d','alloc_level_pct',
 'hy_oas','ig_oas','hy_oas_delta_5d',
 'vix','vix3m','vix_vix3m_ratio','term_slope',
 'credit_vol_composite',
 'basis','fair_basis','basis_vs_fair','basis_zscore_60d',
 'fed_bs','tga','rrp','net_liquidity_1w','net_liquidity_4w',
 'fwd_ret_5d','fwd_ret_10d','fwd_ret_20d',
 'fwd_rv_5d','fwd_rv_10d',
 'fwd_dd_5d','fwd_dd_10d'
]
```

### First plot/table to inspect
1. Missingness heatmap
2. Time-series panel:
   - `vol_target_alloc`
   - `credit_vol_composite`
   - `basis_zscore_60d`
   - `net_liquidity_4w`
3. Correlation matrix of feature candidates

### Done / accept criteria
- Single aligned daily dataframe
- Forward targets correctly shifted, no lookahead
- Warmup period documented

---

## BACKLOG 03 — Vol-target single-signal test
### Feature to compute
Bias signal #1

### Function/module
**`indices_flow_lab.py`**
```python
test_single_bias_signal(
    df, feature_col, target_cols,
    horizons=(5,10,20), 
    n_bins=5,
    non_overlap=True
)
```

### Notebook cell
**Cell 4**

### Expected dataframe columns
Input from `bias_daily_df`:
- `vol_target_alloc`
- `alloc_delta_5d`
- `rv_shock`

Outputs:
- summary table per horizon
- quintile returns
- monotonicity stats
- OOS spread stats

### First plot/table to inspect
1. Quintile table:
   - `alloc_delta_5d` quintile vs `fwd_ret_5d/10d/20d`
2. Boxplot:
   - `rv_shock` buckets vs `fwd_dd_5d`
3. OOS cumulative pseudo-PnL:
   - long top quintile / short bottom quintile

### Done / accept criteria
- Clear conclusion: pass / fail / ambiguous
- Saved summary table `vt_summary`

---

## BACKLOG 04 — Credit + term single/composite test
### Feature to compute
Bias signal #2

### Function/module
Same `test_single_bias_signal(...)`, plus:
```python
build_credit_term_composite(df, cols, method='z_equal_weight')
```

### Notebook cell
**Cell 5**

### Expected dataframe columns
- `hy_oas_delta_5d`
- `vix_vix3m_ratio`
- `term_slope`
- `credit_vol_composite`

### First plot/table to inspect
1. Compare 3 tables side by side:
   - `hy_oas_delta_5d`
   - `vix_vix3m_ratio`
   - `credit_vol_composite`
2. Stress-vs-calm event study:
   - avg path of ES over next 10d
3. Conditional DD table

### Done / accept criteria
- Decide whether composite > term-alone
- Save `credit_term_summary`

---

## BACKLOG 05 — Basis stress single-signal test
### Feature to compute
Bias signal #3

### Function/module
In `indices_flow_lab.py`:
```python
basis_features(es_series, spx_series, rate_series=None, expiry_calendar=None)
```

### Notebook cell
**Cell 6**

### Expected dataframe columns
- `basis`
- `fair_basis`
- `basis_vs_fair`
- `basis_zscore_60d`

### First plot/table to inspect
1. `basis_zscore_60d` quintiles vs `fwd_ret_5d/10d`
2. Scatter:
   - `basis_zscore_60d` vs `fwd_dd_5d`
3. Regime split:
   - stress basis & calm credit
   - calm basis & stress credit

### Done / accept criteria
- Decide if basis adds unique information or is redundant

---

## BACKLOG 06 — Net liquidity backdrop test
### Feature to compute
Slow backdrop only

### Function/module
```python
net_liquidity_features(fred_df)
```

### Notebook cell
**Cell 7**

### Expected dataframe columns
- `fed_bs`
- `tga`
- `rrp`
- `net_liquidity_1w`
- `net_liquidity_4w`
- `net_liquidity_zscore`

### First plot/table to inspect
1. 20d forward return by `net_liquidity_4w` quintile
2. `net_liquidity_4w` vs `fwd_dd_10d`
3. Overlaid chart: ES vs `net_liquidity_4w`

### Done / accept criteria
- Binary decision:
  - keep as backdrop cap
  - or kill entirely

---

## BACKLOG 07 — Bias composite builder
### Feature to compute
2–3 component bias composite from winners only

### Function/module
```python
build_bias_composite(
    df,
    components,
    method='equal_weight_rank',
    clip_z=3.0
)

bias_state_from_composite(series, bins=(-np.inf,-1,-0.25,0.25,1,np.inf))
```

### Notebook cell
**Cell 8**

### Expected dataframe columns
- `bias_score_raw`
- `bias_score_z`
- `bias_state`
  - `strong_neg`
  - `mild_neg`
  - `neutral`
  - `mild_pos`
  - `strong_pos`

### First plot/table to inspect
1. State table:
   - `bias_state` vs forward returns/DD/vol
2. Transition matrix:
   - how often states persist
3. OOS pseudo-equity for:
   - long only when `mild_pos/strong_pos`
   - flat otherwise

### Done / accept criteria
- Freeze MVP bias composite
- Max 3 components

---

## BACKLOG 08 — Add GEX profile functions
### Feature to compute
Execution core features from SPX/SPXW

### Function/module
**Update `intrinio_options.py`**
Add:
```python
gex_profile(date, symbols=['SPX','SPXW'], recompute=True)
daily_gex_panel(symbols=['SPX','SPXW'], start=None, end=None, recompute=True)
```

### Expected `gex_profile` output
```python
{
 'date': ...,
 'spot': ...,
 'total_gex': ...,
 'gex_ratio': ...,
 'gex_norm_60d': ...,
 'zero_gamma_level': ...,
 'call_wall': ...,
 'put_wall': ...,
 'wall_width_pct': ...,
 'spot_vs_zero_gamma_pct': ...,
 'gex_regime': 'pos'/'neg'/'neutral'
}
```

### Notebook cell
**Cell 9** build `exec_daily_df` base

### First plot/table to inspect
1. Time series:
   - `total_gex`
   - `spot_vs_zero_gamma_pct`
2. Histogram:
   - `gex_ratio`
3. Table of extreme days:
   - top 10 positive / negative gamma days

### Done / accept criteria
- Daily GEX panel aligns with ES dates
- Spot inferred correctly
- Zero-gamma / walls sensible visually

---

## BACKLOG 09 — Add OPEX features
### Feature to compute
Execution modifier from expiration structure

### Function/module
**Update `intrinio_options.py`** or `indices_flow_lab.py`
```python
opex_features(options_daily_df_or_dates)
```

### Columns
- `days_to_monthly_opex`
- `days_to_weekly_opex`
- `is_monthly_opex_week`
- `expiring_oi_pct`
- `post_opex_flag`
- `opex_phase`

### Notebook cell
**Cell 9** merge into `exec_daily_df`

### First plot/table to inspect
1. Average `total_gex` by `opex_phase`
2. `expiring_oi_pct` distribution
3. Day-relative event study around monthly OPEX:
   - range
   - intraday RV

### Done / accept criteria
- OPEX tagging deterministic and correct on sample months

---

## BACKLOG 10 — Add VVIX + event flags to `exec_daily_df`
### Feature to compute
Risk/veto metadata

### Function/module
**`indices_flow_lab.py`**
```python
vvix_features(vvix_series, lookback=60)
economic_event_flags(dates, event_csv_or_manual_table)
```

### Notebook cell
**Cell 9**

### Expected dataframe columns
- `vvix`
- `vvix_pctl_60d`
- `vvix_zscore`
- `is_fomc_day`
- `is_cpi_day`
- `is_nfp_day`
- `event_severity`

### First plot/table to inspect
1. `vvix_pctl_60d` over time vs VIX
2. Event day counts by year
3. Table:
   - avg next-day range on event vs non-event

### Done / accept criteria
- No event-date mistakes
- VVIX aligned and usable

---

## BACKLOG 11 — Build intraday ES session features
### Feature to compute
Same-day / next-day execution targets

### Function/module
**`indices_flow_lab.py`**
```python
build_rth_session_features(es_1m_df)
```

### Expected dataframe columns
On minute-level:
- `session_date`
- `gap_pct`
- `ib_high`
- `ib_low`
- `ib_range_pct`
- `session_vwap`
- `rv_30m`
- `dist_to_vwap`

On daily aggregation:
```python
aggregate_intraday_targets(es_1m_df)
```

Daily target columns:
- `next_rth_range_pct`
- `next_intraday_rv`
- `next_breakout_day_flag`
- `next_close_minus_open_pct`
- `next_open_to_close_abs_pct`
- `next_mr_day_flag` *(define carefully, e.g. large excursion + close near VWAP/mid)*

### Notebook cell
**Cell 10**

### First plot/table to inspect
1. Distribution of `next_rth_range_pct`
2. `gex_regime` vs `next_intraday_rv`
3. Example days overlay:
   - positive gamma
   - negative gamma

### Done / accept criteria
- Aggregated daily intraday target table
- Matches known sessions visually

---

## BACKLOG 12 — Build `master_daily_df`
### Feature to compute
Join bias + execution + targets into one research frame

### Function/module
Plain merge in notebook or helper:
```python
build_master_daily_df(bias_daily_df, exec_daily_df, intraday_targets_df)
```

### Notebook cell
**Cell 11**

### Expected dataframe columns
Everything from:
- bias
- execution
- intraday targets

### First plot/table to inspect
1. Missingness table after merge
2. Sample rows around major stress episodes:
   - 2022 selloffs
   - Aug 2024
3. Correlation matrix:
   - `bias_score_z`
   - `gex_score proxy`
   - `next_rth_range_pct`

### Done / accept criteria
- Single clean research frame
- Ready for TEST 06 onward

---

## BACKLOG 13 — GEX regime diagnostic
### Feature to compute
Execution regime sanity check before any PnL rules

### Function/module
Notebook helper or:
```python
regime_summary(df, regime_col, target_cols)
```

### Notebook cell
**Cell 11 or 12**

### Expected columns used
- `gex_regime`
- `gex_ratio`
- `spot_vs_zero_gamma_pct`
- `next_rth_range_pct`
- `next_intraday_rv`
- `next_breakout_day_flag`

### First plot/table to inspect
1. Table:
   - `gex_regime` vs mean/median `next_rth_range_pct`
2. Bucket plot:
   - `gex_ratio` quintiles vs breakout rate
3. `spot_vs_zero_gamma_pct` bins vs intraday RV

### Done / accept criteria
- Clear evidence whether +gamma / -gamma separate regimes at all

---

## BACKLOG 14 — Positive gamma MR baseline backtest
### Feature to compute
Minimal execution rule for +gamma

### Function/module
**`indices_flow_lab.py`**
```python
backtest_positive_gamma_mr(
    es_1m_df,
    exec_daily_df,
    wait_minutes=30,
    wall_buffer_bps=15,
    stop_bps=25,
    target='vwap_or_mid'
)
```

### Notebook cell
**Cell 12**

### Required merged columns
Daily:
- `gex_regime`
- `call_wall`
- `put_wall`
- `zero_gamma_level`
- `event_severity`
- `vvix_pctl_60d`

Intraday:
- `gap_pct`
- `ib_high`
- `ib_low`
- `session_vwap`

### First plot/table to inspect
1. Trade blotter sample
2. PnL by year
3. PnL by `gex_ratio` bucket
4. Worst 10 losses with regime metadata

### Done / accept criteria
- Baseline MR engine with costs
- Decision: live candidate / refine / kill

---

## BACKLOG 15 — Negative gamma breakout vs flat test
### Feature to compute
Decide whether -gamma should be traded or vetoed

### Function/module
```python
backtest_negative_gamma_breakout(
    es_1m_df,
    exec_daily_df,
    ib_window=30,
    stop_multiple=1.0,
    trail_multiple=1.5
)
compare_to_flat(...)
```

### Notebook cell
**Cell 13**

### Required columns
- `gex_regime`
- `spot_vs_zero_gamma_pct`
- `gap_pct`
- `ib_high`
- `ib_low`

### First plot/table to inspect
1. PnL of breakout strategy
2. Compare:
   - breakout
   - flat
3. Contribution analysis:
   - top 10 winning days share of total PnL

### Done / accept criteria
- Binary decision:
  - trade -gamma
  - or hard veto / flat

---

## BACKLOG 16 — OPEX modifier test
### Feature to compute
Does OPEX improve execution reliability?

### Function/module
Can be notebook-level first:
- run MR/backout baseline with and without OPEX filter

### Notebook cell
**Cell 14**

### Expected columns
- `opex_phase`
- `is_monthly_opex_week`
- `expiring_oi_pct`

### First plot/table to inspect
1. Positive gamma MR PnL by `opex_phase`
2. Range / breakout rate by `opex_phase`
3. Monthly OPEX event study

### Done / accept criteria
- Keep or kill OPEX modifier

---

## BACKLOG 17 — VVIX filter test
### Feature to compute
Meta-filter for level reliability

### Function/module
Notebook first, later helper:
- compare baseline execution across `vvix_pctl_60d` buckets

### Notebook cell
**Cell 15**

### Expected columns
- `vvix_pctl_60d`
- `vvix_zscore`

### First plot/table to inspect
1. Execution Sharpe / PF by VVIX bucket
2. Worst-day loss by VVIX bucket
3. Trade count retained vs quality

### Done / accept criteria
- Decide size filter or hard veto

---

## BACKLOG 18 — Event-day handling test
### Feature to compute
Pre-event skip / post-event only rules

### Function/module
Could stay notebook-level initially

### Notebook cell
**Cell 15**

### Expected columns
- `is_fomc_day`
- `is_cpi_day`
- `is_nfp_day`
- `event_severity`

### First plot/table to inspect
1. Baseline execution on event vs non-event
2. Same after event-aware handling
3. Tail-loss comparison

### Done / accept criteria
- Freeze event rules if helpful

---

## BACKLOG 19 — Cascade override detector
### Feature to compute
Rare-event crisis override

### Function/module
**`indices_flow_lab.py`**
```python
cascade_features(df)
```
Inputs:
- `vix`
- `vix_vix3m_ratio`
- `basis_zscore_60d`
- ES volume zscore

Outputs:
- `cascade_score`
- `cascade_flag`
- `post_cascade_flag`

### Notebook cell
**Cell 15**

### First plot/table to inspect
1. List of flagged cascade days
2. Compare worst baseline losses:
   - before override
   - after override
3. Post-cascade 3d / 5d path averages

### Done / accept criteria
- Keep if tail-risk reduction material even with small n

---

## BACKLOG 20 — Bias as veto integration
### Feature to compute
First cross-layer integration

### Function/module
Notebook first:
```python
apply_bias_veto(exec_signals_df, bias_daily_df)
```

### Rule
- strong negative bias → no long MR / no upside breakout
- strong positive bias → no short MR / no downside breakout

### Notebook cell
**Cell 16**

### Required columns
- `bias_state`
- execution trades / signals

### First plot/table to inspect
1. Baseline vs veto:
   - Sharpe
   - PF
   - Max DD
   - trade count
2. Trade removals by bias state
3. Worst-loss reduction

### Done / accept criteria
- Keep only if DD/CI improves without over-pruning

---

## BACKLOG 21 — Bias as side filter integration
### Feature to compute
Second cross-layer integration

### Function/module
Notebook first:
```python
apply_bias_side_filter(exec_signals_df, bias_daily_df)
```

### Notebook cell
**Cell 17**

### Rule examples
- `+gamma + positive bias` → long fades only
- `+gamma + negative bias` → short fades only
- `-gamma + positive bias` → upside breakouts only
- `-gamma + negative bias` → downside breakouts only

### First plot/table to inspect
1. Expectancy/trade vs veto-only
2. PnL by quadrant:
   - gamma regime × bias sign
3. Trade count per quadrant

### Done / accept criteria
- Keep only if strictly incremental over veto

---

## BACKLOG 22 — Bias as size scaling
### Feature to compute
Final cross-layer integration

### Function/module
Notebook first:
```python
apply_bias_size_scaling(exec_trades_df, bias_score_col, scheme='tiered')
```

### Notebook cell
**Cell 18**

### Example size tiers
- strong aligned = `1.25x`
- mild aligned = `1.0x`
- neutral = `0.5x`
- conflict = `0–0.25x`

### First plot/table to inspect
1. Baseline vs veto vs side-filter vs size-scaling
2. Max DD / Sharpe / Sortino comparison
3. Exposure distribution by bias state

### Done / accept criteria
- Choose final MVP integration style

---

# 4. Phase 2 backlog only if core survives

---

## BACKLOG 23 — Vanna/Charm implementation
### Feature to compute
Dealer-flow refinement

### Function/module
**Update `intrinio_options.py`**
```python
_bs_vanna(...)
_bs_charm(...)
vanna_charm_profile(date, symbols=['SPX','SPXW'], recompute=True)
daily_vanna_charm_panel(...)
```

### Notebook cell
**Cell 19 or separate notebook branch**

### Expected columns
- `net_vanna`
- `net_charm`
- `near_expiry_charm`
- `vanna_direction`

### First plot/table to inspect
1. `net_vanna` vs next-day drift
2. `net_charm` vs next-day close-open
3. incremental table over GEX-only regime

### Done / accept criteria
- Only continue if incremental OOS

---

## BACKLOG 24 — CTA replication implementation
### Feature to compute
Optional timing booster

### Function/module
**`indices_flow_lab.py`**
```python
cta_replication_features(price_series, ma_windows=(10,20,50,100,200))
```

### Expected columns
- `ma_score`
- `cta_position_proxy`
- `cta_delta_5d`
- `ma_trigger_distance`
- `ma_alignment`

### Notebook cell
**Cell 20 or branch**

### First plot/table to inspect
1. CTA state vs forward 5/10d return
2. CTA state × bias state interaction
3. CTA state × GEX regime interaction

### Done / accept criteria
- Add only if genuinely orthogonal to existing bias composite

---

# 5. Suggested file-level implementation order

## Week 1
1. `indices_flow_lab.py` skeleton
2. `build_bias_daily_df`
3. single-signal bias tests

## Week 2
4. bias composite
5. `intrinio_options.py::gex_profile`
6. `opex_features`

## Week 3
7. `build_rth_session_features`
8. `master_daily_df`
9. GEX regime diagnostics

## Week 4
10. +gamma MR baseline
11. -gamma breakout vs flat
12. OPEX modifier

## Week 5
13. VVIX filter
14. event overlay
15. cascade override

## Week 6
16. bias veto
17. bias side filter
18. bias size scaling

## Week 7+
19. vanna/charm
20. CTA

---

# 6. What to inspect first, before doing any backtest

Это отдельный важный mini-checklist.

## Before any PnL:
### Bias side
- Quintile monotonicity tables
- Forward DD by bucket
- Feature correlation / redundancy
- State persistence

### Execution side
- `gex_regime` vs next-day range/RV
- `spot_vs_zero_gamma_pct` vs breakout frequency
- OPEX event study
- VVIX bucket vs level reliability proxy

Если это не выглядит осмысленно на descriptive level — **не надо даже писать сложный бэктест**.

---

# 7. Минимальный MVP backlog, если хочешь идти совсем жёстко

Если надо урезать до must-build:

## Must build first
1. `build_bias_daily_df`
2. `VT-01`
3. `CV-02`
4. `BS-03`
5. `build_bias_composite`
6. `gex_profile`
7. `build_rth_session_features`
8. `GEX regime diagnostic`
9. `+gamma MR baseline`
10. `-gamma breakout vs flat`
11. `VVIX filter`
12. `Bias veto`

Этого уже достаточно, чтобы понять, жива ли новая архитектура.

---

# 8. Рекомендуемые названия функций / столбцов без боли на будущее

## Bias
- `vol_target_alloc`
- `alloc_delta_5d`
- `credit_vol_composite`
- `basis_zscore_60d`
- `net_liquidity_4w`
- `bias_score_z`
- `bias_state`

## Execution
- `gex_ratio`
- `zero_gamma_level`
- `spot_vs_zero_gamma_pct`
- `call_wall`
- `put_wall`
- `wall_width_pct`
- `opex_phase`

## Risk
- `vvix_pctl_60d`
- `event_severity`
- `cascade_flag`
- `post_cascade_flag`

---

# 9. Жёсткие acceptance gates по фазам

## Phase A complete if:
- есть не более 3 bias-компонентов
- bias composite OOS лучше лучшего single signal
- net liquidity либо убит, либо переведён в backdrop-only

## Phase B complete if:
- GEX regime реально различает структуру дня
- +gamma MR либо работает, либо убит
- -gamma breakout либо работает, либо зафиксирован как flat/veto
- OPEX либо оставлен как modifier, либо убит

## Phase C complete if:
- хотя бы 1 из `VVIX / event / cascade` улучшает tail control materially

## Phase D complete if:
- bias adds value to execution через veto / side / size
- и итоговая система проще, а не сложнее ради красоты

---

Если хочешь, следующим сообщением я могу сделать ещё более прикладную вещь:  
**готовый шаблон `indices_flow_lab.py` с сигнатурами функций и пустыми docstring'ами**, чтобы можно было сразу начинать кодить.