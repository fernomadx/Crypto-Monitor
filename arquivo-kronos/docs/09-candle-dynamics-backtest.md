# 09 — Candle Dynamics Backtest (BTC)

Bot + backtest da estratégia de dinâmica de candles (retração / impulsão / falha),
gap do pregão, hierarquia multi-TF e regras de proteção.

## Como rodar

```bash
python vps/candle_dynamics_backtest.py --years 5 --symbol BTCUSDT
python vps/candle_dynamics_backtest.py --years 5 --json-out data/candle_dynamics/btc_5y_report.json
```

Dados: Binance Vision (mensal) + fill do mês corrente via MEXC. Cache em `data/candle_dynamics/` (gitignored).

## Formalização usada no código

| Regra | Implementação |
|-------|----------------|
| Microfalha | Candle **fechado** M5: impulsão prévia + fecha dentro do gatilho anterior ou falha em romper máx/mín + reclaim/reject do 50% |
| Compra (gap/retração) | Zona D/W (fundo ou 50% diário) + microfalha de baixa |
| Venda (impulsão) | Zona 50% M30/H1 **e** resistência D/W + microfalha de alta + viés H1 bear; **não** vende no fundo pós gap-down |
| Hierarquia | M5 confirma; M30/H1 estrutura; D/W alvos. Sem antecipar fechamento |
| Risco | BE após movimento a favor; parcial no 50% em retração contra tendência |

## Resultado BTC 5 anos (2021-09-22 → 2026-09-22)

Rodado neste ambiente com posição $100 / capital $1000:

| Métrica | Valor |
|---------|-------|
| Barras M5 | 526 058 |
| Trades | 2 433 |
| Win rate | 19.4% |
| PnL | −$181.83 |
| Equity final | $818.17 |
| Profit factor | 0.59 |
| Max DD | $186.72 |
| Veredito | **INVALIDATED** |

Por tipo: `failure_long` −$196 / `impulse_short` +$15. Todos os anos 2021–2026 com PnL negativo.

A estratégia discricionária das notas assume leitura visual de “alinhamentos” e gatilhos que o código aproxima com Fibonacci 50% e swings — a automação estrita **não** reproduz edge no BTC spot neste horizonte.
