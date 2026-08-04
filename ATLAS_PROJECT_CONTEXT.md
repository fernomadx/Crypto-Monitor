# ATLAS — Adaptive Trading, Learning and Analysis System

## Missão

Analista profissional de Bitcoin: observar o mercado, combinar especialistas
independentes, explicar raciocínio, produzir cenários probabilísticos, registrar
análises e aprender com resultados. **Não é executor automático de ordens.**

## Princípios (resumo)

1. Nenhuma conclusão sem evidências.
2. NO TRADE é decisão válida.
3. Preço é consequência, não explicação suficiente.
4. Correlação ≠ causalidade; relações mudam com o regime.
5. Registrar decisões antes de revelar resultados.
6. Nunca apagar histórico importante — versionar/arquivar/desativar.
7. Sem look-ahead em replay/treino/avaliação.
8. Erros alimentam fila de investigação; não alteram produção automaticamente.
9. Simplicidade antes de complexidade.

## Localização no repositório

Este repositório (`crypto-monitor`) já contém Kronos/COMBO5/QUANT.
O ATLAS vive em `atlas/` de forma isolada — **não altera nem para serviços
existentes** (Railway, Hetzner, daemons Kronos).

## Stack

- Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2
- PostgreSQL, httpx, Polars, NumPy, SciPy, statsmodels, scikit-learn, ccxt
- structlog, pytest, ruff, mypy, Docker Compose

## Especialistas (v1)

| Especialista | Status v1 |
|---|---|
| Market Structure | Implementado |
| Dynamic Correlation / Lead-Lag | Implementado (núcleo) |
| Macro / Cross-Asset | Implementado (fontes públicas + fallback) |
| Liquidez / Derivativos | OKX pública (funding/OI/basis/liqs) |
| News / Events | RSS públicos (CoinDesk/CoinTelegraph) |
| Experience | Similaridade estrutural inicial |
| Risk | Implementado |
| Council Aggregator | Implementado (não é média simples) + calibração versionada |

Extras v0.2:
- Walk-forward replay com purge/embargo
- Dashboard `/dashboard` + alertas `/alerts`
- Pesos versionados (`candidate` → activate explícito)

## API

- `GET /health`, `/ready`, `/version`
- `GET /market/btc/snapshot`
- `GET /analysis/btc/latest`
- `POST /analysis/btc/run`
- `GET /specialists/status`
- `GET /decisions`, `GET /decisions/{id}`

## Status do projeto

Ver `atlas/docs/STATUS.md` para estado atual, limitações e próximos marcos.

## Monetização (direção)

Relatórios → alertas → dashboard → assinatura/API. Sem promessa de lucro.
