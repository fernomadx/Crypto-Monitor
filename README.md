# crypto-monitor

Sistema de monitoramento e alertas crypto — 24/7 no Railway, notificações no Telegram.

**Custo operacional:** ~$6-8/mês ($5 Railway + $1-3 Claude Haiku)

---

## Arquitetura

```
supercronic (cron interno do container)
├── a cada 10 min → agents/sentiment.py   (news + VADER + Haiku)
├── a cada 15 min → agents/hyperliquid.py (funding + posições)
├── a cada 15 min → agents/mexc.py        (saldo + BTC price)
├── a cada 30 min → agents/polymarket.py  (scanner de mercados)
└── a cada 4h     → agents/orchestrator.py (síntese Haiku)

SQLite em /data (volume persistente Railway)
```

---

## Pré-requisitos

Antes de fazer deploy, você precisa ter em mãos:

- [ ] `TELEGRAM_BOT_TOKEN` — token do bot (novo, após revogação)
- [ ] `MEXC_API_KEY` + `MEXC_API_SECRET` — read-only, sem trade/withdraw
- [ ] `ANTHROPIC_API_KEY` — Claude Haiku
- [ ] `CRYPTOPANIC_API_KEY` — free tier em cryptopanic.com
- [ ] `NEWS_API_KEY` — free tier em newsapi.org
- [ ] Conta no Railway com plano Hobby ($5/mês)
- [ ] Repositório privado `crypto-monitor` no GitHub (vazio)

---

## Deploy — passo a passo

### 1. Repositório GitHub

```bash
# No seu terminal local, dentro da pasta do projeto:
git init
git add .
git commit -m "chore: initial commit"
git branch -M main
git remote add origin git@github.com:SEU_USUARIO/crypto-monitor.git
git push -u origin main
```

> **Importante:** `.gitignore` já exclui `.env` e `data/`. Nunca commite credenciais.

---

### 2. Criar projeto no Railway

1. Acesse [railway.app](https://railway.app) → **New Project**
2. Selecione **Deploy from GitHub repo**
3. Autorize o GitHub e escolha `crypto-monitor`
4. Railway detectará o `Dockerfile` automaticamente — clique em **Deploy**

---

### 3. Adicionar variáveis de ambiente

No painel do projeto Railway → **Variables** → **New Variable**, adicione uma por vez:

| Variável | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | seu token |
| `TELEGRAM_CHAT_ID` | `7696151400` |
| `MEXC_API_KEY` | sua key |
| `MEXC_API_SECRET` | seu secret |
| `ANTHROPIC_API_KEY` | sua key |
| `CRYPTOPANIC_API_KEY` | sua key |
| `NEWS_API_KEY` | sua key |
| `HYPERLIQUID_ADDRESS` | `0xA81aac9FbB0659F4e8d33a55cc8bACFF0Ac104b2` |
| `TICKERS` | `BTC,ETH,SOL` |
| `FUNDING_THRESHOLD` | `0.0005` |
| `VADER_THRESHOLD` | `0.5` |
| `DB_PATH` | `/data/crypto_monitor.db` |

> Cole cada valor diretamente no painel. Nunca via chat, nunca no código.

---

### 4. Criar volume persistente (SQLite)

1. No painel Railway → **Settings** → **Volumes**
2. Clique em **Add Volume**
3. Mount Path: `/data`
4. Confirme

Sem este passo o banco SQLite é destruído a cada redeploy.

---

### 5. Verificar deploy

Após o deploy (1-2 min):

1. Vá em **Deployments** → clique no deploy mais recente → **View Logs**
2. Você deve ver logs do supercronic iniciando os agentes
3. No Telegram, espere até 15 min pelo primeiro alerta do Hyperliquid/MEXC

Se o container reiniciar em loop, vá em **Logs** e leia o erro — provavelmente variável de ambiente faltando.

---

### 6. Validação rápida

Para testar um agente isolado sem esperar o cron, use o Railway Shell (aba **Shell** no painel):

```bash
python /app/agents/hyperliquid.py
python /app/agents/mexc.py
python /app/agents/sentiment.py
python /app/agents/orchestrator.py
```

---

## Desenvolvimento local

```bash
cp .env.example .env
# edite .env com suas credenciais
mkdir -p data
docker compose up --build
```

O `docker-compose.yml` monta `./data` em `/data` para persistência local.

---

## Kronos — alerta `[KRONOS]` (mesmo bot, mesmas variáveis)

Usa **automaticamente** o que já está no Railway: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TICKERS` (BTC, ETH, SOL → MEXC).

### Railway (automático no mesmo serviço)

O **`Dockerfile` principal** já inclui Kronos. Após cada deploy:

1. Mensagem `[KRONOS] Serviço iniciado` no Telegram (~1 min)
2. `[KRONOS] Processando...` e depois previsão + **3 gráficos** (15–40 min em CPU)
3. Cron **a cada 4h** (minuto :15)

**Requisito:** aumente RAM do serviço para **≥2 GB** no Railway (Settings → Resources), senão o container pode reiniciar ao carregar o modelo.

Serviço separado (`Dockerfile.kronos`) só se quiser isolar o custo/RAM.

### Opção B — VPS BTCCURSOR (bot Telegram **separado**)

Guia: [`vps/BTCCURSOR.md`](vps/BTCCURSOR.md) — crie um bot em @BotFather (`KRONOS_TELEGRAM_*`).

```bash
sudo bash vps/install.sh
```

[`vps/README.md`](vps/README.md) · DB próprio na VPS (`kronos_vps.db`)

## Arquivo do projeto (consulta rápida)

Tudo documentado em **[`arquivo-kronos/`](arquivo-kronos/README.md)** — índice, Railway, Hetzner, scorecard, comandos e decisões.

## Estrutura de arquivos

```
crypto-monitor/
├── Dockerfile
├── docker-compose.yml       # dev local
├── requirements.txt
├── crontab                  # supercronic schedule
├── railway.toml
├── .env.example
├── .gitignore
├── agents/
│   ├── hyperliquid.py       # funding + posições (15 min)
│   ├── mexc.py              # saldo + BTC price (15 min)
│   ├── polymarket.py        # scanner mercados (30 min)
│   ├── sentiment.py         # news + VADER + Haiku (10 min)
│   └── orchestrator.py      # síntese consensus (4h)
├── vps/
│   ├── kronos_signal.py     # Kronos → Telegram [KRONOS] (rodar na VPS)
│   ├── README.md
│   └── setup_btccursor.sh
└── lib/
    ├── db.py                # SQLite helper
    ├── telegram.py          # Telegram sender (+ send_kronos_alert)
    └── news_sources.py      # RSS + CryptoPanic + NewsAPI
```

---

## Segurança

- Nenhuma credencial no código ou no GitHub
- MEXC key é read-only — sem permissão de trade ou saque
- Hyperliquid usa apenas endereço público (sem chave)
- Token Telegram só no Railway Variables

---

## Custos estimados

| Item | Custo/mês |
|---|---|
| Railway Hobby | $5.00 |
| Claude Haiku (~500 chamadas/mês) | ~$0.50-2.00 |
| CryptoPanic free tier | $0 |
| NewsAPI free tier | $0 |
| **Total** | **~$6-8** |
