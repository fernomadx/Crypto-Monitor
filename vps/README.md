# Kronos na VPS → Telegram `[KRONOS]`

Roda **na VPS** (ex.: BTCCURSOR), separado do **Railway** (`crypto-monitor`).

- **Mesmo bot** Telegram (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`)
- **Alerta visual separado**: prefixo `📈 [KRONOS]` (não mistura com funding, MEXC, consensus)

## Exemplo de mensagem no Telegram

```
📈 [KRONOS] Sinal 15m — 2026-06-02 16:00 UTC

Intervalo: 15m | Lookback: 400 | Horizonte: 12 barras
Modelo: NeoQuasar/Kronos-mini

BTC 🟢 BULLISH
  Agora: $97,500.00
  Previsto (fim do horizonte): $98,200.00 (+0.72%)

ETH ...

Sinal informativo — não é ordem de trade.
```

No app Telegram você pode **silenciar** ou **fixar** por palavra-chave `KRONOS` se quiser filtrar.

## Setup rápido (VPS)

```bash
# 1. Repositório + Kronos
sudo mkdir -p /opt
cd /opt
git clone git@github.com:SEU_USUARIO/crypto-monitor.git
git clone https://github.com/shiyu-coder/Kronos.git

# 2. venv e deps (PyTorch — demora alguns minutos)
cd /opt/crypto-monitor
python3 -m venv vps/.venv
vps/.venv/bin/pip install -r vps/requirements.txt

# 3. Env (mesmo token/chat do Railway)
cp vps/.env.example vps/.env
nano vps/.env

# 4. Teste (primeira execução baixa o modelo do Hugging Face)
set -a && source vps/.env && set +a
vps/.venv/bin/python vps/kronos_signal.py
```

## Cron (a cada 4h)

```bash
crontab -e
```

Cole o conteúdo de `vps/crontab.example` (ajuste `/opt/crypto-monitor`).

## Arquitetura

```
┌─────────────────────┐     ┌──────────────────────┐
│ Railway             │     │ VPS BTCCURSOR        │
│ hyperliquid, mexc,  │     │ vps/kronos_signal.py │
│ sentiment, ...      │     │ + Kronos + PyTorch   │
└─────────┬───────────┘     └──────────┬───────────┘
          │                            │
          └──────────┬─────────────────┘
                     ▼
            Telegram (mesmo bot)
     🔔 alertas normais  |  📈 [KRONOS]
```

## Requisitos VPS

| Item | Mínimo sugerido |
|------|-----------------|
| RAM | 2 GB+ (Kronos-mini em CPU) |
| Disco | ~2 GB (venv + modelo HF) |
| CPU | 2 vCPU — inferência ~1–5 min/símbolo |

Use `KRONOS-mini` em CPU. `Kronos-small` exige mais RAM e é mais lento sem GPU.

## Variáveis principais

Ver `vps/.env.example`. Tickers no formato MEXC: `BTCUSDT`, `ETHUSDT`.
