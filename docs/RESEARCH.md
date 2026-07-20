# AMT Statistical Research — NQ/ES Futures

## Обзор проекта

Статистический анализ Auction Market Theory (Далтон/Стейдлмайер) на 16 годах
OHLCV данных ES и NQ фьючерсов (2010-2026). Цель — собрать условные вероятности
для торговых решений и использовать как основу для ML классификации.

---

## Стек и данные

| Компонент | Описание |
|-----------|----------|
| Python | 3.12, vbt-env |
| Данные | Databento DBN, OHLCV-1m, ES+NQ 2010-2026 (876MB) |
| VIX | OPRA OHLCV-1d 2013-2026 (загружен, кеш vix_daily.parquet) |
| ZN bonds | OHLCV-1d 10yr (есть, pending) |
| ZT 2Y | pending — докачать для yield curve slope |
| Ноутбук | jupyter strats/amt_stats.ipynb |
| Модуль | amt_classify.py |
| ML | pomegranate 1.1.2, hmmlearn 0.3.3, scikit-learn |

---

## Текущий датасет (es_days, nq_days) — 53 колонки

### Структурные переменные
- `open_location` — 6 категорий относительно prev VA/Range/POC
- `open_type` — open_drive / open_test_drive / open_rejection_reverse / open_auction
- `open_dist` — float позиция открытия внутри IB (pending — добавить)
- `activity` — initiative/responsive buying/selling
- `day_type` — trend/normal/nontrend/neutral/normal_variation/double_distribution
- `close_location` — above_va/inside_va/below_va (текущий день)
- `close_vs_poc` — above_poc/below_poc

### ML Features (float)
- `ib_norm` — IB range / (Parkinson RV × open_px)
- `prof_norm` — day range / (Parkinson RV × open_px)
- `ib_profile_ratio` — ib_range / day_range (0-1)
- `poc_bias` — abs(poc_position - 0.5) × 2 (0=центр, 1=экстремум)
- `open_poc_dist` — abs(open_px - curr_poc) / day_range (0-1)
- `vix_close` — дневной VIX (с 2013-04-01)

### Слоты
- `high_slot` / `low_slot` — получасовой период формирования дневного экстремума (0-13)
- `poc_touch_slot`, `vah_touch_slot`, `val_touch_slot` — слоты касания уровней
- `poc_accepted`, `vah_accepted`, `val_accepted` — acceptance/rejection

---

## ML Результаты (GMM n=8 + HMM n=7)

### GMM Кластеры (с VIX)

| Кластер | Характеристика | VIX | Trend% | Win Rate |
|---------|---------------|-----|--------|----------|
| 0 | Initiative, средний prof_norm | 2.3 | 0.2% | 50.5% |
| 1 | Normal/Nontrend, узкий профиль | 2.0 | 0.4% | 51.4% |
| 2 | Балансовый, широкий профиль | 1.9 | 0.4% | 53.1% |
| 3 | Широкий IB, нормальный VIX | 3.6 | 0.0% | 48.9% |
| 4 | Высоковолатильный | 5.1 | 29.7% | 46.7% |
| 5 | Кризисный | 35.4 | 15.9% | 47.8% |
| 6 | Initiative trend | 1.6 | 23.7% | 50.4% |
| 7 | Направленный, POC мигрировал | 3.0 | 29.9% | 53.8% |

### Топ торговые комбинации (open_location × GMM × VIX)

| Комбинация | Win Rate | Count |
|-----------|---------|-------|
| outside_range_above × кластер 2 × low VIX | 66.1% | 245 |
| outside_va_above_poc × кластер 2 × low VIX | 67.0% | 100 |
| inside_va_above_poc × кластер 0 × low VIX | 65.4% | 78 |
| outside_range_above × кластер 4 × low VIX | 15.4% | 39 (антисигнал) |
| inside_va_below_poc × кластер 2 × low VIX | 28.9% | 114 (антисигнал) |

### Топ High/Low slot комбинации

| Комбинация | Early High% | Early Low% | Значение |
|-----------|------------|------------|---------|
| outside_range_above × кластер 4 | 73.8% | 16.7% | Шорт — high рано, падение весь день |
| outside_range_above × кластер 3 | 49.5% | 73.2% | Лонг — low рано, защита известна |
| outside_va_above_poc × кластер 2 | 28.0% | 61.0% | Лонг — low рано + WR 67% |
| inside_va_below_poc × кластер 3 | 43.7% | 69.0% | Low рано, поддержка быстрая |

### HMM Transition Matrix (ключевые переходы)

| From | To | Prob | Интерпретация |
|------|----|------|--------------|
| State 3 | State 3 | 0.347 | Балансовый режим sticky |
| State 4 | State 5 | 0.306 | Кризис → высокая волатильность |
| State 2 | State 3 | 0.302 | Направленный → баланс |
| State 4 | State 4 | 0.272 | Кризис persistence |

HMM State 3 win rate: **55.7%** на 774 днях — самый значимый результат.

---

## Текущая классификация (amt_classify.py)

### Day Type логика (6 переменных)
- VAR1: `ib_width_cat` — small/medium/wide через Parkinson RV
- VAR2: `profile_width_cat` — small/medium/wide
- VAR3: `ib_profile` — full(>0.65) / medium(0.35-0.65) / minimal(<0.35)
- VAR4: `broken_dir` — none/up/down/both (нарушение IB после 60 мин)
- VAR5: `poc_bias` — 0=центр, 1=экстремум
- VAR6: `open_poc_dist` — дистанция Open→POC нормализованная

### Open Type логика
Позиционная через dist = min(open_pos, 1-open_pos) от экстремума IB:
- Open Auction (приоритет): период B (30-60 мин) пересекает open в обе стороны
- Open Drive: dist ≤ 0.05
- Open Test Drive: dist ≤ 0.20
- Open Rejection Reverse: dist > 0.20

### IB определение
- IB = первые 60 минут RTH (периоды A + B)
- `ib_broken` строго без tol — любой бар после iloc[60:] за границу IB
- `find_extreme_slot` — получасовой слот формирования high/low

---

## Известные проблемы классификации

| Проблема | Статус |
|---------|--------|
| normal_variation 67% — слишком много | Pending — GMM найдёт субтипы |
| trend 9.3% — ближе к теории | OK |
| normal 1.6% — мало | Pending |
| nontrend 0.6% — мало | Pending |
| DD не отображается | Pending — GMM/HMM найдёт |
| Inside VA всегда responsive | Частично исправлено |

**REMINDER: IB и day types логика требует переработки после ML валидации**

---

## Roadmap

### Этап 1 — Текущий (финализация статистики)
- [x] AMT классификация базовая
- [x] GMM кластеризация с VIX
- [x] HMM transition matrix
- [x] Win rate по open_location × GMM × VIX
- [x] High/Low slot анализ
- [ ] `open_dist` float в records (pending)
- [ ] ZN 10Y direction как макро feature
- [ ] ZT 2Y yield curve slope (докачать данные)
- [ ] ES/NQ rolling correlation как опережающий индикатор

### Этап 2 — ML улучшения
- [ ] Переобучить GMM/HMM с ZN + ZT features
- [ ] Fuzzy membership через posterior probabilities
- [ ] Walk-forward валидация
- [ ] Out-of-sample тест

### Этап 3 — Бэктест
- [ ] Реализовать топ комбинации в vectorbt
- [ ] outside_range_above × кластер 2 × low VIX → лонг
- [ ] outside_range_above × кластер 4 × low VIX → шорт (антисигнал)
- [ ] HMM state 3 фильтр

### Этап 4 — Live Trading
- [ ] Портировать в nautilus-trader
- [ ] Rithmic paper trading
- [ ] Real-time GMM/HMM inference

---

## Файловая структура

```
~/dev-tools/quant/
├── amt_classify.py          # модуль классификации
├── RESEARCH.md              # этот файл
├── CLAUDE.md                # контекст для Claude Code
├── jupyter strats/
│   └── amt_stats.ipynb      # основной ноутбук
├── cache/
│   ├── es_continuous.parquet  # не трогать
│   ├── nq_continuous.parquet  # не трогать
│   ├── es_va.parquet          # удалить если менял calc_va
│   ├── nq_va.parquet
│   ├── vix_daily.parquet      # не трогать
│   ├── es_days.parquet        # удалить если менял classify_days
│   └── nq_days.parquet
└── data/
    ├── GLBX-20260603-XBMUUNEJJQ 16yr nq es data/
    ├── GLBX-20260604-YY86KWTSMD 10yr/    (ZN 10Y bonds)
    └── OPRA-20260603-MPJCVX5T73 vix/     (VIX)
```

---

## Технические заметки

- `TOL = 1.0` (4 тика) для всех уровневых проверок
- `ib_broken` строго без tol — после iloc[60:]
- IB = первые 60 минут RTH (периоды A + B)
- RTH: 14:30-21:00 UTC (09:30-16:00 ET)
- Parkinson RV: `sqrt((1/4ln2) * ln(H/L)^2)`, rolling 20 дней
- GMM: n=8, covariance_type='full', features нормализованы StandardScaler
- HMM: n=7, GaussianHMM, n_iter=500
- VIX режимы: low(<15), normal(15-25), high(>25)
- Кеш инвалидация: только es_days/nq_days при изменении classify логики
