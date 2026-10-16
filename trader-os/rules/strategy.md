# Estratégia — setups que eu opero

Checklist de referência para o Claude pontuar um setup (estágio 4, Trade Setup
Scoring). Um setup só vira trade plan se casar com um destes — "eu gosto do gráfico"
não é critério.

## Setup A — COMBO5: alinhamento 3TF Kronos + desk

Implementado em `lib/combo5/signal.py` (`evaluate_combo5`). Condições:

- [ ] Viés Kronos alinhado em 1h, 4h e 1d (`bias_1h == bias_4h == bias_1d`, todos
      BULLISH ou todos BEARISH — threshold `COMBO5_KRONOS_THR_PCT`, default 0.35%)
- [ ] Força do movimento 4h ≥ `COMBO5_MIN_STRENGTH_PCT` (default 0.8%)
- [ ] EMA 4h (rápida vs. lenta) alinhada ao viés
- [ ] Trade Desk (técnico + momentum + estrutura) concorda com o lado e
      confiança ≥ `COMBO5_MIN_DESK_CONF` (default 0.65)
- [ ] ATR% do candle 1h dentro da faixa `[COMBO5_ATR_MIN_PCT, COMBO5_ATR_MAX_PCT]`
      (default 0.5%–1.1%) — fora disso é vela demais ou de menos para o setup
- Invalidação: qualquer TF sai do alinhamento, ou desk diverge do Kronos.

## Setup B — Funding extremo (Hyperliquid)

Implementado em `agents/hyperliquid.py`. Condições:

- [ ] |funding rate| ≥ `FUNDING_THRESHOLD` (default 0.0005 = 0.05%)
- [ ] Funding muito positivo → longs pagando shorts → viés de mean-reversion contra a
      multidão alavancada (cautela em novo LONG); muito negativo → o inverso
- [ ] Cruzar com viés técnico/Kronos antes de agir — funding sozinho não é gatilho de
      entrada, é confirmação ou alerta de exaustão

## Setup C — Sentimento extremo confirmado

Implementado em `agents/sentiment.py`. Condições:

- [ ] VADER sinaliza |score| ≥ `VADER_THRESHOLD` (default 0.5) em manchete recente
- [ ] Claude Haiku confirma com |score| ≥ 0.7 (camada 2, filtra ruído/hype)
- [ ] Notícia é catalisador NOVO (não já precificado) — checar timestamp vs. movimento
      de preço já ocorrido
- [ ] Sentimento não contradiz o viés técnico do momento — se contradiz, é red flag,
      não confirmação

## Setup D — Consenso 4h (orchestrator)

Implementado em `agents/orchestrator.py`. Usar como filtro de contexto macro, não como
gatilho isolado: se o consenso 4h é BEARISH forte, evitar novos LONGs em qualquer dos
setups acima até o consenso mudar ou o setup A/B/C ter força excepcional.

## Regra geral de scoring (estágio 4)

Score 1–10 = soma ponderada:

- Alinhamento técnico (Setup A) — peso 4
- Confirmação de desk multi-agente — peso 3
- Sentimento/notícia (Setup C) — peso 1.5
- Funding/estrutura de mercado (Setup B) — peso 1.5

Barra mínima para virar trade plan: **7/10**. Abaixo disso, watchlist apenas — sem
plano de entrada.
