"""Export existing archive snapshots. No downloads; run from project root.
python scripts/import_saved_yahoo.py /path/to/Ichimoku_Backtest/data --output data
"""
import argparse
import json
from pathlib import Path
import pandas as pd

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('source',type=Path)
p.add_argument('--output',type=Path,default=Path('data'))
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
paths=list(a.source.glob('*_yahoo_raw.json'))
if not paths:
    p.error('No *_yahoo_raw.json files found in source')
for path in paths:
    raw=json.loads(path.read_text())['chart']['result'][0]
    q=raw['indicators']['quote'][0]
    dates=pd.to_datetime(raw['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
    d=pd.DataFrame({k.title():q[k] for k in ['open','high','low','close','volume']},index=dates)
    d['AdjClose']=raw['indicators']['adjclose'][0]['adjclose']
    d.index.name='Date'
    d.to_csv(a.output/(path.name.removesuffix('_yahoo_raw.json')+'.csv'),float_format='%.17g')
