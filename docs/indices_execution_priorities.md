Коротко: **это не “финальный навсегда”, а финальный рабочий приоритет для ресерча под indices execution.**  
То есть **именно в таком порядке я бы тестировал**, и только после OOS можно фиксировать окончательный стек.

## Что оставить как **Tier 1 / core**
Это ядро для ES/MES:

1. **GEX levels + regime**
2. **CTA replication**
3. **Vol-target flows**
4. **Vanna/Charm**
5. **OPEX calendar**

Это — не оверлеи, а **основные источники режима/направленного forced flow**.

---

# Что использовать как **overlay / Tier 2**
То, что не должно быть самостоятельным “сигналом на вход”, а должно **фильтровать, усиливать или запрещать** core-сигналы.

## A. Лучшие Tier 2 overlays
### 1. **VVIX / vol-of-vol filter**
Использование:
- **VVIX high** → снижать size / не торговать MR
- **VVIX low-normal** → core сигналы более надёжны

Почему:
- это **meta-filter качества GEX/Vanna режима**, а не отдельная альфа

**Статус:** очень хороший overlay

---

### 2. **Credit + vol term structure veto**
То, что у тебя уже работает в options-движке:
- **HY OAS widening**
- **VIX backwardation / слабый contango**

Использование для indices:
- не как directional signal,
- а как **crisis-off veto**:
  - если stress-on → не торговать MR, не доверять positive gamma
  - если спокойно → core сигналы валиднее

**Статус:** один из лучших risk overlays

---

### 3. **Futures basis (ES-SPX)**
Использование:
- basis abnormal / stressy → leverage unwind risk
- в такие дни:
  - меньше size
  - не фейдить aggressively
  - больше доверять trend continuation

Это хороший **leverage-stress overlay**, не core-entry.

---

### 4. **Event calendar overlay**
- FOMC
- CPI
- NFP
- крупные auction / Treasury events

Использование:
- на таких днях **не запускать обычный MR-модуль как обычно**
- либо:
  - skip first 30–90 min
  - only post-event mode
  - reduced size

Это не альфа, а **режимная коррекция execution**.

---

### 5. **Buyback blackout**
Использование:
- high blackout % → меньше доверия long/MR
- low blackout % → structural support

Это хороший **seasonal confidence overlay**, но не core.

---

## B. Хорошие intraday overlays
### 6. **Spot vs zero-gamma / gamma-wall interaction**
Это скорее часть GEX execution layer, но можно считать overlay:
- above zero-gamma → MR bias
- below zero-gamma → trend bias
- crossing intraday → regime flip

Очень важен не как отдельный signal, а как **state machine overlay**.

---

### 7. **Opening gap × GEX**
- **big overnight gap + positive gamma** → часто сначала шум/hedging, потом MR
- **big overnight gap + negative gamma** → continuation risk

Это хороший **open filter**.

---

### 8. **Initial Balance / first 15–30 min relative to gamma walls**
Использование:
- open near wall in +gamma → fade setup
- open through/under zero-gamma in -gamma → breakout/trend setup

Это уже ближе к execution-логике, чем к alpha signal.

---

### 9. **Intraday realized vol acceleration**
- если intraday RV резко растёт → EOD GEX карта устаревает
- если вола ускоряется → отключать MR overlay

Это очень полезный **live invalidation filter**.

---

## C. Special situation overlays
### 10. **Margin cascade detector**
Не как постоянная стратегия, а как **special-event module**:
- VIX spike / wide range / basis stress / volume surge
- core-модель в такие дни может ломаться
- но после подтверждённой capitulation можно искать post-cascade reversal

Это **редкий, но мощный Tier 2 модуль**.

---

### 11. **Skew divergence**
- skew steepening while spot calm / VIX not exploding
- признак скрытого hedging demand

Использование:
- снижать size MR
- повышать осторожность к long index execution

Хороший overlay, но слабее VVIX/credit/basis.

---

### 12. **Cross-index concordance**
Из ранних идей:
- SPX GEX и QQQ/NDX GEX совпадают → сильнее confidence
- diverge → меньше доверия

Использование:
- **concordance = boost**
- **divergence = cut size / skip**

Очень хороший и недорогой overlay.

---

# Что я бы **НЕ делал core**, но держал как overlay-only
Вот это лучше не делать самостоятельной directional стратегией на индексах:

- **VRP**
- **Vol term structure**
- **Skew level**
- **Retail flow proxy**
- **Funding/rates**
- **Global liquidity**
- **P/C parity violations**

Причина простая:  
они лучше отвечают на вопрос **“какой режим риска/волы?”**, чем на вопрос **“как исполнять индекс directionally intraday?”**

---

# Итоговая архитектура

## Tier 1 / Core
1. **GEX regime + walls**
2. **CTA replication**
3. **Vol-target model**
4. **Vanna/Charm drift**
5. **OPEX regime**

## Tier 2 / Overlay
### Risk / veto overlays
- **VVIX**
- **Credit + vol term structure**
- **Futures basis**
- **Event calendar**
- **Buyback blackout**
- **Skew divergence**
- **Cross-index concordance**

### Intraday execution overlays
- **Opening gap × GEX**
- **IB vs walls**
- **Spot crossing zero-gamma**
- **Intraday RV acceleration**

### Special-event overlays
- **Margin cascade / post-cascade module**
- **Post-OPEX expansion module**

---

# Практический финальный приоритет

## Если совсем жёстко, то я бы делал так:

### **Core build now**
1. GEX regime/walls  
2. CTA replication  
3. Vol-target  
4. Vanna/Charm  
5. OPEX  

### **First overlays to add**
6. VVIX  
7. Credit + VIX term structure  
8. Event calendar  
9. Futures basis  
10. Cross-index concordance  

### **Second-wave overlays**
11. Opening gap × GEX  
12. IB vs walls  
13. Skew divergence  
14. Buyback blackout  
15. Margin cascade module  

---

# Самый короткий ответ
**Да — этот приоритет для indices execution уже близок к финальному.**  
Но **core** должен быть маленьким, а всё остальное — **оверлеями/veto/size modifiers**, а не новыми standalone-стратегиями.

Если хочешь, я могу следующим сообщением собрать это в **одну финальную таблицу “Core vs Overlay vs Skip”** без пояснений, чтобы это можно было прямо вставить в проектный roadmap.



# ФИНАЛЬНАЯ ТАБЛИЦА: Index Execution System

## Tier 1 — CORE (источники режима и forced flow)

---

### 1. GEX Regime + Structural Levels

**Что торгуем:** режим (MR vs trend) + границы диапазона

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `total_gex` | `Σ(call_Γ × call_OI − put_Γ × put_OI) × 100 × S² × 0.01` | >0 = MR, <0 = trend |
| `gex_ratio` | `Σ(call_Γ × call_OI) / Σ(put_Γ × put_OI)` | >1 = call dominated (MR), <1 = put dominated (trend) |
| `zero_gamma_level` | страйк где кумулятивный GEX по страйкам пересекает 0 | выше = +gamma (MR), ниже = −gamma (trend) |
| `call_wall` | страйк с max `call_Γ × call_OI` | resistance / upper bound MR range |
| `put_wall` | страйк с max `put_Γ × put_OI` | support / lower bound MR range |
| `spot_vs_zero_gamma` | `spot − zero_gamma_level` | >0 = в зоне MR, <0 = в зоне trend |
| `gex_norm` | `total_gex / median(abs(total_gex), 60d)` | нормализованная сила режима, сравнимая across time |
| `wall_width` | `(call_wall − put_wall) / spot × 100` | ожидаемый диапазон дня в % |

**Scoring:**

```
gex_score (−2 to +2):

  +2: gex_ratio > 1.5 AND spot > zero_gamma + 0.3%
      (глубоко в positive gamma, сильный MR)

  +1: gex_ratio > 1.0 AND spot > zero_gamma
      (positive gamma, умеренный MR)

   0: gex_ratio 0.8–1.2 OR spot ≈ zero_gamma (±0.2%)
      (нейтрально / переходная зона)

  −1: gex_ratio < 1.0 AND spot < zero_gamma
      (negative gamma, умеренный trend)

  −2: gex_ratio < 0.7 AND spot < zero_gamma − 0.5%
      (глубоко в negative gamma, сильный trend)
```

**Crowding: 2/5 (HIGH crowding)**
- SpotGamma ($500/mo, 50K+ subscribers), Menthor, GammaLab, SqueezeMetrics (DIX/GEX), Unusual Whales
- Уровни публикуются daily в Twitter/Discord до открытия
- Retail awareness: высокая и растёт
- Mitigation: наш self-compute (vendor-independent), можно отличаться в assumptions (OI allocation, DTE weighting). Edge не в знании уровней, а в execution logic + combination с другими signals

**Data:** Intrinio EOD OI + self-compute gamma. Есть.

---

### 2. CTA / Systematic Trend-Following Replication

**Что торгуем:** anticipation of forced mechanical buying/selling от ~$350B AUM

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `ma_score` | `mean([spot>MA_k for k in [10,20,50,100,200]])` | 0→1: доля MA ниже цены. 1.0 = все бычьи, 0.0 = все медвежьи |
| `cta_position_proxy` | `ma_score` нормализованный | 0 = max short, 1 = max long |
| `cta_delta_5d` | `Δma_score` за 5 дней | >0 = CTA покупают, <0 = CTA продают |
| `ma_trigger_distance` | `min(abs(spot − MA_k) / spot)` для всех k | близость к ближайшему MA = close to forced flow trigger |
| `ma_alignment` | все 5 MA в одном порядке (10>20>50>100>200 или наоборот) | full alignment = max positioning, vulnerable to reversal |
| `cta_acceleration` | `Δcta_delta_5d` (2nd derivative) | ускорение/замедление buying/selling pressure |

**Scoring:**

```
cta_flow_score (−2 to +2):

  +2: ma_trigger_distance < 0.3% AND cta_delta_5d > 0
      (цена пробивает MA снизу вверх, CTA ПОКУПАЮТ ПРЯМО СЕЙЧАС)

  +1: ma_score > 0.8 AND cta_delta_5d > 0
      (CTA mostly long, всё ещё добавляют)

   0: ma_score 0.4–0.6 OR cta_delta_5d ≈ 0
      (нейтрально, нет forced flow)

  −1: ma_score < 0.2 AND cta_delta_5d < 0
      (CTA mostly short, всё ещё продают)

  −2: ma_trigger_distance < 0.3% AND cta_delta_5d < 0
      (цена пробивает MA сверху вниз, CTA ПРОДАЮТ ПРЯМО СЕЙЧАС)
```

**Дополнительно: vol-adjusted sizing (как реальные CTA)**

```
cta_size_proxy = cta_position_proxy × (target_vol / realized_vol_20d)
```

CTA увеличивают size в low-vol, уменьшают в high-vol. Это предсказывает MAGNITUDE flow, не только direction.

**Crowding: 3/5 (MODERATE)**
- Концепция известна (Goldman CTA positioning reports, SocGen CTA Index, Nomura McElligott)
- Но: retail систематически это мало кто считает и торгует
- Institutional alpha decay: banks торгуют front-running CTA → edge уменьшается на крупных MA (200MA)
- Mitigation: комбинация с GEX (CTA trigger + positive gamma = strongest setup). Мелкие MA (10/20) менее crowded чем 200MA

**Data:** price only (free). CFTC COT weekly (free, validation). SocGen CTA Index (free, monthly benchmark).

---

### 3. Vol-Target / Risk-Parity Mechanical Flows

**Что торгуем:** anticipation of forced de-risking/re-risking от ~$500B+ AUM

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `rv_20d` | 20-day realized vol (annualized, close-to-close) | текущая реализованная вола |
| `rv_5d` | 5-day realized vol | short-term vol shock detection |
| `vol_target_alloc` | `target_vol / rv_20d`, capped [0, 1.5] | модельная equity allocation vol-target фондов |
| `alloc_delta_5d` | `Δvol_target_alloc` за 5 дней | >0 = фонды покупают (RV fell), <0 = фонды продают (RV rose) |
| `alloc_level` | percentile `vol_target_alloc` за 252d | где мы исторически: 0% = max de-risked, 100% = max levered |
| `rv_shock` | `rv_5d / rv_20d` | >1.5 = vol spike → forced selling imminent. <0.7 = vol crush → forced buying |
| `derisking_pressure` | `max(0, rv_5d − rv_20d) × estimated_AUM` | estimated $ selling pressure |

**Scoring:**

```
voltarget_flow_score (−2 to +2):

  +2: alloc_delta_5d > 0 AND rv_shock < 0.8
      (vol crashing → фонды ВЫНУЖДЕНЫ покупать, re-risking)

  +1: alloc_delta_5d > 0 AND alloc_level < 50th pctl
      (ещё под-инвестированы, re-risking продолжается)

   0: alloc_delta_5d ≈ 0 OR alloc_level 40–60th pctl
      (нейтрально)

  −1: alloc_delta_5d < 0 AND rv_shock > 1.3
      (vol растёт → де-рискинг начался)

  −2: alloc_delta_5d < 0 AND rv_shock > 1.8 AND alloc_level > 80th pctl
      (vol spike при max leverage → МАССОВЫЙ forced selling)
```

**Crowding: 3/5 (MODERATE)**
- Deutsche Bank Equity Positioning Index (институциональный, не retail)
- JPM, Goldman publishing vol-target estimates для клиентов
- Retail: почти никто не считает. Финтвиттер иногда обсуждает, не торгует
- Mitigation: это не "сигнал на вход", а flow-pressure estimate. Crowding менее разрушительно для flow-based signals (flow реален, не зависит от того, знаешь ли ты о нём)

**Data:** price only → RV (free). Target vol assumption = 10% (literature-based, adjustable).

---

### 4. Vanna / Charm Dealer Flow

**Что торгуем:** directional drift от изменения dealer delta exposure при движении IV и времени

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `net_vanna` | `Σ(vanna_i × OI_i × 100 × S)` calls − puts | aggregate dealer vanna exposure |
| `net_charm` | `Σ(charm_i × OI_i × 100)` calls − puts | aggregate dealer charm (delta decay per day) |
| `vanna_direction` | `sign(net_vanna) × sign(−ΔIV_expected)` | если IV falling + vanna negative → dealer buys stock (+1) |
| `charm_drift` | `net_charm × (1/252)` | ожидаемое изменение dealer delta за 1 день от прохождения времени |
| `vanna_charm_combined` | `vanna_direction + sign(charm_drift)` | суммарный ожидаемый drift |
| `near_expiry_charm` | `charm` только для DTE < 7 | charm экспоненциально растёт near expiry |

**Как считать vanna и charm:**

```python
# Vanna: dDelta/dIV (finite difference)
vanna = (delta(IV + 0.01) − delta(IV − 0.01)) / 0.02

# Charm: dDelta/dt (finite difference)  
charm = (delta(T − 1/365) − delta(T)) / (1/365)

# Или аналитически (Black-Scholes):
# vanna = -e^(-qT) × N'(d1) × d2 / σ
# charm = -e^(-qT) × (N'(d1) × (2(r-q)T - d2×σ√T) / (2T×σ√T))
```

**Scoring:**

```
vanna_charm_score (−2 to +2):

  +2: strong positive vanna_direction + positive charm_drift
      (dealer MUST buy stock: IV falling pushes delta + time decay pushes delta)
      → bullish drift intraday

  +1: one of vanna/charm positive, other neutral
      → mild bullish drift

   0: mixed or weak signals
      → no clear dealer drift

  −1: one of vanna/charm negative
      → mild bearish drift

  −2: strong negative vanna_direction + negative charm_drift
      (dealer MUST sell stock: IV rising + time decay both push selling)
      → bearish drift intraday
```

**Crowding: 4/5 (LOW crowding)**
- Cem Karsan (Kai Volatility) обсуждает публично, но не даёт levels
- SpotGamma недавно добавила vanna/charm (premium tier)
- Подавляющее большинство retail: не считает, не понимает
- Это НАИМЕНЕЕ crowded из всех core signals
- Mitigation: edge в computation + interpretation, retail penetration минимальна

**Data:** наш self-compute IV + delta + вычисление vanna/charm конечными разностями. Нужно расширить `intrinio_options.py`.

---

### 5. OPEX Calendar Regime

**Что торгуем:** структурный сдвиг gamma environment до/после экспирации

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `days_to_monthly_opex` | calendar (3rd Friday) | T−5 to T = pinning zone, T+1 to T+3 = gamma vacuum |
| `days_to_weekly_opex` | calendar (every Friday) | weekly cycle (weaker than monthly) |
| `expiring_oi_pct` | `OI(expiring_DTE=0–1) / total_OI` | доля OI, которая умирает: >30% = significant gamma drop |
| `post_opex_gex_drop` | `expected GEX(T+1) / GEX(T)` | estimated gamma removal |
| `opex_phase` | categorical: pre(T−3 to T), day(T), post(T+1 to T+3), mid-cycle | текущая фаза |
| `monthly_vs_weekly` | binary: is this monthly OPEX week? | monthly OPEX = 5–10× larger gamma event than weekly |

**Scoring:**

```
opex_score (−1 to +1, modifier не direction):

  +1: pre-OPEX (T−3 to T−1), monthly, high expiring_oi_pct
      (max pinning effect → BOOST MR confidence)
      (= GEX score более надёжен, MR setups более вероятны)

   0: mid-cycle (T+4 to T−4)
      (normal regime, no OPEX effect)

  −1: post-OPEX (T+1 to T+3), monthly
      (gamma vacuum → GEX levels UNRELIABLE, vol expansion likely)
      (= REDUCE all MR trades, expect trend/breakout)
```

**Crowding: 3/5 (MODERATE)**
- OPEX pin = widely discussed (финтвиттер, options Twitter)
- Post-OPEX gamma vacuum: менее обсуждается, но SpotGamma покрывает
- Но: calendar = deterministic → crowding не "портит" сигнал (дата экспирации не изменится от того, что все знают)
- Mitigation: edge не в знании даты OPEX (все знают), а в количественной оценке gamma removal + combination с другими signals

**Data:** calendar (deterministic, free) + OI по DTE (есть).

---

## Tier 2 — OVERLAYS (фильтры, размер, veto)

### Группа A: Risk / Veto Overlays

---

### 6. VVIX (Vol-of-Vol) Meta-Filter

**Что делает:** оценивает RELIABILITY core signals. Высокий VVIX = GEX/vanna levels нестабильны и могут сдвинуться intraday.

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `vvix_level` | CBOE VVIX (daily close) | уровень vol-of-vol |
| `vvix_pctl` | percentile VVIX за 60 дней | relative to recent history |
| `vvix_zscore` | `(vvix − mean_60d) / std_60d` | spike detection |

**Scoring (overlay modifier):**

```
vvix_modifier (0.0 to 1.0, multiplier на size):

  1.0: vvix_pctl < 30th  (low VVIX → levels stable → trade full size)
  0.8: vvix_pctl 30–60th (normal)
  0.5: vvix_pctl 60–80th (elevated → reduce size)
  0.2: vvix_pctl > 80th  (very high → levels unreliable → minimal size)
  0.0: vvix_zscore > 2.5  (extreme → SKIP all trades)
```

**Crowding: 4/5 (LOW)** — VVIX мало кто смотрит retail. Даже institutional — не все.

**Data:** Yahoo Finance `^VVIX` (free, daily).

---

### 7. Credit + Vol Term Structure Veto

**Что делает:** macro crisis detection. Когда credit/vol structure сигнализируют системный стресс, все MR-стратегии ломаются.

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `hy_oas` | FRED: BAMLH0A0HYM2 | HY credit spread (bps) |
| `hy_oas_delta_5d` | `Δhy_oas` за 5 дней | widening = stress |
| `vix_vix3m_ratio` | `VIX / VIX3M` | >1 = backwardation = panic |
| `vix_term_slope` | `(VIX3M − VIX) / VIX` | negative = inverted = panic |
| `credit_vol_composite` | `0.5 × zscore(hy_oas_delta_5d) + 0.5 × zscore(vix_vix3m_ratio)` | combined stress metric |

**Scoring (veto):**

```
macro_veto (binary + severity):

  CLEAR:   hy_oas_delta_5d < +20bps AND vix_vix3m_ratio < 0.95
           → trade normally

  CAUTION: hy_oas_delta_5d +20–50bps OR vix_vix3m_ratio 0.95–1.00
           → reduce size 50%

  VETO:    hy_oas_delta_5d > +50bps AND vix_vix3m_ratio > 1.00
           → NO TRADES (full stop)

  POST-CRISIS OVERRIDE: 
           veto was active, now:
           hy_oas_delta_5d turning negative AND vix_vix3m_ratio < 1.00
           → re-entry allowed, start with 25% size
```

**Crowding: 3/5** — known macro framework but rarely used as systematic overlay.

**Data:** FRED (free). Already in `intermarket_lab.py`.

---

### 8. Event Calendar Overlay

**Что делает:** adjust execution logic на днях с macro releases.

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `is_fomc_day` | binary | rate decision day |
| `is_cpi_day` | binary | CPI release (8:30 AM) |
| `is_nfp_day` | binary (first Friday) | jobs report |
| `event_severity` | 0–3 | 0=none, 1=minor (PPI), 2=major (CPI/NFP), 3=FOMC |
| `hours_to_event` | continuous | для intraday: до/после release |

**Scoring (modifier):**

```
event_modifier:

  event_severity = 0: no adjustment (1.0×)
  event_severity = 1: size × 0.8
  event_severity = 2: 
    pre-event: size × 0.5, no new MR entries
    post-event (>30 min after release): normal
  event_severity = 3 (FOMC):
    pre-2PM: size × 0.3, no new entries
    post-2:30PM: normal (vol typically crushed post-FOMC)
    FOMC + positive gamma = strongest MR of month (post-decision)
```

**Crowding: 2/5 (HIGH)** — everyone knows FOMC/CPI. But: systematic overlay with GEX = differentiated.

**Data:** economic calendar (FRED releases, free). Deterministic.

---

### 9. Futures Basis Stress

**Что делает:** detects leverage unwind pressure.

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `es_spx_basis` | `(ES_front − SPX) / SPX × 10000` (bps) | theoretical = risk-free rate × DTE/365 |
| `basis_vs_fair` | `es_spx_basis − fair_value_basis` | deviation from fair. Negative = selling pressure |
| `basis_zscore` | zscore of `basis_vs_fair` over 60d | spike detection |

**Scoring (modifier):**

```
basis_modifier:

  basis_zscore > −1:  normal (1.0×)
  basis_zscore −1 to −2: stressed (0.7×)
  basis_zscore < −2: severe leverage unwind (0.3×)
  basis_zscore < −3: extreme (VETO — same as macro veto)
```

**Crowding: 4/5 (LOW)** — mostly institutional. Retail rarely monitors basis.

**Data:** ES continuous (have) + SPX (have/FRED). Free.

---

### 10. Cross-Index GEX Concordance

**Что делает:** confirms or weakens regime conviction by checking if multiple indices agree.

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `spx_gex_sign` | sign(GEX_SPX) | +1 or −1 |
| `ndx_gex_sign` | sign(GEX_NDX) | +1 or −1 |
| `concordance` | `spx_gex_sign × ndx_gex_sign` | +1 = agree, −1 = diverge |
| `concordance_strength` | `min(abs(gex_ratio_SPX − 1), abs(gex_ratio_NDX − 1))` | how strongly they agree |

**Scoring (modifier):**

```
concordance_modifier:

  concordance = +1 AND concordance_strength > 0.3:
    → boost conviction (1.2× size)
  
  concordance = +1 AND concordance_strength < 0.3:
    → normal (1.0×)
  
  concordance = −1:
    → reduce conviction (0.6× size)
    → do NOT trade trend on one if other is MR
```

**Crowding: 5/5 (UNCROWDED)** — nobody does this retail. Even institutional: rare.

**Data:** already computed (SPX, NDX both in cache).

---

### Группа B: Intraday Execution Overlays

---

### 11. Opening Gap × GEX Interaction

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `gap_pct` | `(ES_open − ES_prev_close) / ES_prev_close × 100` | overnight gap % |
| `gap_vs_wall` | `distance from open to nearest GEX wall` | opened near support/resistance? |
| `gap_through_zero_gamma` | binary: did overnight gap push spot across zero-gamma? | regime flip overnight |

**Scoring:**

```
gap_modifier:

  abs(gap) < 0.3%: normal open → standard execution
  
  abs(gap) 0.3–0.7% AND gex_score > 0:
    → likely fade back (dealer hedging supports) 
    → MR entry after first 15 min

  abs(gap) 0.3–0.7% AND gex_score < 0:
    → continuation risk → no fade, wait for IB
  
  abs(gap) > 0.7%: 
    → skip first 30 min (hedging chaos)
    → GEX levels potentially stale
    → reduce size all day

  gap_through_zero_gamma = True:
    → REGIME CHANGED overnight
    → use NEW regime (post-gap), not prior
```

**Crowding: 4/5** — gap trading is old, but gap × GEX interaction is uncrowded.

**Data:** ES 1-min (have). Free.

---

### 12. IB (Initial Balance) vs Gamma Walls

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `ib_high` | max(ES price, first 30 min RTH) | initial balance high |
| `ib_low` | min(ES price, first 30 min RTH) | initial balance low |
| `ib_range_pct` | `(ib_high − ib_low) / spot × 100` | IB width |
| `ib_vs_call_wall` | `(call_wall − ib_high) / spot × 100` | distance from IB top to resistance |
| `ib_vs_put_wall` | `(ib_low − put_wall) / spot × 100` | distance from IB bottom to support |
| `ib_vs_zero_gamma` | position of IB relative to zero-gamma | IB entirely above/below/straddling |

**Scoring:**

```
ib_setup_score:

  IB tight (<0.3%) + inside walls + gex>0:
    → HIGH probability MR setup
    → fade IB extensions toward walls

  IB wide (>0.7%) + gex<0:
    → trend day likely
    → trade IB breakout, trail stop

  IB touching/exceeding wall:
    → wall test: if holds → strong fade signal
    → if breaks → wall failed → trend acceleration

  IB straddling zero-gamma:
    → regime uncertain → reduce size, wait for resolution
```

**Crowding: 3/5** — IB is Market Profile concept (Dalton). Known but rarely combined with GEX.

**Data:** ES 1-min (have).

---

### 13. Intraday RV Acceleration (Regime Invalidation)

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `rv_30min_rolling` | realized vol of ES over last 30 min (annualized) | current intraday vol |
| `rv_ratio` | `rv_30min / rv_session_avg` | acceleration vs session average |
| `rv_vs_expected` | `rv_30min / expected_rv_from_gex_regime` | is vol matching regime prediction? |

**Scoring:**

```
rv_invalidation:

  rv_ratio < 1.5: regime holding → continue strategy
  rv_ratio 1.5–2.5: vol accelerating → tighten stops, reduce size
  rv_ratio > 2.5: regime BROKEN → EXIT all positions
                   (GEX levels likely stale, forced flow overwhelming dealers)
```

**Crowding: 5/5 (UNCROWDED)** — nobody uses this systematically as regime invalidation.

**Data:** ES 1-min (have).

---

### Группа C: Special Situation Overlays

---

### 14. Buyback Blackout Seasonal

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `blackout_pct` | % of S&P 500 market cap in earnings blackout (est. from earnings calendar) | 0–100%. High = largest buyer absent |
| `blackout_phase` | pre-earnings (blackout ON) vs post-earnings (buyback window OPEN) | structural support present or not |

**Scoring:**

```
blackout_modifier:

  blackout_pct < 30%: buybacks active → structural support (1.1× long bias)
  blackout_pct 30–60%: mixed (1.0×)
  blackout_pct > 60%: most buybacks off → vulnerable (0.8× for MR longs, 1.1× for shorts/trend)
```

**Crowding: 3/5** — Goldman publishes. Fintwit discusses. But systematic: rare.

**Data:** earnings calendar for top 50–100 names (free: Yahoo/Alpha Vantage). Computeable.

---

### 15. Skew Divergence Warning

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `skew_25d` | `IV(25Δ put, 30DTE) − IV(25Δ call, 30DTE)` | put skew level |
| `skew_change_5d` | `Δskew_25d` | steepening = more hedging demand |
| `skew_vix_divergence` | `zscore(skew_change_5d) − zscore(ΔVIX_5d)` | skew moving without VIX = hidden stress |

**Scoring:**

```
skew_warning:

  skew_vix_divergence < 1.0: normal (no adjustment)
  skew_vix_divergence 1.0–2.0: caution (0.8× size)
  skew_vix_divergence > 2.0: WARNING — hedgers buying protection 
                              silently → reduce MR, prepare for vol event
```

**Crowding: 4/5 (LOW)** — skew discussed in vol circles, but divergence metric rare.

**Data:** self-compute from strike-level IV (have). Need to add 25-delta interpolation.

---

### 16. Margin Cascade Module (Special Event)

**Метрики:**

| Метрика | Формула | Интерпретация |
|---------|---------|---------------|
| `cascade_score` | composite: VIX level + VIX Δ1d + ES volume zscore + basis stress | 0–10, higher = more likely cascade |
| `cascade_phase` | `during` (selling) vs `post` (exhaustion) vs `none` | current state |
| `post_cascade_signal` | cascade confirmed + VIX declining from peak + basis normalizing | reversal opportunity |

**Trigger thresholds:**

```
cascade_detection:

  VIX > 30 
  AND VIX_change_1d > +5 pts 
  AND ES_volume_zscore > 2.0
  AND basis_zscore < −2
  → CASCADE IN PROGRESS
  → ALL core signals SUSPENDED
  → no trading

  post_cascade:
  VIX peaked (VIX_change_1d < 0 for 2 consecutive days)
  AND basis_zscore improving (> −1.5)
  → POST-CASCADE entry window
  → aggressive short-vol / long index
  → this is highest-premium environment
  → start 25% size, scale in over 3 days
```

**Crowding: 4/5 (LOW)** — buying post-cascade = classic prop, but retail rarely has framework.

**Data:** VIX (FRED), ES volume (have), basis (computable). Free.

---

## Composite Scoring System

### Как всё собирается вместе

```
DAILY PRE-MARKET COMPUTATION:
═════════════════════════════

1. Compute core scores:
   gex_score        ∈ [−2, +2]     (regime)
   cta_flow_score   ∈ [−2, +2]     (directional flow)
   voltarget_score  ∈ [−2, +2]     (directional flow)
   vanna_charm_score∈ [−2, +2]     (directional drift)
   opex_score       ∈ [−1, +1]     (regime modifier)

2. Composite direction score:
   direction_raw = 0.30 × cta_flow_score 
                 + 0.30 × voltarget_score 
                 + 0.25 × vanna_charm_score
                 + 0.15 × gex_score (только sign, не magnitude)
   
   direction_score ∈ [−2, +2]

3. Regime score:
   regime_raw = 0.50 × gex_score 
              + 0.30 × opex_score (scaled to ±2)
              + 0.20 × sign(vanna_charm → vol impact)
   
   regime ∈ {strong_MR, mild_MR, neutral, mild_trend, strong_trend}

4. Apply overlay modifiers:
   size_multiplier = vvix_modifier           [0–1]
                   × macro_veto_modifier     [0–1]
                   × event_modifier          [0–1]
                   × basis_modifier          [0–1]
                   × concordance_modifier    [0.6–1.2]
                   × blackout_modifier       [0.8–1.1]
   
   IF cascade detected: size_multiplier = 0 (override all)

5. Final position:
   
   IF regime = strong_MR or mild_MR:
     strategy = FADE (mean reversion at walls)
     direction_bias = direction_score (lean long/short within MR)
     size = base_size × size_multiplier × abs(gex_score)/2
   
   IF regime = mild_trend or strong_trend:
     strategy = BREAKOUT (IB break, trend follow)
     direction_bias = direction_score (which way to break)
     size = base_size × size_multiplier × 0.5 (trend = lower size)
   
   IF regime = neutral:
     strategy = SKIP or minimal size
     size = base_size × 0.25

6. Intraday adjustments:
   - gap_modifier at open
   - ib_setup_score after 30 min
   - rv_invalidation continuous monitoring
   - zero_gamma crossing → regime flip → reassess
```

---

## Crowding Summary

| Signal | Crowding Score | Who competes | Our differentiation |
|--------|---------------|-------------|-------------------|
| GEX levels | 2/5 (HIGH) | SpotGamma, Menthor, SqueezeMetrics, Unusual Whales, retail Discord | self-compute (vendor-independent), multi-Greek integration, combination scoring |
| CTA replication | 3/5 | Goldman/Nomura/JPM (institutional), some quant Twitter | free data, systematic vs their one-off reports, combination with GEX |
| Vol-target flows | 3/5 | Deutsche Bank, JPM (institutional) | self-compute, real-time vs their weekly reports |
| Vanna/Charm | **4/5 (LOW)** | Kai Volatility, SpotGamma premium (new) | **least crowded core signal**, computation barrier high for retail |
| OPEX calendar | 3/5 | everyone knows dates, SpotGamma publishes gamma impact | quantitative OI analysis + combination |
| VVIX | **4/5** | almost nobody retail | simple but almost nobody uses as meta-filter |
| Credit/vol-term | 3/5 | macro funds, fintwit | already built, systematic veto |
| Event calendar | 2/5 | everyone | combination with GEX = differentiated |
| Futures basis | **4/5** | institutional only | retail edge: nobody else watches |
| Cross-index concordance | **5/5** | **nobody** | completely original as systematic overlay |
| Opening gap × GEX | **4/5** | nobody as interaction | completely original |
| IB vs walls | 3/5 | Market Profile community + GEX community separately, not combined | combination = differentiated |
| RV invalidation | **5/5** | **nobody** | completely original |
| Buyback blackout | 3/5 | Goldman (institutional) | free replication |
| Skew divergence | **4/5** | vol desks (institutional), rare retail | self-computable |
| Margin cascade | **4/5** | prop desks (institutional) | proxy-based but rare retail framework |

**Наименее crowded (наша дифференциация):**
1. Cross-index concordance (5/5)
2. RV invalidation (5/5)
3. Vanna/Charm (4/5)
4. VVIX meta-filter (4/5)
5. Futures basis (4/5)
6. Opening gap × GEX (4/5)