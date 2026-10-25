from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import coletar_dados as collector
import volume_deribit as v


def trade(seq, ts, amount=10, price=100, direction="buy"):
    return dict(trade_seq=seq, trade_id=str(seq), timestamp=ts, amount=amount,
                price=price, direction=direction, instrument_name=v.INSTRUMENT)


def candle(ts, volume=10, source=v.DERIBIT_SOURCE):
    return dict(timestamp_ms=ts, datetime=v.iso(ts)[:10], volume=volume, cost=volume * 100,
                open=100, high=110, low=90, close=100, source=source)


class VolumeTests(unittest.TestCase):
    def test_rvol_uses_previous_20_closed_candles(self):
        candles = [candle(i * v.DAY_MS) for i in range(22)]
        candles[20]["volume"] = 100
        rows = v.enriquecer_precos(candles, {}, 21 * v.DAY_MS)
        self.assertEqual(rows[19]["rvol20"], "")
        self.assertEqual(rows[20]["rvol20"], 10)
        self.assertEqual(rows[21]["rvol20"], "")  # candle ainda aberto
        self.assertEqual(rows[21]["candle_closed"], "false")
        self.assertEqual(rows[0]["delta_usd"], "")  # desconhecido não vira zero

    def test_rvol_resets_at_source_change_and_gaps(self):
        candles = [candle(i * v.DAY_MS, source="Bitfinex BTCUSD (Spot)") for i in range(20)]
        candles += [candle(20 * v.DAY_MS), candle(22 * v.DAY_MS)]
        rows = v.enriquecer_precos(candles, {}, 24 * v.DAY_MS)
        self.assertEqual(rows[20]["rvol20"], "")
        self.assertEqual(rows[21]["rvol20"], "")
        self.assertEqual(rows[0]["volume_usd_estimated"], "true")

    def test_split_pages_keeps_trades_with_identical_timestamp(self):
        trades = [trade(2, 1), trade(1, 1), trade(3, 3), trade(4, 7)]
        calls = []
        def fetch(url):
            q = parse_qs(urlparse(url).query)
            start, end = int(q["start_timestamp"][0]), int(q["end_timestamp"][0])
            calls.append((start, end))
            selected = [t for t in trades if start <= t["timestamp"] <= end]
            return {"result": dict(trades=selected[:2], has_more=len(selected) > 2)}
        with patch.object(v.time, "sleep"):
            result = list(v.iter_trades(fetch, 0, 8, count=2))
        self.assertEqual([t["trade_seq"] for t in result], [1, 2, 3, 4])
        self.assertGreater(len(calls), 1)

    def test_single_millisecond_truncation_fails(self):
        with patch.object(v.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "1 ms"):
                list(v.iter_trades(lambda _: {"result": {"trades": [], "has_more": True}}, 1, 2))

    def test_amount_is_usd_not_contract_count_or_btc(self):
        ts = v.SESSION_MS
        row = v.agregar_fluxo([trade(1, ts, 100, 200), trade(2, ts + 1, 40, 100, "sell")],
                              ts, ts + v.DAY_MS, v.DAY_MS)[0]
        self.assertEqual(row["buy_volume_btc"], Decimal("0.5"))
        self.assertEqual(row["sell_volume_btc"], Decimal("0.4"))
        self.assertEqual(row["delta_usd"], 60)
        self.assertEqual(row["delta_btc"], Decimal("0.1"))
        self.assertEqual(row["trade_count"], 2)
        v.validar_volume({"datetime": "test", "cost": 140, "volume": 0.9}, row)
        with self.assertRaises(RuntimeError):
            v.validar_volume({"datetime": "test", "cost": 150, "volume": 0.9}, row)

    def test_session_boundary_is_08utc_and_half_open(self):
        ts = v.date_ms("2026-10-23") + v.SESSION_MS
        rows = v.agregar_fluxo([trade(1, ts), trade(2, ts + v.DAY_MS - 1)],
                               ts, ts + v.DAY_MS, v.HOUR_MS)
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows[0]["trade_count"], 1)
        self.assertEqual(rows[-1]["trade_count"], 1)
        self.assertIn("08:00:00", rows[0]["datetime_utc"])
        self.assertEqual(rows[1]["buy_ratio"], "")

    def test_cvd_restarts_after_missing_window(self):
        rows = [dict(timestamp_ms=t, delta_usd=10, delta_btc="0.1", coverage_complete="true")
                for t in (0, v.DAY_MS, 3 * v.DAY_MS)]
        result = list(v.recalcular_cvd(rows, v.DAY_MS))
        self.assertEqual([r["cvd_usd"] for r in result], [10, 20, 10])
        self.assertNotEqual(result[1]["cvd_start_utc"], result[2]["cvd_start_utc"])

    def test_oi_snapshots_idempotent_and_first_change_unknown(self):
        def response(ts, oi):
            return {"result": dict(timestamp=ts, instrument_name=v.INSTRUMENT, open_interest=oi,
                                   stats=dict(volume=10, volume_usd=100))}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            v.coletar_open_interest(lambda _: response(1000, 100), directory)
            v.coletar_open_interest(lambda _: response(1000, 100), directory)
            v.coletar_open_interest(lambda _: response(2000, 110), directory)
            rows = v.read_csv(Path(directory) / "btc_open_interest_deribit.csv")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["open_interest_change_usd"], "")
            self.assertEqual(Decimal(rows[1]["open_interest_change_pct"]), 10)
            self.assertEqual(Decimal(rows[1]["seconds_since_previous"]), 1)

    def test_failed_flow_does_not_publish_new_files(self):
        ts = v.date_ms("2018-08-15") + v.SESSION_MS
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, patch.object(v.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "Volume divergente"):
                v.coletar_fluxo([candle(ts)], lambda _: {"result": {"trades": [], "has_more": False}}, directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_flow_rerun_uses_cache_and_repairs_missing_hourly_file(self):
        ts = v.date_ms("2018-08-15") + v.SESSION_MS
        calls = []
        def fetch(_):
            calls.append(True)
            return {"result": {"trades": [trade(1, ts, 1000, 100)], "has_more": False}}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, patch.object(v.time, "sleep"):
            first = v.coletar_fluxo([candle(ts)], fetch, directory)
            saved = (Path(directory) / "btc_fluxo_deribit_diario.csv").read_bytes()
            second = v.coletar_fluxo([candle(ts)], fetch, directory)
            self.assertEqual(first[ts]["cvd_usd"], second[ts]["cvd_usd"])
            self.assertEqual(saved, (Path(directory) / "btc_fluxo_deribit_diario.csv").read_bytes())
            self.assertEqual(len(calls), 1)
            (Path(directory) / "btc_fluxo_deribit_1h.csv").unlink()
            v.coletar_fluxo([candle(ts)], fetch, directory)
            self.assertEqual(len(calls), 2)

    def test_api_error_and_malformed_payload_fail(self):
        with self.assertRaises(RuntimeError):
            v.api_result(lambda _: {"error": {"code": 10000}}, "base", "method")
        with patch.object(v.time, "sleep"):
            with self.assertRaises(RuntimeError):
                list(v.iter_trades(lambda _: {"result": {"trades": []}}, 0, 10))

    def test_chart_filters_previous_candle_and_checks_parallel_arrays(self):
        payload = {"status": "ok", "ticks": [100, 200],
                   **{key: [10, 20] for key in ("open", "high", "low", "close", "volume", "cost")}}
        with patch.object(collector, "fetch_json", return_value={"result": payload}):
            candles = collector.coletar_historico_deribit(200, 300)
            self.assertEqual([c["timestamp_ms"] for c in candles], [200])
            payload["cost"] = []
            with self.assertRaisesRegex(RuntimeError, "comprimentos"):
                collector.coletar_historico_deribit(200, 300)

    def test_cli_date_format_is_unambiguous(self):
        with self.assertRaises(ValueError):
            v.date_ms("2026-1-01")
        with self.assertRaises(ValueError):
            v.date_ms("2026-02-30")

    def test_legacy_csv_and_new_schema_round_trip(self):
        ts = v.date_ms("2018-08-15") + v.SESSION_MS
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, patch.object(collector, "OUTPUT_DIR", directory):
            collector.salvar_precos([candle(ts)], [candle(ts)])
            path = Path(directory) / "btc_ohlc_deribit_puro.csv"
            rows = v.read_csv(path)
            self.assertEqual(rows[0]["cost_btc"], rows[0]["volume_usd"])
            self.assertEqual(v.carregar_velas(path, True)[0]["timestamp_ms"], ts)
            v.atomic_csv(path, ["datetime", "open", "high", "low", "close", "volume", "cost_btc"], rows)
            self.assertEqual(v.carregar_velas(path, True)[0]["timestamp_ms"], ts)


if __name__ == "__main__":
    unittest.main()
