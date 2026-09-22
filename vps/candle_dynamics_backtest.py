#!/usr/bin/env python3
"""
Backtest Candle Dynamics — BTC últimos N anos.

Uso:
  python vps/candle_dynamics_backtest.py
  python vps/candle_dynamics_backtest.py --years 5 --symbol BTCUSDT
  python vps/candle_dynamics_backtest.py --years 1  # reusa cache Vision em data/

Dados: Binance Vision (mensal). Cache em data/candle_dynamics/.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.candle_dynamics.backtest import run_backtest  # noqa: E402
from lib.candle_dynamics.data import load_klines, resample_ohlcv  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("candle_dynamics")


def print_report(result) -> None:
    s = result.summary()
    print()
    print("=" * 64)
    print(f"Candle Dynamics Backtest — {s['symbol']}")
    print(f"Período: {s['period']} | Barras M5: {s['bars']:,}")
    print(f"Capital sim: ${result.initial_capital:.0f} | Posição: ${result.position_usdc:.0f}")
    print("=" * 64)
    if result.n == 0:
        print("Nenhum trade gerado — revise zonas/tolerâncias ou período.")
        return
    print(f"Trades: {s['trades']} | Gain: {s['gains']} | Loss: {s['losses']}")
    print(f"Win rate: {s['win_rate_pct']}%")
    print(f"PnL total: ${s['pnl_usdc']:+.2f}")
    print(f"Equity final: ${s['equity_final']:.2f}")
    print(f"Profit factor: {s['profit_factor']}")
    print(f"Max drawdown: ${s['max_dd_usdc']:.2f}")
    print(f"Veredito: {s.get('verdict', '?')}")
    print(f"Por tipo: {s['by_kind']}")
    print(f"Por ano: {s.get('by_year', {})}")
    print()
    print("Últimos 12 trades:")
    for t in result.trades[-12:]:
        print(
            f"  {t.side:5} {t.kind:18} PnL=${t.pnl_usdc:+7.2f} "
            f"{t.result:7} BE={int(t.be_moved)} partial={int(t.partial_taken)} | {t.reason[:48]}"
        )


def main() -> int:
    p = argparse.ArgumentParser(description="Backtest Candle Dynamics BTC")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--years", type=float, default=5.0)
    p.add_argument("--position", type=float, default=100.0)
    p.add_argument("--capital", type=float, default=1000.0)
    p.add_argument("--json-out", type=Path, default=None)
    p.add_argument("--cache-dir", type=Path, default=None)
    args = p.parse_args()

    logger.info("Carregando %s M5 (%.1f anos)…", args.symbol, args.years)
    df_5m = load_klines(args.symbol, "5m", years=args.years, cache_dir=args.cache_dir)
    logger.info("M5: %d barras (%s → %s)", len(df_5m), df_5m["timestamps"].iloc[0], df_5m["timestamps"].iloc[-1])

    df_30m = resample_ohlcv(df_5m, "30min")
    df_1h = resample_ohlcv(df_5m, "1h")
    df_1d = resample_ohlcv(df_5m, "1D")
    df_1w = resample_ohlcv(df_5m, "1W")
    logger.info(
        "Agregados: M30=%d H1=%d D=%d W=%d",
        len(df_30m),
        len(df_1h),
        len(df_1d),
        len(df_1w),
    )

    result = run_backtest(
        df_5m,
        df_30m,
        df_1h,
        df_1d,
        df_1w,
        symbol=args.symbol,
        initial_capital=args.capital,
        position_usdc=args.position,
    )
    print_report(result)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        payload = result.summary()
        payload["trades_sample"] = [
            {
                "side": t.side,
                "kind": t.kind,
                "pnl_usdc": t.pnl_usdc,
                "result": t.result,
                "reason": t.reason,
            }
            for t in result.trades[:50]
        ]
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("JSON salvo em %s", args.json_out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
