# Decisões e contexto (linha do tempo)

- **MEXC Análise in-repo (2026-08)** — `/mexc` no QUANT bot + `vps/mexc_analise.py` substituem o CCXT `📊 MEXC Análise` (RequestTimeout). Futures 4h usa `Hour4` (`Min240` = code 600). Spot + funding + basis no mesmo relatório.
- **COMBO5 Railway state path (2026-08)** — bug: se `/data/combo5` não existia no volume, o bot caía em path efêmero e “parava” após redeploy. Fix: sempre cria `/data/combo5` + watchdog `ensure_combo5.sh` + rate-limit de erros.
- **COMBO5 na Hetzner (2026-08)** — análise + `/combo5` rodam na VPS (`scripts/hetzner-deploy-combo5.sh`); cron 5 min + `:10` UTC; `quant_bot` com watchdog local.
- **COMBO5 sob demanda (2026-08)** — comandos Telegram `/combo5` · `/analise` · `/c5` no `quant_bot` disparam o mesmo ciclo de análise (candles MEXC + 3TF + desk) fora do cron de 5 min / horário; opcional `/combo5 BTC`.
- **COMBO5 JSON bool (2026-08)** — `ema_4h_aligned` vinha como `numpy.bool_` das comparações pandas; `json.dumps` do status gerava `Object of type bool is not JSON serializable` a cada 5 min no Telegram. Fix: `bool(...)` na origem + `_json_safe` em `Combo5Signal.to_dict()`.
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
- **Qualidade Kronos (2026-06)** — scorecard exige 4H direcional + **3 TFs alinhados**; alvo = previsão do modelo (sem inflar); R:R 2.0; entrada limite com pullback 0.15%; stop 4H 1.8%; vencimento não passa do stop.
