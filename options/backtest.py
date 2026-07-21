"""
backtest.py — консолидированный point-in-time бэктест задеплоенного движка
              (1DTE SPX iron condor, GEX+macro gate, inverse-IV sizing).

ЧЕСТНАЯ МЕТОДОЛОГИЯ (та же логика, что live_signal.py → WF↔live):
  • Real marks (mid из цепочки), held-to-expiry (payoff = интринсик кондора на close T+1).
    НЕ variance-прокси (раздувал Sharpe ×2), НЕ daily-MtM (ловит vega-шум).
  • Всё POINT-IN-TIME / trailing, лукахеда нет — у стратегии НЕТ фитованных параметров,
    поэтому walk-forward тривиален (нет train/test split):
       gex_z   = rolling-GEX_WIN z-score        (скользящее, НЕ full-sample)
       gate    = gex_z>=0 AND vix_term_slope<=0 (фикс. пороги, pre-registered)
       size    = clip((REF_IV/atm_iv_30)^2,0,K) (inverse-IV, известна на входе)
       страйки = ±OTM_PCT short / ±WING_PCT long (константы)
  • НЕТ full-sample статов в РЕШЕНИИ. Капитал-масштаб = фиксированная константа LEVERAGE
    (Sharpe-инвариант; влияет только на абсолют maxDD/CAGR, НЕ на какие дни торговать).
    В прокси-версии было `L = TARGET_VOL/full_sample_std` — это убрано.
  • WARMUP: первые ~GEX_WIN дней без gex_z (нет окна) → .dropna() их естественно срезает,
    ровно как live (live_signal строит GEX_WIN-историю до выдачи сигнала).

Запуск:  python backtest.py            (фичи кэшируются → повторный прогон быстрый)
         python backtest.py --leverage 60 --ref-iv 0.16 --rebuild-features
Вывод:   метрики в консоль + backtest_results.png (4 панели: equity / underwater / годовые / распределение)
"""
import os, sys, argparse, importlib.util, logging
from dataclasses import dataclass, field
import numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('bt')
ANN = np.sqrt(252)


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

iopt = _load('intrinio_options', f'{ROOT}/intrinio_options.py')
# intermarket_lab lives in the sibling indices/ track (shared macro/vol-credit engine)
il   = _load('intermarket_lab',  f'{ROOT}/../indices/core/intermarket_lab.py')


@dataclass
class Config:
    symbol:   tuple = ('SPX', 'SPXW')
    otm_pct:  float = 0.012      # short strangle: страйки ±1.2%
    wing_pct: float = 0.05       # long крылья ±5% (кэп хвоста)
    ref_iv:   float = 0.13       # риск-диал (Sharpe-инвариант)
    gex_win:  int   = 60         # окно z-score GEX (= warmup-период)
    k_max:    float = 3.0        # потолок inverse-IV сайзера
    leverage: float = 1.0        # КАПИТАЛ-ДИАЛ: фикс. константа, Sharpe-инвариант (НЕ full-sample fit)
    signal_lag: int = 1          # ЛАГ GEX/macro-гейта (дни). 1 = РЕАЛИСТИЧНО: OI публикуется T+1 утром →
                                 #   на close T доступен только T-1 gex_z. 0 = идеализированный (нереализуем).
                                 #   IV/spot/марки НЕ лагаются (наблюдаемы вживую на close T).
    use_onset: bool  = False     # 2-й forward-гейт ONSET (ОПЦИЯ, default OFF = чистая база боевой дефолт).
    onset_chg5: float = 0.0      #   skip когда vix_chg5(T)>onset_chg5 И vix_z(T)<onset_vz (vola растёт с низкой
    onset_vz:  float = 0.0       #   базы = зарождение движения). VIX вживую на close T → не лагается.
                                 #   OOS-WF 0.97→1.25, режет 10/15 тейлов. НО: найден из анализа тех же тейлов →
                                 #   residual hindsight; стакать дальше нельзя (vol-energy 3-й фильтр дал 3.20 OOS,
                                 #   но active=14%+worst=0 = overfit-accretion мираж — НЕ добавлен). Честное
                                 #   forward-ожидание = база ~0.97; onset ~1.0 «возможно». Paper = истинный тест.
    gex_margin: float = 0.5      # CONFIDENCE-BUFFER: торгуем только gex_z(T-lag) >= margin (не просто >=0).
                                 #   Лаг убивает голый сигнал (Sharpe 1.04→0.31), т.к. flip-дни у gex_z≈0
                                 #   торгуются неверно. Буфер требует РОБАСТНО long-gamma → отсеивает flip-prone
                                 #   маргинальные дни. T-1-only (чистый PIT). OOS-WF margin: Sharpe→1.53;
                                 #   фикс 0.5 (pre-reg, консерв.) → 0.98. Выше=больше Sharpe/меньше экспозиция/overfit-риск.
    target_dte: int = 1
    fred_key: str   = 'YOUR_FRED_API_KEY'   # бесплатный FRED, не секрет


# ─────────────────────────────────────────────────────────────
# Фичи (point-in-time): spot, atm_iv_30, gex_z(rolling), vix_term_slope, vrp
# ─────────────────────────────────────────────────────────────
def build_features(cfg, rebuild=False):
    cache = f'{ROOT}/cache/bt_features_{"_".join(cfg.symbol)}.parquet'
    if os.path.exists(cache) and not rebuild:
        log.info('Фичи из кэша %s', os.path.basename(cache))
        return pd.read_parquet(cache)
    log.info('Строю фичи (daily_features recompute ~90с) ...')
    of = iopt.daily_features(list(cfg.symbol), None, recompute=True)
    of['rv_21'] = iopt.realized_vol(of['spot'], 21)
    of['vrp']   = of['atm_iv_30'] - of['rv_21']
    # gex_z — СКОЛЬЗЯЩЕЕ окно (НЕ full-sample): использует только прошлое
    of['gex_z'] = (of['gex'] - of['gex'].rolling(cfg.gex_win).mean()) / of['gex'].rolling(cfg.gex_win).std()
    try:
        vc = il.vol_credit_features('2010-01-01', str(of.index.max().date()), cfg.fred_key)
        of = of.join(vc[['vix_term_slope']], how='left')
        of['vix_term_slope'] = of['vix_term_slope'].ffill()
    except Exception as e:
        log.warning('FRED недоступен (%s) → vix_term_slope=-1 (macro_safe всегда)', e)
        of['vix_term_slope'] = -1.0
    keep = of[['spot', 'atm_iv_30', 'vrp', 'gex_z', 'vix_term_slope']].copy()
    keep.to_parquet(cache)
    return keep


# ─────────────────────────────────────────────────────────────
# P&L iron condor (real marks, held-to-expiry) — per day, гейтинг применяется позже
# ─────────────────────────────────────────────────────────────
def condor_pnl(cfg, spot_by_day):
    ch = iopt.load_cached(list(cfg.symbol))
    if ch.empty:
        raise RuntimeError('Нет цепочек в кэше')
    ch['qd']  = pd.to_datetime(ch['quote_date']).dt.normalize()
    ch['exp'] = pd.to_datetime(ch['expiration']).dt.normalize()
    # НЕ фильтруем по mark — иначе дешёвые крылья (±5% 1DTE ≈ 0) пропадут → кэп ломается.
    ch = ch[ch['dte'] == cfg.target_dte].dropna(subset=['strike', 'type', 'bid', 'ask'])

    def pick(df, target):
        r = df.iloc[(df['strike'] - target).abs().argsort().iloc[0]]
        return float(r['mark']), float(r['strike']), float(max(r['ask'] - r['bid'], 0))

    rows = []
    for qd, g in ch.groupby('qd'):
        if qd not in spot_by_day.index:
            continue
        S = spot_by_day[qd]
        exp = g['exp'].iloc[0]
        # spot на экспирации (PM-settle close T+1)
        if exp in spot_by_day.index:
            Se = spot_by_day[exp]
        else:
            prior = spot_by_day.index[spot_by_day.index <= exp]
            Se = spot_by_day[prior[-1]] if len(prior) else np.nan
        if not np.isfinite(Se):
            continue
        ca, pu = g[g['type'] == 'call'], g[g['type'] == 'put']
        # SHORT-ноги: ликвидные (mark>0.05), на нужной стороне от спота
        sc_c = ca[(ca['strike'] >= S) & (ca['mark'] > 0.05)]
        sp_c = pu[(pu['strike'] <= S) & (pu['mark'] > 0.05)]
        if sc_c.empty or sp_c.empty:
            continue
        scm, sck, scs = pick(sc_c, S * (1 + cfg.otm_pct))   # short call
        spm, spk, sps = pick(sp_c, S * (1 - cfg.otm_pct))   # short put
        # LONG-крылья: СТРОГО за шорт-страйком (гарантирует кэп), ближайшее к ±WING% (любой mark)
        lc_c = ca[ca['strike'] > sck]
        lp_c = pu[pu['strike'] < spk]
        if lc_c.empty or lp_c.empty:
            continue                                        # нет крыла за шортом → пропуск (нельзя кэпнуть)
        lcm, lck, lcs = pick(lc_c, S * (1 + cfg.wing_pct))  # long call (крыло)
        lpm, lpk, lps = pick(lp_c, S * (1 - cfg.wing_pct))  # long put (крыло)
        net_prem = (scm + spm) - (lcm + lpm)             # собрали short − заплатили long
        short_pay = max(Se - sck, 0) + max(spk - Se, 0)
        long_pay  = max(Se - lck, 0) + max(lpk - Se, 0)
        payoff = short_pay - long_pay                    # капнутый payoff кондора
        spread_sum = scs + sps + lcs + lps               # bid-ask всех 4 ног
        rows.append({'date': qd,
                     'pnl_ret':  (net_prem - payoff) / S,   # return-on-spot-notional
                     'cost_ret': 0.5 * spread_sum / S})     # ½ спреда × 4 ноги (вход; экспирация без слипа)
    return pd.DataFrame(rows).set_index('date')


# ─────────────────────────────────────────────────────────────
# Сборка стратегии (гейт + сайзинг, point-in-time)
# ─────────────────────────────────────────────────────────────
def run(cfg, rebuild=False):
    feat = build_features(cfg, rebuild)
    cp = condor_pnl(cfg, feat['spot'])
    df = feat.join(cp, how='inner').sort_index()
    # 2-й forward-гейт ONSET: VIX наблюдаем вживую на close T → НЕ лагается (в отличие от OI-based gex_z)
    vix = pd.read_parquet(f'{ROOT}/cache/vix_daily.parquet')['vix_close']; vix.index = pd.to_datetime(vix.index)
    vv = vix.reindex(pd.date_range(vix.index.min(), vix.index.max())).ffill()
    df['vix_chg5'] = (vv / vv.shift(5) - 1).reindex(df.index)
    df['vix_z']    = ((vv - vv.rolling(60).mean()) / vv.rolling(60).std()).reindex(df.index)
    onset = (((df['vix_chg5'] > cfg.onset_chg5) & (df['vix_z'] < cfg.onset_vz)).fillna(False)
             if cfg.use_onset else pd.Series(False, index=df.index))
    # ГЕЙТ по ЛАГНУТОМУ GEX/macro (signal_lag дней) — OI публикуется поздно, на close T доступен T-lag.
    gz = df['gex_z'].shift(cfg.signal_lag); vts = df['vix_term_slope'].shift(cfg.signal_lag)
    df['gate'] = ((gz >= cfg.gex_margin) & (vts <= 0) & ~onset).fillna(False)   # buffer-GEX(lag) AND NOT onset
    # сайзинг по ТЕКУЩЕЙ IV (наблюдаема вживую на close T, не лагается)
    df['size'] = np.clip((cfg.ref_iv / df['atm_iv_30'].clip(lower=0.05)) ** 2, 0, cfg.k_max)
    df['pos']  = np.where(df['gate'], df['size'], 0.0)
    df['ret']  = cfg.leverage * df['pos'] * (df['pnl_ret'] - df['cost_ret'])
    df = df.dropna(subset=['ret', 'gex_z'])   # warmup (первые GEX_WIN дней без gex_z) срезается тут
    return df


# ─────────────────────────────────────────────────────────────
# Метрики
# ─────────────────────────────────────────────────────────────
def metrics(df):
    r = df['ret']
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    dn = np.sqrt((np.minimum(r, 0) ** 2).mean())
    mdd = dd.min()
    active = df['pos'] > 0
    out = dict(
        n_days=len(r), n_trades=int(active.sum()), active_pct=round(active.mean() * 100, 0),
        Sharpe=round(r.mean() / r.std() * ANN, 2) if r.std() > 0 else 0,
        Sortino=round(r.mean() / dn * ANN, 2) if dn > 0 else 0,
        CAGR=f'{((eq.iloc[-1]) ** (252 / len(r)) - 1) * 100:.1f}%',
        annVol=f'{r.std() * ANN * 100:.1f}%',
        maxDD=f'{mdd * 100:.1f}%',
        Calmar=round((r.mean() * 252) / abs(mdd), 2) if mdd < 0 else np.nan,
        worst_day=f'{r.min() * 100:.2f}%',
        win_pct=f'{(r[active] > 0).mean() * 100:.0f}%',
    )
    yr = {int(y): round(g.mean() / g.std() * ANN, 2) for y, g in r.groupby(r.index.year) if len(g) > 40}
    return out, yr, eq, dd


# ─────────────────────────────────────────────────────────────
# Визуализация
# ─────────────────────────────────────────────────────────────
def plot(df, eq, dd, m, yr, cfg, path):
    r = df['ret']
    fig, ax = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle(f'1DTE SPX iron condor ±{cfg.otm_pct*100:.1f}%/±{cfg.wing_pct*100:.0f}% · GEX+macro gate · inverse-IV · '
                 f'Sharpe {m["Sharpe"]}  CAGR {m["CAGR"]}  maxDD {m["maxDD"]}  (LEVERAGE={cfg.leverage:g})',
                 fontsize=12, weight='bold')
    # 1. equity curve
    ax[0, 0].plot(eq.index, eq.values, color='navy', lw=1.5)
    ax[0, 0].axhline(1, color='k', lw=0.5, ls='--')
    ax[0, 0].set_title('Equity curve (cumulative return)'); ax[0, 0].set_ylabel('equity (×)'); ax[0, 0].grid(alpha=0.3)
    # 2. underwater (drawdown)
    ax[0, 1].fill_between(dd.index, dd.values * 100, 0, color='crimson', alpha=0.5)
    ax[0, 1].set_title(f'Underwater (drawdown), maxDD {m["maxDD"]}'); ax[0, 1].set_ylabel('DD %'); ax[0, 1].grid(alpha=0.3)
    # 3. годовые Sharpe (режимность)
    ys = pd.Series(yr); colors = ['seagreen' if v > 0 else 'crimson' for v in ys.values]
    ax[1, 0].bar([str(y) for y in ys.index], ys.values, color=colors, alpha=0.8)
    ax[1, 0].axhline(0, color='k', lw=0.5); ax[1, 0].set_title('Годовой Sharpe (режимность видна)'); ax[1, 0].grid(alpha=0.3, axis='y')
    # 4. распределение дневной доходности (только торговые дни)
    rt = r[df['pos'] > 0] * 100
    ax[1, 1].hist(rt, bins=60, color='steelblue', alpha=0.7)
    ax[1, 1].axvline(0, color='k', lw=0.5, ls='--')
    ax[1, 1].axvline(rt.mean(), color='navy', lw=1.5, label=f'mean {rt.mean():+.3f}%')
    ax[1, 1].axvline(rt.min(), color='crimson', lw=1.5, label=f'worst {rt.min():.2f}%')
    ax[1, 1].set_yscale('log'); ax[1, 1].set_title('Распределение дневной P&L (log-y, торговые дни)')
    ax[1, 1].set_xlabel('daily return %'); ax[1, 1].legend()
    plt.tight_layout(); plt.savefig(path, dpi=110, bbox_inches='tight'); plt.close()
    log.info('Сохранён график → %s', path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref-iv', type=float, default=0.13)
    ap.add_argument('--leverage', type=float, default=1.0)
    ap.add_argument('--otm', type=float, default=0.012)
    ap.add_argument('--wing', type=float, default=0.05)
    ap.add_argument('--signal-lag', type=int, default=1)
    ap.add_argument('--gex-margin', type=float, default=0.5)
    ap.add_argument('--rebuild-features', action='store_true')
    a = ap.parse_args()
    cfg = Config(ref_iv=a.ref_iv, leverage=a.leverage, otm_pct=a.otm, wing_pct=a.wing,
                 signal_lag=a.signal_lag, gex_margin=a.gex_margin)
    df = run(cfg, rebuild=a.rebuild_features)
    m, yr, eq, dd = metrics(df)
    log.info('БЭКТЕСТ %s  %s..%s', '/'.join(cfg.symbol), df.index.min().date(), df.index.max().date())
    print('\n' + '─' * 60)
    for k, v in m.items():
        print(f'  {k:12s}: {v}')
    print(f'  годовой Sharpe: {yr}')
    print('─' * 60 + '\n')
    plot(df, eq, dd, m, yr, cfg, f'{ROOT}/backtest_results.png')


if __name__ == '__main__':
    main()
