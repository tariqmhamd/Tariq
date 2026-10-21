"""Pure signal and accounting functions; no network access or global config."""
import numpy as np
import pandas as pd


def validate(df):
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is not None:
        raise ValueError('Use timezone-naive daily session dates')
    if df.empty or not df.index.is_unique or not df.index.is_monotonic_increasing:
        raise ValueError('History must be nonempty, sorted and unique')
    p = df[['Open', 'High', 'Low', 'Close']]
    if not np.isfinite(p.to_numpy()).all() or (p <= 0).any().any():
        raise ValueError('OHLC must be finite and positive')
    if (p.High < p.max(axis=1) - 1e-6).any() or (p.Low > p.min(axis=1) + 1e-6).any():
        raise ValueError('Inconsistent OHLC')


def bars(df, frequency):
    # Period label is a calendar boundary, NOT an execution timestamp.
    return df.groupby(df.index.to_period(frequency)).agg(
        Open=('Open', 'first'), High=('High', 'max'), Low=('Low', 'min'),
        Close=('Close', 'last')).set_axis(
            df.index.to_period(frequency).unique().end_time.normalize())


def indicators(b, c):
    def midpoint(n):
        return (b.High.rolling(n, min_periods=n).max() +
                b.Low.rolling(n, min_periods=n).min()) / 2
    ten, kij = midpoint(c['tenkan']), midpoint(c['kijun'])
    a = ((ten + kij) / 2).shift(c['displacement'])
    z = midpoint(c['span_b']).shift(c['displacement'])
    cloud = pd.concat([a, z], axis=1)
    return b.assign(tenkan=ten, kijun=kij, span_a=a, span_b=z,
                    top=cloud.max(axis=1, skipna=False),
                    bottom=cloud.min(axis=1, skipna=False))


def orders(df, c):
    """Schedule only after calendar period ends, at a strictly later session open.

    This works at holiday/weekend boundaries without inferring that a partial
    terminal bar is complete. No negative shifts or backfilled indicator values.
    """
    w, m = [indicators(bars(df, f), c) for f in ('W-FRI', 'M')]
    tol = 1 + c['pullback_tolerance']
    m['eligible'] = (m.Close > m.top) & (m.Close > m.kijun) & (m.kijun >= m.kijun.shift(1))
    m['exit'] = m.Close < m.bottom
    w['entry'] = ((w.Close > w.top) & (w.Close > w.kijun) &
                  (w.Low.shift(1) <= w.kijun.shift(1)*tol) &
                  (w.Close.shift(1) <= w.kijun.shift(1)*tol))
    w['exit'] = False
    mode = c['strategy']
    if mode == 'weekly_cross':
        m['eligible'] = m.Close > m.top
        w['entry'] = (w.tenkan > w.kijun) & (w.tenkan.shift(1) <= w.kijun.shift(1))
        w['exit'] = (w.tenkan < w.kijun) & (w.tenkan.shift(1) >= w.kijun.shift(1))
        m['exit'] = False
    elif mode in ('monthly', 'monthly_green'):
        m['eligible'] = (m.Close > m.top) & (m.Close > m.kijun)
        if mode == 'monthly_green':
            m['eligible'] &= m.Close > m.Open
        m['exit'] = m.Close < m.kijun
    elif mode != 'weekly_pullback':
        raise ValueError('Unknown strategy: ' + mode)
    s = pd.DataFrame(index=df.index, data={'entry': False, 'exit': False,
        'eligible': np.nan, 'monthly_period': pd.NaT, 'weekly_period': pd.NaT,
        'signal_date': pd.NaT})
    for boundary, row in m.iterrows():
        j = df.index.searchsorted(boundary, side='right')
        if j == len(df):
            continue
        date = df.index[j]
        s.loc[date, ['eligible', 'exit', 'monthly_period']] = [float(row.eligible), bool(row.exit), boundary]
        if mode.startswith('monthly'):
            s.loc[date, ['entry', 'signal_date']] = [bool(row.eligible), df.index[j-1]]
    s['eligible'] = s.eligible.ffill().fillna(0).astype(bool)
    s['monthly_period'] = s.monthly_period.ffill()
    if not mode.startswith('monthly'):
        for boundary, row in w.iterrows():
            j = df.index.searchsorted(boundary, side='right')
            if j == len(df):
                continue
            date = df.index[j]
            s.loc[date, ['entry', 'weekly_period', 'signal_date']] = [bool(row.entry), boundary, df.index[j-1]]
            s.loc[date, 'exit'] = bool(s.loc[date, 'exit']) or bool(row.exit)
    # Exit may be monthly on a date without a weekly event.
    for date in s.index[s['exit']]:
        s.loc[date, 'signal_date'] = df.index[df.index.get_loc(date)-1]
    return s, w, m


def simulate(df, s, start, end, capital, fee_bps, hold=False):
    dates = df.loc[start:end].index
    if len(dates) < 2:
        raise ValueError('Need at least two test sessions')
    cash, units, fee = float(capital), 0., fee_bps / 10000
    values, tx = [], []
    for d in dates:
        r = s.loc[d]
        side = None
        if hold:
            if d == dates[0]:
                side = 'buy'
        elif units and r['exit']:
            side = 'sell'
        elif not units and r.entry and r.eligible:
            side = 'buy'
        if side:
            before = cash
            price = float(df.loc[d, 'Open'])
            if side == 'buy':
                quantity = cash / (price * (1+fee))
                notional = quantity * price
                units, cash = quantity, 0.
            else:
                quantity = units
                notional = quantity * price
                cash, units = notional * (1-fee), 0.
            signal = None if hold else r.signal_date
            if not hold and (pd.isna(signal) or signal >= d):
                raise ValueError('Signal must precede execution')
            tx.append(dict(date=d, side=side, signal_date=signal,
                monthly_period=None if hold else r.monthly_period,
                weekly_period=None if hold else r.weekly_period,
                price=price, quantity=quantity, notional=notional,
                fee=notional*fee, cash_before=before, cash_after=cash,
                units_after=units, reason='initial_buy' if hold else ('exit_rule' if side=='sell' else 'entry_rule')))
        values.append(dict(date=d, nav=cash+units*df.loc[d, 'Close'], cash=cash, units=units))
    columns = ['date','side','signal_date','monthly_period','weekly_period','price',
               'quantity','notional','fee','cash_before','cash_after','units_after','reason']
    return pd.DataFrame(values).set_index('date'), pd.DataFrame(tx, columns=columns)


def metrics(nav, tx, capital):
    a = np.r_[capital, nav.nav.to_numpy()]
    start = nav.index[0].tz_localize('America/New_York') + pd.Timedelta(hours=9, minutes=30)
    end = nav.index[-1].tz_localize('America/New_York') + pd.Timedelta(hours=16)
    years = (end-start).total_seconds()/(365.25*86400)
    return dict(final_value=a[-1], total_return_pct=(a[-1]/capital-1)*100,
        cagr_pct=((a[-1]/capital)**(1/years)-1)*100,
        max_drawdown_pct=(a/np.maximum.accumulate(a)-1).min()*100,
        transactions=len(tx), buys=int((tx.side=='buy').sum()),
        sells=int((tx.side=='sell').sum()), fees=float(tx.fee.sum()))
