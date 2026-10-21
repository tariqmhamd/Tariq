# Monthly and weekly Ichimoku backtesting

An auditable Python research project for AAPL, MSFT, NVDA, AMZN and GOOGL.
The default recovers the October 13, 2026 weekly-pullback/monthly-exit design.
Named alternatives preserve later interpretations without silently changing it.
Python 3.12 is the tested runtime.

## Quick start

```bash
git clone https://github.com/tariqmhamd/Tariq.git
cd Tariq
# If this project is still in a pull request:
git checkout feature/ichimoku-backtester
python3.12 -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m ichimoku download --config configs/default.json --data data
python -m ichimoku run --config configs/default.json --data data --output results/default
```

Data downloading needs an internet connection and Yahoo availability. The engine
runs offline from saved CSVs. It never silently refreshes inputs. Save the CSVs,
source JSONs, config, requirements and output manifest together to freeze a run.
Existing nonempty output directories are rejected: use a new output name.
An editable-install/package step is unnecessary; run from the repository root.
Pinned direct dependencies are in requirements.txt. For an exact environment,
also retain `python -m pip freeze > environment-lock.txt` after installation.

The default is **October 13, 2016 open through October 12, 2026 close**, with
warmup from January 2008. Change dates and tickers in a copied JSON config.
End dates are inclusive in the project; the downloader translates this to the
vendor's exclusive end. Use a completed daily session as end, not today's
unfinished session. US regular-session, date-indexed data only.

## Recovered rules and alternatives

Standard periods: Tenkan 9, Kijun 26, Span B 52, displacement 26.
All comparisons are strict except flat/rising Kijun and the 2% pullback tests.

| Config / strategy | Entry | Exit |
| --- | --- | --- |
| default.json / weekly_pullback | Latest completed monthly close above displayed cloud and Kijun; monthly Kijun flat/rising. Completed weekly close above displayed cloud and weekly Kijun. Prior week's low AND close at/below 102% of prior Kijun. | Completed monthly close below displayed monthly cloud bottom. |
| weekly_cross.json / weekly_cross | Latest completed monthly close above cloud; weekly Tenkan crosses strictly above Kijun after being at/below. | Weekly Tenkan crosses strictly below Kijun after being at/above. |
| monthly.json / monthly | Completed monthly close above displayed cloud and Kijun. | Completed monthly close below Kijun. |
| monthly_green.json / monthly_green | Monthly rule plus close strictly above open. | Completed monthly close below Kijun. |

The original script and the frozen report agree on the default. Later conversation
context described monthly-only and weekly crossover variants; these are distinct
strategies, not replacements inferred to be approved. The optional ADX/fundamental
screens discussed elsewhere are outside this project's Ichimoku-only rules.
Green monthly candle alone is not an entry condition.
See [rule provenance](docs/RULES.md). Parameters, costs and strategy are JSON
settings; changing them does not overwrite previous output.

```bash
python -m ichimoku run --config configs/weekly_cross.json --output results/weekly_cross
python -m ichimoku run --config configs/monthly.json --output results/monthly
python -m ichimoku run --config configs/monthly_green.json --output results/monthly_green
```

## Timing safeguards

- Indicators use only trailing windows. Displayed spans use a positive 26-bar
  shift; both spans must exist before any cloud comparison is true. There is no
  Chikou look-forward condition.
- Orders execute at the first observed session open strictly AFTER the signal
  period's calendar boundary. A July close cannot trade during July. A Friday
  close first trades the next session; a holiday-shortened week also waits for
  the next session beyond Friday. Weekend month-end works the same way.
- Partial terminal weeks/months can appear in diagnostic indicator CSVs, but can
  NEVER produce an executable order inside the run. Only orders scheduled on an
  actual later session can trade. No unfinished period values are carried back.
- Monthly states carry forward including false values. Same-day monthly and
  weekly confirmations can both be used at the following open. Exits take
  precedence over entries; there is no sell-and-rebuy on the same open.
- XNYS calendar validation rejects missing or extra sessions, including missing
  terminal sessions. Tickers must have identical full date coverage; no price
  forward-filling or silent exclusion. This US-equity scope does not support
  IPOs lacking the full configured warmup or exchange calendars outside XNYS.
- Synthetic tests mutate all future prices and compare prior orders and NAV;
  truncation checks ensure future rows cannot affect already-executable orders.

## Capital, costs, dividends and assumptions

$100,000 is split into five independent $20,000 sleeves. Start flat; no seeded
positions, no forced initial strategy purchase. Full-sleeve fractional-unit
entries; sale proceeds are reinvested within the same sleeve. No periodic
rebalancing between stocks, leverage, shorting, cash interest, taxes or staging.
No forced terminal sale. Buy-and-hold buys at the SAME first session OPEN and
uses the same cost assumptions. Defaults run 0 and 10 basis points per side.
Fees are deducted from cash, including on the benchmark's initial purchase.
Slippage can be approximated by increasing the all-in fee bps; there is no
separate spread/impact execution model.

`price_mode: adjusted` multiplies vendor split-adjusted OHLC by AdjClose/Close.
This is a **dividend-reinvestment total-return proxy**, not an explicit dividend
payment-date ledger. Quantities are adjusted economic units, not historical
broker share counts; audit prices use those same units. Do not add dividends or
splits again. `price_only` uses vendor split-adjusted OHLC and excludes dividends.
Both benchmark and strategy always use the same convention. Vendor revisions
can change subsequent downloads and therefore the results and signals.

The 1–3-year horizon is an intention, **not a holding-time constraint**. The
recovered default has no minimum/maximum hold. Holdings.csv exposes actual
holding durations, including still-open positions. These retrospectively chosen
technology winners introduce selection bias; this project does not claim to
remove that bias or establish future S&P 500 outperformance. To test SPY as a
separate buy-and-hold benchmark, use a copied config with `tickers: ["SPY"]`
and the same dates/capital, then compare its buy_hold row. The default benchmark
is the same five stocks, initially equal weight.

## Outputs and formulas

- `summary.csv`: per-stock and portfolio final value, total return, CAGR,
  maximum drawdown, buys, sells, transaction counts and fees, for each cost case.
- `equity.csv`: daily close equity and cash; stock rows also report units.
- `transactions.csv`: signal date, period labels, execution date, reason, side,
  adjusted open, quantity, notional, fee, cash before/after and units after.
  The date means regular-session open, following a prior session close signal.
  Benchmark buys have no strategy signal date. `weekly_period` may also appear
  on a monthly-exit day if a weekly event happened on the same execution date;
  `reason` identifies the operative exit rule.
- `holdings.csv`: closed round trips and open positions, calendar holding days
  and net position return. Open returns are marked at final close.
- `*_orders.csv`: executable-day order flags, monthly eligibility and source
  periods. `*_monthly.csv` / `*_weekly.csv`: full diagnostic indicators.
- `manifest.json`: full config, runtime versions, input/source-code/output
  SHA-256 hashes and actual first/last dates. Manifests intentionally include
  runtime metadata, so byte identity across runs is not expected.

Total return = final NAV / original capital - 1. CAGR uses elapsed calendar time
from first open to final close (NY time; 365.25 days/year). Drawdown is the worst
NAV / running peak - 1, anchored at original capital BEFORE first-day returns.
Drawdowns use daily closes, not intraday lows. A transaction is one executed buy
or sale; round trips are a separate concept. Terminal open positions do not
count as hypothetical sales. Cash and NAV can be reconciled from the ledger.

## Data CSV contract and reproducibility

One `data/TICKER.csv` per symbol: `Date,Open,High,Low,Close,AdjClose` (optional
Volume, Dividends, Stock Splits). Date must be sorted, unique, timezone-naive
YYYY-MM-DD US trading dates. OHLC must be positive, finite, internally consistent
and split-adjusted exactly once; AdjClose additionally adjusts cash dividends.
Adjusted mode fails if AdjClose is unavailable. Other data vendors may be used
if exported to this exact contract. Never mix adjustment conventions.

Input validation checks dates, prices and calendar coverage, but cannot verify a
vendor's corporate-action correctness. Back-adjusted data are retrospectively
revised data, not point-in-time vintages; timing safeguards prevent future-bar
signal leakage, not all possible vendor/data-selection biases.

The project was tested against saved Yahoo snapshots recovered from
`Ichimoku_Backtest_Reproducible.zip` (October 13, 2026). Those private snapshots
are not distributed in this public repository. To reproduce that exact run,
export the recovered archive's `data/*_yahoo_raw.json` using
`scripts/import_saved_yahoo.py`, then run the default config offline. Fresh
Yahoo downloads are reproducible from their own saved hashes but may differ
from the earlier vendor vintage. `validation/` contains the newly computed
summary and test evidence, not invented live results.

Sources: [pandas time-series documentation](https://pandas.pydata.org/docs/user_guide/timeseries.html),
[yfinance data download](https://ranaroussi.github.io/yfinance/reference/yfinance.functions.html),
[yfinance adjustment convention](https://ranaroussi.github.io/yfinance/advanced/price_adjustment.html),
[exchange_calendars](https://github.com/gerrymanoim/exchange_calendars).

For the saved October 2026 vintage, validate a rerun with:

```bash
python scripts/import_saved_yahoo.py /path/to/Ichimoku_Backtest/data --output data
python -m ichimoku run --output results/frozen-rerun
python scripts/check_regression.py results/frozen-rerun/summary.csv
```

The committed validation ledger and holdings file allow review of the recovered
run's actual trades without a download. A fresh-data run should be labeled with
its own vintage; do not force it to match the old reference by changing rules.
