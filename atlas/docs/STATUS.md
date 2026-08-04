# ATLAS — Status do Projeto

**Versão:** 0.1.0  
**Data:** 2026-08-04  
**Branch:** `cursor/atlas-v1-7092`

## Implementado e validado

- Fundação FastAPI + config tipada + structlog
- PostgreSQL + SQLAlchemy 2 + Alembic
- `/health`, `/ready`, `/version`
- Coletor BTC multi-TF com fallback: **OKX → Coinbase → Binance → Bybit**
- Persistência de candles (dedupe), snapshots e decisões
- Market Structure, Correlation/Lead-Lag, Macro/Cross-Asset, News, Experience, Risk
- Liquidity/Derivatives: interface + `DATA_UNAVAILABLE`
- Council ponderado (prefere NO_TRADE sem edge)
- Relatório Markdown + JSON
- Avaliação posterior (sem recalibrar produção)
- Replay scaffolding (relógio virtual)
- Docker image build OK; `docker compose config` OK
- Testes: **22 passed**; ruff OK; mypy OK
- Smoke real: snapshot via OKX; análise completa com macro (Yahoo fallback) e correlação dinâmica

## Limitações reais observadas neste ambiente

1. **Binance** HTTP 451 (geo-block); **Bybit** HTTP 403.
2. **Stooq** anti-bot (HTML); macro usa **Yahoo chart API como fallback** (FRED preferido com chave).
3. **Derivativos** (funding/OI/liq/basis): `DATA_UNAVAILABLE`.
4. **FRED** exige `ATLAS_FRED_API_KEY`.
5. Experience v0.1 = similaridade estrutural local.
6. Pesos históricos do Council ainda são priors fixos.
7. Investigação adversarial apenas arquitetada.
8. Sem deploy em VPS/Railway nesta fase (Kronos intocado).

## Intervenção do usuário

- Opcional: `ATLAS_FRED_API_KEY` para yields/séries oficiais.
- Autorização explícita para deploy em VPS existente.
- Fontes premium de news, se desejar além de RSS públicos.

## Próximo marco

1. Funding/OI públicos (OKX/Binance futures quando acessível).
2. Walk-forward replay com embargo.
3. Dashboard mínimo + alertas de mudança de decisão.
4. Calibração versionada de pesos após N avaliações.
