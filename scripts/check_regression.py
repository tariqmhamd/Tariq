"""Compare a frozen-data rerun to the committed reference summary.
python scripts/check_regression.py results/myrun/summary.csv
A different vendor vintage may legitimately fail this check.
"""
import sys
import pandas as pd
reference=pd.read_csv('validation/recovered_snapshot_summary.csv')
actual=pd.read_csv(sys.argv[1])
keys=['ticker','mode','fee_bps']
if actual.duplicated(keys).any() or len(actual)!=len(reference):
    raise SystemExit('Unexpected result row count or duplicate keys')
m=actual.merge(reference,on=keys,suffixes=('_actual','_reference'),validate='one_to_one')
if len(m)!=len(reference):
    raise SystemExit('Result keys differ')
for col,tolerance in [('final_value',.001),('cagr_pct',1e-6),('max_drawdown_pct',1e-6),('transactions',0)]:
    if not ((m[col+'_actual']-m[col+'_reference']).abs()<=tolerance).all():
        raise SystemExit('Regression mismatch: '+col)
print('PASS: all 24 reference rows match within documented tolerances')
