"""
Estratégia Candle Dynamics (retração / impulsão / falha) — multi-timeframe.

Formalização operacional das regras de:
  - Dinâmica dos candles (retração, impulsão, falha/microfalha)
  - Gap + movimentos do pregão
  - Operação de venda na impulsão (a favor da tendência)
  - Hierarquia M1→M5→M30/M60 (aqui: M5 confirma; M30/H1 estrutura; D/W alvos)
  - Proteção e risco (BE rápido, parciais em 50%, paciência de zona)

Somente candles FECHADOS geram sinal (nunca antecipar falha).
"""

from lib.candle_dynamics.backtest import BacktestResult, run_backtest
from lib.candle_dynamics.signals import Signal, generate_signals

__all__ = ["BacktestResult", "Signal", "generate_signals", "run_backtest"]
