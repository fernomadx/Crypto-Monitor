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
| Risco | v2-short: lock +1R após 3R (não BE flat); parcial 50% em retração CT |

## Resultado BTC 5 anos — v1 vs v2 (2021-09-22 → 2026-09-22)

Posição $100 / capital $1000.

| Métrica | v1 | v2 | Δ |
|---------|----|----|---|
| Trades | 2 433 | 241 | −2 192 |
| Win rate | 19.4% | 15.5% | −3.9 pp |
| PnL | −$181.83 | −$6.72 | **+$175** |
| Equity | $818 | $993 | +$175 |
| Profit factor | 0.59 | 0.96 | +0.37 |
| Max DD | $186.72 | $15.01 | **−$172** |
| Veredito | INVALIDATED | INVALIDATED | — |

### O que o v2 mudou
1. Long só gap-retrace / fundo semanal (sem `failure_long` genérico no mid diário)
2. Short exige impulsão de alta no **M30** antes da microfalha M5
3. BE seletivo + fee-aware; hold até 12h
4. Cooldown 6h + 1 setup por zona D/W + corpo mínimo no candle

### Por tipo (v2)
- `impulse_short`: 153 trades, **+$13.92**, WR 25%
- `failure_long` restante: 88 trades, **−$20.64**, WR 2.1% ← ainda sangra

### Ablation `v2-short` — sizing + profit-lock (retorno absoluto)

O +$35 com posição fixa $100 era **subutilização de capital**. Bottleneck seguinte:
alavancagem média ~4.7x no teto de 5x, e BE flat @2.5R transformava runners em zeros.

Perfil atual (padrão CLI): **risk 2% / max 8x**, hold **36h**, stop trava **+1R após 3R**
(em vez de BE na entrada).

| | Fixo $100 | Risk 1.5%/5x BE@2.5R | **Risk 2%/8x lock 3→1** |
|--|-----------|----------------------|-------------------------|
| Equity | $1 036 | $3 499 | **$7 960** |
| Retorno 5y | +3.6% | +249.9% | **+696.0%** |
| CAGR | ~0.7% | +28.5% | **+51.4%** |
| PF | 2.87 | 2.46 | **2.89** |
| Max DD | 0.4% | 27.8% | **57.1%** |
| Avg lev | — | 4.7x | **7.2x** |
| Win rate | — | — | **44.6%** |

PnL positivo em todos os anos 2022–2026. DD maior é o preço do compound com lev 8x.

```bash
# Retorno absoluto (recomendado — defaults)
python vps/candle_dynamics_backtest.py --years 5 --version v2-short --sizing risk

# Conservador (1.5% / 5x)
python vps/candle_dynamics_backtest.py --years 5 --version v2-short --sizing risk --risk-pct 1.5 --max-leverage 5

# Comparar setups com notional fixo
python vps/candle_dynamics_backtest.py --years 5 --version v2-short --sizing fixed --position 100
python vps/candle_dynamics_backtest.py --years 5 --compare
```

