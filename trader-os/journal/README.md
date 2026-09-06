# Journal

Um arquivo por dia (`YYYY-MM-DD.md`), uma entrada por trade avaliado — entrado ou
descartado. Use `TEMPLATE.md` como base. Isto complementa (não substitui)
`lib/combo5/journal.py`, que já registra trades numerados do bot COMBO5 em
`COMBO5_STATE_DIR` — aqui é para trades manuais/paper e para o "porquê" por trás de
cada decisão, incluindo os setups que você pulou.

Toda entrada fechada também vira uma linha em `../tracking/trades.csv` para a revisão
semanal (estágio 8).
