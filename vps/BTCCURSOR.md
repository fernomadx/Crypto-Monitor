# BTCCURSOR — Hetzner Cloud

Servidor **Hetzner** (ex.: CX/CPX Ubuntu) rodando só o **Kronos** com bot Telegram **dedicado** (`KRONOS_TELEGRAM_*`).

O **Railway** segue com o `crypto-monitor` (funding, notícias, orchestrator) no bot `TELEGRAM_*`.

---

## Recomendação Hetzner

| Tipo | Spec | Uso |
|------|------|-----|
| **CPX31** ou **CX32** | 4 GB RAM, 2 vCPU | Kronos a cada **1h** (3 moedas × 3 TFs) |
| **CX22** | 4 GB | Mínimo; pode ficar justo em pico de RAM |
| OS | **Ubuntu 24.04** | `install.sh` testado em Debian/Ubuntu |
| Disco | 40 GB+ | ~3 GB venv + modelo Hugging Face em cache |

Região: **Falkenstein / Nuremberg / Helsinki** — latência ok para MEXC API (HTTPS saída).

Não precisa abrir portas inbound (só SSH 22). Kronos só faz **saída** (MEXC, Telegram, Hugging Face).

---

## 1. Criar o bot Telegram

1. [@BotFather](https://t.me/BotFather) → `/newbot` → ex. `BTCCURSOR Kronos` / `@btccursor_kronos_bot`
2. Token → `KRONOS_TELEGRAM_BOT_TOKEN`
3. Abra o bot → `/start`
4. `chat_id`: [@userinfobot](https://t.me/userinfobot) ou  
   `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | head`

---

## 2. Servidor Hetzner (primeira vez)

No painel [Hetzner Cloud](https://console.hetzner.cloud/):

1. **Add Server** → Ubuntu 24.04 → tipo CPX31 (ou CX32)
2. SSH key (recomendado) ou senha root
3. Anote o **IPv4**

```bash
ssh root@SEU_IPV4_HETZNER
apt update && apt upgrade -y
```

Opcional — firewall:

```bash
ufw allow OpenSSH
ufw enable
```

---

## 3. Instalar Kronos (BTCCURSOR)

```bash
git clone https://github.com/fernomadx/Crypto-Monitor.git /opt/crypto-monitor
cd /opt/crypto-monitor
cp vps/.env.example vps/.env
nano vps/.env
```

Preencha no mínimo:

```env
KRONOS_TELEGRAM_BOT_TOKEN=...
KRONOS_TELEGRAM_CHAT_ID=...
DB_PATH=/opt/crypto-monitor/data/kronos_vps.db
KRONOS_PATH=/opt/Kronos
```

```bash
sudo bash vps/install.sh
```

`install.sh` cria venv, clona Kronos, testa 1ª previsão e cron **:15** cada hora.

### Cron completo (scorecard + relatório 12h BRT)

```bash
crontab -e
# cole vps/crontab.example
```

---

## 4. Deploy automático (GitHub → Hetzner)

Repositório → **Settings → Secrets → Actions**:

| Secret | Valor |
|--------|--------|
| `VPS_HOST` | IPv4 do servidor Hetzner |
| `VPS_USER` | `root` (ou usuário com sudo) |
| `VPS_SSH_KEY` | chave privada SSH |

Antes do workflow: `.env` já configurado na VPS (passo 3), senão o teste do `install.sh` falha.

Actions → **Deploy Kronos to VPS** → **Run workflow**

---

## 5. Railway vs Hetzner (BTCCURSOR)

**Kronos roda só no Railway.** A Hetzner não deve enviar sinais `[KRONOS]` (evita duplicar alertas no mesmo bot).

| | Railway | Hetzner BTCCURSOR |
|--|---------|-------------------|
| Kronos | **Ativo** (daemon + crontab) | **Desligado** (`hetzner_disable_kronos.sh`) |
| COMBO5 | **Ativo** — entrada/saída + ranking | **Não duplicar** (sem cron COMBO5) |
| Bot | `TELEGRAM_*` · `/combo5` · `/c5score` | QUANT off (`QUANT_BOT_ENABLED=0`) |
| DB | `/data/crypto_monitor.db` | `/opt/crypto-monitor/data/kronos_vps.db` |
| Cron | COMBO5 5 min + `:10` + ranking 15:10 UTC | sem linhas `kronos_*` / `combo5_*` |

### COMBO5 no Railway (não duplicar na Hetzner)

Alertas `[COMBO5]` (entrada, saída e ranking) saem **só do Railway**. Cron COMBO5 na VPS duplicaria avisos no mesmo chat.

Comandos no Telegram (Railway): `/combo5` · `/combo5 ranking` · `/c5score` · `/analise` · `/c5` · `/mexc`.

Desligar Kronos na Hetzner:

```bash
cd /opt/crypto-monitor && git pull && sudo bash vps/hetzner_disable_kronos.sh
```

Ou no Telegram (Railway): `/vps test` — sincroniza e remove cron Kronos via SSH.

Para **reativar** Kronos na Hetzner (só com bot dedicado): `KRONOS_VPS_ENABLED=1` + `KRONOS_TELEGRAM_*` + `install.sh`.

---

## 6. Comandos úteis na Hetzner

```bash
# Atualizar código
cd /opt/crypto-monitor && git pull && vps/.venv/bin/pip install -r vps/requirements-railway.txt -q

# Logs
tail -f /var/log/kronos_signal.log
tail -f /var/log/kronos_scorecard.log

# Performance / ranking TF
set -a && source vps/.env && set +a
vps/.venv/bin/python vps/kronos_status.py

# Teste manual
vps/run_kronos.sh
```

Cache do modelo (evita re-download):

```bash
mkdir -p /opt/crypto-monitor/data/huggingface
# no .env:
# HF_HOME=/opt/crypto-monitor/data/huggingface
```

---

## 7. `📊 MEXC Análise` (daemon + snapshot, sem CCXT)

O bot que manda **Bot iniciado** (alerts · BTC/USDT:USDT 1h · 20x · poll 15s) agora é o daemon Python neste repo — **não** o CCXT da Hetzner.

- Sobe no **Railway** com o container (`ensure_mexc_analise.sh`)
- Snapshot sob demanda: `/mexc` ou `python vps/mexc_analise.py BTC`
- **Modo alerts** — Telegram no sinal **COMPRA (LONG)** / **VENDA (SHORT)** no fechamento do candle 1h, depois FILL / BE / STOP / TAKE. **Não envia ordem** na exchange (MEXC key continua read-only)

Regras iguais ao banner antigo: cooldown 12h pós-STOP sem inverter, long bloqueado RSI>65 ou ADX≥40, BE em **1.5R** (não 1R), stop máx 5% no short.

Klines 4h de futuros usam **`Hour4`** (`Min240` = code 600). HTTP com timeout 45s + 4 retries.

Se o script CCXT antigo ainda estiver na VPS, mate-o (RequestTimeout). Este daemon substitui.

---

## 8. Teste

Mensagem deve chegar **só no bot Kronos**, não no bot do crypto-monitor Railway.

```bash
set -a && source /opt/crypto-monitor/vps/.env && set +a
cd /opt/crypto-monitor
vps/.venv/bin/python vps/kronos_signal.py
```
