# Decisões e contexto (linha do tempo)

- **Kronos no Railway** — mesmo container que crypto-monitor; prefixo `[KRONOS]` no Telegram.
- **Ordens limite + taxas MEXC** — scorecard simula maker/taker, não market puro.
- **Margem 100 USDC** — alavancagem **10x** na sim (antes 20x; 10x para métrica menos distorcida).
- **Alvo mais longo + stop explícito** — R:R 1.5; stop menor que alvo em %.
- **Filtro multi-timeframe** — scorecard só **4H operável**; conflito = aviso, não bug.
- **Sem reset automático** — histórico no DB mantido; reset só manual (`--confirm`).
- **Não remover Kronos do Railway** — pedido explícito após tentativa de separar Dockerfile.
- **BTCCURSOR na Hetzner** — opcional; bot `KRONOS_TELEGRAM_*` + `kronos_vps.db` separado.
- **Cron** — evoluiu 4h → 2h → 1h (confirmar `crontab` no deploy); alertas 22:15 UTC OK.
- **Relatório diário** — 12:00 BRT (15:00 UTC), ranking 1H/4H/Diário.
- **SMC backtest** — script educacional, não no cron.
- **VPS** — agente não tem IP/SSH; install manual ou GitHub Actions.
- **Qualidade Kronos (2026-06)** — scorecard exige 4H direcional + **3 TFs alinhados** (sem fallback 4H=D com 1H oposto); rejeita alvo contra o modelo; temp 0.65; viés ±0.30%; alvo mín. 0.5%.
