# Watchlist

Tickers ativos = `TICKERS` no `.env` (default `BTC,ETH,SOL`). COMBO5 roda apenas nos
tickers de `COMBO5_TICKERS` (default `BTC`).

| Ticker | Fonte de dados | Nível de gatilho (LONG) | Nível de gatilho (SHORT) | Notas |
|---|---|---|---|---|
| BTC | MEXC + Hyperliquid + Kronos + COMBO5 | — preencher — | — preencher — | setup principal do COMBO5 |
| ETH | MEXC + Hyperliquid | — preencher — | — preencher — | |
| SOL | MEXC + Hyperliquid | — preencher — | — preencher — | |

Preencher "Nível de gatilho" com o nível técnico real (suporte/resistência, EMA, etc.)
antes de tratar qualquer alerta como setup válido — o scanner aponta candidatos, o
nível de gatilho é quem confirma.

## Como popular via Claude Code

```
Aqui estão os candidatos do scanner de hoje [colar tickers + dados básicos]. Rankeie
contra meus critérios de setup [colar rules/strategy.md]. Para cada um, diga quais
critérios cumpre, quais não cumpre, e se vale olhar de perto. Sem previsões.
```

Os 3 melhores do dia entram nesta tabela com nível de gatilho definido antes do
próximo scan.
