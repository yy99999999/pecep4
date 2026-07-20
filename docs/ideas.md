

# Анализ структуры системы и тиринг треков

## Структурная декомпозиция

### Архитектура: трёхслойный стек

```
┌─────────────────────────────────────────────────────────┐
│  LAYER 3 — EXECUTION / SIZING                          │
│  (NOT YET BUILT)                                        │
│  vol-target, DD-cap, kill-switch, confidence calib.     │
│  meta-allocation (contextual bandit over proven legs)   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  LAYER 2 — SIGNAL STACK (VALIDATED)                     │
│                                                         │
│  ┌─────────┐   ┌──────────────────┐   ┌──────────────┐ │
│  │  VRP    │   │  GEX (0–7 DTE   │   │  Vol-term /  │ │
│  │ (size   │   │  gate + tail    │   │  Credit      │ │
│  │ scalar) │   │  filter)        │   │  (crisis-off)│ │
│  └────┬────┘   └────────┬────────┘   └──────┬───────┘ │
│       │                 │                    │         │
│       └────── COMBINE ──┴────────────────────┘         │
│       VRP scales size; GEX gates entry;                │
│       macro-filter vetoes in crisis                    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  LAYER 1 — DATA / COMPUTE INFRASTRUCTURE                │
│                                                         │
│  intrinio_options.py:                                   │
│    fetch → cache → self-compute IV/Δ/Γ → features      │
│    (vendor-independent: vendor SPX greeks broken)       │
│                                                         │
│  intermarket_lab.py:                                    │
│    FRED VIX/VIX3M/VXN + HY/IG OAS → vol-credit feats  │
│                                                         │
│  Spot: SPY/QQQ cache; SPX/NDX put-call parity infer    │
│  Coverage: 2021-09 → 2026-06, ~1150 days, 6 tickers    │
└─────────────────────────────────────────────────────────┘
```

### Что делает каждый компонент и почему он выжил

| Компонент | Роль в стеке | Механизм (flow-counterparty) | Статус валидации |
|-----------|-------------|------------------------------|-----------------|
| **GEX gate** | Бинарный фильтр: торговать / не торговать | Dealer gamma-hedging создаёт предсказуемый vol-режим: +GEX → dealer dampens (short vol safe), −GEX → dealer amplifies (short vol dangerous). Мы — counterparty к dealer hedge-flow | ✅ Sharpe 0.80 @ 10% cost, SPY+SPX cross-validated; worst day −18bp vs −94bp naive. Subperiod stable |
| **VRP (size)** | Непрерывный скаляр: сколько позиции | Hedgers систематически переплачивают за protection → implied > realized. Мы — counterparty к demand for insurance | ✅ Как gate — бесполезен (VRP_only loses). Как size multiplier на GEX-gated позицию — incrementally adds |
| **Vol-term / Credit** | Macro crisis-filter: veto | VIX backwardation + credit spread widening = системный стресс → все vol-premium стратегии ломаются. Фильтр уходит в кэш | ✅ 0.80 → 0.85 Sharpe; incremental OOS |
| **Direction** | — | — | ❌ Нет edge нигде: daily σ~1% vs edge~0bp. FDR kills all. Consistent across MP, VRP, GEX, positioning |
| **MP / Dalton** | Dropped | Vol predictable, but via intermarket not MP; no directional alpha | ❌ Killed by incrementality gate |
| **90DTE positioning** | Dropped | Signs flip across instruments, n=54, noise | ❌ Killed by cross-instrument non-replication |

### Критические зависимости и риски инфраструктуры

```
RISK MAP:
                                                    IMPACT
                                            Low          High
                                    ┌────────────┬────────────┐
                           High     │            │ Intrinio   │
                                    │            │ data loss / │
                    LIKELIHOOD      │            │ price hike  │
                                    ├────────────┼────────────┤
                           Low      │ FRED       │ Deep hist   │
                                    │ downtime   │ never avail │
                                    └────────────┴────────────┘
```

- **Single-vendor risk**: Intrinio Individual — единственный source. Vendor greeks broken (mitigated: self-compute). Deep history gated (NOT mitigated: стресс-тесты 2008/2011/2015/2018 невозможны).
- **History depth**: 2021-09 → present = ~4.7 лет. Покрывает 2022 bear + Aug 2024 VIX spike, но НЕ покрывает GFC, Volmageddon (Feb 2018), COVID crash (Mar 2020 частично). Это **главная неизвестная** для survival.
- **Self-compute IV**: корректен (vendor-independent), но зависит от mark quality. Marks clean → ОК.

---

## Тиринг треков

### Фреймворк оценки

Оцениваю по 5 осям (1–5 каждая, 5 = лучший):

| Ось | Что измеряет |
|-----|-------------|
| **Signal edge confidence** | Насколько валидирован альфа-источник (OOS, cross-instrument, incremental) |
| **Executability** | Можно ли реально торговать (инструменты доступны, ликвидность, prop-constraints) |
| **Data readiness** | Данные есть / нужны доп. затраты |
| **Breadth & capacity** | IR=IC·√breadth; сколько bets/day, capacity |
| **Marginal effort to deploy** | Сколько работы от текущего состояния до live |

---

### TIER S — **Options vol-engine (текущий: GEX-gated short-vol + VRP sizing + macro filter)**

```
Signal edge confidence:  ★★★★☆  (4)  — validated 2021-2026, cross-instrument (SPY+SPX),
                                        but NO crisis stress-test pre-2021
Executability:           ★★★★☆  (4)  — SPY/SPX options liquid; straddles executable;
                                        prop accounts can trade options
Data readiness:          ★★★★★  (5)  — all data live, pipeline built, self-compute working
Breadth & capacity:      ★★★☆☆  (3)  — daily signal, 1 bet/day per instrument,
                                        ~2-4 instruments; moderate breadth
Marginal effort:         ★★★☆☆  (3)  — needs: sizing layer, real execution cost model,
                                        stress episodes cell, kill-switch
                         ─────────
COMPOSITE:               19/25
```

**Почему Tier S:**
- Единственный трек с **полностью валидированным сигнальным стеком**, прошедшим FDR + incrementality + cross-instrument.
- Mechanism ясен (flow-counterparty к hedger demand + dealer gamma-hedging) и structural (не arbitrage, не alpha decay — пока hedgers существуют, premium существует).
- Sharpe 0.80–0.85 при 10% cost — это **реалистичный** уровень после friction.
- Tail risk managed: worst day −18bp vs −94bp naive = GEX gate работает как intended.

**Главные блокеры для перехода в live:**
1. Отсутствие crisis stress-test (2008, 2018, 2020) — unknown unknown на tail risk
2. Execution cost model (straddle slippage, assignment risk, gamma near expiry)
3. Risk/sizing layer не построен

---

### TIER A — **Track 2: Intraday gamma-levels → ES/MES direction**

```
Signal edge confidence:  ★★☆☆☆  (2)  — THEORETICAL; same GEX signal but applied to
                                        direction (which has 0 edge daily). Intraday
                                        MR/trend regime switch is plausible but UNTESTED.
                                        Crowding concern (SpotGamma et al.)
Executability:           ★★★★★  (5)  — ES/MES = most liquid futures, prop-friendly,
                                        low margin, 23h trading
Data readiness:          ★★★★☆  (4)  — EOD SPX OI (have) + ES 1-min (have es_continuous).
                                        Missing: intraday OI updates (EOD only = stale
                                        during session), real-time GEX would need live feed
Breadth & capacity:      ★★★★★  (5)  — multiple intraday trades, scalable, ES depth
Marginal effort:         ★★☆☆☆  (2)  — needs: full signal validation (strict OOS, subperiod),
                                        intraday backtesting framework (not built),
                                        execution logic, DoF control
                         ─────────
COMPOSITE:               18/25
```

**Почему Tier A, не S:**
- **Direction НЕ валидирован** — все предыдущие тесты показали 0 directional edge daily. Intraday *может* быть другим (gamma flip = regime switch — теория верна), но это ещё **гипотеза**, не факт.
- Crowding: SpotGamma, Menthor, GammaLab публикуют те же уровни → edge decay risk.
- Intraday backtest = огромный DoF explosion (entry/exit timing, hold period, threshold) → overfit risk высок. Требуется жёсткий OOS + subperiod + FDR.
- EOD-only OI → levels stale intraday (крупные flows после open не видны до следующего дня).

**Почему не ниже A:**
- Execution vehicle (ES/MES) — best-in-class: liquid, cheap, prop-friendly.
- Breadth огромен (intraday × daily).
- Signal layer (GEX) уже построен и validated *для vol prediction* — переиспользование, не с нуля.
- Если работает, это **highest capacity** трек (ES depth >> options).
- Является natural extension: vol-engine (Layer 2) → execution layer (Layer 2.5) → ES (Layer 3).

**Что нужно для promotion в S:**
1. Strict expanding-WF backtest: GEX flip level → ES 1-min → MR vs trend regime → P&L (with costs: ~$2.12 RT per MES)
2. Subperiod stability (2022 bear ≠ 2023 low-vol ≠ 2024 spikes)
3. Comparison vs naive (random entry same holding period) via FDR
4. Incrementality over current vol-engine

---

### TIER B — **Track 1: VX-futures short-vol execution**

```
Signal edge confidence:  ★★★★☆  (4)  — VRP = same edge source; VX contango = direct
                                        expression of VRP, cleaner than straddle
Executability:           ★☆☆☆☆  (1)  — ⛔ BLOCKED: prop firms generally CANNOT trade
                                        VIX futures (CBOE). Requires funded account or
                                        personal capital. Hard blocker.
Data readiness:          ★★☆☆☆  (2)  — need VX futures data (CBOE, not in Intrinio),
                                        VVIX (available via FRED/CBOE). Not cached.
Breadth & capacity:      ★★★☆☆  (3)  — daily, 1-2 rolls per month, moderate.
                                        Capacity ok (VX liquid) but infrequent.
Marginal effort:         ★★★☆☆  (3)  — signal layer exists (VRP+GEX+macro), but
                                        execution mapping (straddle→VX roll) needs build
                         ─────────
COMPOSITE:               13/25
```

**Почему Tier B:**
- **Hard executability blocker** доминирует. Не важно, насколько хорош сигнал, если инструмент недоступен.
- Тот же alpha source (VRP), но *более чистая* экспрессия (no gamma risk near expiry, no assignment, contango = carry). Если доступ появится, сразу promotion.
- VX-specific risks: roll cost, backwardation events (Volmageddon Feb 2018 = −96% XIV), margin spikes.

**Условие promotion в A/S:**
- Получить доступ к VX (personal account, или prop с VIX access)
- Получить VX data (CBOE settlement + continuous)
- Stress-test: Volmageddon, COVID, Aug 2024 through GEX/macro filter

---

## Сводная таблица

| Tier | Трек | Composite | Rate-limiter | ETA to live |
|------|-------|-----------|-------------|-------------|
| **S** | Options vol-engine (GEX+VRP+macro) | 19/25 | Crisis stress-test + sizing layer | 2–4 weeks if stress-test passes |
| **A** | Intraday gamma → ES/MES | 18/25 | Signal validation (direction untested intraday) | 2–3 months (backtest framework + validation) |
| **B** | VX-futures short-vol | 13/25 | ⛔ Instrument access blocked | Indefinite (blocked) |

```
DEPLOYMENT SEQUENCE:

  NOW          +1mo         +2mo         +3mo         +6mo
   │            │            │            │            │
   ▼            ▼            ▼            ▼            ▼
  [S: stress   [S: sizing   [S: LIVE    [A: OOS      [A: LIVE
   episodes     + exec       paper→      validated    if edge
   cell 12]     cost model]  real]       or killed]   holds]
                                                       │
                                          [B: unblocked?─── if yes → fast-track]
```

### Мета-наблюдение

Система в здоровом состоянии **методологически** — убито всё, что не прошло FDR + incrementality (MP, positioning, direction). Осталось только то, что structural и validated. Главные риски:

1. **Unknown tail**: 4.7 лет истории — недостаточно для short-vol strategy. 2008 (VIX 80), 2018 Volmageddon, 2020 March (VIX 82) — всё за пределами данных. GEX gate *должен* выключать в этих режимах, но это **непроверенная гипотеза**.

2. **Single-strategy risk**: один alpha source (VRP + flow-counterparty), три expression — но mechanism один. Correlated drawdown across all tracks if mechanism breaks.

3. **Crowding**: GEX levels becoming commoditized (SpotGamma mainstream). Edge may decay. Subperiod test (cell 8) — мониторить.




# Track 2: Повышение Signal Edge Confidence + альтернативные сигналы

## Проблема текущего Track 2

Текущая логика: EOD GEX flip → режим (positive gamma = MR, negative gamma = trend) → trade ES intraday.

Почему confidence = 2/5:
- **Daily direction = 0 edge** — доказано многократно, FDR kills all
- GEX flip — один бинарный сигнал с EOD лагом
- Crowding (SpotGamma и клоны)
- Огромный DoF intraday → overfit

Ключевой вопрос: можно ли **добавить сигналы**, чтобы от «голого GEX flip» перейти к **multi-signal regime-conditional execution** — и поднять confidence ДО валидации?

---

## Архитектура: от одного сигнала к режимно-условному стеку

```
                    LAYER: REGIME CONTEXT (daily, pre-session)
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    │  GEX regime    ──┐                      │
                    │  VIX microstructure ─┤                  │
                    │  Vol-of-vol state ───┤   REGIME         │
                    │  Term structure  ────┤   CLASSIFIER     │
                    │  Credit/macro  ──────┤   (daily)        │
                    │  Options flow  ──────┘                  │
                    │         │                                │
                    │         ▼                                │
                    │  { MR-safe | trend-likely | crisis-off } │
                    │         │                                │
                    └─────────┼───────────────────────────────┘
                              │
                    LAYER: EXECUTION LOGIC (intraday)
                    ┌─────────▼───────────────────────────────┐
                    │                                         │
                    │  if MR-safe:                            │
                    │    fade moves to GEX walls,             │
                    │    tight stops, size up                  │
                    │                                         │
                    │  if trend-likely:                       │
                    │    breakout/momentum, trail stops,       │
                    │    reduced size                          │
                    │                                         │
                    │  if crisis-off:                         │
                    │    NO TRADE (same as vol-engine veto)   │
                    │                                         │
                    │  Execute: ES/MES                        │
                    └─────────────────────────────────────────┘
```

**Idea: не предсказывать direction, а предсказывать REGIME (MR vs trend vs chaos) — и подбирать execution style.** Это ближе к vol prediction (где edge есть) чем к direction prediction (где edge = 0).

---

## Конкретные сигналы: что добавить к GEX flip

### 1. VIX Microstructure (данные: есть — FRED VIX daily + ES 1-min)

**a) VIX level → intraday MR strength**

```
Механизм: высокий VIX = дорогие опционы = dealer gamma-hedging
более агрессивен = сильнее MR. 
Но: высокий VIX + GEX<0 = amplification = тренд.

Сигнал: VIX_level × sign(GEX) = interaction term
  - VIX high + GEX>0 → STRONG MR (fade hard)
  - VIX high + GEX<0 → STRONG TREND (don't fade)
  - VIX low  + either → weak signal, small size or skip
```

Почему может работать: это не direction — это **vol-of-intraday-path prediction**. Мы уже показали vol predictability.

**b) VIX intraday change → regime shift detection**

```
Механизм: VIX spike intraday = dealer re-hedging = 
gamma-flip может произойти ВНУТРИ дня, 
делая утренний EOD GEX stale.

Сигнал: ΔVIX > threshold intraday → 
  reduce/exit (EOD levels unreliable)

Данные: VIX не в 1-min, но VIXM/VIX9D есть daily.
Proxy: ES realized vol last 30-min vs session avg.
Или: VIX futures (если добудем intraday VX).
```

**c) VIX term structure intraday slope**

```
Мы уже используем VIX/VIX3M для macro filter (daily).
Intraday: если VIX front > VIX3M (backwardation), 
это panic/hedging demand → negative gamma regime 
даже если EOD GEX was positive.

Проблема: VIX3M не в real-time. 
Proxy: IV of near-term SPX puts vs 3M puts 
(у нас есть EOD, не intraday).
```

**Verdict: (a) testable NOW with existing data. (b) proxy-only. (c) EOD-only = daily filter, не intraday.**

---

### 2. Vol-of-Vol / VVIX (данные: CBOE VVIX daily — можно достать через FRED/Yahoo)

```
Механизм: VVIX = implied vol OF VIX options = 
цена хеджирования хвостового риска.

VVIX high → dealers hedge VIX options aggressively → 
second-order gamma effects on SPX → 
intraday paths более хаотичны, MR breaks down.

VVIX low → стабильный vol regime → 
GEX levels более надёжны, MR works.

Сигнал: VVIX_percentile (rolling 60d)
  - VVIX < 30th pctl: GEX levels trustworthy → trade normally
  - VVIX 30-70th: normal
  - VVIX > 80th: GEX levels unreliable → reduce size / skip
```

**Почему ценно: это мета-сигнал — не direction, а RELIABILITY of other signals.** Прямо фильтрует когда GEX flip level стабилен vs шумит.

**Данные**: VVIX daily через Yahoo Finance (`^VVIX`) или CBOE download. Бесплатно.

**Verdict: HIGH priority. Easy to get, theoretically sound, testable.**

---

### 3. Options Flow Imbalance — Put/Call $ Volume Ratio (данные: есть — Intrinio EOD OI + volume)

**a) Daily P/C dollar volume ratio**

```
Механизм: hedgers buy puts → P/C ratio up → 
dealer short puts → dealer short gamma → 
REINFORCES GEX signal.

Но: если P/C high AND GEX still positive → 
divergence = GEX about to flip → caution.

Сигнал: 
  PC_dollar = Σ(put_volume × put_mid × 100) / Σ(call_volume × call_mid × 100)
  
  Concordance: PC_dollar high + GEX<0 → STRONG trend signal
  Divergence: PC_dollar high + GEX>0 → GEX flip imminent → reduce

Тест: daily feature, уже computeable из intrinio_options.
```

**b) OI change concentration — «whale hedges»**

```
Механизм: крупные put OI additions at specific strikes → 
новые dealer short gamma obligations → 
pull zero-gamma flip toward that strike.

Сигнал: 
  ΔOI_puts(K) > 2σ of rolling mean → 
  new gamma wall at K → 
  adjust GEX flip level expectation

У нас ЕСТЬ strike-level OI daily → можно считать ΔOI(K).
```

**c) Volume-vs-OI divergence**

```
Механизм: high volume but OI flat → closing/rolling (not new position) → 
dealers unwinding gamma → GEX level shifting.

High volume AND OI increase → new positions → GEX level reinforced.

Сигнал: vol_oi_ratio per strike, flag когда 
volume >> OI_change (= rolls, not flow).
```

**Verdict: (a) implementable NOW, theoretically sound. (b) interesting but noisy. (c) second-order, test after (a).**

---

### 4. Cross-Asset Macro Context (данные: есть — FRED, intermarket_lab.py)

**a) Credit impulse → vol regime shift leading indicator**

```
Механизм: HY OAS widening LEADS VIX spikes by 1-3 days 
(credit market prices risk before equity vol).

Если credit widening → even with GEX>0, 
MR regime about to break → reduce size.

Сигнал: 
  ΔOAShy_5d > threshold → caution flag
  
Уже в intermarket_lab.vol_credit_features.
Нужно: протестировать как DAILY pre-filter для Track 2.
```

**b) Rate vol (MOVE index) → equity vol transmission**

```
Механизм: MOVE high → bond dealers hedging → 
cross-asset vol transmission → equity vol spills, 
SPX gamma levels less stable.

Данные: MOVE через FRED (ICE BofA MOVE, серия может быть gated).
Или proxy: |Δ10Y yield| 5d rolling.

Сигнал: MOVE_percentile > 80th → reduce Track 2 size.
```

**c) Dollar / DXY strength → risk regime**

```
Механизм: strong $ = EM stress / liquidity drain → 
risk-off flows → put buying → GEX shifts.

Проблема: direction-adjacent. Likely noisy for index MR/trend.
Low priority.
```

**Verdict: (a) ALREADY BUILT, just needs repurpose as daily filter. (b) worth testing. (c) skip.**

---

### 5. Realized Vol Path Features — ES intraday (данные: есть — es_continuous 1-min)

**Эти не macro/options — это PRICE MICROSTRUCTURE из самого ES.**

**a) Overnight vs RTH gap**

```
Механизм: overnight = lower liquidity, thinner book → 
large gap at open = forced re-hedging → 
первые 30 мин = noise/hedging flow, затем MR.

Сигнал: |gap| > 0.5% → first 30 min = no trade; 
then fade if GEX>0.

Gap direction + GEX sign = interaction.
```

**b) RTH opening range (первые 15-30 мин) relative to GEX levels**

```
Механизм: initial balance (IB) relative to 
GEX walls/flip level → «is price at a wall or in no-man's-land?»

Сигнал: 
  open_price near put_wall (within 0.3%) → support, fade down
  open_price near call_wall (within 0.3%) → resistance, fade up
  open_price between walls, no nearby level → no edge, skip

Это буквально Market Profile IB 
но ANCHORED TO OPTIONS-DERIVED LEVELS rather than 
volume-derived (which we killed).
Ключевое отличие: levels имеют structural причину 
(dealer hedging), а не statistical (volume clustering).
```

**c) Intraday realized vol trajectory**

```
RV_30min rolling → если RV accelerating → 
regime shifting, GEX levels breaking → 
reduce/exit.

RV declining within session → MR regime 
consolidating → increase confidence in fade.
```

**d) ES order flow / volume clock**

```
Volume-weighted returns, 
VWAP slope, 
cumulative delta (if available — 
нет в текущих данных, нужен tick data).

Без tick data: volume surge detection 
(1-min volume > 3σ → forced flow event).
```

**Verdict: (a)(b) HIGH value — testable now. (c) testable. (d) data-limited.**

---

### 6. Cross-Instrument GEX Divergence (данные: есть — SPY vs SPX, QQQ vs NDX)

```
Механизм: SPX GEX driven by institutional/dealer hedging.
SPY GEX driven by retail + ETF flows.
QQQ GEX = tech-specific hedging.

Divergence: SPX GEX>0 но QQQ GEX<0 → 
tech is in negative gamma, broad market is not → 
sector rotation risk, overall MR weaker.

Concordance: SPX GEX>0 AND QQQ GEX>0 → 
broad-based positive gamma → strong MR.

Сигнал: concordance_score = sign(GEX_SPX) × sign(GEX_QQQ)
  +1 → high conviction
  -1 → low conviction / skip
```

**Verdict: implementable NOW — мы уже compute GEX для всех 4 instruments. Never tested as interaction.**

---

## Приоритизация: что тестировать и в каком порядке

```
PRIORITY MATRIX
                        
                        Theoretical         Data
                        Soundness           Ready?     Implementation
Signal                  (mechanism)                    Effort          TEST ORDER
─────────────────────────────────────────────────────────────────────
VIX × GEX interaction   ★★★★★ (direct)     ✅ yes     low             ① FIRST
VVIX meta-filter         ★★★★★ (meta)       🟡 fetch   low             ② 
GEX cross-instrument     ★★★★☆              ✅ yes     low             ③
concordance
P/C $ volume ratio       ★★★★☆ (flow)       ✅ yes     medium          ④
Credit impulse ΔOAShy    ★★★★☆ (lead)       ✅ yes     low (built)     ⑤
IB relative to GEX walls ★★★★☆ (structure)  ✅ yes     medium          ⑥
Overnight gap × GEX      ★★★☆☆              ✅ yes     low             ⑦
VVIX → GEX reliability   ★★★★★              🟡 fetch   low             (= ②)
RV trajectory intraday   ★★★☆☆              ✅ yes     medium          ⑧
MOVE / rate vol           ★★★☆☆              🟡 fetch   low             ⑨
ΔOI concentration        ★★★☆☆              ✅ yes     high            ⑩
DXY                      ★★☆☆☆              🟡 fetch   low             SKIP
```

---

## Validation protocol (чтобы не повторить ошибки)

```
FOR EACH CANDIDATE SIGNAL:

1. Compute daily feature → merge with ES daily returns 
   (NOT intraday yet — first pass: does regime predict 
   daily vol / daily |return| / daily range?)

2. Expanding-WF, train-only quantile splits.
   Target: NOT daily return sign (proven = no edge).
   Target: daily range, daily |return|, 
   max-adverse-excursion, close-vs-IB.

3. FDR (BH) across all cells/signals tested.

4. Incrementality: does new signal add to GEX alone?
   Nested OOS comparison.

5. ONLY IF (1-4) pass: 
   move to intraday backtest 
   (1-min ES, regime-conditional execution rules).

6. Intraday: fixed rule per regime (no optimization), 
   out-of-sample only. 
   Costs: $2.12 RT per MES, 1 tick slippage.

7. Subperiod stability: 2021-2022 | 2023 | 2024 | 2025-2026.

8. Crowding check: compare pre-2023 (SpotGamma less mainstream)
   vs post-2023 (crowded).
```

**Цель: превратить Track 2 из «one untested signal» (confidence 2/5) в «multi-signal validated regime system» (confidence 4/5) ДО того, как строить intraday execution framework.**

---

## Ожидание: куда confidence может дойти

| Scenario | Tests pass? | New confidence | Tier |
|----------|------------|---------------|------|
| GEX regime + VIX interaction + VVIX filter → daily range predictable, incremental | Yes all | 4/5 → **Tier S** | S |
| GEX regime + 1-2 signals help but small lift | Partial | 3/5 → **stays A** | A |
| Все intraday direction tests fail (vol predictable but direction = 0 even conditioned on regime) | No | 2/5 → **kill Track 2** or pivot to pure vol-trade intraday (VIX options intraday?) | drop/pivot |

Последний сценарий (всё fails) — **вполне возможен**. Это ок. Именно за этим protocol: не строить execution framework на untested hypothesis. Test first, build second.

---

## Ключевой insight

Track 2 по сути — вопрос: **«можно ли monетизировать vol-regime prediction через DIRECTION, а не через options premium?»**

Vol-regime мы предсказываем (доказано). Options premium — монетизируем (Track S). Но direction — нет (доказано daily).

Track 2 делает ставку, что **intraday** + **regime-conditional** + **anchored to structural levels** = достаточно другая задача, чтобы direction edge появился.

Это **разумная гипотеза**. Но именно гипотеза. Все сигналы выше — способы сделать её более testable и более robust, если она верна.




# Если intraday direction = 0: куда перестраивать

## Сначала — что именно мы узнаём при провале Track 2

Track 2 fail означает конкретно:

```
Даже с мультисигнальным режимным контекстом 
(GEX + VIX + VVIX + credit + flow),
conditioned intraday ES direction 
НЕ имеет edge после costs + FDR.

НО: vol-regime prediction ПО-ПРЕЖНЕМУ РАБОТАЕТ.
```

Это не провал системы. Это подтверждение фундаментального вывода: **flow-counterparty alpha живёт в vol/premium, не в direction**. Просто мы пытались monetize через direction и не получилось.

Вопрос перестраивается: **как ещё можно monетизировать validated vol-regime prediction, кроме short straddle?**

---

## Два пути

```
                    VOL-REGIME PREDICTION (validated)
                              │
              ┌───────────────┴───────────────┐
              │                               │
    PATH A: OPTIMIZE                 PATH B: NEW EXECUTION
    current options engine           vehicles для того же edge
    (short vol via options)          (не direction, не straddle)
              │                               │
     deeper, wider, smarter          same alpha, other instruments
```

---

## PATH A — Оптимизация текущего options engine

Текущее: daily short straddle, GEX-gated, VRP-sized, macro-filtered. Sharpe 0.85.

Что можно улучшить **без нового alpha source**:

### A1. Structure selection: straddle → оптимальная структура по режиму

```
Сейчас: всегда short straddle (ATM put + call).

Проблема: straddle = max vega/gamma exposure, 
но в разных GEX-режимах optimal structure разная:

GEX strongly positive (deep MR regime):
  → short straddle ОК (range-bound → theta wins)
  → но можно: short iron butterfly (capped risk, 
    similar theta, lower margin)

GEX weakly positive (mild MR):
  → short strangle (wider wings, less gamma risk,
    lower premium but higher win rate)
  → или: short iron condor 
    С КРЫЛЬЯМИ НА GEX WALLS (structural levels!)

High VRP + GEX positive:
  → wider strangle (collect more premium, 
    walls protect)

Low VRP + GEX positive:
  → tight structure or skip (premium не оправдывает risk)
```

**Ключевая идея: GEX walls = natural strike selection.** Put wall → sell put spread below it. Call wall → sell call spread above it. Это не direction bet — это vol structure anchored to dealer hedging levels.

```python
# Pseudo-logic:
put_wall = gex_levels['max_put_gamma_strike']  
call_wall = gex_levels['max_call_gamma_strike']

if regime == 'strong_MR':
    sell_put_at(put_wall - buffer)
    sell_call_at(call_wall + buffer)
    # = iron condor with structurally-informed wings
elif regime == 'mild_MR':
    sell_strangle(put_wall - 2*buffer, call_wall + 2*buffer)
    # wider, less premium, higher survival
```

**Testable NOW** — strike-level GEX data существует, нужно только backtest с разными structures.

Effort: medium. Value: potentially significant (better risk-adjusted from same edge).

---

### A2. DTE optimization: не только 0-7 DTE

```
Сейчас: GEX gate использует 0-7 DTE (validated).
Execution: какой DTE продавать?

Варианты:
- 0 DTE (same-day expiry): max theta, max gamma risk.
  = 0DTE boom в SPX/SPY. Огромная ликвидность.
  GEX gate буквально создан для этого: 
  "is today safe to sell 0DTE?"

- 1-3 DTE: lower gamma, still high theta.

- 7 DTE: moderate theta, moderate gamma. 
  Roll weekly.

- 30-45 DTE: classic. Low gamma, low theta/day.
  VRP extraction smoother.

Optimal DTE может зависеть от режима:
  - GEX strongly positive → safe to sell 0-1 DTE 
    (dealer hedging suppresses moves)
  - GEX weakly positive → sell 7-14 DTE 
    (less intraday gamma risk)
  - High VVIX → sell 30+ DTE 
    (avoid near-term vol-of-vol)
```

**0DTE short premium с GEX gate — отдельная стратегия, extremely high breadth (daily!) и fits perfectly в flow-counterparty framework.** Retail покупает 0DTE лотерейные билеты → мы counterparty.

**Testable NOW** — 0DTE data есть в SPXW (daily expiries с 2022).

Effort: medium (нужен intraday P&L tracking для 0DTE). Value: HIGH (breadth ×5, capacity huge).

---

### A3. Multi-underlying: расширение breadth

```
Сейчас: SPY, SPX (validated). QQQ, NDX (partially tested).

Расширение (с текущим Intrinio Individual plan):
- IWM (Russell 2000) — другой risk profile, less correlated
- DIA (DJIA) — less liquid but decorrelated
- Sector ETFs: XLF, XLE, XLK — 
  sector-specific hedging flows, less crowded

Для каждого: compute GEX, test VRP, same framework.

Breadth: IR = IC × √breadth. 
Если IC stable across 4-6 underlyings → 
√breadth goes from √1 ≈ 1 to √6 ≈ 2.45 → 
IR doubles+ при том же IC.
```

**Проблема: sector ETFs имеют lower options volume → GEX менее reliable. Нужно тестировать.**

Effort: low (same code, new symbols). Value: potentially large (breadth).

---

### A4. Dynamic sizing: Kelly / vol-target / conviction-weighted

```
Сейчас: VRP как size scalar (validated incrementally).

Улучшение: полноценный sizing layer.

Inputs:
- VRP level (continuous) → expected premium
- GEX strength (not just sign, but magnitude) → expected regime stability
- VVIX → confidence in GEX levels
- Credit → macro stress
- Recent P&L → drawdown management

Output: fraction of max position (0% → 100%)

Framework: fractional Kelly on estimated 
win_rate × avg_win vs loss_rate × avg_loss, 
conditional on regime.

+ Hard constraints:
  - Max loss per day (e.g., 2% of account)
  - Max consecutive losses before pause (kill switch)
  - Vol-target: scale position so portfolio vol = target
```

Effort: medium. Value: HIGH (same alpha, much better risk-adjusted returns via sizing).

---

### A5. Calendar/diagonal spreads: exploit vol term structure

```
Сейчас: vol-term slope (VIX/VIX3M) используется 
как binary macro filter.

Идея: monetize term structure DIRECTLY.

Если VIX/VIX3M slope steep (contango):
  sell near-term vol, buy far-term vol = 
  calendar spread (short front, long back).
  
  Это = short roll-down + VRP extraction.
  Similar to VX futures (Track 1) but 
  done in SPX options (no VX needed, no prop restriction).

Если VIX/VIX3M slope flat/inverted:
  skip (no term structure premium to extract).

GEX gate: determines STRIKE selection 
(ATM calendar vs at a wall).
VRP: determines SIZE.
Term structure slope: determines STRUCTURE (calendar vs vertical).
```

**Это фактически Track 1 (VX short vol) реализованный через SPX options.** Обходит prop-блокер VX access.

Effort: medium-high (new backtest needed). Value: HIGH (new expression of same alpha, prop-tradeable).

---

## PATH B — Новые execution vehicles (тот же alpha, другие инструменты)

### B1. VIX options (не VX futures — options НА VIX)

```
Блокер Track 1: prop firms can't trade VX futures.
Но: VIX options торгуются на CBOE, 
некоторые prop firms / brokers позволяют 
(нужно проверить конкретно).

Execution:
  Short VIX put spreads (sell 15 put, buy 12 put)
  когда VRP positive + GEX safe + VIX elevated.

  = selling vol insurance on vol itself.
  = counterparty to tail hedgers (who buy VIX calls/puts).

Данные: VIX options через Intrinio? 
Нужно проверить. Если да — тот же pipeline.

Advantage: VIX options = PURE vol instrument, 
no delta contamination. Cleaner than SPX straddle.
```

Effort: medium (data check + new backtest). Value: HIGH if accessible.

---

### B2. Variance/vol swaps через replication (retail-accessible)

```
Variance swap payoff = realized_var - implied_var.
Short variance = short realized, long implied = 
collect VRP.

Replication: portfolio of options across strikes 
(1/K² weighting). Not practical retail.

BUT: simplified version = 
straddle + strangle portfolio at multiple strikes 
= "short variance-like" exposure.

Мы уже знаем optimal strikes (GEX walls) → 
structure = short iron condor / butterfly LADDER 
across multiple strikes weighted by 1/K².

Advanced, but computable.
```

Effort: high. Value: theoretical, maybe over-engineered.

---

### B3. Cross-asset vol premium: rates, commodities, FX

```
Если VRP exists в equities → it exists elsewhere 
(hedgers pay premium in every asset class).

Candidates:
- Treasury options (TLT): rate vol premium.
  GEX → n/a (different market structure), 
  but VRP likely exists.
  
- Gold options (GLD): hedger demand = real.
  
- Oil (USO/CL): producer hedging = structural 
  put buying → VRP.

- FX (FXE, UUP or direct): corporate hedging = 
  structural flow.

Problem: our entire pipeline is equity-options specific.
Porting = significant effort. GEX mechanism may not apply 
(different dealer structure).

BUT: VRP is universal. Could test with simple 
short straddle + vol-term filter (no GEX).
```

Effort: high. Value: diversification (uncorrelated VRP extraction).

---

### B4. ETF options vol premium (beyond indices)

```
Sector/thematic ETFs with structural hedging demand:
- XLF (financials) — banks hedge
- XLE (energy) — producers hedge
- HYG (high yield) — credit hedgers
- EEM (EM) — EM hedgers
- TLT (bonds) — duration hedgers

Each has own vol premium + own flow dynamics.
Less crowded than SPX GEX.

Test: compute VRP (IV-RV) per ETF, 
short straddle gated by own-GEX + broad GEX + VRP.

Breadth expansion: 6-10 underlyings → 
√breadth = √10 ≈ 3.2 → IR ×3 if IC holds.
```

Effort: medium (same code, many symbols). Value: HIGH (breadth).

---

### B5. Dispersion: index vs single-stock vol

```
Механизм: index vol < sum of component vols 
(correlation < 1). Hedgers buy index puts 
(cheap protection) → index vol inflated relative 
to single-stock vol.

Trade: short index vol + long single-stock vol 
= short correlation.

Classic prop/vol-arb strategy. 
Structural edge (index hedging demand) = 
flow-counterparty.

Problem: needs single-stock options data 
(have it for any ticker via Intrinio, 
but constituents = current only, survivorship).
Capital intensive (many legs).

Simplified version: 
short SPY straddle + long top-5 component straddles 
(AAPL, MSFT, AMZN, NVDA, GOOG).
```

Effort: high (many legs, correlation modeling). Value: HIGH conceptually, execution complex.

---

## Рекомендуемая последовательность (если Track 2 direction fails)

```
 PHASE 1 (immediate, weeks 1-4): optimize current engine
 ─────────────────────────────────────────────────────────
 
 A2: 0DTE strategy                    ◄── HIGHEST PRIORITY
     (GEX gate + 0DTE short premium)      breadth ×5, retail counterparty,
     Data: SPXW 0DTE exists.              fits theory perfectly
     Test: daily short 0DTE straddle/     
     strangle, GEX-gated.                  
                                           
 A1: Structure by regime               ◄── second
     (iron condor at GEX walls vs         structural strike selection,
     straddle vs strangle)                better risk/reward
     
 A4: Sizing layer                     ◄── third (infra, always needed)
     (Kelly, vol-target, kill-switch)

 PHASE 2 (weeks 4-8): breadth expansion
 ─────────────────────────────────────────────────────────
 
 A3: Multi-underlying                 ◄── same code, new tickers
     IWM, QQQ (if not already),           breadth is free IR
     XLF, XLE, TLT                        
     Test GEX viability per ticker.

 A5: Calendar spreads                 ◄── term structure monetization
     (SPX calendars = Track 1 via         replaces blocked VX access
     options, no prop restriction)

 PHASE 3 (weeks 8-12): new instruments
 ─────────────────────────────────────────────────────────
 
 B1: VIX options (if accessible)      ◄── pure vol instrument
 B4: Sector ETF vol premium           ◄── decorrelation + breadth
 B5: Dispersion (simplified)          ◄── if capital allows

 PHASE 4 (stretch): cross-asset
 ─────────────────────────────────────────────────────────
 B3: TLT, GLD, FX vol premium        ◄── uncorrelated VRP
```

---

## Переосмысление: как выглядит система после этой перестройки

```
BEFORE (current):
  1 signal (GEX) × 1 structure (straddle) × 2 instruments (SPY/SPX) 
  = ~2 daily bets
  Sharpe 0.85

AFTER (Phase 1-2 complete):
  3 signals (GEX, VRP-size, macro) 
  × 3 structures (straddle, strangle, iron condor, 0DTE, calendar)
  × 6 instruments (SPY, SPX, QQQ, IWM, XLF, TLT)
  × sizing layer
  = ~6-10 daily bets, diversified
  
  Target Sharpe: 0.85 × √(breadth multiplier) 
  → if IC holds: 0.85 × √3 ≈ 1.47
  → conservative (IC decays for weaker underlyings): ~1.1-1.2

AFTER (Phase 3):
  + VIX options, sector ETFs
  = 10-15 daily bets
  Target: Sharpe 1.2-1.5
```

Это **vol-premium harvesting portfolio** — не одна стратегия, а портфель экспрессий одного structural edge, диверсифицированный по structure × instrument × DTE.

---

## Ключевой принцип

```
┌─────────────────────────────────────────────────┐
│                                                 │
│  Если direction = 0 (confirmed),                │
│  НЕ ИЩИ direction в другом месте.              │
│                                                 │
│  Вместо этого:                                  │
│  ОДИН validated edge (VRP / flow-counterparty)  │
│  × МНОГО expressions (structure × instrument    │
│    × DTE × sizing)                              │
│  = portfolio of premium extraction.             │
│                                                 │
│  IR = IC × √breadth.                            │
│  IC фиксирован (structural edge).              │
│  √breadth — то, что ты оптимизируешь.          │
│                                                 │
└─────────────────────────────────────────────────┘
```

Это фундаментально **insurance company model**: не predict кто разобьётся, а price premium correctly, diversify across many policies, survive tail events (GEX gate + macro filter = underwriting standards).




# Полная ревизия: все идеи × данные × исполнение × edge

## Сначала — переосмысление логики поиска

Ты прав, что нужно вернуться к фундаментальному вопросу. Не «как улучшить текущую систему», а **«где вообще существует extractable edge для retail на индексах, с какими данными, на каком горизонте»**.

Переформулирую критерии жёстко:

```
MUST HAVE:
1. Данные доступны retail (бесплатно или <$100/мес)
2. Исполняется на индексах/index ETFs/index futures
3. Механизм = structural (не data-mining pattern)
4. Edge target ≠ обязательно direction 
   (vol, premium, relative value, timing — всё ОК)
5. Testable with honest methodology (WF, FDR, incrementality)

SCORING:
- Data accessibility (1-5)
- Mechanism clarity (structural vs statistical) (1-5)  
- Crowding risk (5 = uncrowded, 1 = everyone does it)
- Capacity / breadth (1-5)
- Testability with what we HAVE or can GET cheaply (1-5)
```

---

## Полная карта идей

Разбираю ВСЁ из твоих четырёх фреймворков + добавляю то, что пропущено.

---

### FRAMEWORK 1: FLOW-FIRST

#### 1.1 Dealer Gamma Hedging (GEX)

**Что это**: dealers short options → must delta-hedge → создают mechanical price impact. GEX>0 = suppress vol, GEX<0 = amplify vol.

**Data accessibility: 4/5**
- OI по strike: Intrinio (есть), CBOE (платно), OCC (бесплатно с задержкой)
- Нужно: self-compute gamma per strike from OI + IV. Мы уже делаем это.
- Limitation: EOD only (intraday OI = institutional/vendor only, $$$)

**Mechanism clarity: 5/5** — чистая механика. Dealer обязан хеджировать по регулятории. Нет discretion.

**Crowding: 2/5** — SpotGamma, Menthor, GammaLab, SqueezeMetrics всё публикуют. Crowded. Но: crowding в *interpretation*, raw levels различаются (разные модели assumptions). И edge в vol prediction, не direction — crowding менее релевантно.

**Breadth: 3/5** — daily signal, ~2-6 instruments.

**Testability: 5/5** — уже validated.

**Наш статус: ✅ VALIDATED. Sharpe 0.85. Это якорь системы.**

**Что ещё можно извлечь (не direction)**:
- Pinning к max-gamma strikes на OPEX → calendar effects
- Charm/vanna flow (delta decay by time/vol change) → second-order dealer flow
- GEX inversion events → regime transition detection

---

#### 1.2 CTA / Systematic Trend Following Replication

**Что это**: ~$350B AUM торгует по mechanical rules (MA crossovers, breakouts, vol-adjusted). Если знаешь их уровни → знаешь будущий flow.

**Data accessibility: 3/5**
- Price data (MA levels): бесплатно (any source)
- CTA positioning estimates: SocGen CTA Index (free, weekly), Deutsche Bank CTA proxy (Bloomberg terminal = не retail)
- CFTC Commitment of Traders: бесплатно, weekly, lagged (Tue data → Fri release)
- Goldman/JPM CTA positioning reports: paywalled (зачастую утекает в финтвиттер, ненадёжно)

**Mechanism clarity: 4/5** — rules известны (10/20/50/100/200 MA, breakout, vol-scale). Но: heterogeneity (не все CTA одинаковы), entry/exit timing varies. Aggregate flow predictable, individual fund — нет.

**Crowding: 3/5** — идея известна (CTA replication papers exist: Blin, Dao, etc.), но retail реально этим мало кто торгует. Institutional — да (Goldman, JPM публикуют CTA estimates для клиентов).

**Capacity: 4/5** — ежедневные сигналы, multiple instruments (ES, NQ, bonds, commodities — но мы ограничены индексами).

**Testability: 4/5** — MA levels computeable, backtest straightforward. Проблема: нет точного ground truth «CTA position», только proxy.

**Наш статус: ❌ НЕ ТЕСТИРОВАНО.**

**Конкретный тест (доступный нам)**:
```
Сигнал: SPX цена relative to 10/20/50/100/200 MA envelope.
  - Все MAs bullish aligned + price >200MA → CTAs maximally long
    → further upside = buying exhausted → MR / vulnerable to reversal
  - Price crosses below 200MA → CTAs FORCED to sell
    → mechanical sell pressure → short-term underperformance

Prediction target: NOT direction. 
  → Forward 5-20 day realized vol
  → Forward max drawdown
  → «Is selling pressure imminent?» (binary: 
    distance to nearest MA < threshold)

Execution: 
  - Near CTA sell trigger → buy puts / increase VRP hedge
  - CTA fully long → reduce short-vol size (crowded long)
  - CTA fully short → increase short-vol size 
    (forced selling done, vol premium rich)

Integration: это не новая стратегия, это ДОПОЛНИТЕЛЬНЫЙ 
FILTER/SIZER к vol-engine.
```

**Data needed**: price only (free). CFTC COT for validation (free, weekly).

**Verdict: HIGH PRIORITY. Testable free. Mechanism structural. Natural complement to GEX (different timescale: GEX = days, CTA = weeks).**

---

#### 1.3 Vol-Targeting / Risk-Parity Mechanical Flows

**Что это**: ~$500B+ в vol-targeting strategies. RV goes up → they sell equities (mechanically). RV goes down → they buy. Feedback loop.

**Data accessibility: 4/5**
- Realized vol: compute from price (free)
- Vol-target thresholds: research estimates (10-15% target typical)
- Current equity allocation estimate: RV → model their position (Deutsche Bank publishes estimates, not free; but replicable)

**Mechanism clarity: 5/5** — pure mechanical. Vol up → sell. No discretion. Academic papers confirm (Moallemi & Saglam 2015, Sornette et al.).

**Crowding: 3/5** — known concept but not widely traded against.

**Testability: 5/5** — RV computable, model vol-target position, backtest.

**Наш статус: ❌ НЕ ТЕСТИРОВАНО explicitly (partially captured by VRP — when RV spikes, VRP changes, but not same signal).**

**Конкретный тест**:
```
Model: estimate aggregate vol-target equity allocation
  equity_alloc = target_vol / realized_vol_20d
  (capped 0-150%)

Signal:
  - Δalloc < -X% (forced selling coming or happening)
    → short-term pressure down → vol will spike more → 
    DON'T sell vol (even if GEX says ok)
  
  - Δalloc > +X% (forced buying coming)
    → short-term support → vol will compress → 
    sell vol aggressively

  - alloc near 0% (fully de-risked after crash)
    → max forced buying ahead when vol normalizes →
    strongest buy signal (NOT direction — vol compression signal)

Target: forward realized vol (not direction)
Integration: filter/sizer for vol-engine (like CTA)
```

**Verdict: HIGH PRIORITY. Free data. Strongest mechanism after GEX. Different timescale (vol-target = days-weeks, GEX = hours-days).**

---

#### 1.4 Pension / Sovereign Wealth Rebalancing

**Что это**: $30T+ quarterly/monthly rebalancing to target allocation (e.g., 60/40). Equities rally → overweight → sell equities end-of-quarter.

**Data accessibility: 2/5**
- Quarterly equity returns: free → estimate rebalancing magnitude
- Actual flows: not observable directly
- Calendar: quarter-end dates known perfectly
- State Street, ICI fund flow data: lagged, institutional

**Mechanism clarity: 4/5** — mechanical, but timing uncertain (some rebalance daily, most monthly/quarterly). Magnitude depends on drift, not just direction.

**Crowding: 2/5** — quarter-end rebalancing is well-known (JPM publishes estimates pre-quarter-end). But quantifying and trading it: less crowded.

**Testability: 3/5** — calendar effect, testable but small sample (4 quarter-ends per year × 5 years = 20 obs). Power problem.

**Конкретный тест**:
```
Signal: 
  rebal_estimate = (equity_return_QTD / bond_return_QTD) 
                    × total_pension_AUM × target_weight_change

  Last 3-5 days of quarter: estimated sell/buy pressure.

  If equities up big in Q → sell pressure last week → 
  don't sell vol near quarter-end? Or: expect vol to compress 
  after rebal done.

Problem: 20 observations in our data. n=20 → 
no statistical power for any edge.
```

**Verdict: LOW PRIORITY now. n too small. Could be filter (quarter-end caution flag) but not testable as alpha source with 5 years of data. Revisit with deep history.**

---

#### 1.5 Corporate Buyback Blackout

**Что это**: ~$800B+/year. Companies can't buy back shares ~2 weeks before earnings. Removes largest buyer.

**Data accessibility: 3/5**
- Earnings calendar: free (Yahoo, Alpha Vantage)
- Blackout window: ~2 weeks before earnings (not exact, company-specific, but aggregate index-level estimable)
- Actual buyback execution: SEC filings (10-Q), lagged by quarter. Not real-time.
- Aggregate buyback blackout % of S&P: Goldman publishes (not free), but replicable from earnings calendar.

**Mechanism clarity: 4/5** — structural: legal restriction prevents buying. But: companies can file 10b5-1 plans (pre-scheduled) which partially bypass blackout. Attenuates signal.

**Crowding: 3/5** — known seasonality, but not widely traded systematically.

**Testability: 4/5** — earnings dates → blackout window → compute % of S&P in blackout → correlate with returns/vol.

**Конкретный тест**:
```
Signal: 
  blackout_pct = % of S&P 500 market cap currently in 
                 earnings blackout window (2 weeks pre-earnings)

  Peak blackout: ~Jan, Apr, Jul, Oct (earnings season start)
  
  → High blackout % → largest buyer absent → 
    more downside vulnerability → vol should be higher → 
    buy vol or reduce short-vol size

  → Low blackout % → buybacks active → 
    support → vol should be lower → 
    sell vol more aggressively

Target: forward vol, not direction
Integration: seasonal sizer for vol-engine
```

**Data**: earnings dates for top 100 S&P names → compute rolling blackout %. Free.

**Verdict: MEDIUM PRIORITY. Testable. Structural. But: partial bypass (10b5-1), calendar overlap with earnings vol (hard to separate buyback effect from earnings vol effect). Test as seasonal sizer.**

---

#### 1.6 OPEX Pin / Dealer De-risking (ДОБАВЛЕНО — не в твоём списке)

**Что это**: monthly/weekly OPEX (options expiration) → max OI strikes attract price (pinning). After OPEX → GEX drops sharply → gamma vacuum → vol spike.

**Data accessibility: 5/5** — expiration calendar is deterministic. OI by strike = already have.

**Mechanism clarity: 5/5** — dealer hedging concentrated near expiry. At expiry, hedging unwinds → flow disappears → vol regime changes. Well-documented (Ni, Pearson, Poteshman 2005; Avellaneda & Lipkin 2003).

**Crowding: 3/5** — OPEX effects well-known. But trading the POST-OPEX gamma vacuum is less crowded than the pin itself.

**Testability: 5/5** — calendar-based, perfect hindsight-free dating.

**Конкретный тест**:
```
OPEX calendar effect on vol-engine:
  - T-2 to OPEX: vol suppressed (max GEX) → 
    safe to sell vol → increase size
  - T+1 to T+3 post-OPEX: gamma vacuum → 
    vol spike risk → reduce/skip short-vol
  - Monthly OPEX > weekly OPEX (more OI expiring)

Target: forward 1-3 day realized vol
Integration: calendar overlay on vol-engine sizing.

Bonus: 0DTE daily expiry = DAILY mini-OPEX. 
  Intraday pin effects computable.
```

**Verdict: HIGH PRIORITY. Free, structural, testable, natural complement to GEX.**

---

#### 1.7 Margin Call / Forced Liquidation Cascades (ДОБАВЛЕНО)

**Что это**: volatility spike → margin calls → forced selling → more volatility → more margin calls. Cascade. Forced sellers = price insensitive = exploitable.

**Data accessibility: 2/5**
- Margin debt: FINRA monthly (free, lagged 1 month). Too slow for timing.
- Margin call proxy: VIX spike velocity + volume surge + specific indicators
- Futures basis collapse (ES vs SPX) = liquidation pressure proxy
- Breadth collapse (% stocks >MA) as cascade indicator

**Mechanism clarity: 5/5** — structural. Margin call is contractual obligation. Must sell.

**Crowding: 4/5** — surprisingly uncrowded for retail. Institutions trade this (buying crashed assets from forced sellers = classic prop).

**Testability: 3/5** — proxies only, not direct observation. But cascade events identifiable (Aug 2024, Mar 2020, Feb 2018).

**Конкретный тест**:
```
Cascade detection:
  VIX >30 AND VIX Δ1d >5pts AND ES volume >2σ 
  → likely margin cascade in progress

Post-cascade trade:
  NOT catch falling knife. 
  Wait for: VIX peak + 1 day decline → sell vol 
  (premium is MAXIMUM after cascade, 
   forced selling exhausted, 
   vol mean-reverts)

This is the ULTIMATE flow-counterparty trade:
  forced sellers dump → you buy the premium they're paying.

Target: post-cascade VRP extraction
Integration: 
  Special override for vol-engine: 
  normally GEX<0 + VIX spike = DON'T sell vol.
  Post-cascade confirmed: OVERRIDE → sell vol aggressively.
```

**Verdict: MEDIUM-HIGH PRIORITY. Rare (2-4 per year) but highest premium per event. Needs careful detection (selling DURING cascade = death). Testable on Aug 2024, 2022 drawdowns.**

---

#### 1.8 ETF Creation/Redemption & Index Rebalancing (ДОБАВЛЕНО)

**Что это**: ETF inflows → authorized participants must buy underlying basket. S&P 500 adds/deletes → forced buying/selling of specific names. Aggregate: index reconstitution = mechanical flow.

**Data accessibility: 3/5**
- ETF flows: ICI weekly (free, lagged), ETF.com daily estimates
- Index reconstitution: S&P announces in advance (free, known dates)
- Magnitude: estimable from AUM × flow

**Mechanism clarity: 4/5** — mechanical (AP must create/redeem). But: index level effect small (individual stock effect large, but we trade indices).

**Testability: 3/5** — calendar dates known. Effect on index vol/direction: small, mostly affects individual stocks.

**Verdict: LOW PRIORITY for index trading. More relevant for single-stock.**

---

### FRAMEWORK 2: INFORMATION-THEORETIC

#### 2.1 Cross-Market Lead-Lag

**a) Credit → Equity**

**Что это**: credit markets (HY spreads, IG OAS) often lead equity moves by 1-5 days. «Smart money» in credit, «dumb money» in equity (oversimplification, but empirically observed).

**Data accessibility: 5/5** — FRED: HY OAS, IG OAS, daily, free. Already in our pipeline.

**Mechanism clarity: 3/5** — empirical observation, not pure mechanism. Could be spurious lead-lag or regime-dependent.

**Crowding: 3/5** — well-known in macro circles. But not systematically traded by retail.

**Testability: 5/5** — already have data in intermarket_lab.

**Наш статус: PARTIALLY TESTED — used as crisis filter (binary). Not tested as lead-lag directional signal.**

**Конкретный тест**:
```
Signal: ΔOAS_HY_5d (5-day change in HY spread)

Test 1: does ΔOAS predict forward SPX returns? 
  (Likely: no, based on everything we've seen about direction)

Test 2: does ΔOAS predict forward SPX vol?
  (More likely — credit stress → vol transmission)

Test 3: does ΔOAS ADD to GEX + VRP stack?
  (Incrementality test — does credit lead vol beyond 
   what VIX term structure already tells us?)

Concern: VIX term structure (VIX/VIX3M) may already 
capture the same information (credit stress → VIX backwardation).
If so, credit is redundant (not incremental).
```

**Verdict: MEDIUM PRIORITY. Easy test (data exists). But may be redundant with macro filter already in place. Test incrementality.**

---

**b) Futures Basis → Spot**

**Что это**: ES-SPX basis reflects cost of carry + demand for leverage. Negative basis (backwardation) = selling pressure / de-leveraging. Positive basis = leveraged demand.

**Data accessibility: 5/5** — ES from es_continuous, SPX from cache/FRED. Basis = ES - SPX.

**Mechanism clarity: 4/5** — basis reflects funding costs + positioning demand. Directly tied to leverage/margin.

**Testability: 5/5** — computable now.

**Конкретный тест**:
```
Signal: ES_basis_annualized = (ES - SPX) / SPX × (365/DTE_to_expiry) × 100

  - Basis > normal (high carry cost) → leveraged longs crowded
    → vulnerable to unwind → vol will spike
  
  - Basis < normal or negative → de-leveraging in progress
    → selling pressure → vol elevated
  
  - Basis normalizing from extreme → flow pressure abating

Target: forward vol, not direction.
Integration: leverage-proxy sizer for vol-engine.
```

**Verdict: MEDIUM PRIORITY. Free, computable, structural interpretation. Test incrementality.**

---

**c) Overseas Sessions Lead**

**Что это**: Asia/Europe sessions contain information for US open. ETFs trading overseas (EWJ, FXI, VGK) move before US open.

**Data accessibility: 3/5** — need Asia/Europe session data. Free from Yahoo (EWJ, FXI, etc.) or futures (ES globex). ES 1-min already have globex hours.

**Mechanism clarity: 2/5** — empirical, weak mechanism. Global macro propagation, but timing uncertainty.

**Crowding: 2/5** — well-studied. Lead-lag probably arbed away.

**Testability: 3/5** — ES globex = have. But extracting signal from overnight session = noisy.

**Verdict: LOW PRIORITY. Weak mechanism, likely arbed, direction-adjacent.**

---

**d) Alternative Data**

Satellite, web traffic, job postings, patent filings, insider trading (Form 4), government contracts.

**Data accessibility: 1-3/5** — варьируется:
- Insider trading (Form 4): SEC EDGAR, бесплатно, parseable. But: single-stock, not index-level.
- Job postings: Indeed, LinkedIn — scrapers break. Aggregated: Revealera, LinkUp — paid.
- Satellite: expensive ($5K+/mo for useful data).
- Web traffic: SimilarWeb — paid tier for useful data.
- Patent filings: USPTO — free, but relevance to index = marginal.

**Mechanism**: information → fair value revision → price adjustment. Classic. But: retail gets data LATE (institutional alt data providers sell to HFs first).

**Index relevance: 1/5** — most alt data = single-stock. Index effect = diluted across 500 names. Exception: aggregate macro alt data (shipping, flights — but expensive).

**Verdict: SKIP for index trading. Wrong asset class for alt data edge. Alt data = stock picking, not index.**

---

### FRAMEWORK 3: LIQUIDITY-CENTRIC

#### 3.1 Global Liquidity Macro

**Что это**: Fed + ECB + BOJ + PBOC balance sheets → total liquidity → correlates with risk asset prices on 6-18 month horizon (r ≈ 0.85 claimed, though this is likely overfitted).

**Data accessibility: 5/5** — FRED: Fed balance sheet (H.4.1, weekly), ECB (ECB SDW, free), BOJ (free), RRP (FRED: RRPONTSYD). All free, weekly/daily.

**Mechanism clarity: 3/5** — macro correlation, not direct flow mechanism. Correlation ≠ causation. Timing uncertainty is HUGE (6-18 month horizon = untradeable for short-vol).

**Crowding: 3/5** — popular in macro Twitter/fintwit. Michael Howell, CrossBorder Capital. But: most just plot overlay, few trade systematically.

**Testability: 3/5** — long horizon → few independent observations. 5 years / 12 months = ~5 independent signals. Power: zero.

**Конкретный тест**:
```
Signal: Δ(Fed_BS + ECB_BS + BOJ_BS) rolling 3 months
  → liquidity expanding vs contracting

Test: predicts SPX 6-month forward returns?
Problem: n = ~10 independent observations (5 years, 6-month horizon).
Cannot validate with statistical confidence.

Alternative: shorter horizon proxy.
  Fed balance sheet Δweekly + RRP Δweekly → 
  does weekly liquidity change predict next-week vol?
  
  More obs, but mechanism weaker at short horizon.
```

**Verdict: LOW PRIORITY as standalone. Interesting as very-long-term regime backdrop (risk-on vs risk-off context for everything else). But not testable with 5 years, not tradeable at high frequency. Maybe: use as top-level regime (expand/contract) that sets overall allocation to vol strategies.**

---

#### 3.2 Risk Appetite Allocation (VIX → vol-target → allocation)

**Overlap with 1.3 (vol-targeting flows).** Same mechanism viewed from liquidity perspective. Already discussed. **See 1.3.**

---

#### 3.3 Intra-Equity Rotation (Growth/Value, Large/Small, Sectors)

**Что это**: rotation flows between equity sub-classes. If money rotates from tech to value → QQQ vol ≠ IWM vol.

**Data accessibility: 4/5** — ETF prices free. Factor returns (Fama-French): free (daily, updated monthly).

**Mechanism clarity: 2/5** — discretionary + systematic + momentum. Not purely mechanical.

**Index relevance**: index = blend. Rotation within index doesn't move the index much (rotation ≠ net flow in/out). More relevant for pair trades (QQQ vs IWM) than for SPX vol.

**Verdict: LOW PRIORITY for vol-engine. Maybe relevant for multi-underlying A3 (different vol dynamics per ETF). Not a new alpha source.**

---

#### 3.4 Market Microstructure: Dealer Inventory, Depth, Dark Pool

**a) Dealer inventory / market maker positioning**

Not directly observable retail. Proxy: realized bid-ask behavior, order flow imbalance.

**Data**: Intrinio has no dark pool data (access_code gated, 403). TAQ data = $$$. IEX TOPS = free but single exchange.

**b) S&P futures depth / book imbalance**

**Data**: CME depth of book = institutional (CQG/Rithmic). Not in our data. 1-min volume = proxy only.

**c) Dark pool activity**

FINRA ATS data: free, biweekly, lagged 2 weeks. Not useful for timing.
Intrinio dark pool: blocked (access_code required, 403).

**Verdict: LOW PRIORITY. Data mostly unavailable/gated for retail. Proxies weak.**

---

### FRAMEWORK 4: VOL SURFACE

#### 4.1 Term Structure Slope

**Что это**: VIX/VIX3M ratio. Contango (normal) vs backwardation (panic).

**Data accessibility: 5/5** — FRED, daily, free. Already in pipeline.

**Наш статус: ✅ VALIDATED as macro crisis filter. 0.80 → 0.85 Sharpe.**

**Дополнительный тест (не сделан)**:
```
Degree of contango as continuous sizer 
(not just binary backwardation flag).

Steep contango → VRP very rich → increase size
Flat contango → VRP thin → reduce size
Backwardation → crisis → skip

This is basically EMBEDDING term structure 
INTO VRP sizing (continuous, not binary).
```

**Verdict: ALREADY USED. Can be enhanced from binary to continuous. Easy test.**

---

#### 4.2 Skew Dynamics

**Что это**: put skew = price of downside protection. Rich put skew = hedging demand. Changes in skew = flow changes.

**Data accessibility: 4/5** — computable from our strike-level IV data (self-computed). 25-delta put IV - 25-delta call IV = risk reversal / skew.

**Mechanism clarity: 4/5** — hedger demand for puts → dealer supply → skew reflects hedging pressure. Changes in skew = changes in hedging urgency.

**Crowding: 3/5** — known, but mostly traded by vol desks, not retail.

**Testability: 5/5** — strike-level IV already computed. Skew = derived feature.

**Конкретный тест**:
```
Signal: 
  skew_25d = IV(25d_put) - IV(25d_call)  [30DTE surface]
  skew_change = Δskew_25d over 5 days

Tests:
  1. Skew level → forward realized vol? 
     (Rich skew = hedging demand high = vol may spike)
  
  2. Skew change → GEX reliability?
     (Skew steepening = new put buying = dealer getting more 
      short gamma at low strikes = GEX profile changing)
  
  3. Skew divergence from VIX:
     VIX falling + skew steepening = 
     "market calm on surface but hedgers buying protection"
     → WARNING signal → reduce short-vol

Integration: additional filter for vol-engine.
Potentially high value: skew contains information 
NOT in VIX/VIX3M (skew ≠ level).
```

**Verdict: HIGH PRIORITY. Computable from existing data. New dimension (not redundant with VIX). Structural mechanism. Not yet tested.**

---

#### 4.3 VRP (Variance Risk Premium)

**Наш статус: ✅ VALIDATED as sizer. Already in stack.**

Nothing to add — working component.

---

#### 4.4 GEX as Market Structure

**Наш статус: ✅ VALIDATED as gate. Already in stack.**

See 1.1 above.

---

#### 4.5 Vanna / Charm Flows (ДОБАВЛЕНО — не в твоём списке)

**Что это**: 
- **Vanna** = dδ/dσ: when IV drops, dealer delta changes → forced buying/selling. Major flow driver.
- **Charm** = dδ/dt: as time passes, dealer delta changes → forced rehedging. Strongest near expiry.

**Data accessibility: 4/5** — computable from our self-computed Greeks + IV surface. Vanna = need second derivative (dDelta/dIV), computeable from finite differences.

**Mechanism clarity: 5/5** — pure options mechanics. As time passes / vol changes, dealer delta exposure shifts, FORCING them to trade the underlying.

**Crowding: 4/5** — less mainstream than GEX. Vanna/charm modeling is mostly institutional (Cem Karsan, Brent Kochuba territory). Retail awareness: low.

**Testability: 4/5** — requires extending self-compute pipeline. Not trivial but doable.

**Конкретный тест**:
```
Compute aggregate vanna exposure:
  vanna_exposure = Σ(vanna_i × OI_i × contract_mult × spot)
  
  For each strike/expiry in SPX chain.

Signal:
  IV dropping + large negative vanna exposure → 
  dealers must buy stock (delta moves toward 0 on puts) →
  SUPPORTIVE flow → vol suppression → sell vol safely

  IV rising + large negative vanna exposure → 
  dealers must sell stock → 
  AMPLIFYING flow → vol spike → don't sell vol

Interaction with GEX:
  GEX = gamma hedging (price moves)
  Vanna = vol hedging (IV moves)
  Charm = time hedging (passage of time)
  
  Together: FULL PICTURE of forced dealer flow.
  GEX alone is one-dimensional.

Integration: 
  Replace single GEX signal with multi-Greek flow model:
  net_dealer_flow = f(GEX, vanna_exposure, charm_exposure)
  
  This is strictly richer signal, testable incrementally.
```

**Verdict: HIGH PRIORITY. This is the natural EVOLUTION of GEX — from one Greek to full dealer flow model. Same data, strictly richer. Must test incrementality over GEX alone.**

---

#### 4.6 Put-Call Parity Violations / Conversion/Reversal Pricing (ДОБАВЛЕНО)

**Что это**: put-call parity violations → funding stress, dividend expectations, or mispricing. Conversion/reversal = arb-like: synthetic vs actual. When stressed, violations widen.

**Data accessibility: 5/5** — we already use put-call parity (infer_spot). Extension: measure violation magnitude.

**Mechanism clarity: 3/5** — violations reflect funding/borrow costs, not directly tradeable at retail (need simultaneous execution of synthetic + stock). But: violation magnitude = stress indicator.

**Testability: 5/5** — literally derived from data we already compute.

**Verdict: MEDIUM PRIORITY as stress indicator (not as trade). Easy to compute. Test as filter: large violations → market stress → don't sell vol.**

---

### ADDITIONAL IDEAS (не в твоих фреймворках)

#### 5.1 Seasonal / Calendar Effects in Vol

**Что это**: vol has strong calendar patterns beyond OPEX:
- FOMC days: vol compressed before, released after
- CPI/NFP days: similar
- Tuesday-Thursday vs Monday/Friday vol differences
- January effect, September effect, etc.
- Holiday-thinned markets: vol regime change

**Data accessibility: 5/5** — economic calendar: free (FRED, investing.com). Day of week: free.

**Mechanism clarity: 4/5** — known: dealers position ahead of events, vol sold pre-event (premium collection), vol realized post-event.

**Crowding: 3/5** — event vol selling is common. But: combining with GEX gate = differentiated.

**Testability: 5/5** — calendar = no lookahead by definition.

**Конкретный тест**:
```
Event calendar overlay on vol-engine:

FOMC day: 
  - Sell vol morning (vol typically declines into decision)?
  - Or: skip (vol spike risk if surprise)?
  
  Better: does GEX gate ADAPT correctly to FOMC days?
  If GEX positive + FOMC → still safe?
  If GEX positive but non-FOMC → different sizing?

CPI: largest single-release vol mover post-2022.
  Does pre-CPI GEX predict CPI-day vol better than no-GEX?

Day-of-week: Monday = highest vol historically.
  GEX-gated short-vol: skip Mondays? Or size down?

Integration: event calendar × GEX interaction.
```

**Verdict: MEDIUM PRIORITY. Easy, free, testable. Incremental to vol-engine. Not a new alpha source but a refinement.**

---

#### 5.2 Retail Flow as Counterparty Signal (ДОБАВЛЕНО)

**Что это**: retail investors trade options systematically (0DTE calls, meme stocks, small-lot trades). They are net buyers of options → dealers are net sellers → GEX reflects this. But: can we measure retail flow SEPARATELY?

**Data accessibility: 3/5**
- CBOE small-lot option trades: not directly available retail
- Retail order flow: SEC 605/606 reports, lagged
- Proxy: 0DTE call volume (overwhelmingly retail)
- Proxy: options volume by lot size (Intrinio has volume, not lot-size breakdown)

**Mechanism clarity: 4/5** — retail = informed about nothing, systematic losers on average (academic evidence). Being counterparty to retail = edge (DRW, Citadel do this).

**Testability: 3/5** — proxies only.

**Verdict: MEDIUM PRIORITY. Already partially captured by GEX (retail flows create dealer gamma). Explicit retail flow proxy might add incrementally. Test: 0DTE call volume as retail demand proxy → GEX interaction.**

---

#### 5.3 Funding / Rates as Vol Predictor (ДОБАВЛЕНО)

**Что это**: overnight funding rates (SOFR, Fed Funds), repo market stress → impact dealer willingness to warehouse risk → impact option liquidity → impact vol.

**Data accessibility: 5/5** — FRED: SOFR, Fed Funds, Treasury GC repo. Daily, free.

**Mechanism clarity: 3/5** — indirect: funding tight → dealers reduce balance sheet → less vol suppression → vol up. Theoretical, not always empirical.

**Testability: 5/5** — data available, merge with vol features.

**Verdict: LOW-MEDIUM PRIORITY. Worth a test but probably redundant with credit (OAS) or VIX term structure. Test incrementality.**

---

#### 5.4 Implied Correlation as Vol Predictor (ДОБАВЛЕНО)

**Что это**: CBOE publishes Implied Correlation Index (ICJ, JCJ). When implied correlation is high → all stocks expected to move together → index vol will be high. When low → dispersed → index vol lower.

**Data accessibility: 3/5** — CBOE implied correlation index: available as CBOE data (need to check free access). Or: compute from sector ETF IVs vs SPX IV.

**Mechanism clarity: 4/5** — structural: index_vol = avg_stock_vol × correlation. If correlation changes, index vol must change even if stock vols don't.

**Testability: 4/5** — if data obtainable.

**Verdict: MEDIUM PRIORITY. Interesting for vol prediction. Orthogonal to GEX. Test if obtainable.**

---

## СВОДНАЯ ТАБЛИЦА

| # | Signal | Framework | Data | Mechanism | Crowding (5=uncrowded) | Breadth | Testability | Status | PRIORITY |
|---|--------|-----------|------|-----------|---------|---------|-------------|--------|----------|
| 1.1 | **GEX** | Flow | 4 | 5 | 2 | 3 | 5 | ✅ Validated | DONE |
| 4.3 | **VRP** | Vol Surface | 5 | 5 | 3 | 3 | 5 | ✅ Validated | DONE |
| 4.1 | **Vol term structure** | Vol Surface | 5 | 4 | 3 | 3 | 5 | ✅ Validated | DONE |
| **4.5** | **Vanna/Charm flows** | Vol Surface+ | 4 | 5 | **4** | 3 | 4 | ❌ Not tested | **🔴 #1** |
| **1.2** | **CTA replication** | Flow | 3 | 4 | 3 | 4 | 4 | ❌ Not tested | **🔴 #2** |
| **1.3** | **Vol-target flows** | Flow | 4 | 5 | 3 | 3 | 5 | ❌ Not tested | **🔴 #3** |
| **4.2** | **Skew dynamics** | Vol Surface | 4 | 4 | 3 | 3 | 5 | ❌ Not tested | **🔴 #4** |
| **1.6** | **OPEX calendar** | Flow | 5 | 5 | 3 | 3 | 5 | ❌ Not tested | **🔴 #5** |
| 1.7 | Margin cascade | Flow | 2 | 5 | 4 | 2 | 3 | ❌ Not tested | **#6** |
| 1.5 | Buyback blackout | Flow | 3 | 4 | 3 | 3 | 4 | ❌ Not tested | **#7** |
| 2.1a | Credit lead-lag | Info | 5 | 3 | 3 | 3 | 5 | Partial (filter) | **#8** |
| 5.1 | Calendar/events | Calendar | 5 | 4 | 3 | 3 | 5 | ❌ Not tested | **#9** |
| 2.1b | Futures basis | Info | 5 | 4 | 4 | 3 | 5 | ❌ Not tested | **#10** |
| 5.2 | Retail flow proxy | Flow | 3 | 4 | 3 | 3 | 3 | ❌ Not tested | **#11** |
| 5.4 | Implied correlation | Vol Surface | 3 | 4 | 4 | 3 | 4 | ❌ Not tested | **#12** |
| 4.6 | P/C parity violations | Vol Surface | 5 | 3 | 4 | 2 | 5 | ❌ Not tested | **#13** |
| 5.3 | Funding/rates | Liquidity | 5 | 3 | 3 | 2 | 5 | ❌ Not tested | **#14** |
| 3.1 | Global liquidity macro | Liquidity | 5 | 3 | 3 | 1 | 3 | ❌ Not tested | **#15** |
| 1.4 | Pension rebalancing | Flow | 2 | 4 | 2 | 1 | 3 | ❌ Not tested | Low (n too small) |
| 3.3 | Rotation | Liquidity | 4 | 2 | 2 | 2 | 3 | ❌ Not tested | Low |
| 3.4 | Microstructure | Liquidity | 1 | 3 | 3 | 2 | 1 | ❌ No data | Skip |
| 2.1c | Overseas lead-lag | Info | 3 | 2 | 2 | 2 | 3 | ❌ Not tested | Skip |
| 2.2 | Alt data | Info | 1 | 3 | 4 | 1 | 1 | ❌ No data | Skip (wrong asset) |
| 1.8 | ETF creation/rebal | Flow | 3 | 4 | 3 | 1 | 3 | ❌ Not tested | Skip (index effect tiny) |

---

## Рекомендуемый план (если Track 2 intraday direction fails)

```
PHASE 0: CONFIRM KILL (1 week)
──────────────────────────────
  Track 2 intraday direction tested, failed → confirmed: 
  direction = 0 at ALL horizons (daily, intraday, conditioned).
  Document & move on.


PHASE 1: DEEPEN VOL-ENGINE — same alpha, richer signals (weeks 1-6)
──────────────────────────────────────────────────────────────────

  Step 1: Vanna + Charm → full dealer flow model (#1 priority)
  ────────────────────────────────────────────────────────────
  Extend intrinio_options.py:
    - Compute vanna per strike/expiry: dDelta/dIV (finite diff)
    - Compute charm per strike/expiry: dDelta/dt (finite diff)
    - Aggregate: net_vanna_exposure, net_charm_exposure
    - New features: vanna_gex_ratio, charm_near_expiry
  
  Test: does multi-Greek flow model (GEX + vanna + charm) 
  predict forward vol BETTER than GEX alone?
  Incrementality test: nested WF comparison.
  
  Expected: YES — vanna captures IV-driven dealer flow 
  (GEX only captures price-driven). Orthogonal dimension.
  
  If validated: replace GEX-only gate with 
  multi-Greek dealer flow gate. Sharpe 0.85 → ???

  Step 2: CTA positioning model (#2 priority)
  ────────────────────────────────────────────
  Build simple CTA replication:
    MA_scores = [price > MA_k for k in [10,20,50,100,200]]
    cta_position_proxy = mean(MA_scores)  # 0 to 1
    cta_delta = Δcta_position_proxy over 5 days
    cta_trigger_distance = min distance to any MA crossing
  
  Test: does CTA proxy predict forward vol?
    - Near CTA trigger → vol will spike (forced flow imminent)
    - CTA max long → vol compressed but vulnerable
    - CTA max short → vol elevated, mean-reversion imminent
  
  Integration: sizer overlay. When CTA trigger near → 
  reduce short-vol size (vol about to spike from forced flow).

  Step 3: Vol-target flow model (#3 priority)
  ────────────────────────────────────────────
  Build vol-target equity allocation estimate:
    RV_20d = realized vol 20 days
    vol_target = 0.10  # typical
    equity_alloc = vol_target / RV_20d  # capped [0, 1.5]
    Δalloc_5d = change over 5 days
  
  Test: does Δalloc predict forward vol?
    - Δalloc large negative → forced selling → vol spikes more
    - Δalloc large positive → forced buying → vol compresses
  
  Integration: another sizer/filter.
  
  Step 4: Skew dynamics (#4 priority)
  ────────────────────────────────────
  Compute from existing IV surface:
    skew_25d = IV(25d_put, 30DTE) - IV(25d_call, 30DTE)
    skew_change_5d = Δskew_25d
    skew_vix_divergence = Δskew_25d - ΔVIX
  
  Test: skew change → forward vol? 
  Skew-VIX divergence → warning signal?
  
  Integration: filter. Divergence → reduce size.

  Step 5: OPEX calendar (#5 priority)
  ────────────────────────────────────
  Compute: days to next monthly OPEX, weekly OPEX.
  Feature: is_opex_week, days_post_opex, opex_magnitude 
  (estimated OI expiring).
  
  Test: vol regime pre-OPEX vs post-OPEX.
  Integration: calendar sizer.


PHASE 2: EXPAND BREADTH (weeks 6-10)
─────────────────────────────────────
  A3 from previous plan: 
  Apply validated multi-signal vol-engine to:
  - IWM, XLF, XLE, TLT, QQQ
  - Compute GEX/vanna/charm/VRP per underlying
  - Test: does edge hold? (some will fail — that's fine)
  
  A2: 0DTE specific strategy
  - SPXW 0DTE short premium, GEX-gated
  - Breadth: daily!
  
  A5: SPX calendar spreads (Track 1 via options)


PHASE 3: CONSTRUCT PORTFOLIO (weeks 10-14)
──────────────────────────────────────────
  Meta-allocation:
  - Multiple expressions × multiple underlyings × multiple DTEs
  - Correlation matrix of expressions
  - Vol-target at portfolio level
  - Kill-switch logic
  
  Target: Sharpe 1.2+ from portfolio of vol-premium strategies
  with validated, incremental, structural edge.
```

---

## Архитектурная диаграмма после перестройки

```
┌─────────────────────────────────────────────────────────────────┐
│                    META-ALLOCATION LAYER                        │
│         (vol-target, Kelly sizing, kill-switch,                 │
│          correlation-aware position limits)                     │
└───────┬────────────┬────────────┬──────────┬───────────────────┘
        │            │            │          │
   ┌────▼────┐  ┌────▼────┐  ┌───▼───┐  ┌──▼──────┐
   │ SHORT   │  │  0DTE   │  │CALENDAR│ │ STRANGLE│  ...expressions
   │STRADDLE │  │ PREMIUM │  │SPREAD  │  │CONDOR  │
   │(current)│  │ (new)   │  │(new)   │  │at walls │
   └────┬────┘  └────┬────┘  └───┬───┘  └──┬─────┘
        │            │            │          │
        └────────────┴──────┬─────┴──────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    SIGNAL STACK (multi-signal)                   │
│                                                                 │
│  ┌──────────────────────────────────────────────────┐           │
│  │  DEALER FLOW MODEL                               │           │
│  │  GEX (price-driven) + Vanna (IV-driven)          │   GATE    │
│  │  + Charm (time-driven)                            │           │
│  │  = net forced dealer flow direction               │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                 │
│  ┌──────────────────────────────────────────────────┐           │
│  │  SYSTEMATIC FLOW MODEL                            │           │
│  │  CTA proxy (MA envelope) + Vol-target             │   SIZE    │
│  │  (RV → alloc) + Buyback blackout                  │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                 │
│  ┌──────────────────────────────────────────────────┐           │
│  │  VOL SURFACE MODEL                                │           │
│  │  VRP (IV-RV spread) + Skew dynamics               │   SIZE    │
│  │  + Term structure (VIX/VIX3M continuous)           │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                 │
│  ┌──────────────────────────────────────────────────┐           │
│  │  MACRO/STRESS MODEL                               │           │
│  │  Credit (OAS) + VVIX + Futures basis              │   VETO    │
│  │  + Margin cascade detector                        │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                 │
│  ┌──────────────────────────────────────────────────┐           │
│  │  CALENDAR MODEL                                   │           │
│  │  OPEX cycle + Event (FOMC/CPI) + Day-of-week     │ SCHEDULE  │
│  └──────────────────────────────────────────────────┘           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    INSTRUMENTS                                   │
│  SPX/SPXW  SPY  QQQ/NDX  IWM  XLF  XLE  TLT  (+ 0DTE SPXW)  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Финальная мысль

Если ВСЁ из вышеперечисленного не работает (крайний сценарий — ни один сигнал не проходит incrementality test), это означает одно из двух:

**A) Vol premium существует, но не extractable retail** — execution costs, timing, data latency съедают edge. В этом случае:
- Reduce friction: switch to futures (ES options on CME, lower cost than SPX)
- Accept lower Sharpe (0.3-0.5) and scale via leverage/capital
- Or: this is not a retail-viable strategy, period

**B) Methodology too strict** — FDR + incrementality убивает слабые-но-реальные edges. В этом случае:
- Relax incrementality: allow portfolio of individually-weak-but-uncorrelated signals
- Diversification argument: 10 signals each with Sharpe 0.15, correlation 0.1 → portfolio Sharpe ~0.47
- But: this is dangerous territory (data mining with excuse)

Моя оценка: **вероятность тотального провала = низкая**. VRP structural, GEX mechanical, 0.85 Sharpe already validated. Вопрос не «работает ли», а «как далеко можно push Sharpe через breadth + richer signals». Vanna/charm = наиболее вероятный incremental improvement (same mechanism, more dimensions). CTA/vol-target = наиболее вероятный новый timescale (weeks vs days).