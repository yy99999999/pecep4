# ЧЕКЛИСТ — 2026-06-24

Главный принцип для всего ниже: **breadth (IR = IC·√breadth) важнее редких сетапов.** Каждый новый движок оценивается НЕ по своему standalone Sharpe, а по **Sharpe × (1 − corr-к-портфелю), мерено на ХВОСТОВЫХ днях** (corr→1 в кризис; full-sample corr врёт). Цель — стек мелких, genuinely независимых, плюсовых после костов sleeves, разруленных мета-слоем.

Reality-check уже зафиксирован (2026-06-23): basis / credit-vol / cascade как standalone daily-фичи = **МЁРТВЫ** (basis = in-sample мираж, дохнет OOS; credit и cascade редундантны с VIX/vix_term, которые уже в движке). Урок: лёгкие daily макро/liquidity-сигналы на SPX/ES перемолоты или сидят внутри VIX. Независимость живёт в **других активах / другом часовом механизме / другой структуре данных** — отсюда три трека ниже.

---

## ТРЕК 1 — ОПЦИОНЫ (breadth вокруг проверенного vol-движка)

### 1A. Cross-asset VRP — **ОСНОВНОЙ** 🥇
Тот же ПРОВЕРЕННЫЙ движок (short vol, regime-gated, real-marks, inverse-IV sizing) направленный на **TLT / IEF / GLD / USO** вместо SPX. Bond-vol VRP и equity-vol VRP имеют **разные драйверы** (ставки vs риск-аппетит) → genuinely низкая corr вне кризиса = реальная диверсификация портфеля (в отличие от 0DTE, который corr-0.80 к SPX).
- [x] Данные: GLD, USO готовы; **TLT + IEF поставлены на докачку** (`/tmp/fetch_bonds.py`, resumable). TY-futures опционов НЕТ на Intrinio `by_ticker` → **IEF = прокси 10yr/belly**, TLT = длинный конец (паттерн USO-вместо-CL).
- [ ] Completeness-проверка TLT/IEF после докачки (отметить пустые/missing дни).
- [ ] Прогнать 1DTE-strangle / iron-condor движок по каждому активу через ТОТ ЖЕ гонтлет (FDR / OOS-WF / incrementality / real-marks).
- [ ] GEX может не применяться (другая дилерская структура) — тестить VRP + vol-term-macro gate отдельно по активу; GEX оставить только где он даёт incrementality.
- [ ] **ГЛАВНАЯ метрика:** corr P&L vs SPX-движок, именно на хвостовых днях. Низкая tail-corr = зелёный свет на стакинг.

### 1B. Convex / long-vol overlay — **элегантный турбонаддув** ⚡
Единственное, что НЕ падает вместе с short-vol — это **противоположный знак.** Купить дешёвые хвосты когда skew/GEX сигналят crash-risk. Standalone Sharpe НИЗКИЙ (long-vol кровоточит) — но **отрицательная corr поднимает портфельный Sharpe даже при низком своём.** Это не «1.5 в одиночку» — это «turbocharge всего портфеля».
- [ ] Ключ к убийству bleed = **ex-ante тайминг КОГДА держать хвост.** Кандидат-таймер = **L3 idea #4 (liquidity-vacuum):** тонкий ES-стакан ⇒ покупаем дешёвый long-tail только тогда ⇒ меньше bleed, ровно на том сетапе где случаются gap/gamma-flip хвосты.
- [ ] Это же — естественный фикс наших нерешённых −5.3% condor-дней → связывает ТРЕК 1 и ТРЕК 2.

### 1C. Дисперсия / implied-correlation premium — вторично (отложить)
Genuinely НОВЫЙ эдж (correlation premium ≠ VRP): short index vol + long single-name vol = short correlation. Высокий ceiling, институционального уровня.
- [ ] **Отложено** — дорого (30–50 component-ног), execution-heavy, survivorship-caveat, крашится в correlation spikes. Вернуться только после того как cross-asset VRP в банке.

### 1D. Event-vol crush — независимый часовой механизм
IV систематически переоценивает реализованный move вокруг **запланированных макро-событий (FOMC / CPI / NFP)** → продать vol в событие, откупить crush. Независимый ТРИГГЕР (календарь, не gamma-режим) → ортогонален daily-движку по конструкции; переиспользует SPX-опционы.
- [ ] Тест: event-day IV vs реализованный crush; tail-control (move может превысить implied); проверка crowding.

---

## ТРЕК 2 — L3 / МИКРОСТРУКТУРА (GEX + L3)

- [ ] **Проверить макс. глубину через londonstrategicresearch API** — ES (~1 год?) vs NQ (~5 лет, в облаке). Кэш `.dbn` = **бары, НЕ MBO**. Нужен **MBP-10** (хватит для Stage 0/1 resilience-at-walls; полный **MBO** только для Stage 2 queue-sim).
- [ ] **Stage 0** (самое дешёвое, без филлов): book replay → **`replenishment ratio` на gamma-walls** → тест **wall-resilience → forward-return**. Отвечает «есть ли сигнал» ДО постройки симулятора. Валидировать Stage 0 до любого fill-sim.
- [ ] Топ-кандидаты: **#1 gamma×L3-absorption** (дифференциатор — gamma-карта = WHERE, L3-resilience = WHEN) и **#4 liquidity-vacuum** (он же tail-предиктор для ТРЕКА 1B).
- [ ] Полный список 5 идей + staged-архитектура + элегантный book-resilience reversal примитив — в памяти [[l3-gex-microstructure]].
- Принцип: не гнаться за HFT sub-ms; играть **секунды-минуты + структурные уровни** где живёт преимущество gamma-карты.

---

## ТРЕК 3 — PREDICTION MARKETS (Kalshi)

### 3A. Как арбитраж-sleeve (genuinely uncorrelated — идеально ложится в breadth)
Исход события ⟂ market beta = premium diversifier. Лучшие углы для нас (играем от опционной силы):
- [ ] **Kalshi binary ↔ SPX options digital:** контракт «SPX выше X к дате» ЕСТЬ digital option, реплицируется из нашей IV-поверхности → считаем fair value, торгуем расхождение.
- [ ] **Kalshi Fed ↔ CME FedWatch** дивергенция (cross-market RV).
- [ ] Internal dutch-book (взаимоисключающие бакеты сумма ≠ 100%) — очевидные разбирают быстро.
- Caveats: крошечный capacity (position limits, тонкие книги), заметные fees vs эдж, settlement/регуляторный риск → **малый sleeve, не основной движок.**

### 3B. Как макро-фильтр
Kalshi даёт **market-implied вероятность/направление** макро-исходов — измерение, которого нет в (симметричной) vol-поверхности.
- [ ] Использовать как **live/forward feature**, НЕ backtested-gate — история Kalshi слишком короткая для нашего WF/FDR гонтлета.
- [ ] Сильнейшая версия = спред binary-vs-options-implied (то же что 3A).

---

## Хозяйство сессии
- [ ] Докачка бондов (`/tmp/fetch_bonds.py`) крутится в фоне — **resumable**, поэтому ребут сессии безопасен; перезапустить чтобы продолжить если прервётся.
- [ ] Ребут сессии после завершения записи (чистый контекст под per-asset гонтлет).
