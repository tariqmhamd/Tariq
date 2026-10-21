# Rule provenance and decisions

Recovered October 13 source: `ichimoku_backtest.py` and its identical duplicate,
plus `Ichimoku_Backtest_2016_2026.pdf` and `Ichimoku_Backtest_Reproducible.zip`.
The PDF's “Exact frozen rules” and saved corrected engine define weekly_pullback.
The script's 2% proximity tests are a concrete interpretation of “pullback and
recovery”, not an independently specified precision requirement from the user.
`docs/recovered_design.json` preserves the original machine-readable design;
`docs/legacy_reference.py` is archival source only, not the project's entry point.
It expects the old archive's directory structure and is not imported by this package.

Later recovered conversation context (October 17–20) describes monthly Kijun
exits, a green-candle variant, and weekly Tenkan/Kijun crosses under a monthly
cloud filter. These are exposed as separate configs. Crossing equality uses
prior <= / current > for entry, prior >= / current < for exit. That boundary
choice is an explicit implementation assumption. No optimization or strategy
selection based on best historical return has been performed here.

Differences from the early 5,237-byte script: both cloud spans required; no
partial-period execution; benchmark starts at first OPEN; original capital
anchors performance; reusable paths/settings; full transaction/holding ledger;
strict validation and run hashes. The recovered corrected archive had already
fixed several issues; this project preserves its default results and generalizes
its timing to holiday/weekend terminal boundaries by scheduling beyond period end.

No previously reported numerical performance is taken on trust. The validation
summary is recomputed from recovered input data. It is not a new live-data run.
