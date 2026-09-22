# 09 — Candle Dynamics Backtest (BTC)

Bot + backtest da estratégia de dinâmica de candles (retração / impulsão / falha),
gap do pregão, hierarquia multi-TF e regras de proteção.

## Como rodar

```bash
python vps/candle_dynamics_backtest.py --years 5 --version v2-short
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
| Risco | v2-short: lock +1R após 3R; hold 36h; swings HTF com `shift(1)`; viés H1 só com hora **fechada** |

## Auditoria do “$1000 → $7960” (2026-09-22)

### O que passava
- Soma dos trades = +$6960 → equity $7960 (aritmética OK)
- Sizing/stop/leverage por trade consistente; sem overlap; entry = close M5

### O que invalidava o número
1. **Look-ahead no viés H1** — `htf_bear` usava o **close final** da hora ainda aberta (resample full-history). Em **96%** dos trades o close H1 mudava depois da entrada; **61/154** sinais só existiam porque a hora *depois* fechou bear.
2. Com viés H1 só em candle fechado: equity cai de **$7960 → ~$431 (−57%)**, PF 0.49 → **INVALIDATED**.
3. Fee 0.04% RT otimista; com slip ~5 bps/lado o cenário viesado já caía para ~$3k.
4. Top 3 trades = **52%** do PnL viesado (concentração).
5. Max DD% reportado era vs capital inicial (57%); vs pico era ~10%.

### Resultado honesto BTC 5y — v2-short (pós-correção)

Capital $1000 · risk 2% · max 8x · profit-lock 3R→1R · hold 36h · **H1 close só fechado**

| Métrica | Valor |
|---------|-------|
| Trades | 135 |
| Win rate | 17.8% |
| PnL | **−$569** |
| Equity | **$431** |
| Retorno / CAGR | −56.9% / −15.5% |
| Profit factor | 0.49 |
| Max DD | 63.2% |
| Veredito | **INVALIDATED** |

```bash
python vps/candle_dynamics_backtest.py --years 5 --version v2-short --sizing risk
```

## Resultado BTC 5 anos — v1 vs v2 (fixed $100, referência)

| Métrica | v1 | v2 |
|---------|----|----|
| Trades | 2 433 | 241 |
| PnL | −$181.83 | −$6.72 |
| Veredito | INVALIDATED | INVALIDATED |
