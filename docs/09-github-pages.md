# GitHub Pages — portal web

## URL

https://fernomadx.github.io/Crypto-Monitor/

## Pré-requisitos (obrigatório)

1. Repositório **público** (Settings → Danger Zone → Change visibility → Public)
2. Pages ligado: Settings → Pages → **Deploy from a branch**
3. Branch: **gh-pages** · Pasta: **/ (root)** · Save

O workflow `Arquivo Kronos — GitHub Pages` atualiza a branch `gh-pages` automaticamente a cada push em `arquivo-kronos/`.

## Se a página não abrir

| Sintoma | Causa | Solução |
|---------|-------|---------|
| Não carrega / 404 | Repo ainda privado | Tornar público (passo 1) |
| 404 após público | Pages não configurado | Passo 2 acima |
| Página em branco | DNS ainda propagando | Aguardar 2–5 min e recarregar |

## Testar sem Pages

Arquivos no GitHub: `arquivo-kronos/index.html` (visualizar no repo).
