"""Frozen monthly-filter, weekly-pullback Ichimoku backtest, no parameter search.

Run: python ichimoku_verified.py
Inputs: frozen_design.json and saved data/*_yahoo_raw.json.
Fresh data are fetched separately by fetch_data.py; the engine never downloads.
Dependencies: Python 3.12, pandas, numpy. USD, long-only, fractional shares.
"""
from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / 'frozen_design.json').read_text())
START = pd.Timestamp(CONFIG['start'])
END = pd.Timestamp(CONFIG['end'])
START_TIME = START.tz_localize('America/New_York') + pd.Timedelta(hours=9, minutes=30)
END_TIME = END.tz_localize('America/New_York') + pd.Timedelta(hours=16)
YEARS = (END_TIME - START_TIME).total_seconds() / (365.25 * 86400)

def load(ticker):
    raw = json.loads((ROOT / 'data' / f'{ticker}_yahoo_raw.json').read_text())['chart']['result'][0]
    q = raw['indicators']['quote'][0]
    dates = pd.to_datetime(raw['timestamp'], unit='s', utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
    df = pd.DataFrame({k.title(): q[k] for k in ['open', 'high', 'low', 'close', 'volume']}, index=dates)
    df.index.name = 'date'
    df['AdjClose'] = raw['indicators']['adjclose'][0]['adjclose']
    assert df.index.is_unique and df.index.is_monotonic_increasing
    assert df[['Open','High','Low','Close','AdjClose']].notna().all().all()
    assert (df[['Open','High','Low','Close','AdjClose']] > 0).all().all()
    assert (df.High >= df[['Open','Close','Low']].max(axis=1) - 1e-5).all()
    assert (df.Low <= df[['Open','Close','High']].min(axis=1) + 1e-5).all()
    assert df.index[-1] == END and START in df.index
    df['AdjustmentFactor'] = df.AdjClose / df.Close
    for k in ['Open','High','Low','Close']:
        df[f'Raw{k}'] = df[k]  # Yahoo quote OHLC already reflects stock splits.
        df[k] *= df.AdjustmentFactor
    return df, raw

def bars(df, frequency, cutoff=END):
    """Only closed calendar periods. Store actual final trading date separately.

    All history ends at cutoff. Excluding any period with a later calendar end
    removes Oct 2026 and the Oct 16 weekly bar from the frozen Oct 12 run.
    A holiday-shortened completed week is available at its last trading close.
    """
    rows = []
    for period, group in df.loc[:cutoff].groupby(df.loc[:cutoff].index.to_period(frequency)):
        if period.end_time.normalize() > cutoff:
            continue
        rows.append({'period_end':period.end_time.normalize(), 'available_date':group.index[-1],
                     'Open':group.Open.iloc[0], 'High':group.High.max(),
                     'Low':group.Low.min(), 'Close':group.Close.iloc[-1]})
    return pd.DataFrame(rows).set_index('period_end')

def ichi(b):
    high, low = b.High, b.Low
    tenkan = (high.rolling(9, min_periods=9).max() + low.rolling(9, min_periods=9).min()) / 2
    kijun = (high.rolling(26, min_periods=26).max() + low.rolling(26, min_periods=26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((high.rolling(52, min_periods=52).max() + low.rolling(52, min_periods=52).min()) / 2).shift(26)
    cloud = pd.concat([span_a,span_b],axis=1)
    return pd.DataFrame({'tenkan':tenkan,'kijun':kijun,'span_a':span_a,'span_b':span_b,
                         'top':cloud.max(axis=1,skipna=False),'bottom':cloud.min(axis=1,skipna=False)})

def signals(df, cutoff=END):
    w, m = bars(df,'W-FRI',cutoff), bars(df,'M',cutoff)
    w, m = w.join(ichi(w)), m.join(ichi(m))
    w['prior_tested'] = (w.Low.shift(1) <= w.kijun.shift(1) * 1.02)
    w['prior_close_near'] = w.Close.shift(1) <= w.kijun.shift(1) * 1.02
    w['entry'] = (w.Close > w.top) & (w.Close > w.kijun) & w.prior_tested & w.prior_close_near
    m['eligible'] = (m.Close > m.top) & (m.Close > m.kijun) & (m.kijun >= m.kijun.shift(1))
    m['exit'] = m.Close < m.bottom
    s = pd.DataFrame(index=df.loc[:cutoff].index)
    s['weekly_entry'] = False
    s['monthly_exit'] = False
    s['monthly_eligible'] = np.nan
    s['monthly_period'] = pd.Series(pd.NaT,index=s.index,dtype='datetime64[ns]')
    s['weekly_period'] = pd.Series(pd.NaT,index=s.index,dtype='datetime64[ns]')
    for period,row in w.iterrows():
        s.loc[row.available_date,'weekly_entry'] = bool(row.entry)
        s.loc[row.available_date,'weekly_period'] = period
    for period,row in m.iterrows():
        s.loc[row.available_date,'monthly_eligible'] = float(row.eligible)
        s.loc[row.available_date,'monthly_exit'] = bool(row.exit)
        s.loc[row.available_date,'monthly_period'] = period
    s['monthly_eligible'] = s.monthly_eligible.ffill().fillna(0).astype(bool)
    s['monthly_period'] = s.monthly_period.ffill()
    return s,w,m

def simulate(ticker,df,s,fee_bps,mode='ichimoku'):
    fee = fee_bps/10000
    cash = float(CONFIG['initial_per_ticker'])
    shares = 0.0
    nav,transactions,holdings = [],[],[]
    open_lot = None
    dates = df.index[(df.index>=START)&(df.index<=END)]
    for date in dates:
        prev = df.index[df.index.get_loc(date)-1]
        sig = s.loc[prev]
        side = None
        if mode == 'buy_hold':
            if date == dates[0]: side='buy'
        elif shares > 0 and sig.monthly_exit:
            side='sell'
        elif shares == 0 and sig.weekly_entry and sig.monthly_eligible:
            side='buy'
        op = float(df.loc[date,'Open'])
        execution_time = date.tz_localize('America/New_York') + pd.Timedelta(hours=9,minutes=30)
        if side:
            prior_cash = cash
            if side=='buy':
                shares = cash/(op*(1+fee))
                cost = shares*op*fee
                notional = shares*op
                cash=0.0
                open_lot={'ticker':ticker,'mode':mode,'fee_bps':fee_bps,'entry_date':str(date.date()),'entry_time':execution_time.isoformat(),'entry_capital':prior_cash,'entry_adjusted_price':op,'shares_adjusted_units':shares}
            else:
                notional = shares*op
                cost = notional*fee
                cash = notional-cost
                lot=dict(open_lot)
                lot.update(exit_date=str(date.date()),exit_time=execution_time.isoformat(),status='closed',ending_value=cash,holding_calendar_days=(execution_time-pd.Timestamp(lot['entry_time'])).total_seconds()/86400,net_return_pct=100*(cash/lot['entry_capital']-1))
                holdings.append(lot)
                shares=0.0
                open_lot=None
            transactions.append({'ticker':ticker,'mode':mode,'fee_bps':fee_bps,'execution_date':str(date.date()),'execution_time':execution_time.isoformat(),'side':side,'signal_date':str(prev.date()) if mode=='ichimoku' else None,'monthly_period':str(sig.monthly_period.date()) if pd.notna(sig.monthly_period) and mode=='ichimoku' else None,'weekly_period':str(sig.weekly_period.date()) if pd.notna(sig.weekly_period) and mode=='ichimoku' else None,'adjusted_open':op,'raw_split_adjusted_open':float(df.loc[date,'RawOpen']),'notional':notional,'cost':cost,'cash_after':cash,'shares_adjusted_units_after':shares})
        invested_value = shares*float(df.loc[date,'Close'])
        nav.append({'date':date,'ticker':ticker,'mode':mode,'fee_bps':fee_bps,'nav':cash+invested_value,'cash':cash,'invested_value':invested_value,'invested':int(shares>0)})
    if open_lot:
        lot=dict(open_lot)
        ending_value=nav[-1]['nav']
        lot.update(exit_date=None,exit_time=None,status='open',ending_value=ending_value,holding_calendar_days=(END_TIME-pd.Timestamp(lot['entry_time'])).total_seconds()/86400,net_return_pct=100*(ending_value/lot['entry_capital']-1))
        holdings.append(lot)
    return pd.DataFrame(nav),pd.DataFrame(transactions),pd.DataFrame(holdings)

def statistics(ticker,mode,fee_bps,nav,tx,holdings,initial):
    values = nav.nav.to_numpy(dtype=float)
    anchored = np.r_[initial,values]
    drawdowns = anchored/np.maximum.accumulate(anchored)-1
    days = holdings.holding_calendar_days if len(holdings) else pd.Series(dtype=float)
    closed = holdings.loc[holdings.status=='closed','holding_calendar_days'] if len(holdings) else pd.Series(dtype=float)
    return {'ticker':ticker,'mode':mode,'fee_bps_per_side':int(fee_bps),'initial_value':initial,'final_value':float(values[-1]),'total_return_pct':float((values[-1]/initial-1)*100),'cagr_pct':float(((values[-1]/initial)**(1/YEARS)-1)*100),'max_drawdown_pct':float(drawdowns.min()*100),'entries':int((tx.side=='buy').sum()) if len(tx) else 0,'exits':int((tx.side=='sell').sum()) if len(tx) else 0,'transactions':len(tx),'completed_round_trips':len(closed),'open_positions':int((holdings.status=='open').sum()) if len(holdings) else 0,'time_invested_sleeve_days_pct':float(nav.invested.mean()*100),'mean_daily_capital_exposure_pct':float((nav.invested_value/nav.nav).mean()*100),'median_holding_calendar_days_all':float(days.median()) if len(days) else None,'mean_holding_calendar_days_all':float(days.mean()) if len(days) else None,'median_completed_holding_calendar_days':float(closed.median()) if len(closed) else None,'min_holding_calendar_days':float(days.min()) if len(days) else None,'max_holding_calendar_days':float(days.max()) if len(days) else None,'total_transaction_costs':float(tx.cost.sum()) if len(tx) else 0}

def main():
    out=ROOT/'output';out.mkdir(exist_ok=True)
    allnav,alltx,allhold,results,diagnostics=[],[],[],[],[]
    common=None
    for ticker in CONFIG['tickers']:
        df,raw=load(ticker)
        if common is None: common=df.index
        else: assert common.equals(df.index), 'Mismatched session dates'
        df.to_csv(ROOT/'data'/f'{ticker}_adjusted_daily.csv',float_format='%.12g')
        s,w,m=signals(df)
        s.to_csv(out/f'{ticker}_daily_signals.csv')
        w.to_csv(out/f'{ticker}_weekly_indicators.csv',float_format='%.12g')
        m.to_csv(out/f'{ticker}_monthly_indicators.csv',float_format='%.12g')
        diagnostics.append({'ticker':ticker,'rows':len(df),'test_rows':int(((df.index>=START)&(df.index<=END)).sum()),'first_valid_monthly_cloud':str(m.top.first_valid_index().date()),'last_completed_week':str(w.index[-1].date()),'last_completed_month':str(m.index[-1].date()),'start_adjusted_open':df.loc[START,'Open'],'end_adjusted_close':df.loc[END,'Close'],'start_raw_open':df.loc[START,'RawOpen'],'end_raw_close':df.loc[END,'RawClose']})
        for fee in CONFIG['fee_cases_bps_per_side']:
            for mode in ['ichimoku','buy_hold']:
                nav,tx,h=simulate(ticker,df,s,fee,mode)
                results.append(statistics(ticker,mode,fee,nav,tx,h,CONFIG['initial_per_ticker']))
                allnav.append(nav);alltx.append(tx);allhold.append(h)
    nav=pd.concat(allnav,ignore_index=True)
    tx=pd.concat(alltx,ignore_index=True)
    hold=pd.concat(allhold,ignore_index=True)
    portfolio=[]
    for (mode,fee),rows in nav.groupby(['mode','fee_bps']):
        p=rows.groupby('date')[['nav','cash','invested_value']].sum()
        p['invested']=rows.groupby('date').invested.mean()
        p=p.reset_index();p['ticker']='PORTFOLIO';p['mode']=mode;p['fee_bps']=fee
        t=tx[(tx['mode']==mode)&(tx.fee_bps==fee)]
        h=hold[(hold['mode']==mode)&(hold.fee_bps==fee)]
        results.append(statistics('PORTFOLIO',mode,fee,p,t,h,CONFIG['initial_capital']))
        portfolio.append(p)
    summary=pd.DataFrame(results)
    summary.to_csv(out/'summary.csv',index=False,float_format='%.10g')
    nav=pd.concat([nav,*portfolio],ignore_index=True)
    nav.to_csv(out/'daily_equity.csv',index=False,float_format='%.12g')
    tx.to_csv(out/'transactions.csv',index=False,float_format='%.12g')
    hold.to_csv(out/'holding_periods.csv',index=False,float_format='%.12g')
    (out/'results.json').write_text(json.dumps({'configuration':CONFIG,'elapsed_years':YEARS,'diagnostics':diagnostics,'results':results},indent=2,allow_nan=False)+'\n')
    print(summary[['ticker','mode','fee_bps_per_side','final_value','cagr_pct','max_drawdown_pct','entries','exits','time_invested_sleeve_days_pct']].to_string(index=False))

if __name__=='__main__':
    main()
