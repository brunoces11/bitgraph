# BTC Graph - Histórico de Preços e Vencimentos Deribit

[English](README.md) | [Português](README.pt-BR.md)

---

Este repositório contém a automação em Python para coleta de dados de mercado do Bitcoin via APIs públicas (sem necessidade de chaves de autenticação ou cadastro).

## Volume, agressão e Open Interest

O coletor agora adiciona volume explícito em BTC e USD, RVOL de 20 sessões e, nas sessões de fluxo coletadas, volume por agressão compradora/vendedora, delta e CVD. Também mantém um histórico local de snapshots de Open Interest.

| Informação | Já existia? | Coleta/cálculo e utilidade para análise |
| :--- | :--- | :--- |
| Volume BTC e volume financeiro USD | Sim, mas com nomes ambíguos | `get_tradingview_chart_data`: ajuda a medir contração/expansão da atividade. `volume_btc` é o volume base; `volume_usd` é o financeiro. |
| RVOL de 20 sessões | Não | Volume BTC do candle fechado dividido pela média dos **20 candles anteriores fechados**, da mesma fonte. Permite comparar a atividade com sua própria referência recente. |
| Agressão compradora/vendedora, delta e CVD | Não | Negócios individuais via servidor `history.deribit.com`. Delta = compras agressoras menos vendas agressoras; CVD = soma dos deltas a partir da âncora informada. Ajuda a investigar pressão e divergências com preço. |
| Open Interest e variação entre observações | Não | `public/ticker`: posições em aberto em USD no BTC-PERPETUAL. É uma medida de estoque de posições, complementar ao fluxo negociado, e não indica direção sozinha. |

São **três fontes públicas da Deribit** (candles, negócios e ticker); RVOL, delta e CVD são métricas derivadas, não fontes independentes. Nenhuma delas, isoladamente, comprova antecipação ou confirma um rompimento. A capacidade preditiva precisa ser medida em backtest com regras e resultados fora da amostra.

### Arquivos e cobertura

- `btc_ohlc_deribit_puro.csv` e `btc_ohlc_10_anos.csv`: preservam as colunas originais e acrescentam `timestamp_ms`, início/fim do candle em UTC, `candle_closed`, `volume_btc`, `volume_usd`, `volume_usd_estimated`, `volume_sma20_btc`, `rvol20`, `buy_volume_usd`, `sell_volume_usd`, `delta_usd`, `cvd_usd`, `cvd_start_utc` e `flow_coverage_complete`.
- `btc_fluxo_deribit_diario.csv`: fluxo das sessões coletadas, incluindo volumes compradores/vendedores em BTC/USD, deltas, proporção compradora, número de negócios e CVD.
- `btc_fluxo_deribit_1h.csv`: as mesmas métricas em janelas de uma hora, para permitir examinar a evolução dentro das sessões diárias.
- `btc_open_interest_deribit.csv`: um snapshot por timestamp do ticker, variação absoluta/percentual e segundos desde a observação anterior.

**O fluxo padrão cobre as duas últimas sessões fechadas.** Não há backfill automático de milhões de negócios de todos os anos. Períodos históricos podem ser pedidos pelas opções abaixo; as sessões já coletadas são reutilizadas. O arquivo de uma hora contém as mesmas sessões históricas fechadas; ele não é uma assinatura em tempo real. OI é observado a cada execução, sem agendamento automático. O primeiro snapshot tem variação vazia, pois não há observação anterior. O coletor não preenche OI de 2018–2026 com o valor atual: os endpoints utilizados não fornecem essa série histórica.

### Unidades, horários e dados ausentes

- **Deribit diário: 08:00 até 08:00 UTC do dia seguinte.** O timestamp real é preservado. Bitfinex usa seus timestamps originais; ao migrar CSVs antigos, suas datas são interpretadas às 00:00 UTC, e as da Deribit às 08:00 UTC. Portanto, a série combinada muda de mercado (spot para perpétuo) e de janela diária. O RVOL reinicia na mudança de fonte e em lacunas.
- `cost_btc` é um **nome legado incorreto**: seus valores sempre vieram de `cost`, o volume financeiro USD da Deribit. A coluna é mantida para compatibilidade; use `volume_usd`. `volume` continua sendo BTC.
- Na Bitfinex, `volume_usd` permanece uma **estimativa** (`volume × close`), marcada por `volume_usd_estimated=true`; na Deribit é o valor informado pela API.
- O RVOL fica vazio nos primeiros 20 candles de cada trecho e em candles ainda abertos. Não mistura spot/perpétuo nem usa o próprio candle na média.
- Fluxo não coletado fica vazio e `flow_coverage_complete=false`, não zero. CVD reinicia depois de lacunas e informa sua âncora em `cvd_start_utc`. CVD diário e horário compartilham a âncora quando cobrem as mesmas sessões.
- A quantidade `amount` de um negócio de BTC-PERPETUAL já está em USD; `amount / price` produz BTC. Não se multiplica por `contract_size` novamente.

### Atualizar somente volume

```powershell
python coletar_dados.py --somente-volume
```
**O que este código faz exatamente?**
1. Lê os CSVs existentes, atualiza candles recentes e calcula volume/RVOL.
2. Coleta as duas últimas sessões fechadas de fluxo e registra o OI observado agora, sem atualizar os contratos de vencimento.

### Coletar um período histórico de fluxo

```powershell
python coletar_dados.py --somente-volume --inicio-fluxo 2018-08-15 --fim-fluxo 2018-08-16
```
**O que este código faz exatamente?**
1. Coleta as sessões com abertura às 08:00 UTC de 15 e 16 de agosto de 2018, incluindo a sessão final inteira.
2. Salva fluxo diário e horário e incorpora as métricas nos CSVs de preços; preserva as sessões já coletadas.

`--dias-fluxo N` altera a quantidade de sessões recentes (padrão: 2).
`--inicio-fluxo` sem `--fim-fluxo` coleta até a última sessão fechada disponível.
Datas fora do histórico disponível ou de candles ainda abertos são rejeitadas.

### Validação e publicação

Páginas com `has_more=true` são subdivididas em intervalos de tempo disjuntos, até obter respostas completas. Isso evita perder negócios com o mesmo milissegundo ou sequência fora de ordem. Duplicatas de `trade_id` são eliminadas; truncamento irredutível, erros da API e dados inválidos interrompem a coleta.
Antes de publicar, o volume USD agregado deve bater com o candle a US$ 0,01; para BTC, a tolerância é o maior entre 0,00001 BTC e 0,0001% do candle, devido ao arredondamento dos negócios. Divergências não são publicadas como fluxo completo.
Cada CSV de volume/preço é substituído atomicamente; os arquivos não formam uma transação conjunta. O cache exige o diário e suas 24 horas correspondentes, permitindo reparar uma execução interrompida entre publicações.

```powershell
python -m unittest -v test_volume_deribit
```
**O que este código faz exatamente?**
1. Verifica unidades, janelas de sessão, RVOL sem dados futuros, CVD com lacunas e paginação com timestamps repetidos.
2. Verifica reconciliação, compatibilidade dos CSVs, cache, snapshots e falhas sem publicação de fluxo incompleto.

Referências oficiais:
[candles e unidades](https://docs.deribit.com/api-reference/market-data/public-get_tradingview_chart_data),
[negócios e direção do agressor](https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_instrument),
[ticker e Open Interest](https://docs.deribit.com/api-reference/market-data/public-ticker),
[servidor de histórico, guia institucional, p. 31](https://statics.deribit.com/files/DeribitInstitutionalSetupGuide.pdf),
[sessões às 08:00 UTC](https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement).

Validação real em **25/10/2026**: 14 testes automatizados aprovados e 601.529 negócios coletados nas sessões abaixo, com reconciliação de volume BTC/USD contra os candles. Os 48 intervalos de uma hora somam os mesmos totais diários. A reexecução preservou os dois arquivos de fluxo byte a byte, e dois snapshots reais de OI validaram o cálculo da variação entre observações.

| Abertura da sessão (UTC) | Negócios | Volume financeiro USD | Delta USD |
| :--- | ---: | ---: | ---: |
| 2026-10-23 08:00 | 366.908 | 984.537.870 | +8.713.410 |
| 2026-10-24 08:00 | 234.621 | 765.445.100 | -3.890.140 |

O histórico anterior a 23/10/2026 manteve todos os valores das colunas originais. Os CSVs passaram a conter 3.650 registros na série combinada e 2.995 na Deribit, incluindo o candle aberto de 25/10/2026, identificado como `candle_closed=false`.

---

## 📁 Arquivos Gerados

| Arquivo | Descrição | Registros | Cobertura / Período |
| :--- | :--- | :--- | :--- |
| **[`btc_ohlc_10_anos.csv`](btc_ohlc_10_anos.csv)** | Histórico completo de 10 anos de velas diárias (OHLCV). Transição contínua de Bitfinex (Spot) para Deribit (Perpétuo). | ~3.650 linhas | 2016 até o presente |
| **[`btc_ohlc_deribit_puro.csv`](btc_ohlc_deribit_puro.csv)** | Histórico integral da Deribit (`BTC-PERPETUAL`) desde o primeiro dia de negociação do contrato contínuo. | ~3.000 linhas | 14/08/2018 até o presente |
| **[`btc_fluxo_deribit_diario.csv`](btc_fluxo_deribit_diario.csv)** | Fluxo de ordens das sessões diárias fechadas com métricas de agressão, delta e CVD. | Sessões coletadas | Sessões recentes e histórico sob demanda |
| **[`btc_fluxo_deribit_1h.csv`](btc_fluxo_deribit_1h.csv)** | Detalhamento horário (1 hora) do fluxo das sessões diárias fechadas. | Janelas horárias | 24 janelas por sessão diária |
| **[`btc_open_interest_deribit.csv`](btc_open_interest_deribit.csv)** | Snapshots pontuais de Open Interest do `BTC-PERPETUAL` e variação entre coletas. | Histórico cumulativo | Cada execução do script |
| **[`deribit_ciclos_vencimento.csv`](deribit_ciclos_vencimento.csv)** | Tabela consolidada de todos os **ciclos de vencimento** na Deribit, indicando data de publicação, vida útil e contratos vinculados. | 14 ciclos | Diários, Semanais, Mensais, Trimestrais e Anuais |
| **[`deribit_todos_contratos.csv`](deribit_todos_contratos.csv)** | Mapeamento detalhado de **todos os 1.000+ contratos individuais** (Futuros e Opções por strike/put/call), com timestamps de criação e expiração. | ~1.000 linhas | Todos os contratos ativos e recentes |
| **[`coletar_dados.py`](coletar_dados.py)** | Script principal em Python que orquestra a coleta de todos os dados acima. | Script executável | - |
| **[`volume_deribit.py`](volume_deribit.py)** | Módulo dedicado de coleta, paginação resiliente, cálculo de fluxo e reconciliação de volume. | Módulo Python | - |
| **[`test_volume_deribit.py`](test_volume_deribit.py)** | Suíte de testes unitários para cálculo de volume, reconciliação, RVOL, CVD e integridade dos CSVs. | Suíte de Testes | - |

---

## 📅 Ciclos de Vencimento Deribit (Publicação vs Expiração)

Abaixo estão os ciclos mapeados diretamente da API da Deribit:

| Vencimento (UTC) | Publicado em (UTC) | Duração do Contrato | Período | Tipos | Instrumento de Referência |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **2026-10-25 08:00:00** | 2026-10-21 08:00:11 | 4 dias | Diário (`day`) | Futuro / Opções | `BTC-25OCT26` |
| **2026-10-26 08:00:00** | 2026-10-22 08:00:11 | 4 dias | Diário (`day`) | Futuro / Opções | `BTC-26OCT26` |
| **2026-10-27 08:00:00** | 2026-10-23 08:00:11 | 4 dias | Diário (`day`) | Futuro / Opções | `BTC-27OCT26` |
| **2026-10-28 08:00:00** | 2026-10-24 08:00:10 | 4 dias | Diário (`day`) | Futuro / Opções | `BTC-28OCT26` |
| **2026-10-30 08:00:00** | 2026-07-30 08:00:13 | 92 dias (~3 meses) | Mensal (`month`) | Futuro / Opções | `BTC-30OCT26` |
| **2026-11-06 08:00:00** | 2026-10-15 08:00:11 | 22 dias (~3 semanas) | Semanal (`week`) | Futuro / Opções | `BTC-6NOV26` |
| **2026-11-13 08:00:00** | 2026-10-22 08:00:11 | 22 dias (~3 semanas) | Semanal (`week`) | Futuro / Opções | `BTC-13NOV26` |
| **2026-11-27 08:00:00** | 2026-08-27 08:00:24 | 92 dias (~3 meses) | Mensal (`month`) | Futuro / Opções | `BTC-27NOV26` |
| **2026-12-25 08:00:00** | 2025-12-25 08:00:15 | 365 dias (1 ano) | Anual (`month`) | Futuro / Opções | `BTC-25DEC26` |
| **2027-03-26 08:00:00** | 2026-03-26 08:00:27 | 365 dias (1 ano) | Anual (`month`) | Futuro / Opções | `BTC-26MAR27` |
| **2027-06-25 08:00:00** | 2026-06-25 08:00:14 | 365 dias (1 ano) | Anual (`month`) | Futuro / Opções | `BTC-25JUN27` |
| **2027-09-24 08:00:00** | 2026-09-24 08:00:23 | 365 dias (1 ano) | Anual (`month`) | Futuro / Opções | `BTC-24SEP27` |
| **Sem vencimento** | 2018-08-14 10:24:47 | Perpétuo | Perpétuo | Futuro | `BTC-PERPETUAL` |

> **Nota sobre o exemplo citado (`BTC-26MAR27`)**:
> O contrato com vencimento em **26 de março de 2027 às 08:00 UTC** foi criado e publicado pela Deribit em **26 de março de 2026 às 08:00:27 UTC** (exatamente 365 dias antes de seu vencimento, seguindo o ciclo padrão de 1 ano de antecedência para contratos de março/junho/setembro/dezembro).

---

## 🚀 Como Executar / Atualizar os Dados

Para atualizar todos os arquivos a qualquer momento, abra o terminal nesta pasta e execute:

```powershell
python coletar_dados.py
```
**O que este código faz exatamente?**
1. Atualiza preços, volumes e métricas de fluxo e registra um snapshot de Open Interest.
2. Atualiza os arquivos de contratos e ciclos de vencimento da Deribit.

- **Zero dependências extras**: Usa apenas módulos nativos do Python (`urllib`, `json`, `csv`, `datetime`, `time`).
- **Codificação UTF-8 com BOM (`utf-8-sig`)**: Abre diretamente no Microsoft Excel, LibreOffice, Google Sheets e bibliotecas de dados sem erros de acentuação.
