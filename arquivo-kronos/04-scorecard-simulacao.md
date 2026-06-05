# Scorecard — regras de simulação

**Não é trade real** — catálogo + estatísticas.

## Parâmetros padrão

| Item | Valor |
|------|--------|
| Capital sim | 1000 USDC |
| Margem/trade | 100 USDC |
| Alavancagem | **10x** (nocional 1000) |
| Entrada | Ordem **limite** no preço base |
| Saída | Limite no **alvo**; senão stop ou vencimento |
| Taxas | Maker/taker sobre nocional (MEXC %) |

## O que entra no catálogo

- Timeframe **4H** apenas (`KRONOS_SCORE_INTERVAL=4h`)
- Símbolo **operável** (alinhamento multi-TF):
  - ≥2 TFs mesma direção, **ou**
  - 4H = Diário (1H pode divergir → ignorado)

## Resultados possíveis

| Resultado | Significado |
|-----------|-------------|
| gain / loss / flat | Trade simulado fechado |
| no_fill | Entrada limite não tocou |
| skip | NEUTRO |
| conflito (alerta) | Informativo — não entra no scorecard (exceto 4H operável) |

## Alvo / stop (alerta)

- Viés: 4 barras
- Alvo trade: 8 barras (1H), 6 (4H), 4 (1D)
- R:R mínimo **1.5** — stop menor que alvo em %
