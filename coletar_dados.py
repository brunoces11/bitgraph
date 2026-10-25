#!/usr/bin/env python3
"""
Coletor de Dados de Mercado - Deribit & Bitcoin
------------------------------------------------
Este script realiza duas tarefas principais utilizando endpoints públicos (sem necessidade de chave de API):
1. Download do histórico diário de preços do Bitcoin (OHLCV) dos últimos 10 anos:
   - 2016 a 2018: Bitfinex (BTC/USD Spot)
   - 2018 a atual: Deribit (BTC-PERPETUAL)
   - Também salva um arquivo dedicado exclusivamente ao histórico da Deribit.
2. Mapeamento das datas de vencimento e datas de publicação (criação) de contratos da Deribit (Futuros e Opções).

Desenvolvido para execução com a biblioteca padrão do Python (sem dependências externas).
"""

import csv
from datetime import datetime, timezone
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Constantes e caminhos
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
DERIBIT_BASE_URL = "https://www.deribit.com/api/v2/public"
BITFINEX_BASE_URL = "https://api-pub.bitfinex.com/v2"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_json(url, retries=3, delay=2):
    """Realiza requisição HTTP GET retornando o JSON decodificado."""
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries:
                raise RuntimeError(
                    f"Falha ao conectar com {url} após {retries} tentativas: {e}"
                )
            time.sleep(delay * attempt)


def ms_to_iso(ms):
    """Converte timestamp em milissegundos para string ISO UTC (YYYY-MM-DD HH:MM:SS UTC)."""
    if not ms or ms > 3000000000000:  # Ex: vencimento do perpétuo
        return "PERPETUO (Sem vencimento)"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def ms_to_date_only(ms):
    """Converte timestamp em milissegundos para data UTC (YYYY-MM-DD)."""
    if not ms or ms > 3000000000000:
        return "N/A"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d"
    )


# ==============================================================================
# 1. COLETA DO HISTÓRICO DE PREÇOS (OHLCV)
# ==============================================================================


def coletar_historico_deribit(start_ms, end_ms):
    """Coleta velas diárias de BTC-PERPETUAL na Deribit."""
    print("-> Coletando velas diárias da Deribit (BTC-PERPETUAL)...")
    url = (
        f"{DERIBIT_BASE_URL}/get_tradingview_chart_data"
        f"?instrument_name=BTC-PERPETUAL"
        f"&start_timestamp={start_ms}&end_timestamp={end_ms}&resolution=1D"
    )
    res = fetch_json(url)
    if "result" not in res or res["result"].get("status") != "ok":
        raise RuntimeError(f"Erro na resposta da Deribit: {res}")

    data = res["result"]
    ticks = data.get("ticks", [])
    opens = data.get("open", [])
    highs = data.get("high", [])
    lows = data.get("low", [])
    closes = data.get("close", [])
    volumes = data.get("volume", [])
    costs = data.get("cost", [])

    velas = []
    for i in range(len(ticks)):
        velas.append(
            {
                "timestamp_ms": ticks[i],
                "datetime": datetime.fromtimestamp(
                    ticks[i] / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d"),
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i],
                "cost": costs[i],
                "source": "Deribit BTC-PERPETUAL",
            }
        )

    print(
        f"   [Deribit] {len(velas)} velas diárias obtidas (de {velas[0]['datetime']} a {velas[-1]['datetime']})."
    )
    return velas


def coletar_historico_bitfinex(start_ms, end_ms):
    """Coleta velas diárias de BTCUSD na Bitfinex para o período de 2016 até o início da Deribit."""
    print("-> Coletando histórico complementar (2016 a 2018) via Bitfinex...")
    url = (
        f"{BITFINEX_BASE_URL}/candles/trade:1D:tBTCUSD/hist"
        f"?start={start_ms}&end={end_ms}&limit=10000&sort=1"
    )
    res = fetch_json(url)
    if not isinstance(res, list):
        print(
            f"   [Aviso] Resposta inesperada da Bitfinex: {res}. Continuando sem histórico pré-2018."
        )
        return []

    # Formato Bitfinex: [MTS, OPEN, CLOSE, HIGH, LOW, VOLUME]
    velas = []
    for item in res:
        ts = item[0]
        velas.append(
            {
                "timestamp_ms": ts,
                "datetime": datetime.fromtimestamp(
                    ts / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d"),
                "open": item[1],
                "high": item[3],
                "low": item[4],
                "close": item[2],
                "volume": item[5],
                "cost": round(item[5] * item[2], 2),  # Estimativa de volume USD
                "source": "Bitfinex BTCUSD (Spot)",
            }
        )

    if velas:
        print(
            f"   [Bitfinex] {len(velas)} velas diárias obtidas (de {velas[0]['datetime']} a {velas[-1]['datetime']})."
        )
    return velas


def salvar_precos(velas_deribit, velas_completas):
    """Salva os arquivos CSV de preço."""
    # 1. Arquivo somente Deribit
    path_deribit = os.path.join(OUTPUT_DIR, "btc_ohlc_deribit_puro.csv")
    with open(path_deribit, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["datetime", "open", "high", "low", "close", "volume", "cost_btc"]
        )
        for v in velas_deribit:
            writer.writerow(
                [
                    v["datetime"],
                    v["open"],
                    v["high"],
                    v["low"],
                    v["close"],
                    v["volume"],
                    v["cost"],
                ]
            )
    print(f"-> Salvo: {path_deribit} ({len(velas_deribit)} registros)")

    # 2. Arquivo 10 anos completos
    path_10y = os.path.join(OUTPUT_DIR, "btc_ohlc_10_anos.csv")
    with open(path_10y, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "cost_volume",
                "source",
            ]
        )
        for v in velas_completas:
            writer.writerow(
                [
                    v["datetime"],
                    v["open"],
                    v["high"],
                    v["low"],
                    v["close"],
                    v["volume"],
                    v["cost"],
                    v["source"],
                ]
            )
    print(f"-> Salvo: {path_10y} ({len(velas_completas)} registros)")


# ==============================================================================
# 2. COLETA DE VENCIMENTOS E DATAS DE PUBLICAÇÃO DERIBIT
# ==============================================================================


def coletar_instrumentos_deribit():
    """Coleta todos os contratos (Futuros e Opções) ativos e recentemente expirados da Deribit."""
    print(
        "-> Consultando contratos de Futuros e Opções da Deribit para mapear vencimentos..."
    )

    contratos = []
    # Consultar futuros (ativos e expirados) e opções (ativas e expiradas)
    consultas = [
        ("future", "false"),
        ("future", "true"),
        ("option", "false"),
        ("option", "true"),
    ]

    ids_vistos = set()
    for kind, expired in consultas:
        url = f"{DERIBIT_BASE_URL}/get_instruments?currency=BTC&kind={kind}&expired={expired}"
        try:
            res = fetch_json(url)
            items = res.get("result", [])
            for item in items:
                name = item["instrument_name"]
                if name not in ids_vistos:
                    ids_vistos.add(name)
                    contratos.append(item)
        except Exception as e:
            print(f"   [Aviso] Falha ao consultar {kind} (expired={expired}): {e}")

    print(
        f"   Total de contratos individuais localizados na Deribit: {len(contratos)}"
    )
    return contratos


def processar_e_salvar_vencimentos(contratos):
    """Processa os dados de contratos gerando:
    1. deribit_ciclos_vencimento.csv: Visão agregada por ciclo/data de vencimento
    2. deribit_todos_contratos.csv: Visão detalhada de cada instrumento e strike
    """
    now_ms = int(time.time() * 1000)

    # 1. Agregação por data de vencimento
    ciclos = {}
    lista_detalhada = []

    for c in contratos:
        name = c["instrument_name"]
        kind = c["kind"]
        created_ms = c["creation_timestamp"]
        exp_ms = c["expiration_timestamp"]
        is_perp = exp_ms > 3000000000000

        # Cálculo de duração
        if is_perp:
            vida_dias = "PERPETUO"
            dias_restantes = "N/A"
        else:
            vida_dias = round((exp_ms - created_ms) / 86400000, 1)
            dias_restantes = round((exp_ms - now_ms) / 86400000, 1)

        strike = c.get("strike", "N/A")
        opt_type = c.get("option_type", "N/A")
        settlement_period = c.get("settlement_period", "N/A")
        is_active = c.get("is_active", True)

        lista_detalhada.append(
            {
                "instrument_name": name,
                "kind": kind,
                "data_publicacao_utc": ms_to_iso(created_ms),
                "data_vencimento_utc": ms_to_iso(exp_ms),
                "vida_contrato_dias": vida_dias,
                "dias_restantes": dias_restantes,
                "settlement_period": settlement_period,
                "strike": strike,
                "option_type": opt_type,
                "ativo": is_active,
                "timestamp_publicacao_ms": created_ms,
                "timestamp_vencimento_ms": exp_ms,
            }
        )

        # Agrupar ciclos de vencimento
        ciclo_key = exp_ms
        if ciclo_key not in ciclos:
            ciclos[ciclo_key] = {
                "expiration_ms": exp_ms,
                "earliest_creation_ms": created_ms,
                "latest_creation_ms": created_ms,
                "settlement_period": settlement_period,
                "kinds": set(),
                "total_instruments": 0,
                "sample_instrument": name,
            }
        ciclos[ciclo_key]["kinds"].add(kind)
        ciclos[ciclo_key]["total_instruments"] += 1
        if created_ms < ciclos[ciclo_key]["earliest_creation_ms"]:
            ciclos[ciclo_key]["earliest_creation_ms"] = created_ms
        if created_ms > ciclos[ciclo_key]["latest_creation_ms"]:
            ciclos[ciclo_key]["latest_creation_ms"] = created_ms
        if kind == "future":
            ciclos[ciclo_key]["sample_instrument"] = name

    # Salvar tabela de ciclos únicos
    path_ciclos = os.path.join(OUTPUT_DIR, "deribit_ciclos_vencimento.csv")
    with open(path_ciclos, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "data_vencimento_utc",
                "data_publicacao_utc",
                "vida_contrato_dias",
                "dias_restantes_ate_vencer",
                "periodo_liquidacao",
                "tipos_disponiveis",
                "total_instrumentos",
                "instrumento_referencia",
            ]
        )

        # Ordenar ciclos cronologicamente por vencimento
        for exp_ms, info in sorted(ciclos.items(), key=lambda x: x[0]):
            is_perp = exp_ms > 3000000000000
            vida_dias = (
                "PERPETUO"
                if is_perp
                else round(
                    (exp_ms - info["earliest_creation_ms"]) / 86400000, 1
                )
            )
            dias_rest = (
                "N/A" if is_perp else round((exp_ms - now_ms) / 86400000, 1)
            )

            writer.writerow(
                [
                    ms_to_iso(exp_ms),
                    ms_to_iso(info["earliest_creation_ms"]),
                    vida_dias,
                    dias_rest,
                    info["settlement_period"],
                    "/".join(sorted(info["kinds"])),
                    info["total_instruments"],
                    info["sample_instrument"],
                ]
            )

    print(
        f"-> Salvo: {path_ciclos} ({len(ciclos)} ciclos de vencimento mapeados)"
    )

    # Salvar tabela detalhada de todos os contratos
    path_detalhado = os.path.join(OUTPUT_DIR, "deribit_todos_contratos.csv")
    with open(path_detalhado, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "instrument_name",
                "kind",
                "data_publicacao_utc",
                "data_vencimento_utc",
                "vida_contrato_dias",
                "dias_restantes",
                "periodo_liquidacao",
                "strike",
                "option_type",
                "ativo",
            ]
        )
        # Ordenar por timestamp de vencimento e depois por nome
        for item in sorted(
            lista_detalhada,
            key=lambda x: (x["timestamp_vencimento_ms"], x["instrument_name"]),
        ):
            writer.writerow(
                [
                    item["instrument_name"],
                    item["kind"],
                    item["data_publicacao_utc"],
                    item["data_vencimento_utc"],
                    item["vida_contrato_dias"],
                    item["dias_restantes"],
                    item["settlement_period"],
                    item["strike"],
                    item["option_type"],
                    item["ativo"],
                ]
            )

    print(f"-> Salvo: {path_detalhado} ({len(lista_detalhada)} contratos)")


# ==============================================================================
# EXECUÇÃO PRINCIPAL
# ==============================================================================


def main():
    print("=" * 70)
    print("COLETOR DE DADOS DE MERCADO - BITCOIN & DERIBIT")
    print("=" * 70)

    now_ms = int(time.time() * 1000)
    # 10 anos atrás (~3.652 dias)
    ten_years_ago_ms = now_ms - (10 * 365 * 24 * 3600 * 1000)

    # 1. Coletar velas Deribit
    velas_deribit = coletar_historico_deribit(ten_years_ago_ms, now_ms)

    # Data de início da Deribit obtida
    first_deribit_ms = (
        velas_deribit[0]["timestamp_ms"]
        if velas_deribit
        else 1534242287000  # 14/08/2018
    )

    # 2. Coletar velas Bitfinex para completar os 10 anos (de 10 anos atrás até o início da Deribit)
    velas_bitfinex = coletar_historico_bitfinex(
        ten_years_ago_ms, first_deribit_ms - 86400000
    )

    # Unir séries históricas
    velas_10y = velas_bitfinex + velas_deribit
    salvar_precos(velas_deribit, velas_10y)

    # 3. Coletar instrumentos e datas de vencimento / publicação
    contratos = coletar_instrumentos_deribit()
    processar_e_salvar_vencimentos(contratos)

    print("\n" + "=" * 70)
    print("CONCLUÍDO COM SUCESSO!")
    print(
        f"Todos os arquivos foram gerados no diretório: {OUTPUT_DIR}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
