# ATLAS — Status do Projeto

**Versão:** 0.2.0  
**Data:** 2026-08-04  
**Branch:** `cursor/atlas-v1-7092`

## v0.2 — próximo marco entregue

1. **Liquidity/Derivatives** conectado via OKX pública (funding, OI, basis, liquidações)
2. **Walk-forward replay** com purge + embargo (`POST /replay/walkforward/demo`)
3. **Dashboard** mínimo em `/dashboard` + **alertas** de mudança de decisão (`/alerts`)
4. **Calibração versionada de pesos** (`/weights/propose|activate|reject`) — não altera produção automaticamente

## Validação

- `pytest` → **28 passed**
- `ruff` / `mypy` → OK
- Smoke: liquidity `AVAILABLE`; walk-forward 6 folds; dashboard HTTP 200; weights propose retorna `insufficient_sample` até haver ≥20 avaliações

## Limitações

- Binance/Bybit geo-bloqueados; Stooq frágil → Yahoo fallback macro
- `oi_change` histórico ainda não persistido entre coletas
- Alertas in-process (sem Telegram nesta fase)
- Ativação de pesos requer chamada explícita
- Sem deploy VPS

## Próximo

- Persistência de série OI para `oi_change`
- Alertas Telegram opcionais
- Avaliação automática em lote + proposta de pesos após N outcomes
