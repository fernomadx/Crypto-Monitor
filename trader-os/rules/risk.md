# Risco — não-negociáveis

Espelha o checklist do framework "THE SYSTEM", com os valores já usados pelos agentes
deste repo como referência (ver `.env.example`).

- [ ] Máx 1% da conta arriscado por trade (iniciante: 0.5%)
- [ ] Size = (Conta × risco%) ÷ distância do stop — sempre calculado a partir do stop,
      nunca "quanto eu quero comprar"
- [ ] Stop diário: 2 perdas seguidas = parar por hoje, sem exceção
- [ ] Máx 3 posições abertas simultâneas enquanto em aprendizado; checar correlação
      entre BTC/ETH/SOL antes de abrir a 2ª ou 3ª (correlacionadas = risco concentrado,
      não diversificado)
- [ ] Nunca alargar um stop. Nunca fazer average down.
- [ ] 30+ trades em paper de qualquer setup novo antes de considerar dinheiro real
- [ ] R:R mínimo 1:2 (ver `COMBO5_RR`, default 2.0) — abaixo disso, pular o setup
- [ ] SL sempre no nível de invalidação da tese, nunca em número redondo arbitrário —
      `lib/combo5/signal.py` usa ATR (`COMBO5_ATR_SL_MULT`) com piso/teto
      (`COMBO5_SL_FLOOR` 2%, `COMBO5_SL_CAP` 4.5%) como referência de ordem de grandeza
- [ ] Tamanho de posição do Trade Desk é limitado por `TRADE_DESK_MAX_POSITION_PCT`
      (default 25% do capital alocado à mesa) — não é o mesmo que risco de conta; ainda
      aplicar a regra de 1% em cima disso

## Cálculo de tamanho (colar no prompt)

```
Conta [$X], risco 1%, entrada [$A], stop [$B].
Calcule meu tamanho em unidades/contratos e o risco em dólar. Mostre a conta.
Depois verifique: isso quebra meu limite de máx 3 posições ou de correlação dado
[posições atuais]?
```

## Lembrete de execução

Este repositório não envia ordens para MEXC/Hyperliquid — os agentes só alertam e
registram no journal (`lib/combo5/journal.py`). A execução real (ou em paper) é manual,
fora do bot, na corretora. Trate qualquer "ENTRADA Nº N" do Telegram como um trade
plan sugerido, não como uma posição já aberta.
