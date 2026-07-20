import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

TICK      = 0.25
TOL       = 4 * TICK
VA_PCT    = 0.70
RTH_START = 14 * 60 + 30
RTH_END   = 21 * 60 + 0


# ─────────────────────────────────────────────────────────────
# VALUE AREA + HVN / LVN
# ─────────────────────────────────────────────────────────────
def calc_va(day_bars, tick=TICK, va_pct=VA_PCT,
            hvn_threshold=0.70, lvn_threshold=0.30, smooth=3):
    lo = day_bars['low'].min()
    hi = day_bars['high'].max()
    if hi - lo < tick:
        return None

    levels = np.arange(lo, hi + tick, tick)
    vol    = np.zeros(len(levels))
    tpo    = np.zeros(len(levels))

    for _, bar in day_bars.iterrows():
        mask = (levels >= bar['low']) & (levels <= bar['high'])
        n    = mask.sum()
        if n == 0:
            continue
        vol[mask] += bar['volume'] / n
        tpo[mask] += 1

    if vol.sum() == 0:
        return None

    smoothed = uniform_filter1d(vol, size=smooth)
    poc_i    = int(np.argmax(smoothed))

    target = vol.sum() * va_pct
    lo_i, hi_i = poc_i, poc_i
    acc = vol[poc_i]
    while acc < target:
        can_up = hi_i < len(levels) - 1
        can_dn = lo_i > 0
        if not can_up and not can_dn:
            break
        v_up = vol[hi_i + 1] if can_up else -1
        v_dn = vol[lo_i - 1] if can_dn else -1
        if v_up >= v_dn:
            hi_i += 1; acc += vol[hi_i]
        else:
            lo_i -= 1; acc += vol[lo_i]

    hvn_levels = levels[smoothed >= smoothed.max() * hvn_threshold].tolist()
    lvn_levels = levels[smoothed < smoothed.mean() * lvn_threshold].tolist()

    return {
        'poc':        float(levels[poc_i]),
        'vah':        float(levels[hi_i]),
        'val':        float(levels[lo_i]),
        'day_high':   float(hi),
        'day_low':    float(lo),
        'hvn_levels': hvn_levels,
        'lvn_levels': lvn_levels,
        'levels':     levels,
        'tpo':        tpo,
        'vol':        vol,
    }


def build_va_database(rth_data, tick=TICK):
    rth_data = rth_data.copy()
    rth_data['date'] = rth_data.index.date
    records = []
    for date, group in rth_data.groupby('date'):
        va = calc_va(group, tick=tick)
        if va is None:
            continue
        records.append({
            'date':       date,
            'poc':        va['poc'],
            'vah':        va['vah'],
            'val':        va['val'],
            'day_high':   va['day_high'],
            'day_low':    va['day_low'],
            'hvn_levels': va['hvn_levels'],
            'lvn_levels': va['lvn_levels'],
        })
    return pd.DataFrame(records).set_index('date')


# ─────────────────────────────────────────────────────────────
# INTRADAY RV
# ─────────────────────────────────────────────────────────────
def calc_intraday_rv(rth_data, window=20):
    """
    Intraday RV из 1m баров за rolling window торговых дней.
    std логарифмических возвратов * sqrt(390 минут в RTH).
    """
    rth = rth_data.copy()
    rth['date'] = rth.index.date
    log_ret = np.log(rth['close'] / rth['close'].shift(1))
    day_starts = rth.groupby('date').head(1).index
    log_ret.loc[day_starts] = np.nan
    daily_std = log_ret.groupby(rth['date']).std()
    daily_std.index = pd.to_datetime(daily_std.index)
    return daily_std.rolling(window).mean() * np.sqrt(390)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def near(price, level, tol=TOL):
    return abs(price - level) <= tol


def touches(bar_low, bar_high, level, tol=TOL):
    return bar_low <= level + tol and bar_high >= level - tol


def open_on_hvn_lvn(open_px, hvn_levels, lvn_levels, tol=TOL):
    if any(near(open_px, h, tol) for h in hvn_levels):
        return 'hvn'
    if any(near(open_px, l, tol) for l in lvn_levels):
        return 'lvn'
    return 'none'


def ib_broken(today, ib_high, ib_low):
    """
    Строгая проверка: IB нарушен если хотя бы один бар
    после первых 60 минут имеет high > ib_high или low < ib_low.
    Никаких допущений, никакого tol.
    """
    after_ib = today.iloc[60:]
    if len(after_ib) == 0:
        return False
    broken_up   = (after_ib['high'] > ib_high).any()
    broken_down = (after_ib['low']  < ib_low).any()
    return broken_up or broken_down


def ib_broken_direction(today, ib_high, ib_low):
    """Возвращает сторону нарушения IB: 'up', 'down', 'both', 'none'."""
    after_ib    = today.iloc[60:]
    broken_up   = (after_ib['high'] > ib_high).any()
    broken_down = (after_ib['low']  < ib_low).any()
    if broken_up and broken_down:
        return 'both'
    if broken_up:
        return 'up'
    if broken_down:
        return 'down'
    return 'none'

def find_extreme_slot(bars, extreme_val, side='high'):
    """Возвращает номер получасового слота где сформировался экстремум дня."""
    for slot in range(14):
        sb = bars.iloc[slot*30:(slot+1)*30]
        if len(sb) == 0:
            continue
        if side == 'high' and sb['high'].max() >= extreme_val:
            return slot
        if side == 'low' and sb['low'].min() <= extreme_val:
            return slot
    return None


# ─────────────────────────────────────────────────────────────
# OPEN TYPE
# ─────────────────────────────────────────────────────────────
def classify_open_type(today, open_px, tol=TOL):
    """
    Классификация по позиции открытия внутри IB (кривая нормального
    распределения) + проверка периода B на пересечение open.

    IB = первые 30 минут (период A)
    Период B = следующие 30 минут (бары 30-60)

    open_position = (open_px - ib_low) / ib_range  → 0..1
    Расстояние от ближайшего экстремума:
      dist = min(open_position, 1 - open_position)

    Приоритет:
      1. Open Auction   : период B торгуется через open (обе стороны)
      2. Open Drive     : dist <= 0.05  (крайние 5% IB)
      3. Open Test Drive: dist <= 0.20  (зона 5-20%)
      4. ORR            : dist <= 0.50  (зона 20-50%, ближе к середине)
    """
    bars_a       = today.iloc[:30]   # период A — начальное движение
    bars_b       = today.iloc[30:60] # период B — проверка auction
    bars_ib      = today.iloc[:60]   # IB = A + B — для ширины
    bars_after_ib = today.iloc[60:]  # после IB — для broken логики

    if len(bars_a) < 5:
        return 'unknown'

    ib_high = float(bars_a['high'].max())
    ib_low  = float(bars_a['low'].min())
    ib_range = ib_high - ib_low

    if ib_range < TICK:
        return 'unknown'

    # Позиция открытия внутри IB
    open_pos = (open_px - ib_low) / ib_range          # 0=low, 1=high
    open_pos = max(0.0, min(1.0, open_pos))            # clip
    dist     = min(open_pos, 1.0 - open_pos)           # расстояние от экстремума

    # ── 1. Open Auction (приоритет): период B пересекает open ─
    if len(bars_b) >= 5:
        b_high = float(bars_b['high'].max())
        b_low  = float(bars_b['low'].min())
        b_crosses_open = (b_high > open_px + tol) and (b_low < open_px - tol)
        if b_crosses_open:
            return 'open_auction'

    # ── 2. Open Drive: открытие в крайних 5% IB ──────────────
    if dist <= 0.05:
        return 'open_drive'

    # ── 3. Open Test Drive: открытие в зоне 5-20% ────────────
    if dist <= 0.20:
        return 'open_test_drive'

    # ── 4. Open Rejection Reverse: открытие в зоне 20-50% ────
    return 'open_rejection_reverse'


# ─────────────────────────────────────────────────────────────
# ACCEPTANCE / REJECTION
# ─────────────────────────────────────────────────────────────
def check_level_interaction(bars, level, tol=TOL):
    slot_touched = []
    for slot in range(14):
        sb = bars.iloc[slot * 30:(slot + 1) * 30]
        if len(sb) == 0:
            continue
        t = touches(sb['low'].min(), sb['high'].max(), level, tol)
        slot_touched.append((slot, t))

    touch_slots = [s for s, t in slot_touched if t]
    if not touch_slots:
        return None, None, False

    first_slot = touch_slots[0]
    consec = max_c = 1
    for i in range(1, len(slot_touched)):
        if slot_touched[i][1] and slot_touched[i-1][1]:
            consec += 1
            max_c = max(max_c, consec)
        else:
            consec = 1

    accepted = max_c >= 2
    return first_slot, 'acceptance' if accepted else 'rejection', accepted


# ─────────────────────────────────────────────────────────────
# INITIATIVE / RESPONSIVE
# ─────────────────────────────────────────────────────────────
def classify_activity(bars, prev_vah, prev_val, prev_poc,
                      prev_high, prev_low, tol=TOL):
    early    = bars.iloc[:60]
    if len(early) < 5:
        return 'unknown'

    open_px  = float(early['open'].iloc[0])
    close_60 = float(early['close'].iloc[-1])

    # Range как первичный критерий
    if open_px > prev_high + tol:
        return 'initiative_buying' if close_60 > prev_high - tol else 'responsive_selling'
    if open_px < prev_low - tol:
        return 'initiative_selling' if close_60 < prev_low + tol else 'responsive_buying'

    # VA как вторичный критерий
    if open_px > prev_vah + tol:
        return 'initiative_buying' if close_60 > prev_vah - tol else 'responsive_selling'
    if open_px < prev_val - tol:
        return 'initiative_selling' if close_60 < prev_val + tol else 'responsive_buying'

    # Внутри VA
    return 'responsive_buying' if close_60 > prev_poc else 'responsive_selling'


# ─────────────────────────────────────────────────────────────
# DAY TYPE
# ─────────────────────────────────────────────────────────────
def intraday_profile(today, tick=TICK, smooth=3):
    """Внутридневной volume-профиль по уровням цены (как в calc_va)."""
    lo = float(today['low'].min())
    hi = float(today['high'].max())
    if hi - lo < tick:
        return None, None
    levels = np.arange(lo, hi + tick, tick)
    vol    = np.zeros(len(levels))
    for bl, bh, bv in zip(today['low'].values,
                          today['high'].values,
                          today['volume'].values):
        mask = (levels >= bl) & (levels <= bh)
        n = mask.sum()
        if n:
            vol[mask] += bv / n
    if vol.sum() == 0:
        return None, None
    return levels, uniform_filter1d(vol, size=smooth)


def is_double_distribution(today, tick=TICK,
                           peak_frac=0.35, valley_frac=0.50,
                           min_sep_frac=0.30):
    """
    Double distribution = бимодальный профиль:
      • >= 2 пика (HVN) высотой >= peak_frac * max,
      • разделённых долиной (LVN) <= valley_frac * меньшего пика,
      • с разносом мод >= min_sep_frac диапазона дня (две отдельные
        дистрибуции, а не два соседних бугра).
    Использует форму профиля, а не позицию хай/лоу после IB.
    """
    levels, sm = intraday_profile(today, tick)
    if sm is None or len(sm) < 5:
        return False
    mx = sm.max()
    if mx <= 0:
        return False
    min_dist = max(1, int(min_sep_frac * len(sm)))
    peaks, _ = find_peaks(sm, height=peak_frac * mx, distance=min_dist)
    if len(peaks) < 2:
        return False
    # две сильнейшие моды
    top2 = peaks[np.argsort(sm[peaks])[-2:]]
    p_lo, p_hi   = int(min(top2)), int(max(top2))
    valley       = sm[p_lo:p_hi + 1].min()
    smaller_peak = min(sm[p_lo], sm[p_hi])
    sep_ok    = (p_hi - p_lo) >= min_sep_frac * len(sm)
    valley_ok = valley <= valley_frac * smaller_peak
    return bool(sep_ok and valley_ok)


def bimodality_score(today, tick=TICK, peak_frac=0.35, min_sep_frac=0.30):
    """Непрерывная мера бимодальности профиля [0..1] = глубина LVN-долины
    между двумя сильнейшими HVN-модами (0 = унимодальный/слитный,
    1 = две чётко разделённые дистрибуции). Это x6 для session-shape."""
    levels, sm = intraday_profile(today, tick)
    if sm is None or len(sm) < 5:
        return 0.0
    mx = sm.max()
    if mx <= 0:
        return 0.0
    min_dist = max(1, int(min_sep_frac * len(sm)))
    peaks, _ = find_peaks(sm, height=peak_frac * mx, distance=min_dist)
    if len(peaks) < 2:
        return 0.0
    top2 = peaks[np.argsort(sm[peaks])[-2:]]
    p_lo, p_hi = int(min(top2)), int(max(top2))
    if (p_hi - p_lo) < min_sep_frac * len(sm):
        return 0.0
    valley       = sm[p_lo:p_hi + 1].min()
    smaller_peak = min(sm[p_lo], sm[p_hi])
    if smaller_peak <= 0:
        return 0.0
    return float(np.clip(1.0 - valley / smaller_peak, 0.0, 1.0))


def classify_day_type(today, ib_high, ib_low,
                      day_high, day_low, curr_vah, curr_val, curr_poc,
                      ib_width_cat, profile_width_cat,
                      tol=TOL):
    """
    VAR1: ib_width_cat      — ширина IB нормализованная через Parkinson RV
    VAR2: profile_width_cat — ширина дневного профиля нормализованная
    VAR3: ib_profile        — соотношение IB/profile (full/medium/minimal)
    VAR4: broken_dir        — направленность нарушения IB (none/up/down/both)
    VAR5: poc_bias          — положение POC в дневном профиле (0=центр, 1=экстремум)
    VAR6: open_poc_dist     — дистанция Open→POC нормализованная (0=рядом, 1=далеко)

    poc_bias:
      0 = POC в центре (баланс)
      1 = POC у экстремума (направленность)
    """
    close_px  = float(today['close'].iloc[-1])
    ib_range  = ib_high - ib_low
    day_range = day_high - day_low

    if day_range == 0:
        return 'unknown'

    ib_profile = ib_range / day_range
    broken     = ib_broken(today, ib_high, ib_low)
    broken_dir = ib_broken_direction(today, ib_high, ib_low)

    # VAR4: направленность через POC bias
    poc_position = (curr_poc - day_low) / day_range
    poc_bias     = abs(poc_position - 0.5) * 2  # 0=центр, 1=экстремум

    iw = ib_width_cat      # 'small' | 'medium' | 'wide'
    pw = profile_width_cat # 'small' | 'medium' | 'wide'

    # VAR3: категория соотношения IB/profile
    if ib_profile > 0.65:
        ratio_cat = 'full'      # профиль ≈ IB
    elif ib_profile > 0.35:
        ratio_cat = 'medium'    # умеренный выход
    else:
        ratio_cat = 'minimal'   # сильный выход за IB

    # ── 1. Nontrend: IB строго не нарушен, всё узкое ─────────
    if not broken and iw == 'small' and pw == 'small':
        return 'nontrend'

    # ── 2. Normal: IB строго не нарушен, широкий IB ──────────
    if not broken and ratio_cat == 'full':
        return 'normal'

    # ── 3. Double Distribution: бимодальный профиль (две дистрибуции) ─
    # Раньше детектился gap хай/лоу после IB (≈ runaway, срабатывал ~0 дней).
    # Теперь — реальная бимодальность volume-профиля: два HVN-пика с LVN между.
    if pw in ('medium', 'wide') and is_double_distribution(today):
        return 'double_distribution'

    # ── 4. Trend: POC у экстремума + минимальный ratio ────────
    if ratio_cat == 'minimal' and poc_bias >= 0.50:
        return 'trend'

    # ── 5. Neutral: IB нарушен с обеих сторон + POC в центре ─
    if broken_dir == 'both' and poc_bias < 0.50:
        return 'neutral'

    # ── 6. Normal Variation: всё остальное broken ────────────
    if broken_dir in ('up', 'down', 'both'):
        return 'normal_variation'

    # ── 7. Fallback ───────────────────────────────────────────
    return 'normal'


# ─────────────────────────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────────────────────
def classify_days(rth_data, va_db, irv_dict=None,
                  ib_rv_quantiles=None, profile_rv_quantiles=None,
                  ib_profile_quantiles=None):
    """
    irv_dict              : {date: intraday_rv} для нормализации IB/profile
    ib_rv_quantiles       : [q33, q66] для разбивки IB (переопределяет авто)
    profile_rv_quantiles  : [q33, q66] для разбивки profile (переопределяет авто)
    ib_profile_quantiles  : не используется, оставлен для совместимости
    """
    if irv_dict is None:
        irv_dict = {}

    rth_data = rth_data.copy()
    rth_data['date'] = rth_data.index.date
    dates   = sorted(rth_data['date'].unique())

    # Первый проход — собираем нормализованные метрики
    raw = []
    for i, date in enumerate(dates):
        if i == 0:
            continue
        prev_date = dates[i - 1]
        if prev_date not in va_db.index or date not in va_db.index:
            continue
        today    = rth_data[rth_data['date'] == date]
        tva      = va_db.loc[date]
        if len(today) < 10:
            continue

        ib_bars   = today.iloc[:60]
        ib_high   = float(ib_bars['high'].max())
        ib_low    = float(ib_bars['low'].min())
        ib_range  = ib_high - ib_low
        day_high  = float(tva['day_high'])
        day_low   = float(tva['day_low'])
        day_range = day_high - day_low
        open_px   = float(today['open'].iloc[0])

        irv = irv_dict.get(date, None)
        if irv and irv > 0:
            daily_expected = irv * open_px
            ib_norm   = ib_range  / daily_expected
            prof_norm = day_range / daily_expected
        else:
            ib_norm   = ib_range  / open_px * 100
            prof_norm = day_range / open_px * 100

        raw.append({
            'date':       date,
            'ib_norm':    ib_norm,
            'prof_norm':  prof_norm,
            'ib_profile': ib_range / day_range if day_range > 0 else 0,
        })

    raw_df = pd.DataFrame(raw)

    ib_q  = (ib_rv_quantiles if ib_rv_quantiles is not None
             else [raw_df['ib_norm'].quantile(0.33),   raw_df['ib_norm'].quantile(0.66)])
    pr_q  = (profile_rv_quantiles if profile_rv_quantiles is not None
             else [raw_df['prof_norm'].quantile(0.33), raw_df['prof_norm'].quantile(0.66)])
    ipr_q = [0.35, 0.65]  # фиксированные пороги

    def categorize(val, q):
        if val <= q[0]:
            return 'small'
        elif val <= q[1]:
            return 'medium'
        return 'wide'

    # Второй проход: полная классификация
    records = []
    for i, date in enumerate(dates):
        if i == 0:
            continue
        prev_date = dates[i - 1]
        if prev_date not in va_db.index or date not in va_db.index:
            continue

        today = rth_data[rth_data['date'] == date]
        pva   = va_db.loc[prev_date]
        tva   = va_db.loc[date]
        if len(today) < 10:
            continue

        open_px  = float(today['open'].iloc[0])
        close_px = float(today['close'].iloc[-1])
        day_high = float(tva['day_high'])
        day_low  = float(tva['day_low'])
        day_range = day_high - day_low
        poc      = float(pva['poc'])
        vah      = float(pva['vah'])
        val      = float(pva['val'])
        pd_high  = float(pva['day_high'])
        pd_low   = float(pva['day_low'])
        curr_vah = float(tva['vah'])
        curr_val = float(tva['val'])
        curr_poc = float(tva['poc'])

        hvn = pva.get('hvn_levels', []) or []
        lvn = pva.get('lvn_levels', []) or []
        if not isinstance(hvn, list): hvn = []
        if not isinstance(lvn, list): lvn = []

        ib_bars  = today.iloc[:60]
        ib_high  = float(ib_bars['high'].max())
        ib_low   = float(ib_bars['low'].min())
        ib_range = ib_high - ib_low
        ib_profile = ib_range / day_range if day_range > 0 else 0

        high_slot = find_extreme_slot(today, day_high, 'high')
        low_slot  = find_extreme_slot(today, day_low,  'low')
        bimodality = bimodality_score(today)

        irv = irv_dict.get(date, None)
        if irv and irv > 0:
            daily_expected = irv * open_px
            ib_norm   = ib_range  / daily_expected
            prof_norm = day_range / daily_expected
        else:
            ib_norm   = ib_range  / open_px * 100
            prof_norm = day_range / open_px * 100

        iw  = categorize(ib_norm,    ib_q)
        pw  = categorize(prof_norm,  pr_q)
        ipr = {'small': 'low', 'medium': 'medium', 'wide': 'high'}[categorize(ib_profile, ipr_q)]

        # Условие открытия
        if val - TOL <= open_px <= vah + TOL:
            open_location = 'inside_va_above_poc' if open_px >= poc else 'inside_va_below_poc'
        elif pd_low - TOL <= open_px <= pd_high + TOL:
            open_location = 'outside_va_above_poc' if open_px >= poc else 'outside_va_below_poc'
        else:
            open_location = 'outside_range_above' if open_px >= poc else 'outside_range_below'

        direction    = 'long' if open_px >= poc else 'short'
        open_type    = classify_open_type(today, open_px)
        activity     = classify_activity(today, vah, val, poc, pd_high, pd_low)
        day_type     = classify_day_type(today, ib_high, ib_low,
                                          day_high, day_low,
                                          curr_vah, curr_val, curr_poc,
                                          iw, pw)
        open_hvn_lvn = open_on_hvn_lvn(open_px, hvn, lvn)

        poc_slot, poc_int, poc_acc = check_level_interaction(today, poc)
        vah_slot, vah_int, vah_acc = check_level_interaction(today, vah)
        val_slot, val_int, val_acc = check_level_interaction(today, val)
        pdh_slot, pdh_int, pdh_acc = check_level_interaction(today, pd_high)
        pdl_slot, pdl_int, pdl_acc = check_level_interaction(today, pd_low)

        open_poc_dist = abs(open_px - curr_poc) / day_range if day_range > 0 else 0
        poc_position  = (curr_poc - day_low) / day_range if day_range > 0 else 0.5
        poc_bias      = abs(poc_position - 0.5) * 2

        close_pos = (close_px - day_low) / day_range if day_range > 0 else 0.5
        if close_px >= curr_vah - TOL:
            close_location = 'above_va'
        elif close_px <= curr_val + TOL:
            close_location = 'below_va'
        else:
            close_location = 'inside_va'
        close_vs_poc = 'above_poc' if close_px >= curr_poc else 'below_poc'

        records.append({
            'date':             date,
            'open_px':          open_px,
            'close_px':         close_px,
            'day_high':         day_high,
            'day_low':          day_low,
            'ib_high':          ib_high,
            'ib_low':           ib_low,
            'ib_range':         ib_range,
            'day_range':        day_range,
            'ib_profile_ratio': round(ib_profile, 3),
            'ib_width_cat':     iw,
            'profile_width_cat': pw,
            'ib_profile_cat':   ipr,
            'high_slot':        high_slot,
            'low_slot':         low_slot,
            'bimodality':       round(bimodality, 3),
            'prev_poc':         poc,
            'prev_vah':         vah,
            'prev_val':         val,
            'prev_high':        pd_high,
            'prev_low':         pd_low,
            'curr_poc':         curr_poc,
            'curr_vah':         curr_vah,
            'curr_val':         curr_val,
            'open_poc_dist':    round(open_poc_dist, 3),
            'poc_bias':         round(poc_bias, 3),
            'open_location':    open_location,
            'open_hvn_lvn':     open_hvn_lvn,
            'direction':        direction,
            'open_type':        open_type,
            'activity':         activity,
            'day_type':         day_type,
            'close_location':   close_location,
            'close_vs_poc':     close_vs_poc,
            'close_position':   round(close_pos, 3),
            'poc_touch_slot':   poc_slot,
            'poc_interaction':  poc_int,
            'poc_accepted':     poc_acc,
            'vah_touch_slot':   vah_slot,
            'vah_interaction':  vah_int,
            'vah_accepted':     vah_acc,
            'val_touch_slot':   val_slot,
            'val_interaction':  val_int,
            'val_accepted':     val_acc,
            'pdh_touch_slot':   pdh_slot,
            'pdh_interaction':  pdh_int,
            'pdh_accepted':     pdh_acc,
            'pdl_touch_slot':   pdl_slot,
            'pdl_interaction':  pdl_int,
            'pdl_accepted':     pdl_acc,
        })

    return pd.DataFrame(records).set_index('date')


print('amt_classify OK')