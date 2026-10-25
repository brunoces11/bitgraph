# BTC Graph - Historical Price Data and Deribit Expiry Cycles

[English](README.md) | [Português](README.pt-BR.md)

---

This repository provides Python automation for collecting Bitcoin market data via public APIs (no authentication keys or account required).

## Volume, Aggression, and Open Interest

The collector includes explicit volume in BTC and USD, 20-session RVOL, and—for collected flow sessions—volume by buyer/seller aggression, delta, and CVD. It also maintains a local historical log of Open Interest snapshots.

| Information | Previously existed? | Collection/calculation and analytical utility |
| :--- | :--- | :--- |
| BTC Volume and USD Notional Volume | Yes, but with ambiguous names | `get_tradingview_chart_data`: helps measure activity contraction/expansion. `volume_btc` is the base volume; `volume_usd` is notional volume. |
| 20-session RVOL | No | Closed candle BTC volume divided by the moving average of the **previous 20 closed candles** from the same source. Enables benchmarking activity against its own recent baseline. |
| Aggressor Buy/Sell Volume, Delta, and CVD | No | Individual tick trades via the `history.deribit.com` server. Delta = aggressive buys minus aggressive sells; CVD = cumulative sum of deltas from the defined anchor. Helps identify order flow pressure and divergences with price. |
| Open Interest and observation-to-observation change | No | `public/ticker`: outstanding positions in USD on `BTC-PERPETUAL`. Represents open market inventory, complementary to traded flow, without indicating direction on its own. |

These originate from **three public Deribit data sources** (candles, trades, and ticker); RVOL, delta, and CVD are derived metrics, not independent sources. None of them in isolation proves anticipation or confirms a breakout. Predictive power must be evaluated through backtesting with explicit out-of-sample rules and metrics.

### Files and Coverage

- `btc_ohlc_deribit_puro.csv` and `btc_ohlc_10_anos.csv`: preserve original columns and add `timestamp_ms`, candle start/end in UTC, `candle_closed`, `volume_btc`, `volume_usd`, `volume_usd_estimated`, `volume_sma20_btc`, `rvol20`, `buy_volume_usd`, `sell_volume_usd`, `delta_usd`, `cvd_usd`, `cvd_start_utc`, and `flow_coverage_complete`.
- `btc_fluxo_deribit_diario.csv`: order flow for collected sessions, including buyer/seller volumes in BTC/USD, deltas, buyer ratio, trade count, and CVD.
- `btc_fluxo_deribit_1h.csv`: same metrics in 1-hour windows to inspect intra-day flow evolution within daily sessions.
- `btc_open_interest_deribit.csv`: one snapshot per ticker timestamp, absolute/percentage change, and seconds elapsed since previous observation.

**Default flow collection covers the last two closed sessions.** There is no automatic backfill of millions of historical trades across all years. Historical windows can be requested using the CLI flags below; previously collected sessions are cached and reused. The 1-hour file contains the same closed historical sessions; it is not a real-time streaming feed. OI is sampled on each script execution without automated background scheduling. The initial snapshot has empty delta fields since no prior observation exists. The collector does not backfill 2018–2026 OI with current values: Deribit public endpoints do not provide historical OI series.

### Units, Timestamps, and Missing Data

- **Deribit daily session: 08:00 to 08:00 UTC the following day.** The true timestamp is preserved. Bitfinex uses its native timestamps; when migrating legacy CSVs, dates are parsed at 00:00 UTC, while Deribit dates are parsed at 08:00 UTC. Thus, the combined series transitions both in market structure (spot to perpetual) and daily cutoff. RVOL resets across source transitions and data gaps.
- `cost_btc` is an **incorrect legacy column name**: its values always came from `cost`, which represents USD notional volume in Deribit. The column is maintained for backwards compatibility; use `volume_usd`. `volume` remains BTC.
- On Bitfinex, `volume_usd` remains an **estimate** (`volume × close`), flagged with `volume_usd_estimated=true`; on Deribit it is the exact value reported by the API.
- RVOL remains empty for the first 20 candles of each continuous segment and on currently open candles. It never mixes spot/perpetual data nor includes the active candle in its moving average.
- Uncollected flow leaves fields blank with `flow_coverage_complete=false`, rather than zero. CVD resets following gaps and reports its anchor timestamp in `cvd_start_utc`. Daily and hourly CVD share the anchor when covering identical session intervals.
- The `amount` field in `BTC-PERPETUAL` trades is already denominated in USD; `amount / price` yields BTC. Do not multiply by `contract_size` again.

### Update Volume Only

```powershell
python coletar_dados.py --somente-volume
```
**What does this command do?**
1. Reads existing CSVs, updates recent candles, and calculates volume/RVOL.
2. Collects the last two closed flow sessions and logs the current OI snapshot, skipping contract/expiry cycle updates.

### Collect Historical Flow for a Specific Window

```powershell
python coletar_dados.py --somente-volume --inicio-fluxo 2018-08-15 --fim-fluxo 2018-08-16
```
**What does this command do?**
1. Fetches sessions opening at 08:00 UTC on August 15 and 16, 2018, including the full final session.
2. Saves daily and hourly flow and integrates metrics into price CSVs; preserves previously cached sessions.

`--dias-fluxo N` adjusts the number of recent sessions to collect (default: 2).  
`--inicio-fluxo` without `--fim-fluxo` collects up to the most recent closed session available.  
Dates outside available history or corresponding to still-open candles are rejected.

### Validation and Publishing

Responses with `has_more=true` are subdivided into disjoint time sub-intervals until complete, untruncated datasets are retrieved. This prevents losing trades that share the same millisecond or out-of-order sequence numbers. Duplicate `trade_id` records are pruned; irreducible truncation, API errors, and invalid data abort collection safely.  
Before publishing, aggregated USD volume must match candle volume within $0.01; for BTC, tolerance is the greater of 0.00001 BTC or 0.0001% of candle volume, accounting for trade rounding. Divergences are never published as complete flow.  
Each volume/price CSV is replaced atomically; files do not share a multi-table database transaction. Cache verification mandates both daily totals and their 24 hourly intervals, enabling automatic recovery if an execution is interrupted between writes.

```powershell
python -m unittest -v test_volume_deribit
```
**What does this test suite verify?**
1. Validates units, session cutoffs, RVOL free of lookahead bias, CVD across gaps, and pagination over duplicate timestamps.
2. Validates candle-to-trade reconciliation, CSV backward compatibility, caching, snapshots, and error handling without incomplete flow publishing.

Official API references:
[Candles and units](https://docs.deribit.com/api-reference/market-data/public-get_tradingview_chart_data),
[Trades and aggressor side](https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_instrument),
[Ticker and Open Interest](https://docs.deribit.com/api-reference/market-data/public-ticker),
[History Server Setup Guide, p. 31](https://statics.deribit.com/files/DeribitInstitutionalSetupGuide.pdf),
[08:00 UTC Daily Settlement](https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement).

Production validation as of **2026-10-25**: 14 automated unit tests passed and 601,529 individual trades collected across the sessions below, with complete volume reconciliation against official candles. All 48 hourly intervals sum exactly to their respective daily totals. Re-execution preserved both flow files byte-for-byte, and consecutive real OI snapshots confirmed delta calculations between observations.

| Session Open (UTC) | Trades | USD Notional Volume | USD Delta |
| :--- | ---: | ---: | ---: |
| 2026-10-23 08:00 | 366,908 | 984,537,870 | +8,713,410 |
| 2026-10-24 08:00 | 234,621 | 765,445,100 | -3,890,140 |

Historical data prior to 2026-10-23 maintained all original column values intact. Combined series CSV contains 3,650 rows and Deribit series contains 2,995 rows, including the active open candle flagged as `candle_closed=false`.

---

## 📁 Generated Files

| File | Description | Rows | Coverage / Window |
| :--- | :--- | :--- | :--- |
| **[`btc_ohlc_10_anos.csv`](btc_ohlc_10_anos.csv)** | Full 10-year daily OHLCV history. Seamless transition from Bitfinex (Spot) to Deribit (Perpetual). | ~3,650 lines | 2016 to present |
| **[`btc_ohlc_deribit_puro.csv`](btc_ohlc_deribit_puro.csv)** | Complete Deribit (`BTC-PERPETUAL`) history since day one of the continuous perpetual contract. | ~3,000 lines | 2018-08-14 to present |
| **[`btc_fluxo_deribit_diario.csv`](btc_fluxo_deribit_diario.csv)** | Closed daily session order flow with aggression metrics, delta, and CVD. | Collected sessions | Recent sessions and on-demand history |
| **[`btc_fluxo_deribit_1h.csv`](btc_fluxo_deribit_1h.csv)** | Hourly (1h) breakdown of flow for closed daily sessions. | Hourly windows | 24 windows per daily session |
| **[`btc_open_interest_deribit.csv`](btc_open_interest_deribit.csv)** | Point-in-time Open Interest snapshots for `BTC-PERPETUAL` and change between runs. | Cumulative history | Logged per script execution |
| **[`deribit_ciclos_vencimento.csv`](deribit_ciclos_vencimento.csv)** | Consolidated summary of all Deribit **expiry cycles**, listing creation timestamp, lifetime in days, and linked contracts. | 14 cycles | Daily, Weekly, Monthly, Quarterly, and Annual |
| **[`deribit_todos_contratos.csv`](deribit_todos_contratos.csv)** | Detailed catalog of **1,000+ individual contracts** (Futures and Options across strikes/calls/puts) with creation and expiry timestamps. | ~1,000 lines | All active and recent instruments |
| **[`coletar_dados.py`](coletar_dados.py)** | Main Python orchestrator script that fetches and synchronizes all market datasets above. | Executable script | - |
| **[`volume_deribit.py`](volume_deribit.py)** | Dedicated module handling resilient pagination, flow calculation, and volume reconciliation. | Python module | - |
| **[`test_volume_deribit.py`](test_volume_deribit.py)** | Comprehensive unit test suite covering volume calculation, reconciliation, RVOL, CVD, and CSV schemas. | Test suite | - |

---

## 📅 Deribit Expiry Cycles (Creation vs Expiration)

Active cycles mapped directly from the Deribit API:

| Expiry (UTC) | Published at (UTC) | Contract Duration | Cycle Period | Types | Reference Instrument |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **2026-10-25 08:00:00** | 2026-10-21 08:00:11 | 4 days | Daily (`day`) | Futures / Options | `BTC-25OCT26` |
| **2026-10-26 08:00:00** | 2026-10-22 08:00:11 | 4 days | Daily (`day`) | Futures / Options | `BTC-26OCT26` |
| **2026-10-27 08:00:00** | 2026-10-23 08:00:11 | 4 days | Daily (`day`) | Futures / Options | `BTC-27OCT26` |
| **2026-10-28 08:00:00** | 2026-10-24 08:00:10 | 4 days | Daily (`day`) | Futures / Options | `BTC-28OCT26` |
| **2026-10-30 08:00:00** | 2026-07-30 08:00:13 | 92 days (~3 months) | Monthly (`month`) | Futures / Options | `BTC-30OCT26` |
| **2026-11-06 08:00:00** | 2026-10-15 08:00:11 | 22 days (~3 weeks) | Weekly (`week`) | Futures / Options | `BTC-6NOV26` |
| **2026-11-13 08:00:00** | 2026-10-22 08:00:11 | 22 days (~3 weeks) | Weekly (`week`) | Futures / Options | `BTC-13NOV26` |
| **2026-11-27 08:00:00** | 2026-08-27 08:00:24 | 92 days (~3 months) | Monthly (`month`) | Futures / Options | `BTC-27NOV26` |
| **2026-12-25 08:00:00** | 2025-12-25 08:00:15 | 365 days (1 year) | Annual (`month`) | Futures / Options | `BTC-25DEC26` |
| **2027-03-26 08:00:00** | 2026-03-26 08:00:27 | 365 days (1 year) | Annual (`month`) | Futures / Options | `BTC-26MAR27` |
| **2027-06-25 08:00:00** | 2026-06-25 08:00:14 | 365 days (1 year) | Annual (`month`) | Futures / Options | `BTC-25JUN27` |
| **2027-09-24 08:00:00** | 2026-09-24 08:00:23 | 365 days (1 year) | Annual (`month`) | Futures / Options | `BTC-24SEP27` |
| **No expiration** | 2018-08-14 10:24:47 | Perpetual | Perpetual | Futures | `BTC-PERPETUAL` |

> **Note on example contract (`BTC-26MAR27`)**:
> The contract expiring on **March 26, 2027 at 08:00 UTC** was created and published by Deribit on **March 26, 2026 at 08:00:27 UTC** (precisely 365 days prior to expiration, following the standard 1-year publication cycle for March/June/September/December maturities).

---

## 🚀 How to Run / Update Data

To refresh all datasets at any time, open a terminal in this repository and execute:

```powershell
python coletar_dados.py
```
**What does this script do?**
1. Updates price candles, volumes, order flow metrics, and logs an Open Interest snapshot.
2. Updates the active Deribit contract catalogue and expiry cycle tables.

- **Zero extra dependencies**: Built entirely with Python's standard library (`urllib`, `json`, `csv`, `datetime`, `time`).
- **UTF-8 with BOM (`utf-8-sig`)**: Opens seamlessly in Microsoft Excel, LibreOffice, Google Sheets, and standard data science libraries without character encoding issues.
