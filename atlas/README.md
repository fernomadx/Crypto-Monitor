# ATLAS

Adaptive Trading, Learning and Analysis System — analista profissional de Bitcoin.

> O primeiro produto é inteligência e apoio à decisão. **Não executa ordens.**
> NO TRADE é uma decisão válida. Não há promessa de lucro.

## Localização

Este pacote vive em `atlas/` dentro do repositório `crypto-monitor`, isolado do Kronos/COMBO5.

## Requisitos

- Python 3.12+
- PostgreSQL 16+
- Docker / Docker Compose (opcional, recomendado)

## Setup rápido (local)

```bash
cd atlas
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# PostgreSQL (exemplo local)
# CREATE USER atlas WITH PASSWORD 'atlas';
# CREATE DATABASE atlas OWNER atlas;

alembic -c migrations/alembic.ini upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Docker Compose

```bash
cd atlas
cp .env.example .env
docker compose up --build
```

API em `http://localhost:8080`.

## Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| GET | `/` ou `/dashboard` | Dashboard mínimo |
| GET | `/health` | Saúde app/DB/coletores |
| GET | `/ready` | Readiness (DB) |
| GET | `/version` | Versão |
| GET | `/market/btc/snapshot?refresh=true` | Snapshot BTC |
| POST | `/analysis/btc/run` | Roda análise completa |
| GET | `/analysis/btc/latest` | Última análise |
| GET | `/specialists/status` | Status dos especialistas |
| GET | `/decisions` | Lista decisões |
| GET | `/decisions/{id}` | Decisão por id |
| GET | `/alerts` | Alertas de mudança |
| POST | `/alerts/{id}/ack` | Confirma alerta |
| GET | `/weights` | Versões de pesos |
| POST | `/weights/propose` | Propõe calibração (não ativa) |
| POST | `/weights/{id}/activate` | Ativa versão explicitamente |
| POST | `/weights/{id}/reject` | Rejeita versão |
| POST | `/replay/walkforward/demo` | Demo walk-forward purged |

## Testes e qualidade

```bash
cd atlas
pytest -q
ruff check app tests
mypy app
docker compose config
```

## Variáveis de ambiente

Ver `.env.example`. Opcional: `ATLAS_FRED_API_KEY` para séries FRED.
Stooq é usado por padrão para macro/cross-asset (sem chave).

## Status e limitações

Ver `docs/STATUS.md`.

## Segurança

- Nunca commit de tokens/senhas
- Sem execução real de trades nesta fase
- Sem chaves de exchange com permissão de saque
