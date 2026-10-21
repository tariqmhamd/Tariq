"""python -m ichimoku {download,run} --help"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from .core import validate, orders, simulate, metrics


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, mode):
    d = pd.read_csv(path, parse_dates=['Date']).set_index('Date')
    validate(d)
    if mode == 'adjusted':
        if 'AdjClose' not in d or d.AdjClose.isna().any() or (d.AdjClose <= 0).any():
            raise ValueError('Adjusted mode requires positive AdjClose')
        factor = d.AdjClose / d.Close
        d[['Open','High','Low','Close']] = d[['Open','High','Low','Close']].mul(factor, axis=0)
    elif mode != 'price_only':
        raise ValueError('price_mode must be adjusted or price_only')
    validate(d)
    return d


def download(c, dest):
    import yfinance as yf
    dest.mkdir(parents=True, exist_ok=True)
    for symbol in c['tickers']:
        d = yf.download(symbol, start=c['warmup_start'],
            end=str((pd.Timestamp(c['end'])+pd.Timedelta(days=1)).date()),
            auto_adjust=False, actions=True, progress=False, threads=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        if d.empty:
            raise ValueError('No download for '+symbol)
        d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
        d.index.name = 'Date'
        d = d.rename(columns={'Adj Close':'AdjClose'})
        validate(d)
        path = dest / (symbol+'.csv')
        d.to_csv(path, float_format='%.17g')
        (dest/(symbol+'.source.json')).write_text(json.dumps(dict(
            vendor='Yahoo Finance via yfinance', fetched_utc=datetime.now(timezone.utc).isoformat(),
            symbol=symbol, start=c['warmup_start'], end_inclusive=c['end'],
            auto_adjust=False, sha256=sha(path), yfinance=yf.__version__), indent=2))


def run(c, data, out):
    if out.exists() and any(out.iterdir()):
        raise ValueError('Output directory must be empty; preserve previous runs')
    out.mkdir(parents=True, exist_ok=True)
    frames = {t:load(data/(t+'.csv'),c['price_mode']).loc[:c['end']] for t in c['tickers']}
    common = None
    import exchange_calendars as xc
    calendar = xc.get_calendar('XNYS',
        start=pd.Timestamp(c['warmup_start'])-pd.Timedelta(days=10),
        end=pd.Timestamp(c['end'])+pd.Timedelta(days=10))
    expected = calendar.sessions_in_range(c['warmup_start'], c['end'])
    if expected.tz is not None:
        expected = expected.tz_localize(None)
    for t,d in frames.items():
        validate(d)
        if not d.index.equals(expected):
            missing = expected.difference(d.index)
            extra = d.index.difference(expected)
            raise ValueError(f'XNYS session coverage mismatch for {t}: missing={list(missing[:5])}, extra={list(extra[:5])}')
        if common is None:
            common = d.index
        elif not d.index.equals(common):
            raise ValueError('Mismatched session dates; do not forward-fill missing stock prices')
        if d.index[0] > pd.Timestamp(c['warmup_start']) + pd.Timedelta(days=7):
            raise ValueError('Insufficient configured warmup coverage: '+t)
        if len(d.loc[c['start']:c['end']]) < 2:
            raise ValueError('No test coverage: '+t)
    summaries, curves, transactions = [], [], []
    initial = c['capital']/len(c['tickers'])
    for t,d in frames.items():
        s,w,m = orders(d,c)
        # Require enough monthly warmup for both displaced cloud spans.
        if not m.loc[m.index < pd.Timestamp(c['start']), 'top'].notna().any():
            raise ValueError('Need at least span_b + displacement completed months before start')
        s.to_csv(out/(t+'_orders.csv'))
        w.to_csv(out/(t+'_weekly.csv')); m.to_csv(out/(t+'_monthly.csv'))
        for bps in c['fee_bps']:
            for mode in [c['strategy'], 'buy_hold']:
                nav,tx = simulate(d,s,c['start'],c['end'],initial,bps,mode=='buy_hold')
                summaries.append(dict(ticker=t, mode=mode, fee_bps=bps, **metrics(nav,tx,initial)))
                curves.append(nav.reset_index().assign(ticker=t,mode=mode,fee_bps=bps))
                transactions.append(tx.assign(ticker=t,mode=mode,fee_bps=bps))
    nav = pd.concat(curves,ignore_index=True)
    tx = pd.DataFrame([r for t in transactions for r in t.to_dict('records')],
                      columns=transactions[0].columns)
    for (mode,bps),group in nav.groupby(['mode','fee_bps']):
        p = group.groupby('date')[['nav','cash']].sum()
        t = tx[(tx['mode']==mode)&(tx.fee_bps==bps)]
        summaries.append(dict(ticker='PORTFOLIO',mode=mode,fee_bps=bps,**metrics(p,t,c['capital'])))
        curves.append(p.reset_index().assign(ticker='PORTFOLIO',mode=mode,fee_bps=bps))
    summary = pd.DataFrame(summaries)
    summary.to_csv(out/'summary.csv',index=False)
    pd.concat(curves,ignore_index=True).to_csv(out/'equity.csv',index=False)
    tx.to_csv(out/'transactions.csv',index=False)
    holdings=[]
    for (ticker,mode,bps),group in tx.groupby(['ticker','mode','fee_bps']):
        lot=None
        for r in group.itertuples():
            if r.side=='buy':
                lot=r
            elif lot is not None:
                holdings.append(dict(ticker=ticker,mode=mode,fee_bps=bps,entry=lot.date,
                    exit=r.date,status='closed',days=(r.date-lot.date).days,
                    return_pct=(r.cash_after/lot.cash_before-1)*100))
                lot=None
        if lot is not None:
            n=nav[(nav.ticker==ticker)&(nav['mode']==mode)&(nav.fee_bps==bps)].iloc[-1]
            holdings.append(dict(ticker=ticker,mode=mode,fee_bps=bps,entry=lot.date,
                exit=None,status='open',days=(n.date-lot.date).days,
                return_pct=(n.nav/lot.cash_before-1)*100))
    pd.DataFrame(holdings,columns=['ticker','mode','fee_bps','entry','exit','status','days','return_pct']).to_csv(out/'holdings.csv',index=False)
    versions={}
    for package in ['pandas','numpy','yfinance','exchange-calendars']:
        try:
            versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package]='not installed (offline run)'
    manifest=dict(config=c,python=platform.python_version(),versions=versions,
        created_utc=datetime.now(timezone.utc).isoformat(),
        inputs={t+'.csv':sha(data/(t+'.csv')) for t in c['tickers']},
        code={p.name:sha(p) for p in Path(__file__).parent.glob('*.py')},
        actual_start=str(nav.date.min()),actual_end=str(nav.date.max()),
        dividend_method='adjusted OHLC total-return proxy; no additional dividend cash' if c['price_mode']=='adjusted' else 'price only; dividends excluded',
        outputs={p.name:sha(p) for p in out.iterdir() if p.is_file()})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(summary[summary.ticker=='PORTFOLIO'].to_string(index=False))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['download','run'])
    p.add_argument('--config',default='configs/default.json')
    p.add_argument('--data',default='data')
    p.add_argument('--output',default='results/default')
    a=p.parse_args()
    c=json.loads(Path(a.config).read_text())
    if not c['tickers'] or len(set(c['tickers'])) != len(c['tickers']):
        p.error('tickers must be nonempty and unique')
    if c['capital']<=0 or any(x<0 for x in c['fee_bps']):
        p.error('capital must be positive and costs nonnegative')
    if any(not isinstance(c[k],int) or c[k]<1 for k in ['tenkan','kijun','span_b','displacement']):
        p.error('Indicator lengths must be positive integers')
    if pd.Timestamp(c['start']) >= pd.Timestamp(c['end']):
        p.error('start must precede end')
    if a.action=='download':
        download(c,Path(a.data))
    else:
        run(c,Path(a.data),Path(a.output))

if __name__=='__main__':
    main()
