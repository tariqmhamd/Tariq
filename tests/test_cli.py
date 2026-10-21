import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from ichimoku.__main__ import run, download


class InputTests(unittest.TestCase):
    def test_missing_terminal_session_fails(self):
        c=json.loads(Path('configs/default.json').read_text())
        c.update(tickers=['TEST'],warmup_start='2020-01-01',start='2020-01-02',end='2020-01-06')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir()
            pd.DataFrame(dict(Date=['2020-01-02','2020-01-03'],Open=[10,10],
                High=[10,10],Low=[10,10],Close=[10,10],AdjClose=[10,10])).to_csv(data/'TEST.csv',index=False)
            with self.assertRaisesRegex(ValueError,'session coverage mismatch'):
                run(c,data,root/'out')

    def test_download_contract(self):
        c=dict(tickers=['TEST'],warmup_start='2020-01-01',end='2020-01-06')
        d=pd.DataFrame(dict(Open=[10.],High=[11.],Low=[9.],Close=[10.],
                            **{'Adj Close':[9.]}),index=pd.to_datetime(['2020-01-02']))
        with tempfile.TemporaryDirectory() as tmp:
            with patch('yfinance.download',return_value=d) as mock:
                download(c,Path(tmp))
            self.assertEqual(mock.call_args.kwargs['end'],'2020-01-07')
            self.assertFalse(mock.call_args.kwargs['auto_adjust'])
            saved=pd.read_csv(Path(tmp)/'TEST.csv')
            self.assertIn('AdjClose',saved)
            self.assertTrue((Path(tmp)/'TEST.source.json').is_file())

if __name__=='__main__':unittest.main()
