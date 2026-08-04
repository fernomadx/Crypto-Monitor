# ATLAS — Status do Projeto

**Versão:** 0.3.0  
**Data:** 2026-08-04  
**Branch:** `cursor/atlas-v1-7092`

## v0.3 — próximo marco entregue

1. **Série OI persistida** (`derivative_observations`) → `oi_change` / `oi_change_pct` entre coletas
2. **Telegram opcional** via `ATLAS_TELEGRAM_*` (sem secrets no git; desabilitado se vazio)
3. **Avaliação em lote** `POST /evaluation/batch` + avaliação unitária; proposta de pesos após N outcomes (nunca auto-ativa produção)
4. Endpoints: `GET /derivatives/btc/recent`, `POST /evaluation/decisions/{id}`

## Validação

- `pytest` / `ruff` / `mypy` — ver commit
- Smoke: segunda coleta com OI anterior → `oi_change` não-nulo; Telegram `disabled` sem token; batch retorna `production_weights_unchanged`

## Limitações

- Binance/Bybit geo-bloqueados; Stooq frágil → Yahoo fallback macro
- `oi_change` exige ≥2 observações persistidas
- Ativação de pesos requer chamada explícita `/weights/{id}/activate`
- Sem deploy VPS

## Próximo

- Scheduler de batch eval / coleta periódica
- Enriquecer dashboard com OI series e alerts Telegram status
- Mais amostras de avaliação para calibração real
