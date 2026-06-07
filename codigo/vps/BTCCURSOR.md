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

| | Railway | Hetzner BTCCURSOR |
|--|---------|-------------------|
| Bot | `TELEGRAM_*` | `KRONOS_TELEGRAM_*` |
| DB | `/data/crypto_monitor.db` | `/opt/crypto-monitor/data/kronos_vps.db` |
| Cron | no container | `crontab` do host |
| Custo | RAM limitada | CPX31 ~fixo/mês, CPU estável |

Para **não duplicar** alertas Kronos no bot do Railway, remova as linhas `kronos_*` do `crontab` do Dockerfile no Railway (ou desative só o Kronos lá).

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

## 7. Erro `RequestTimeout` — MEXC Análise (futures)

Se o bot **BTCCURSOR** mostrar:

```
📊 MEXC Análise
Erro
RequestTimeout: mexc GET .../api/v1/contract/kline/BTC_USDT?interval=Min60
```

Isso é a API de **futuros** MEXC (CCXT ou script separado), não o Kronos spot.

**Causa:** timeout curto ou pico de latência MEXC (intermitente).

**Correções no script CCXT/Node (se usar):**

```javascript
const exchange = new ccxt.mexc({
  timeout: 45000,
  enableRateLimit: true,
});
// retry manual 3–4x com sleep 2s entre tentativas
```

**Alternativa Python (neste repo):** `lib/mexc_contract.py` — retry + fallback `contract.mexc.com`:

```bash
cd /opt/crypto-monitor && git pull
set -a && source vps/.env && set +a
vps/.venv/bin/python -c "
from lib.mexc_contract import fetch_contract_klines
print(fetch_contract_klines('BTCUSDT','1h',50).tail(2))
"
```

Variáveis opcionais no `.env`:

```env
MEXC_HTTP_TIMEOUT_SEC=45
MEXC_HTTP_RETRIES=4
MEXC_CONTRACT_BASE=https://contract.mexc.com
```

O **Kronos** usa spot (`/api/v3/klines`) — também ganha retry após `git pull` (`lib/mexc_http.py`).

---

## 8. Teste

Mensagem deve chegar **só no bot Kronos**, não no bot do crypto-monitor Railway.

```bash
set -a && source /opt/crypto-monitor/vps/.env && set +a
cd /opt/crypto-monitor
vps/.venv/bin/python vps/kronos_signal.py
```
