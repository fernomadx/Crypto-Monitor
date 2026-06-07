# QUANT — pesquisa sob demanda + alertas de impacto + Kronos

Três peças **separadas** do `[KRONOS]`:

| Peça | Script | Função |
|------|--------|--------|
| **On-demand** | `vps/quant_bot.py` | Você pergunta quando quiser (`/pesquisa`, `/quant`) |
| **Notícias 1H** | `vps/quant_hourly_news.py` | Digest no fechamento candle 1H → `[QUANT]` |
| **Alertas** | `vps/quant_watcher.py` | Alto impacto imediato (opcional, `QUANT_IMPACT_ALERTS`) |
| **Kronos** | `lib/kronos_quant.py` | Lê estado e pode **vetar** scorecard 4H se contexto contradiz |

## Setup Railway (mesmo container do Kronos)

O `railway_boot.sh` sobe o `quant_bot` e o `crontab` roda o `quant_watcher` a cada 5 min.

1. Railway → **Variables** → **Raw Editor** → cole `LLMQUANT_API_KEY` + demais `QUANT_*` (ver `.env.example`).
2. Redeploy (push na `main` ou botão **Deploy**).
3. Telegram: `[QUANT] Online` → `/ping` → `/pesquisa momentum bitcoin`.

O bot sobe via `ensure_quant_bot.sh` (boot + cron a cada 3 min). Se `/ping` falhar, confira `/data/quant_bot.log` no Railway.

Ou rode `bash scripts/railway-configure-quant.sh` com `RAILWAY_TOKEN` + `LLMQUANT_API_KEY`.

## Setup Hetzner (recomendado)

```bash
cd /opt/crypto-monitor
git pull
cp vps/.env.example vps/.env
nano vps/.env   # LLMQUANT_API_KEY, TELEGRAM_*, ANTHROPIC_API_KEY, news keys
```

### Teste rápido (rode primeiro)

```bash
chmod +x vps/start_quant.sh
bash vps/start_quant.sh
```

Ou só o teste:

```bash
set -a && source vps/.env && set +a
vps/.venv/bin/python vps/quant_test.py
```

No Telegram: `/ping` → deve responder `QUANT online`.

### 1. Bot sob demanda (sempre ativo)

`start_quant.sh` já sobe o bot. Manual:

```bash
set -a && source vps/.env && set +a
nohup vps/.venv/bin/python vps/quant_bot.py >> /data/quant_bot.log 2>&1 &
```

### 2. Notícias a cada 1H (fechamento candle)

Cron `1 * * * *` → `quant_hourly_news.py` (só notícias **relevantes** + resumo Haiku + mercado).

Ajuste o filtro: `QUANT_HOURLY_MIN_RELEVANCE=0.45` (mais alto = mais rígido).

Desative alertas imediatos e use só o digest:

```env
QUANT_IMPACT_ALERTS=false
```

### 3. Watcher de alto impacto (opcional, cron 5 min)

Ver `crontab` — `quant_watcher.py` (só se `QUANT_IMPACT_ALERTS=true`).

### 4. Kronos na mesma VPS

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
| `QUANT_KRONOS_MODE` | `warn` (teste) / `veto` (produção) / `off` |
| `QUANT_KRONOS_VETO` | legado `0/1` — use `QUANT_KRONOS_MODE` |
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
