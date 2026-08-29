# Cron e Telegram

## Tipos de mensagem `[KRONOS]`

| Mensagem | Quando |
|----------|--------|
| Serviço iniciado | Após deploy (boot) |
| Processando | Início de cada previsão |
| Previsão — DATA | Texto 1H/4H/D + gráficos + consenso + scorecard 7d |
| Scorecard | Trade fechado ou semanal |
| Relatório diário | 12:00 BRT — ranking por TF |

## Conflito entre timeframes

**Normal** — modelo prevê 3 horizontes separados.  
⚠️ = não usar como sinal único.  
✅ operável (4H) = entra na estatística.

## Filtro no app Telegram

- Railway: mesmo bot do monitor — filtre texto `KRONOS`
- BTCCURSOR: bot separado — só alertas Kronos
