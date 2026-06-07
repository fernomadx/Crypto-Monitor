# QUANT — pesquisa sob demanda + alertas de impacto + Kronos

Três peças **separadas** do `[KRONOS]`:

| Peça | Script | Função |
|------|--------|--------|
| **On-demand** | `vps/quant_bot.py` | Você pergunta quando quiser (`/pesquisa`, `/quant`) |
| **Alertas** | `vps/quant_watcher.py` | Notícia de impacto → Telegram `[QUANT]` |
| **Kronos** | `lib/kronos_quant.py` | Lê estado e pode **vetar** scorecard 4H se contexto contradiz |

## Setup Hetzner (recomendado)

```bash
cd /opt/crypto-monitor
cp vps/.env.example vps/.env
nano vps/.env   # LLMQUANT_API_KEY, TELEGRAM_*, ANTHROPIC_API_KEY, news keys
```

### 1. Bot sob demanda (sempre ativo)

```bash
set -a && source vps/.env && set +a
nohup vps/.venv/bin/python vps/quant_bot.py >> /data/quant_bot.log 2>&1 &
```

### 2. Watcher de notícias (cron a cada 5 min)

Ver `vps/crontab.example` — linha `quant_watcher.py`.

### 3. Kronos na mesma VPS

O `kronos_signal.py` já inclui bloco **Contexto QUANT** e veto no scorecard 4H
(`QUANT_KRONOS_VETO=1`).

## Comandos Telegram

```
/quant          — estado atual (impacto por BTC/ETH/SOL)
/pesquisa momentum em crypto após ETF
/btc            — preço LLMQuant + contexto
/help
```

## Variáveis

| Variável | Descrição |
|----------|-----------|
| `LLMQUANT_API_KEY` | [llmquantdata.com](https://llmquantdata.com) (beta grátis) |
| `ANTHROPIC_API_KEY` | Resumo + detecção de impacto |
| `QUANT_STATE_PATH` | `/data/quant_state.json` (compartilhado com Kronos) |
| `QUANT_IMPACT_THRESHOLD` | `0.65` — mínimo para alerta |
| `QUANT_KRONOS_VETO` | `1` — bloqueia scorecard 4H se QUANT contradiz |
| `QUANT_MAX_AGE_HOURS` | `4` — janela do contexto no Kronos |

## Arquitetura

```
Você → /pesquisa ──► quant_bot ──► LLMQuant API + Haiku
                         │
Cron ─► quant_watcher ──► notícias ──► quant_state.json
                         │                    │
                         ▼                    ▼
                    [QUANT] alert      kronos_signal lê + veto 4H
```
