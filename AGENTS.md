# AGENTS.md

## Cursor Cloud specific instructions

This is a Python 3.12 crypto monitoring bot that runs scheduled agents via supercronic in Docker. For local development, agents are run individually.

### Running agents locally

```bash
python3 agents/hyperliquid.py
```

Agents auto-resolve the project root via `Path(__file__)`, so no `PYTHONPATH` override is needed.

### Environment variables

Set `DB_PATH` to control the SQLite location (defaults to `/data/crypto_monitor.db`):

```bash
export DB_PATH="./data/crypto_monitor.db"
```

`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are optional for local dev — if missing, a warning is logged and Telegram alerts are silently skipped.

### Agents that work without API keys

- `agents/hyperliquid.py` — public API, no auth needed (funding rates + positions)
- `agents/polymarket.py` — public API, no auth needed (prediction markets scanner)

### Agents that need API keys

- `agents/mexc.py` — needs `MEXC_API_KEY` + `MEXC_API_SECRET` for balance; BTC price fetch is public
- `agents/sentiment.py` — needs `ANTHROPIC_API_KEY` for Claude Haiku layer; RSS works without keys
- `agents/orchestrator.py` — needs `ANTHROPIC_API_KEY` + data in DB from other agents

### No linting or test framework

This project has no linter configuration, no test suite, and no CI pipeline. Validation is done by running agents individually and checking logs/DB output.

### Database

SQLite at `./data/crypto_monitor.db`. The `data/` directory must exist before running agents. Each agent calls `db.init_db()` to create tables if needed.
