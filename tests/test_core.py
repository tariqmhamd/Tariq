import unittest
import numpy as np
import pandas as pd
from ichimoku.core import bars, indicators, orders, simulate, metrics, validate

C=dict(tenkan=2,kijun=3,span_b=4,displacement=2,pullback_tolerance=.02,strategy='monthly')


def prices(start='2000-01-03',end='2010-07-15'):
    ix=pd.bdate_range(start,end)
    n=np.arange(len(ix),dtype=float)
    close=100+n*.03+8*np.sin(n/23)
    return pd.DataFrame(dict(Open=close-.1,High=close+1,Low=close-1,Close=close),index=ix)


class TimingTests(unittest.TestCase):
    def test_cloud_requires_both_spans(self):
        b=bars(prices(),'M'); i=indicators(b,C)
        self.assertTrue(i.top.iloc[:5].isna().all())
        self.assertTrue(pd.notna(i.top.iloc[5]))
        expected=(b.High.iloc[:4].max()+b.Low.iloc[:4].min())/2
        self.assertAlmostEqual(i.span_b.iloc[5],expected)

    def test_unfinished_terminal_month_and_week(self):
        d=prices(end='2010-07-15');s,_,_=orders(d,C)
        self.assertTrue((s.monthly_period.dropna() <= pd.Timestamp('2010-06-30')).all())
        c=dict(C,strategy='weekly_cross');s,_,_=orders(d,c)
        self.assertTrue((s.weekly_period.dropna()<=pd.Timestamp('2010-07-09')).all())

    def test_july_close_executes_august(self):
        d=prices(end='2010-08-04');s,_,_=orders(d,C)
        changed=s.monthly_period.ne(s.monthly_period.shift()) & s.monthly_period.notna()
        july=s.index[changed & s.monthly_period.eq(pd.Timestamp('2010-07-31'))]
        self.assertEqual(list(july),[pd.Timestamp('2010-08-02')])
        self.assertEqual(s.loc[july[0],'signal_date'],pd.Timestamp('2010-07-30'))

    def test_false_monthly_filter_replaces_true(self):
        d=prices();s,_,_=orders(d,C)
        self.assertGreater(s.eligible.astype(int).diff().eq(-1).sum(),0)

    def test_future_perturbation_does_not_change_orders_or_nav(self):
        d=prices();cut=pd.Timestamp('2008-07-15'); altered=d.copy()
        altered.loc[altered.index>cut]*=10
        for mode in ['monthly','monthly_green','weekly_cross','weekly_pullback']:
            c=dict(C,strategy=mode)
            s,_,_=orders(d,c);future,_,_=orders(altered,c)
            pd.testing.assert_frame_equal(s.loc[:cut],future.loc[:cut])
            truncated,_,_=orders(d.loc[:cut],c)
            pd.testing.assert_frame_equal(s.loc[:cut],truncated)
            n,t=simulate(d,s,'2005-01-03',cut,10000,10)
            nn,tt=simulate(altered,future,'2005-01-03',cut,10000,10)
            pd.testing.assert_frame_equal(n,nn);pd.testing.assert_frame_equal(t,tt)

    def test_missing_duplicate_prices_rejected(self):
        d=prices();d.iloc[2,0]=np.nan
        with self.assertRaises(ValueError):validate(d)
        with self.assertRaises(ValueError):validate(pd.concat([prices(),prices()]))


class AccountingTests(unittest.TestCase):
    def setup_case(self):
        d=prices(start='2020-01-01',end='2020-01-06')
        d[:]=100
        s=pd.DataFrame(index=d.index,data=dict(entry=False,exit=False,eligible=True,
            monthly_period=pd.NaT,weekly_period=pd.NaT,signal_date=pd.NaT))
        s.loc[d.index[1],['entry','signal_date']]=[True,d.index[0]]
        s.loc[d.index[2],['exit','signal_date']]=[True,d.index[1]]
        return d,s

    def test_roundtrip_costs_and_cash_reconciliation(self):
        d,s=self.setup_case();n,t=simulate(d,s,d.index[0],d.index[-1],1000,10)
        self.assertEqual(list(t.side),['buy','sell'])
        self.assertAlmostEqual(n.nav.iloc[-1],1000*(1-.001)/(1+.001))
        for r in t.itertuples():
            self.assertLess(r.signal_date,r.date)
            self.assertAlmostEqual(r.cash_after,
                r.cash_before-r.notional-r.fee if r.side=='buy' else r.cash_before+r.notional-r.fee)
            self.assertAlmostEqual(r.notional,r.price*r.quantity)
        self.assertTrue((n.cash>=-1e-8).all())

    def test_first_day_loss_in_drawdown(self):
        d,s=self.setup_case();d.loc[d.index[0],['Low','Close']]=50
        n,t=simulate(d,s,d.index[0],d.index[-1],1000,0,True)
        self.assertEqual(metrics(n,t,1000)['max_drawdown_pct'],-50)
        self.assertEqual(len(t),1)

    def test_dividend_adjusted_proxy(self):
        # Ex-dividend price falls 100 -> 90; total-return adjusted price is flat.
        from ichimoku.__main__ import load
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'x.csv'
            pd.DataFrame(dict(Date=['2020-01-02','2020-01-03'],Open=[100,90],
                High=[100,90],Low=[100,90],Close=[100,90],AdjClose=[90,90])).to_csv(path,index=False)
            a=load(path,'adjusted');r=load(path,'price_only')
            self.assertAlmostEqual(a.Close.iloc[-1]/a.Open.iloc[0],1)
            self.assertAlmostEqual(r.Close.iloc[-1]/r.Open.iloc[0],.9)

    def test_same_day_signal_is_rejected(self):
        d,s=self.setup_case();s.loc[d.index[1],'signal_date']=d.index[1]
        with self.assertRaises(ValueError):simulate(d,s,d.index[0],d.index[-1],1000,0)

if __name__=='__main__':unittest.main()
