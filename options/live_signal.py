"""
live_signal.py — ежедневный лайв-сигнал short-vol движка (SPX, 1DTE iron condor).

БОЕВАЯ КОНФИГУРАЦИЯ (real-marks honest backtest 2026-06, Sharpe ~1.2):
    Продать 1DTE IRON CONDOR (short strangle ±OTM_PCT + long крылья ±WING_PCT,
    экспирация СЛЕДУЮЩИЙ торговый день), держать до экспирации.  ТОЛЬКО когда:
    GATE = (gex_z >= 0)  AND  (vix_term_slope <= 0)
           # forward crisis-off, pre-registered, point-in-time (gex_z>=0 ⇒ long-gamma режим).
    SIZE = clip( (REF_IV / atm_iv_30)^2 , 0, K_MAX )
           # forward inverse-IV vol-target (высокая IV ⇒ меньше размер ДО шторма).
    n_condors = round( BASE * SIZE )  если GATE иначе 0  (FLAT).
    КРЫЛЬЯ кэпят хвост: Monte-Carlo (jump-diffusion с крах-гэпами) → naked P(ruin>50%DD за 5л)
    =3.5%, worst-day −64%; iron condor → 0% ruin, worst-day −16.6%. Naked Sharpe чуть выше, но
    несёт нескомпенсированный ruin-риск (нет в спокойном 2021-26 сэмпле) → крылья обязательны.

ПОЧЕМУ 1DTE: edge GEX = NEXT-DAY сигнал → монетизируется только тенором, чьё окно риска = тот
один день (DTE-свип: 1D Sharpe 1.29, 2D+ ~0/минус). «30DTE-движок» с Sharpe 2.1 был variance-
ПРОКСИ (игнорировал vega·dIV) → инфляция ~2×. Честный naked-strangle ~1.2. Flat gate (БЕЗ
VRP-веса — он вредит и на real marks). Crisis-off = только forward-гейты, НЕТ DD/kill.
⚠️ Эдж режимный (силён 2024-25, минус 2022/23/26) + 1DTE = max gamma/gap-риск; 2021-26 не
содержит 2008/2020-краха. Strangle смягчает хвост, размер держи малым. См. PROJECT.md / память.

КЛЮЧ: env INTRINIO_API_KEY → файл ~/.intrinio_key → ROOT/.intrinio_key (gitignored). НЕ хардкодить.

Запуск:
    python live_signal.py                 # фетчит свежий EOD, выдаёт сигнал
    python live_signal.py --use-cache     # без фетча, сигнал по последней кэш-дате (для проверки)
    python live_signal.py --ref-iv 0.16   # агрессивнее (risk-диал)
    python live_signal.py --base 4        # масштаб капитала: 4 стрэнгла при нормальной IV
"""
import os, sys, argparse, logging, importlib.util
import numpy as np, pandas as pd

ROOT       = os.path.dirname(os.path.abspath(__file__))   # портативно: путь от расположения скрипта
SYMBOL     = ['SPX', 'SPXW']
REF_IV     = 0.13          # риск-диал по умолчанию
GEX_MARGIN = 0.5           # CONFIDENCE-BUFFER: торгуем только gex_z >= 0.5 (НЕ просто >=0). Причина:
                           #   gex_z тут = последний ДОСТУПНЫЙ EOD (= T-1 на close T, OI публикуется поздно).
                           #   Лагнутый сигнал у границы (gex_z≈0) переворачивается → flip-дни торгуются неверно
                           #   (Sharpe 1.04→0.31). Буфер требует РОБАСТНО long-gamma → отсеивает flip-prone дни →
                           #   реализуемый лайв Sharpe ~0.98 (фикс 0.5, pre-reg) / 1.53 (OOS-WF). Деплой консерв. 0.5.
K_MAX      = 3.0           # потолок плеча на сайзере
BASE       = 1.0           # размер (стрэнглов) при IV = REF_IV; масштаб капитала — твоё решение
TARGET_DTE = 1             # 1DTE: продаём опцион с экспирацией на след. торговый день
OTM_PCT    = 0.012         # IRON CONDOR — short-нога: страйки ±1.2% (robust: Sharpe 1.22→1.31)
WING_PCT   = 0.05          # long-крылья ±5%: кэпят хвост. MC: naked P(ruin>50%DD за 5л)=3.5%→0%,
                           #   worst-day −64%→−16.6%. Naked Sharpe чуть выше, но несёт нескомп. ruin-риск
                           #   (нет в 2021-26 выборке). Крылья = известный макс-дебет за модест премии.
FRED_KEY   = 'YOUR_FRED_API_KEY'   # бесплатный FRED, не секрет
SIGNALS_LOG = f'{ROOT}/signals_log.csv'


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('live')


def load_key():
    k = os.environ.get('INTRINIO_API_KEY')
    if k:
        return k
    for p in (os.path.expanduser('~/.intrinio_key'), f'{ROOT}/.intrinio_key'):
        if os.path.exists(p):
            key = open(p).read().strip()
            if key:
                return key
    raise RuntimeError('Нет ключа: `export INTRINIO_API_KEY=...` или создай файл ~/.intrinio_key')


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def recommend_condor(iopt, target_date, spot):
    """Iron condor из кэш-цепочки: SHORT strangle (±OTM_PCT) + LONG крылья (±WING_PCT), 1DTE."""
    chain = iopt.load_cached(SYMBOL)
    if chain.empty or 'quote_date' not in chain.columns:
        return None
    chain = chain[pd.to_datetime(chain['quote_date']).dt.date == target_date]
    chain = chain.dropna(subset=['expiration', 'strike', 'dte', 'type'])
    chain = chain[chain['dte'] > 0]
    if chain.empty:
        return None
    exp = chain.iloc[(chain['dte'] - TARGET_DTE).abs().argsort().iloc[0]]['expiration']
    leg = chain[chain['expiration'] == exp]
    calls = leg[leg['type'] == 'call']; puts = leg[leg['type'] == 'put']
    if calls.empty or puts.empty:
        return None
    def nearest(df, target):
        return float(df.iloc[(df['strike'] - target).abs().argsort().iloc[0]]['strike'])
    return {'expiration': str(pd.to_datetime(exp).date()), 'dte': int(leg['dte'].iloc[0]),
            'short_put':  nearest(puts,  spot*(1-OTM_PCT)),  'short_call': nearest(calls, spot*(1+OTM_PCT)),
            'long_put':   nearest(puts,  spot*(1-WING_PCT)), 'long_call':  nearest(calls, spot*(1+WING_PCT))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--use-cache', action='store_true', help='не фетчить, сигнал по последней кэш-дате')
    ap.add_argument('--ref-iv', type=float, default=REF_IV)
    ap.add_argument('--base', type=float, default=BASE)
    args = ap.parse_args()

    iopt = _load('intrinio_options', f'{ROOT}/intrinio_options.py')
    # intermarket_lab lives in the sibling indices/ track (shared macro/vol-credit engine)
    il   = _load('intermarket_lab',  f'{ROOT}/../indices/core/intermarket_lab.py')

    # 1) обновить кэш свежим EOD (если не --use-cache)
    if not args.use_cache:
        key = load_key()
        # trailing-окно последних торговых дней: EOD за день T публикуется после закрытия
        # (часто T+1 утром), поэтому «сегодня» обычно ещё 403 — окно подтянет свежий EOD,
        # как только он выйдет. resume пропускает скачанное; 403 не пишет .empty → ретрай назавтра.
        today = pd.Timestamp.now().normalize()
        dates = [str(d.date()) for d in pd.bdate_range(today - pd.Timedelta(days=8), today)]
        log.info('Фетч SPX+SPXW, trailing-окно %s..%s ...', dates[0], dates[-1])
        for sym in SYMBOL:
            iopt.fetch_range(sym, dates, api=iopt.get_api(key), recalc=False)

    # 2) дневные фичи из кэша (SPX: вендорская IV битая → self-greeks recompute=True)
    of = iopt.daily_features(SYMBOL, None, recompute=True)
    if of.empty:
        log.error('Нет данных в кэше — нечего считать'); sys.exit(1)
    of['rv_21'] = iopt.realized_vol(of['spot'], 21)
    of['vrp']   = of['atm_iv_30'] - of['rv_21']
    of['gex_z'] = (of['gex'] - of['gex'].rolling(60).mean()) / of['gex'].rolling(60).std()

    # 3) макро-гейт (FRED, point-in-time на последнюю доступную дату)
    try:
        vc = il.vol_credit_features('2010-01-01', str(of.index.max().date()), FRED_KEY)
        vix_term_slope = float(vc['vix_term_slope'].ffill().iloc[-1])
    except Exception as e:
        log.warning('FRED недоступен (%s) → macro_safe=True по умолчанию', e)
        vix_term_slope = -1.0

    # 4) сигнал на последнюю дату
    row  = of.iloc[-1]
    date = of.index[-1].date()
    gex_z = float(row['gex_z']); iv = float(row['atm_iv_30']); spot = float(row['spot'])

    gex_ok   = gex_z >= GEX_MARGIN          # confidence-buffer (gex_z = последний EOD = T-1 на close T)
    macro_ok = vix_term_slope <= 0
    gate     = gex_ok and macro_ok
    sizer    = float(np.clip((args.ref_iv / max(iv, 0.05))**2, 0, K_MAX))
    n_cond   = max(1, round(args.base * sizer)) if gate else 0   # активный сигнал = мин. 1 контракт
    rec      = recommend_condor(iopt, date, spot)

    # 5) отчёт
    print('\n' + '='*64)
    print(f'  SHORT-VOL ЛАЙВ-СИГНАЛ · SPX 1DTE iron condor · {date}')
    print('='*64)
    print(f'  spot={spot:.0f}   ATM_IV_30={iv*100:.1f}%   VRP={float(row["vrp"])*100:+.1f}pp   GEX_z={gex_z:+.2f}')
    print('-'*64)
    print(f'  GATE: gex_z>={GEX_MARGIN:g} [{"✓" if gex_ok else "✗"} {gex_z:+.2f}]   '
          f'vix_term_slope<=0 [{"✓" if macro_ok else "✗"} {vix_term_slope:+.2f}]')
    print(f'  SIZER (REF_IV={args.ref_iv:g}): (REF/IV)^2 = {sizer:.2f}×')
    print('-'*64)
    if gate:
        print(f'  ▶ ШОРТ-VOL: {n_cond} iron condor  (base={args.base:g} × sizer={sizer:.2f})')
        if rec:
            print(f'    SPX exp {rec["expiration"]} (DTE {rec["dte"]}):')
            print(f'      SHORT  put {rec["short_put"]:.0f} / call {rec["short_call"]:.0f}   (±{OTM_PCT*100:.1f}%)')
            print(f'      LONG   put {rec["long_put"]:.0f} / call {rec["long_call"]:.0f}   (±{WING_PCT*100:.0f}% крылья = кэп хвоста)')
        print('  ⚠ honest Sharpe ~0.97 (реальный тайминг lag+buffer); крылья кэпят ruin (MC: P>50%DD 3.5%→0%).')
        print('    Филлы не проверены paper — деплой малым размером.')
    else:
        why = f'GEX недостаточно long-gamma (gex_z {gex_z:+.2f} < {GEX_MARGIN:g} буфер)' if not gex_ok else ''
        why += (' + ' if why and not macro_ok else '') + ('VIX backwardation (кризис)' if not macro_ok else '')
        print(f'  ▣ FLAT — вне рынка.  Причина: {why}')
    print('='*64 + '\n')

    # 6) аудит-лог (тот же сигнал, что пойдёт в исполнение)
    sig = dict(date=str(date), spot=round(spot, 1), atm_iv=round(iv, 4), vrp=round(float(row['vrp']), 4),
               gex_z=round(gex_z, 3), vix_term_slope=round(vix_term_slope, 3),
               gex_ok=gex_ok, macro_ok=macro_ok, gate=gate, ref_iv=args.ref_iv,
               sizer=round(sizer, 3), n_condors=n_cond,
               expiration=(rec['expiration'] if rec else ''),
               short_put=(rec['short_put'] if rec else np.nan), short_call=(rec['short_call'] if rec else np.nan),
               long_put=(rec['long_put'] if rec else np.nan), long_call=(rec['long_call'] if rec else np.nan))
    df = pd.DataFrame([sig])
    if os.path.exists(SIGNALS_LOG):
        old = pd.read_csv(SIGNALS_LOG)
        df = pd.concat([old[old['date'] != str(date)], df], ignore_index=True)
    df.to_csv(SIGNALS_LOG, index=False)
    log.info('Записано в %s', SIGNALS_LOG)


if __name__ == '__main__':
    main()
