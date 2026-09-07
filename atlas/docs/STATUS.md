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

- `pytest` → **34 passed**
- `ruff` / `mypy` → OK
- Smoke: liquidity `AVAILABLE`; 2ª coleta com `previous_oi`/`oi_change`; `/derivatives/btc/recent` e `/evaluation/batch` OK
- Telegram `disabled` sem token; produção de pesos inalterada pelo batch

## Limitações

- Binance/Bybit geo-bloqueados; Stooq frágil → Yahoo fallback macro
- `oi_change` exige ≥2 observações persistidas
- Ativação de pesos requer chamada explícita `/weights/{id}/activate`
- Sem deploy VPS

## Próximo

- Scheduler de batch eval / coleta periódica
- Enriquecer dashboard com OI series e alerts Telegram status
- Mais amostras de avaliação para calibração real
