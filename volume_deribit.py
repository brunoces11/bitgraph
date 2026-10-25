"""Volume do BTC-PERPETUAL: unidades explícitas, RVOL, fluxo e snapshots de OI.

Somente biblioteca padrão. Nenhum valor ausente é convertido em volume zero.
O CVD tem uma âncora explícita e reinicia quando existe uma lacuna na coleta.
"""

from collections import deque
import csv
from datetime import datetime, timezone
from decimal import Decimal
import math
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlencode

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
SESSION_MS = 8 * HOUR_MS
HISTORY_URL = "https://history.deribit.com/api/v2/public"
PUBLIC_URL = "https://www.deribit.com/api/v2/public"
INSTRUMENT = "BTC-PERPETUAL"
DERIBIT_SOURCE = "Deribit BTC-PERPETUAL"
FLOW_FIELDS = [
    "timestamp_ms", "datetime_utc", "interval_end_utc", "instrument_name",
    "buy_volume_usd", "sell_volume_usd", "buy_volume_btc", "sell_volume_btc",
    "delta_usd", "delta_btc", "buy_ratio", "trade_count",
    "cvd_usd", "cvd_btc", "cvd_start_utc", "coverage_complete",
]
PRICE_FIELDS = [
    "timestamp_ms", "candle_start_utc", "candle_end_utc", "candle_closed",
    "volume_btc", "volume_usd", "volume_usd_estimated", "volume_sma20_btc",
    "rvol20", "buy_volume_usd", "sell_volume_usd", "delta_usd", "cvd_usd",
    "cvd_start_utc", "flow_coverage_complete",
]
OI_FIELDS = [
    "timestamp_ms", "datetime_utc", "instrument_name", "open_interest_usd",
    "open_interest_change_usd", "open_interest_change_pct", "seconds_since_previous",
    "volume_24h_btc", "volume_24h_usd",
]


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def date_ms(value):
    parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError("Use YYYY-MM-DD com mês e dia de dois dígitos")
    return int(parsed.timestamp() * 1000)


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"Valor numérico inválido: {value!r}")
    return result


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def atomic_csv(path, fields, rows):
    """Só substitui o arquivo depois de terminar a escrita e fechar o temporário."""
    path = Path(path)
    with tempfile.NamedTemporaryFile(
        mode="w", newline="", encoding="utf-8-sig", dir=path.parent,
        prefix=path.name + ".", suffix=".tmp", delete=False,
    ) as stream:
        temporary = stream.name
        try:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        except BaseException:
            stream.close()
            os.unlink(temporary)
            raise
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def api_result(fetch_json, base, method, **params):
    payload = fetch_json(f"{base}/{method}?{urlencode(params)}")
    if not isinstance(payload, dict) or "error" in payload or "result" not in payload:
        raise RuntimeError(f"Erro da Deribit em {method}: {payload}")
    return payload["result"]


def carregar_velas(path, deribit_only=False):
    """Lê também os CSVs originais, cujo timestamp diário havia sido descartado."""
    result = []
    for row in read_csv(path):
        source = DERIBIT_SOURCE if deribit_only else row["source"]
        timestamp = int(row["timestamp_ms"]) if row.get("timestamp_ms") else (
            date_ms(row["datetime"]) + (SESSION_MS if source == DERIBIT_SOURCE else 0)
        )
        result.append({
            "datetime": row["datetime"], "timestamp_ms": timestamp, "source": source,
            **{key: row[key] for key in ("open", "high", "low", "close", "volume")},
            "cost": row["cost_btc"] if deribit_only else row["cost_volume"],
        })
    if not result:
        raise RuntimeError(f"CSV ausente ou vazio: {path}. Execute a coleta completa primeiro.")
    return result


def enriquecer_precos(velas, flows, now_ms):
    """RVOL usa somente os 20 candles ANTERIORES fechados da mesma fonte."""
    previous = deque(maxlen=20)
    last_source = last_timestamp = None
    rows = []
    for candle in sorted(velas, key=lambda value: value["timestamp_ms"]):
        ts = int(candle["timestamp_ms"])
        source = candle["source"]
        if source != last_source or (last_timestamp is not None and ts - last_timestamp != DAY_MS):
            previous.clear()
        volume = number(candle["volume"])
        if volume < 0:
            raise ValueError("Volume negativo no histórico")
        closed = ts + DAY_MS <= now_ms
        baseline = sum(previous) / 20 if len(previous) == 20 else None
        flow = flows.get(ts, {}) if source == DERIBIT_SOURCE else {}
        row = {
            **candle, "timestamp_ms": ts, "candle_start_utc": iso(ts),
            "candle_end_utc": iso(ts + DAY_MS), "candle_closed": str(closed).lower(),
            "volume_btc": candle["volume"], "volume_usd": candle["cost"],
            "volume_usd_estimated": str(source != DERIBIT_SOURCE).lower(),
            "volume_sma20_btc": baseline if baseline is not None else "",
            "rvol20": volume / baseline if closed and baseline else "",
            "flow_coverage_complete": flow.get("coverage_complete", "false"),
        }
        for key in ("buy_volume_usd", "sell_volume_usd", "delta_usd", "cvd_usd", "cvd_start_utc"):
            row[key] = flow.get(key, "")
        if closed:
            previous.append(volume)
        last_source, last_timestamp = source, ts
        rows.append(row)
    return rows


def iter_trades(fetch_json, start_ms, end_ms, count=10000):
    """Intervalo [início,fim). Subdivide páginas truncadas sem pular timestamps.

    A API pode ordenar sequências fora de ordem dentro do mesmo milissegundo.
    Por isso não se avança por último timestamp+1 nem por máximo trade_seq.
    Cada folha precisa retornar has_more=false; limites de 1 ms falham de forma
    explícita, em vez de publicar um fluxo incompleto como se fosse completo.
    """
    pending = [(start_ms, end_ms)]
    seen = set()
    requests = 0
    while pending:
        start, end = pending.pop()
        result = api_result(
            fetch_json, HISTORY_URL, "get_last_trades_by_instrument_and_time",
            instrument_name=INSTRUMENT, start_timestamp=start, end_timestamp=end - 1,
            count=count, sorting="asc", include_old="true",
        )
        requests += 1
        trades = result.get("trades")
        if not isinstance(trades, list) or not isinstance(result.get("has_more"), bool):
            raise RuntimeError("Resposta de negócios sem trades/has_more válidos")
        if result["has_more"]:
            if end - start <= 1:
                raise RuntimeError("Mais negócios que o limite da API em 1 ms; coleta não publicada")
            midpoint = (start + end) // 2
            pending.extend([(midpoint, end), (start, midpoint)])
        else:
            for trade in sorted(trades, key=lambda value: (value["timestamp"], value["trade_seq"])):
                timestamp = int(trade["timestamp"])
                if not start <= timestamp < end or trade["instrument_name"] != INSTRUMENT:
                    raise RuntimeError("API devolveu um negócio fora da janela/instrumento")
                trade_id = trade["trade_id"]
                if trade_id in seen:
                    continue
                seen.add(trade_id)
                yield trade
        # Servidor de histórico: manter consultas sequenciais e moderadas.
        time.sleep(0.1)
        if requests % 20 == 0:
            print(f"   [Fluxo] {requests} consultas; {len(seen)} negócios completos", flush=True)


def agregar_fluxo(trades, start_ms, end_ms, interval_ms):
    buckets = {}
    for ts in range(start_ms, end_ms, interval_ms):
        buckets[ts] = {
            "timestamp_ms": ts, "datetime_utc": iso(ts),
            "interval_end_utc": iso(min(ts + interval_ms, end_ms)),
            "instrument_name": INSTRUMENT, "buy_volume_usd": Decimal(0),
            "sell_volume_usd": Decimal(0), "buy_volume_btc": Decimal(0),
            "sell_volume_btc": Decimal(0), "trade_count": 0,
            "coverage_complete": "true",
        }
    for trade in trades:
        ts = int(trade["timestamp"])
        if not start_ms <= ts < end_ms:
            raise ValueError("Negócio fora do intervalo agregado")
        direction = trade["direction"]
        amount, price = number(trade["amount"]), number(trade["price"])
        if direction not in ("buy", "sell") or amount < 0 or price <= 0:
            raise ValueError("Negócio com direção, quantidade ou preço inválido")
        bucket = buckets[start_ms + ((ts - start_ms) // interval_ms) * interval_ms]
        bucket[direction + "_volume_usd"] += amount
        bucket[direction + "_volume_btc"] += amount / price
        bucket["trade_count"] += 1
    for row in buckets.values():
        row["delta_usd"] = row["buy_volume_usd"] - row["sell_volume_usd"]
        row["delta_btc"] = row["buy_volume_btc"] - row["sell_volume_btc"]
        total = row["buy_volume_usd"] + row["sell_volume_usd"]
        row["buy_ratio"] = row["buy_volume_usd"] / total if total else ""
    return list(buckets.values())


def recalcular_cvd(rows, interval_ms):
    cumulative_usd = cumulative_btc = Decimal(0)
    last_ts = None
    anchor = None
    for row in sorted(rows, key=lambda value: int(value["timestamp_ms"])):
        ts = int(row["timestamp_ms"])
        if row["coverage_complete"] != "true":
            raise ValueError("CVD exige janelas completas")
        if last_ts is None or ts != last_ts + interval_ms:
            cumulative_usd = cumulative_btc = Decimal(0)
            anchor = iso(ts)
        cumulative_usd += number(row["delta_usd"])
        cumulative_btc += number(row["delta_btc"])
        row.update(cvd_usd=cumulative_usd, cvd_btc=cumulative_btc, cvd_start_utc=anchor)
        last_ts = ts
        yield row


def validar_volume(candle, row):
    """Reconciliação independente de cobertura com o volume financeiro do candle."""
    actual_usd = number(row["buy_volume_usd"]) + number(row["sell_volume_usd"])
    actual_btc = number(row["buy_volume_btc"]) + number(row["sell_volume_btc"])
    expected_usd, expected_btc = number(candle["cost"]), number(candle["volume"])
    # USD é soma exata de quantidades. BTC sofre arredondamento em cada trade.
    if abs(actual_usd - expected_usd) > Decimal("0.01") or abs(actual_btc - expected_btc) > max(
        Decimal("0.00001"), expected_btc * Decimal("0.000001")
    ):
        raise RuntimeError(
            f"Volume divergente em {candle['datetime']}: negócios={actual_usd} USD / "
            f"{actual_btc} BTC; candle={expected_usd} USD / {expected_btc} BTC. "
            "Nenhum fluxo novo foi publicado; confira janela e atualização do candle."
        )


def coletar_fluxo(velas, fetch_json, output_dir, days=2, start_date=None, end_date=None):
    output_dir = Path(output_dir)
    daily_path = output_dir / "btc_fluxo_deribit_diario.csv"
    hourly_path = output_dir / "btc_fluxo_deribit_1h.csv"
    daily = {int(row["timestamp_ms"]): row for row in read_csv(daily_path)}
    hourly = {int(row["timestamp_ms"]): row for row in read_csv(hourly_path)}
    now_ms = int(time.time() * 1000)
    eligible = sorted((c for c in velas if c["timestamp_ms"] + DAY_MS <= now_ms), key=lambda c: c["timestamp_ms"])
    if start_date:
        start = date_ms(start_date) + SESSION_MS
        end = date_ms(end_date) + SESSION_MS if end_date else math.inf
        eligible = [c for c in eligible if start <= c["timestamp_ms"] <= end]
        if not eligible or eligible[0]["timestamp_ms"] != start or (
            end_date and eligible[-1]["timestamp_ms"] != end
        ):
            raise ValueError("Período de fluxo fora dos candles fechados disponíveis")
        if any(b["timestamp_ms"] - a["timestamp_ms"] != DAY_MS for a, b in zip(eligible, eligible[1:])):
            raise ValueError("Período de fluxo contém lacunas de candles")
    else:
        eligible = eligible[-days:]
    for candle in eligible:
        ts = candle["timestamp_ms"]
        if ts in daily and daily[ts].get("coverage_complete") == "true" and all(
            t in hourly and hourly[t].get("coverage_complete") == "true"
            for t in range(ts, ts + DAY_MS, HOUR_MS)
        ):
            validar_volume(candle, daily[ts])
            continue
        print(f"-> Coletando fluxo {candle['datetime']} (08:00 a 08:00 UTC)...", flush=True)
        # Um dia por vez limita a memória; só publica após todas as validações.
        trades = list(iter_trades(fetch_json, ts, ts + DAY_MS))
        day = agregar_fluxo(trades, ts, ts + DAY_MS, DAY_MS)[0]
        validar_volume(candle, day)
        hours = agregar_fluxo(trades, ts, ts + DAY_MS, HOUR_MS)
        daily[ts] = day
        hourly.update({row["timestamp_ms"]: row for row in hours})
        print(f"   [OK] {day['trade_count']} negócios; volume BTC e USD reconciliado", flush=True)
    daily_rows = list(recalcular_cvd(daily.values(), DAY_MS))
    hourly_rows = list(recalcular_cvd(hourly.values(), HOUR_MS))
    # Arquivos individuais são gravados atomicamente. Reexecução repara uma
    # eventual interrupção entre publicações: cache exige diário + 24 horas.
    atomic_csv(hourly_path, FLOW_FIELDS, hourly_rows)
    atomic_csv(daily_path, FLOW_FIELDS, daily_rows)
    return {int(row["timestamp_ms"]): row for row in daily_rows}


def coletar_open_interest(fetch_json, output_dir):
    """OI observado agora; não representa o fechamento de candles anteriores."""
    ticker = api_result(fetch_json, PUBLIC_URL, "ticker", instrument_name=INSTRUMENT)
    if ticker.get("instrument_name") != INSTRUMENT:
        raise RuntimeError("Ticker de instrumento inesperado")
    path = Path(output_dir) / "btc_open_interest_deribit.csv"
    rows = read_csv(path)
    snapshots = {int(row["timestamp_ms"]): row for row in rows}
    ts, oi = int(ticker["timestamp"]), number(ticker["open_interest"])
    if oi < 0:
        raise ValueError("Open Interest negativo")
    if ts in snapshots:
        return
    if snapshots and ts < max(snapshots):
        raise RuntimeError("Ticker anterior ao último snapshot; OI não atualizado")
    previous = snapshots[max(snapshots)] if snapshots else None
    previous_oi = number(previous["open_interest_usd"]) if previous else None
    stats = ticker["stats"]
    row = {
        "timestamp_ms": ts, "datetime_utc": iso(ts), "instrument_name": INSTRUMENT,
        "open_interest_usd": oi,
        "open_interest_change_usd": oi - previous_oi if previous else "",
        "open_interest_change_pct": (oi / previous_oi - 1) * 100 if previous_oi else "",
        "seconds_since_previous": (ts - max(snapshots)) / 1000 if snapshots else "",
        "volume_24h_btc": number(stats["volume"]),
        "volume_24h_usd": number(stats["volume_usd"]),
    }
    snapshots[ts] = row
    atomic_csv(path, OI_FIELDS, [snapshots[key] for key in sorted(snapshots)])
    print(f"-> Open Interest observado: {oi} USD em {iso(ts)}", flush=True)
