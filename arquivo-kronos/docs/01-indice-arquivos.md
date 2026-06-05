# Índice — Arquivo Kronos

## Acesso web

**Portal:** https://fernomadx.github.io/Crypto-Monitor/

Navegue por pastas, abra documentação e código no browser. Atualize com `./sync-from-repo.sh` após mudanças no repo.

---

## Estrutura

```
arquivo-kronos/
├── index.html          # Portal web
├── assets/style.css
├── sync-from-repo.sh   # Copia código/docs do repo
├── docs/               # Documentação (01–08)
└── codigo/             # Cópia do código Kronos
    ├── lib/
    ├── vps/
    └── workflows/      # GitHub Actions (+ Dockerfile, crontab na raiz)
```

---

## Documentação (`docs/`)

| Arquivo | Conteúdo |
|---------|----------|
| `01-indice-arquivos.md` | Este índice |
| `02-railway.md` | Deploy Railway, cron, variáveis |
| `03-hetzner-btccursor.md` | VPS Hetzner + bot dedicado |
| `04-scorecard-simulacao.md` | $100×10x, limit, fees, 4H |
| `05-cron-e-telegram.md` | Horários e tipos de alerta |
| `06-comandos-uteis.md` | Comandos Shell / testes |
| `07-decisoes-e-contexto.md` | Decisões e histórico do projeto |
| `08-export-memorias.md` | Preferências e contexto exportado |

---

## Código (`codigo/`)

| Pasta | Arquivos principais |
|-------|---------------------|
| `lib/` | kronos_tracker, levels, alignment, mexc_klines, telegram, smc_strategy |
| `vps/` | kronos_signal, scorecard, daily_report, status, reset, smc_backtest |
| raiz | Dockerfile, crontab, railway.toml |
| `workflows/` | deploy-kronos-vps, kronos-daily-report, kronos-telegram-cron |

---

## Atualização automática

| Workflow | Quando roda | O que faz |
|----------|-------------|-----------|
| `sync-arquivo-kronos.yml` | Push em `lib/`, `vps/`, infra | Atualiza `codigo/` |
| `arquivo-kronos-pages.yml` | Push em `arquivo-kronos/` | Publica o site |

Manual: `cd arquivo-kronos && ./sync-from-repo.sh`
