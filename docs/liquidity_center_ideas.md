Коротко: **не “не работают”, а плохо работают как standalone retail-стратегии на индексных фьючерсах.**

## Разделение по типам

### 1. **Global liquidity**  
Fed/ECB/BOJ balance sheet, RRP, reserves и т.д.

**Не то чтобы не работает** — скорее:
- слишком **медленно**
- слишком **мало независимых наблюдений**
- слишком **размазан горизонт** (недели/месяцы/кварталы)
- плохо подходит под **ES intraday / short-horizon execution**

**Вывод:**  
✅ можно использовать как **верхнеуровневый regime filter**  
❌ не как основной торговый сигнал на фьючерсах

---

### 2. **Risk-allocation liquidity**  
vol-target, credit stress, VIX backwardation, deleveraging

Это уже **работоспособнее**.

Почему:
- это реально связано с **forced flows**
- данные доступны retail
- горизонт ближе к tradeable (дни → неделя)

По сути:
- **vol-target flows**
- **credit stress**
- **basis stress**
- **macro crisis-off**

— это и есть **liquidity-centric сигналы, которые стоит брать**.

**Вывод:**  
✅ как overlay / veto / pressure model — да  
⚠️ как чистый directional trigger — осторожно

---

### 3. **True microstructure liquidity**  
order book depth, queue, dealer inventory, dark pool, footprint, MBO

Вот это на фьючерсах **может работать лучше всего**, но проблема в другом:

- нужны **дорогие/тяжёлые данные**
- нужен **очень точный execution stack**
- edge быстро съедается latency/fees/slippage
- retail без хорошей DOM/MBO инфраструктуры почти всегда в невыгодной позиции

**Вывод:**  
✅ conceptually работает  
❌ practically для твоего текущего retail-стека — скорее нет

---

# Практический ответ для твоего случая

Если вопрос:  
**“строить ли ядро стратегии на liquidity-centric идеях для ES/MES?”**

Ответ:

## Да, но только в двух формах:
### A. **как regime/overlay слой**
Лучшие liquidity-centered штуки для тебя:
- **vol-target flows**
- **credit widening**
- **VIX term structure**
- **ES-SPX basis**
- **margin cascade detector**
- **event liquidity days** (FOMC/CPI/NFP)

### B. **как execution context**
Не “куда пойдёт рынок”, а:
- когда **не фейдить**
- когда **ликвидность тонкая**
- когда **режим может сорваться**
- когда **forced selling / deleveraging** усиливает тренд

---

# Что я бы НЕ делал
Не делал бы core-стратегию вида:

- “Fed BS растёт → long ES”
- “RRP падает → buy risk”
- “global liquidity overlay → directional futures alpha”

Почему:
- слишком медленно
- мало power
- легко переобъясняется задним числом
- тяжело честно валидировать на твоём окне данных

---

# Что я бы делал вместо этого

## На futures liquidity-centric имеет смысл в 3 нишах:

### 1. **Deleveraging / forced-flow detection**
- vol-target
- basis stress
- credit spread widening
- VIX backwardation

Это лучший retail-viable liquidity block.

---

### 2. **Session liquidity / thin market behavior**
- overnight gap
- open location vs gamma walls
- IB width
- intraday RV acceleration
- pre/post event liquidity holes

Это ближе к execution edge, чем к macro alpha.

---

### 3. **Special event liquidity dislocations**
- OPEX unwind
- post-cascade reversal
- quarter-end rebal stress
- blackout + stress regime

Редко, но очень ценно.

---

# Мой итог

## Liquidity-centric стратегии на фьючерсах:
- **не мертвы**
- но **редко хороши как standalone core alpha для retail**
- **хороши как overlay / veto / flow-pressure layer**
- **лучше всего работают, когда соединены с GEX / CTA / vol-target**, а не вместо них

## То есть:
**Liquidity ≠ основной мотор**
**Liquidity = усилитель, тормоз и контекст**

Да — на **недельном/месячном горизонте** liquidity-based идеи уже **не мертвы**, потому что:

- частота данных совпадает с горизонтом исполнения,
- forced flows разворачиваются не за минуты, а за **дни/недели**,
- slippage/latency уже не убивают edge так быстро, как в intraday.

Ниже — **только liquidity-based** карта под **ES/MES / index execution**.

---

# Система скоринга

## Оси
- **Data** — доступность retail-данных
- **Mechanism** — насколько поток реально механический
- **Timing** — насколько хорошо сигнал таймит вход на 1–4 недели
- **Crowding** — `5 = мало кто торгует`, `1 = overcrowded`
- **Testability** — можно ли честно проверить на доступной истории
- **ES Fit** — насколько хорошо выражается через ES/MES

## Tiers
- **Tier S / Core** — можно строить основной weekly/monthly bias
- **Tier A / Overlay** — сильный size/veto/regime layer
- **Tier B / Seasonal/Event** — полезно, но узко
- **Skip** — либо слабая тайминговость, либо плохие данные, либо слишком медленно

---

# TIER S / CORE — liquidity-based идеи для weekly/monthly execution

| Idea | Main metrics | Horizon | Data | Mech | Timing | Crowding | Test | ES Fit | Score | Role |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **Vol-target / Risk-parity deleveraging** | `RV20`, `RV5/RV20`, `alloc = target_vol / RV20`, `Δalloc_5d` | 3d–15d | 5 | 5 | 4 | 3 | 5 | 5 | **27/30** | **Core #1** |
| **Credit stress + vol-term composite** | `ΔHY_OAS_5d`, `VIX/VIX3M`, `credit_vol_composite` | 5d–20d | 5 | 4 | 4 | 3 | 5 | 5 | **26/30** | **Core #2** |
| **ES-SPX basis / leverage stress** | `basis_vs_fair`, `basis_zscore`, `roll pressure` | 2d–10d | 5 | 4 | 4 | 4 | 5 | 4 | **26/30** | **Core #3** |
| **US liquidity impulse (Fed − TGA − RRP)** | `ΔFedBS`, `−ΔTGA`, `−ΔRRP`, net liquidity impulse | 1w–6w | 5 | 4 | 3 | 2 | 4 | 4 | **22/30** | **Core #4 (monthly-biased)** |
| **Funding / repo stress** | `SOFR−IORB`, repo spikes, funding z-score | 2d–10d | 5 | 3 | 3 | 4 | 5 | 3 | **23/30** | **Core/Overlay bridge** |

---

## 1) Vol-target / Risk-parity deleveraging
**Логика:** RV растёт → vol-target фонды **вынуждены продавать** equity exposure. RV падает → **вынуждены покупать**.

### Метрики
- `RV20` — 20-day realized vol
- `RV5` — 5-day realized vol
- `rv_shock = RV5 / RV20`
- `vol_target_alloc = target_vol / RV20`, cap `[0, 1.5]`
- `alloc_delta_5d = Δ(vol_target_alloc, 5d)`

### Сигнальная логика
- `alloc_delta_5d << 0` + `rv_shock > 1.3` → forced selling pressure
- `alloc_delta_5d >> 0` + `rv_shock < 0.8` → re-risking support

### Лучшее использование
- **weekly directional bias**
- **size model**
- **deleveraging detector**

### Crowding
**3/5**
- знают банки и макро-дески,
- retail почти не моделирует,
- front-running есть, но поток всё равно реален.

---

## 2) Credit stress + vol-term composite
**Логика:** widening credit spreads + VIX backwardation = liquidity/risk-off tightening. Это не просто “страх”, а перераспределение капитала из risk assets.

### Метрики
- `HY_OAS`, `IG_OAS`
- `ΔHY_OAS_5d`
- `VIX/VIX3M`
- `term_slope = (VIX3M - VIX)/VIX`
- `credit_vol_composite = z(ΔHY_OAS_5d) + z(VIX/VIX3M)`

### Сигнальная логика
- `ΔHY_OAS > 30–50 bps` + `VIX/VIX3M > 1` → stress-on
- tightening OAS + contango restoration → liquidity returning

### Лучшее использование
- **regime veto**
- **weekly short bias confirmation**
- **don’t-fade-risk signal**

### Crowding
**3/5**
- известная macro logic,
- но retail редко делает это системно.

---

## 3) ES-SPX basis / leverage stress
**Логика:** basis отражает leverage demand / forced unwind / funding pressure. Когда basis уходит ниже fair value, это часто значит deleveraging и стресс ликвидности.

### Метрики
- `basis = ES_front - SPX`
- `fair_basis ≈ carry`
- `basis_vs_fair = actual - fair`
- `basis_zscore(60d)`

### Сигнальная логика
- `basis_zscore < -2` → stress / unwind
- нормализация basis после экстремума → forced flow затухает

### Лучшее использование
- **weekly stress-timing**
- **add-on to credit/vol stress**
- **entry refinement for short-term swings**

### Crowding
**4/5**
- retail почти не смотрит,
- больше institutional/futures-aware participants.

---

## 4) US liquidity impulse: Fed BS − TGA − RRP
**Логика:** это одна из самых practical retail-версий “liquidity”. Не абстрактная global liquidity, а **операционный net liquidity flow в систему**.

### Метрики
- `ΔFed_balance_sheet`
- `−ΔTGA` (когда TGA падает — ликвидность в систему)
- `−ΔRRP` (когда RRP падает — деньги выходят в риск/банковскую систему)
- `US_net_liquidity = ΔFedBS − ΔTGA − ΔRRP`

### Сигнальная логика
- положительный 2–4 недельный impulse → headwind снимается, equity-friendly
- отрицательный impulse → liquidity drain

### Лучшее использование
- **monthly regime**
- **exposure scaler**
- **don’t-fight-liquidity background**

### Crowding
**2/5**
- очень популярен в macro Twitter,
- но тайминг обычно плохой,
- именно поэтому это **не standalone trigger**, а monthly core backdrop.

---

## 5) Funding / repo stress
**Логика:** если фондирование напрягается, баланс-шит capacity падает, dealers и leveraged players хуже абсорбируют риск.

### Метрики
- `SOFR - IORB`
- repo spike indicators
- `funding_zscore`
- при наличии: GC repo / secured funding proxies

### Сигнальная логика
- funding spread widening → tighter market plumbing
- особенно полезно в сочетании с basis и credit

### Лучшее использование
- **stress overlay**
- **short-horizon weekly warning**
- bridge between macro liquidity and market action

### Crowding
**4/5**
- retail почти не смотрит,
- данные бесплатные,
- но interpretation сложнее.

---

# TIER A / OVERLAY — сильные liquidity overlays

| Idea | Main metrics | Horizon | Data | Mech | Timing | Crowding | Test | ES Fit | Score | Role |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **Global liquidity composite (Fed+ECB+BOJ+PBOC)** | FX-adjusted CB BS impulse | 1m–6m | 4 | 3 | 2 | 2 | 3 | 4 | **18/30** | Overlay |
| **Buyback blackout / reopen** | `blackout_pct`, `reopen_pct` | 1w–6w | 3 | 4 | 3 | 3 | 4 | 4 | **21/30** | Overlay |
| **ETF / mutual fund flow pressure** | weekly net flows / AUM | 1w–4w | 3 | 3 | 3 | 3 | 4 | 4 | **20/30** | Overlay |
| **Treasury issuance / settlement drain** | coupon settlement weeks, cash drain | 1w–4w | 4 | 4 | 3 | 4 | 4 | 3 | **22/30** | Overlay |
| **Dollar liquidity / DXY stress proxy** | DXY, USD funding proxies | 2w–8w | 5 | 2 | 2 | 3 | 5 | 2 | **19/30** | Weak overlay |

---

## 6) Global liquidity composite
**Логика:** aggregate balance-sheet expansion/withdrawal major CBs влияет на risk assets, но тайминг очень размазан.

### Метрики
- `ΔFedBS + FXadj(ΔECBBS + ΔBOJBS + ΔPBOCBS)`
- rolling 4w / 13w impulse

### Почему не core
- для **месячного** фона — да
- для weekly entry timing — слишком тупой
- высокая опасность красивой постфактум-корреляции

### Crowding
**2/5**
- popular macro theme
- low edge as direct signal
- useful only as big-picture backdrop

---

## 7) Buyback blackout / reopen
**Логика:** когда buybacks выключены, исчезает крупный естественный покупатель equity.

### Метрики
- `blackout_pct` — % S&P mcap в blackout
- `reopen_pct` — % S&P mcap с открытым окном buyback

### Использование
- **support overlay**
- high blackout → меньше доверия longs / MR
- reopen wave → better support for monthly longs

### Crowding
**3/5**
- обсуждается, но системно мало кто считает сам.

---

## 8) ETF / mutual fund flow pressure
**Логика:** persistent inflows/outflows в индексные продукты создают реальный demand/supply pressure, особенно на горизонте неделя–месяц.

### Метрики
- weekly net flows for `SPY/IVV/VOO/QQQ/IWM`
- `flow_to_AUM`
- cumulative 4-week flow impulse

### Использование
- **confirmation**
- хороший overlay к vol-target и liquidity impulse
- отдельно — слабоват

### Crowding
**3/5**
- данные доступны,
- но retail редко агрегирует нормально.

---

## 9) Treasury issuance / settlement drain
**Логика:** крупные settlement weeks и наращивание TGA могут временно высасывать ликвидность из системы.

### Метрики
- settlement calendar Treasury auctions
- `ΔTGA`
- heavy coupon issuance weeks

### Использование
- **short-term liquidity headwind overlay**
- особенно полезно на 1–4 недели

### Crowding
**4/5**
- относительно недоиспользовано retail,
- но interpretation требует макро-контекста.

---

## 10) Dollar liquidity / DXY
**Логика:** сильный доллар часто совпадает с tightening global liquidity / risk-off.

### Метрики
- `DXY z-score`
- `ΔDXY_20d`
- при наличии: cross-currency basis proxies

### Почему не выше
- это часто **proxy proxy**, а не прямой liquidity flow
- directionality noisy
- лучше как дополнительный stress overlay

### Crowding
**3/5**
- все смотрят DXY,
- мало кто превращает в robust signal.

---

# TIER B / SEASONAL / EVENT — полезно, но узко

| Idea | Main metrics | Horizon | Data | Mech | Timing | Crowding | Test | ES Fit | Score | Role |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **Pension / quarter-end rebalancing** | equity-bond drift, EOQ windows | 3d–10d around EOM/EOQ | 2 | 4 | 2 | 2 | 3 | 3 | **16/30** | Event |
| **Month-end mutual fund rebalance** | monthly equity/bond relative return | 2d–5d | 2 | 3 | 2 | 2 | 3 | 3 | **15/30** | Event |
| **Dealer balance-sheet capacity proxies** | bid-ask, realized impact, volume stress | 1d–2w | 2 | 3 | 2 | 4 | 2 | 3 | **16/30** | Niche |

---

## 11) Pension / quarter-end rebalancing
**Логика:** после сильного QTD move pensions rebalance back to target weights.

### Проблема
- слишком мало наблюдений
- edge календарный, но слабый
- useful as event overlay, not core

### Crowding
**2/5**
- известен sell-side,
- но power слабый.

---

## 12) Month-end mutual fund rebalance
Похоже на pension idea, но ещё более шумно.  
Можно держать как **даты повышенного внимания**, но не как систему.

---

## 13) Dealer balance-sheet capacity proxies
Это уже более “микро-лиquidity”, но без нормальных данных retail остаётся на прокси.  
На weekly/monthly горизонте usefulness ограничен.

---

# SKIP / НИЗКИЙ ПРИОРИТЕТ

| Idea | Почему skip |
|---|---|
| **Dark pool / ATS delayed data** | lagged, слабая пригодность для weekly/monthly timing на ES |
| **Simple M2 overlays** | слишком грубая макро-корреляция, слабый timing |
| **Pure central bank balance-sheet charts без TGA/RRP** | красиво визуально, но operationally слишком тупо |
| **Commercial bank reserves standalone** | overlap с net liquidity, отдельный edge сомнителен |
| **Order-book depth / DOM retail-style** | для weekly/monthly не даёт достаточно clean signal, а хорошие данные дорогие |

---

# Финальный приоритет только по liquidity-based под weekly/monthly

## Core stack
1. **Vol-target / risk-parity deleveraging**
2. **Credit stress + VIX term structure composite**
3. **ES-SPX basis / leverage stress**
4. **US liquidity impulse (Fed − TGA − RRP)**
5. **Funding/repo stress**

## Tier 2 overlays
6. **Buyback blackout / reopen**
7. **ETF / mutual fund flow pressure**
8. **Treasury issuance / settlement drain**
9. **Global liquidity composite**
10. **Dollar liquidity / DXY stress**

## Event-only
11. **Pension / quarter-end rebalancing**
12. **Month-end rebalance windows**

---

# Что именно тестировать на ES/MES

## Targets
Для liquidity-идей я бы тестировал не intraday, а:

- **Forward 5d return**
- **Forward 10d return**
- **Forward 20d return**
- **Forward 5d/20d realized vol**
- **Forward max drawdown / max run-up**

## Методология
- non-overlap blocks для 5d/10d/20d
- expanding walk-forward
- rank by **IR / Sharpe / CI lower bound**
- обязательно incrementality:
  - даёт ли `US liquidity impulse` что-то **поверх** `credit + vol-target`?
  - даёт ли `ETF flows` что-то **поверх** `buyback + liquidity impulse`?

---

# Самый короткий вывод

Если смотреть **именно liquidity-based** и **не intraday, а weekly/monthly**, то:

## Стоит смотреть в первую очередь:
- **Vol-target**
- **Credit + vol-term**
- **Basis stress**
- **Fed−TGA−RRP net liquidity**

## Стоит использовать как overlay:
- **Buyback blackout**
- **ETF flows**
- **Treasury settlement drain**
- **Global liquidity composite**

## Не стоит строить ядро на:
- simple M2 / красивых liquidity overlays
- dark pool lagged data
- quarter-end rebalance как standalone alpha


Да — если **option-adjusted = execution**, а **liquidity-centered = bias**, то систему лучше **сильно упростить** и разложить по слоям.

Не пытаться делать всё сигналом.  
Нужно разделить:

1. **Bias** — в какую сторону/против чего вообще разумно работать на горизонте 1–4 недель  
2. **Execution** — где и как входить/выходить на ES/MES внутри bias  
3. **Veto / Risk** — когда вообще не торговать или резко уменьшать риск  
4. **Optional timing booster** — только если core уже живой

---

# 1) Финальная архитектура: за что держаться

## A. Bias layer = **Liquidity-centered**
Это верхний слой. Он **не должен давать точку входа**, он должен отвечать:

- long bias / short bias / neutral
- risk-on / risk-off
- trend continuation likely / no strong pressure

### Оставить в ядре bias:
1. **Vol-target / risk-parity deleveraging**
2. **Credit + VIX term structure composite**
3. **ES-SPX basis / leverage stress**
4. **Fed − TGA − RRP net liquidity** — только как **slow backdrop**, не trigger

---

## B. Execution layer = **Option-adjusted**
Это слой, который отвечает:

- когда именно входить
- mean reversion или breakout
- где invalidation
- где structural levels

### Оставить в ядре execution:
1. **GEX regime + zero-gamma + walls**
2. **OPEX phase**
3. **Vanna/Charm** — но только вторым этапом, не сразу

---

## C. Veto / Risk layer
Это не альфа. Это защита от режимов, где даже хороший execution ломается.

### Оставить:
1. **VVIX**
2. **Event calendar** (FOMC/CPI/NFP)
3. **Margin-cascade detector**
4. **Portfolio risk rules**: vol-target, DD cap, kill-switch

---

## D. Optional timing booster
Это слой **не обязателен** в MVP.

### Единственное, что можно добавить позже:
- **CTA replication**

Почему не в core сразу:  
он хороший, но если ты одновременно запускаешь liquidity bias + option execution + CTA, то увеличиваешь DoF.  
CTA лучше тестировать **после** того, как связка `Liquidity Bias + Options Execution` уже понятна.

---

# 2) Что убрать сейчас

## Убрать из этой конкретной системы
Это либо слишком медленно, либо слабо таймит, либо перегружает стек.

### Убить/отложить сразу:
- **Global liquidity composite (Fed+ECB+BOJ+PBOC)** как standalone signal
- **ETF / mutual fund flows**
- **Buyback blackout** как отдельный драйвер
- **Pension / quarter-end rebalancing**
- **DXY / dollar liquidity** как отдельный сигнал
- **Funding / repo standalone**
- **Retail flow proxy**
- **Skew dynamics** для index direction
- **VRP** как directional input для ES
- **P/C parity violations**
- **Dark pool / ATS / microstructure proxies** без нормальных данных

### Почему:
- либо это **слишком слабый bias**
- либо **слишком редкий**
- либо **не даёт incremental edge**
- либо это лучше работает для **options execution**, а не для delta-one на индексах

---

# 3) Финальная таблица: Keep / Later / Kill

## CORE NOW

| Layer | Signal | Role | Why keep |
|---|---|---|---|
| Bias | Vol-target deleveraging | Core bias | самый чистый forced-flow liquidity signal |
| Bias | Credit + VIX term composite | Core bias | лучший stress/risk-off liquidity regime |
| Bias | ES-SPX basis stress | Core bias | хороший leverage/liquidity pressure proxy |
| Bias | Fed−TGA−RRP | Slow backdrop | useful monthly exposure cap, not trigger |
| Execution | GEX + zero-gamma + walls | Core execution | лучший option-adjusted structure map |
| Execution | OPEX phase | Core execution modifier | structural shift in dealer environment |
| Veto | VVIX | Meta-filter | reliability of options-derived levels |
| Veto | Event calendar | Execution veto | avoids false MR/trend reads on macro days |
| Veto | Margin cascade | Crisis override | protects against regime breaks |

---

## LATER / PHASE 2

| Layer | Signal | Role | Why later |
|---|---|---|---|
| Execution | Vanna/Charm | execution upgrade | powerful, but higher modeling complexity |
| Timing booster | CTA replication | bias/timing booster | useful, but adds another axis too early |
| Veto | Buyback blackout | support overlay | maybe helpful, not first-order |
| Bias | Funding/repo stress | stress overlay | possibly redundant with basis+credit |
| Bias | ETF flows | weak confirmation | probably too soft for first pass |

---

## KILL / PARK

| Signal | Why kill now |
|---|---|
| Global liquidity standalone | too slow, too low timing precision |
| Pension/EOQ rebalance | low sample size, weak power |
| DXY standalone | too noisy, indirect proxy |
| Retail flow proxy | noisy, poor retail data |
| Skew as ES direction | better as options context, not index bias |
| VRP as ES direction | predicts vol premium, not direction |
| P/C parity violations | stress proxy at best, low marginal value |
| Alt/microstructure without data | infra-heavy, likely no retail edge |
| Dark pool lagged data | bad timing |

---

# 4) В каком порядке тестировать

Главный принцип:  
**не тестировать сразу всё вместе.**  
Сначала слои отдельно, потом только их комбинации.

---

## Этап 1 — Bias-only
Сначала вообще **не трогаем execution**.  
Нужно понять: есть ли weekly/monthly bias в liquidity.

### Тестировать по одному:
1. **Vol-target**
2. **Credit + term structure**
3. **Basis stress**
4. **Fed−TGA−RRP**

### Targets:
- Forward **5d return**
- Forward **10d return**
- Forward **20d return**
- Forward **5d / 10d max drawdown**
- Forward **5d / 10d realized vol**

### Что считаем:
- monotonic bins/quintiles
- win rate
- mean return
- downside asymmetry
- conditional DD
- CI lower bound
- OOS Sharpe / IR

### Что убивать первым:
Порядок kill:
1. **Fed−TGA−RRP** если не даёт хотя бы backdrop discrimination на 20d
2. **Basis** если полностью редундантен к credit
3. **Credit** только если всё уже объясняет vol-target
4. **Vol-target** убивать последним — это strongest structural candidate

---

## Этап 2 — Execution-only
Теперь отдельно проверяем option-adjusted execution **без liquidity bias**.

### Порядок:
1. **GEX regime + walls**
2. **+ OPEX**
3. **+ Vanna/Charm** только потом

### Targets:
- next-day range / vol
- intraday regime stats:
  - range expansion
  - follow-through
  - mean-reversion rate from wall touches
  - breakout persistence
- PnL after costs on simple rules:
  - MR when +gamma
  - breakout/flat when −gamma

### Что убивать первым:
1. **Vanna/Charm** — если не добавляет к GEX
2. **OPEX** — если не улучшает regime discrimination
3. **GEX** не убивать быстро, только если честный OOS полностью пустой

---

## Этап 3 — Сначала простые комбинации
Не надо сразу делать composite monster.

Сначала комбинируем **один bias + один execution stack**.

### Порядок комбинаций:
1. **Bias as veto**
2. **Bias as side filter**
3. **Bias as size multiplier**

Это очень важно.

---

# 5) В каком порядке комбинировать

## Комбинация 1 — Bias as veto
Самая robust.

### Логика:
- если liquidity bias сильно positive → не брать short setups / не агрессивно шортить
- если strongly negative → не брать long MR setups
- если stress extreme → skip

### Почему first:
- minimum DoF
- easiest to validate
- меньше шансов data-mine’ить

### Первая связка:
**Vol-target + GEX**

Если она не даёт прироста, это важный red flag.

---

## Комбинация 2 — Bias as side filter
Только после veto.

### Логика:
- liquidity bias > 0:
  - в +gamma → брать только long fades
  - в −gamma → брать только upside breakouts
- liquidity bias < 0:
  - в +gamma → только short fades
  - в −gamma → только downside breakouts

### Первая связка:
**Credit/term composite + GEX/OPEX**

Почему:
credit/term лучше определяет risk-off side than exact trigger.

---

## Комбинация 3 — Bias as size multiplier
Только после первых двух.

### Логика:
- execution решает вход
- liquidity bias решает **сколько риска брать**

Пример:
- strong +gamma MR setup + positive liquidity = 1.25x
- same setup + neutral liquidity = 1.0x
- same setup + stress-on = 0.25x or skip

### Первая связка:
**Vol-target + credit composite + GEX execution**

---

# 6) Финальный порядок тестов

## Фаза A — Single-signal ranking
1. Vol-target
2. Credit + VIX term
3. Basis
4. Fed−TGA−RRP
5. GEX
6. OPEX
7. Vanna/Charm

---

## Фаза B — Bias composite building
Только forward selection, не brute force.

### Порядок:
1. Лучший single bias
2. Добавить второй bias только если даёт OOS incrementality
3. Добавить третий bias только если второй реально добавил
4. Максимум **3 bias-компонента**

### Скорее всего оптимальный bias composite:
- **Vol-target**
- **Credit + term**
- **Basis**

### Fed−TGA−RRP:
оставить как **backdrop cap**, а не как часть агрессивного daily composite

---

## Фаза C — Execution composite building
1. GEX baseline
2. + OPEX
3. + Vanna/Charm only if incremental

### Максимум 3 execution components:
- GEX regime
- gamma levels
- OPEX  
Vanna/Charm — только если реально даёт lift

---

## Фаза D — Cross-layer integration
Тестировать строго в этом порядке:

1. **Bias-only**
2. **Execution-only**
3. **Bias veto on execution**
4. **Bias side filter on execution**
5. **Bias size scaling on execution**
6. **Add risk vetoes** (VVIX, events, cascade)
7. **Only then CTA**

---

# 7) За что держаться, если нужно выбрать совсем мало

Если тебе нужно **сжать всё до MVP**, я бы оставил вот это:

## MVP Bias
1. **Vol-target**
2. **Credit + VIX term**
3. **Basis**

## MVP Execution
4. **GEX regime + zero-gamma + walls**
5. **OPEX**

## MVP Veto
6. **VVIX**
7. **Event days**
8. **Cascade override**

Всё.  
Это уже полноценная система.

---

# 8) Что убивать первым при фейле

Если смотреть жёстко по исследовательской дисциплине:

## Убивать первым:
1. **Fed−TGA−RRP как trigger**
2. **Basis**, если нет incrementality к credit/vol-target
3. **OPEX**, если effect only anecdotal
4. **Vanna/Charm**, если lift красивый только in-sample
5. **Buyback/funding/ETF flows**, если вообще решишь до них дойти

## Убивать последним:
1. **Vol-target**
2. **Credit + term**
3. **GEX execution**

Это самые structural pieces.

---

# 9) Жёсткие kill rules

Чтобы не тащить мёртвые идеи:

## Bias signal kill if:
- нет monotonicity по квинтилям
- нет OOS advantage на 5d/10d/20d
- no incrementality vs stronger bias
- работает только на одном subperiod

## Execution signal kill if:
- нет lift к baseline GEX
- lift исчезает после costs/slippage
- regime logic unstable across years
- слишком много tuning degrees of freedom

## Overlay kill if:
- не улучшает DD / tail control
- не повышает CI lower bound
- только снижает число трейдов без улучшения качества

---

# 10) Лучшая последовательность комбинаций

Если совсем прикладно:

## Комбо #1
**Vol-target bias × GEX execution**

Это самое важное первое комбо.

---

## Комбо #2
**(Vol-target + Credit/term) bias × GEX + OPEX execution**

Это likely best first serious system.

---

## Комбо #3
**(Vol-target + Credit/term + Basis) bias × GEX + OPEX execution × VVIX/event veto**

Это уже основной кандидат в live research stack.

---

## Комбо #4
**+ Vanna/Charm**

Только если реально incremental.

---

## Комбо #5
**+ CTA**

Только если после всего вышеперечисленного ещё нужен timing booster.

---

# 11) Мой финальный вердикт

## Держаться:
- **Liquidity bias = vol-target + credit/term + basis**
- **Option-adjusted execution = GEX/walls + OPEX**
- **Risk veto = VVIX + events + cascade**
- **Fed−TGA−RRP = backdrop, не trigger**

## Убить/отложить:
- global liquidity standalone
- buyback как core
- ETF flows
- pension rebal
- DXY
- retail flow
- skew/VRP as futures direction
- funding standalone

## Тестировать в порядке:
1. single bias signals
2. bias composite
3. execution stack
4. bias-as-veto
5. bias-as-side-filter
6. bias-as-size
7. veto overlays
8. vanna/charm
9. CTA last


