# BTC Graph - Histórico de Preços e Vencimentos Deribit

Este repositório contém a automação em Python para coleta de dados de mercado do Bitcoin via APIs públicas (sem necessidade de chaves de autenticação ou cadastro).

---

## 📁 Arquivos Gerados

| Arquivo | Descrição | Registros | Cobertura / Período |
| :--- | :--- | :--- | :--- |
| **[`btc_ohlc_10_anos.csv`](btc_ohlc_10_anos.csv)** | Histórico completo de 10 anos de velas diárias (OHLCV). Transição contínua de Bitfinex (Spot) para Deribit (Perpétuo). | ~3.650 linhas | 2016 até o presente |
| **[`btc_ohlc_deribit_puro.csv`](btc_ohlc_deribit_puro.csv)** | Histórico integral da Deribit (`BTC-PERPETUAL`) desde o primeiro dia de negociação do contrato contínuo. | ~3.000 linhas | 14/08/2018 até o presente |
| **[`deribit_ciclos_vencimento.csv`](deribit_ciclos_vencimento.csv)** | Tabela consolidada de todos os **ciclos de vencimento** na Deribit, indicando a data exata de publicação/criação, vida útil em dias e contratos vinculados. | 14 ciclos | Diários, Semanais, Mensais, Trimestrais e Anuais |
| **[`deribit_todos_contratos.csv`](deribit_todos_contratos.csv)** | Mapeamento detalhado de **todos os 1.000+ contratos individuais** (Futuros e Opções por strike/put/call), com timestamps de criação e expiração. | ~1.000 linhas | Todos os contratos ativos e recentes |
| **[`coletar_dados.py`](coletar_dados.py)** | Script em Python (biblioteca padrão, sem necessidade de `pip install`) que baixa e atualiza todos os arquivos acima. | Script executável | - |

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

```bash
python coletar_dados.py
```

- **Zero dependências extras**: Usa apenas módulos nativos do Python (`urllib`, `json`, `csv`, `datetime`, `time`).
- **Codificação UTF-8 com BOM (`utf-8-sig`)**: Abre diretamente no Microsoft Excel, LibreOffice, Google Sheets e bibliotecas de dados sem erros de acentuação.
