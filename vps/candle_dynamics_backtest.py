#!/usr/bin/env python3
"""
Backtest Candle Dynamics — BTC últimos N anos.

Uso:
  python vps/candle_dynamics_backtest.py --years 5 --version v2-short
  python vps/candle_dynamics_backtest.py --years 5 --version v2-short --sizing risk --risk-pct 2 --max-leverage 8
  python vps/candle_dynamics_backtest.py --years 5 --compare

Sizing:
  fixed — notional fixo (--position), útil p/ comparar setups
  risk  — arrisca --risk-pct% do equity no stop, alavancagem até --max-leverage (compound)
          Padrão v2-short: risk 2% / max 8x + profit-lock 3R→1R / hold 36h
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


def print_report(result, label: str | None = None) -> None:
    s = result.summary()
    tag = label or s.get("version", "?")
    print()
    print("=" * 64)
    print(f"Candle Dynamics [{tag}] — {s['symbol']}")
    print(f"Período: {s['period']} | Barras M5: {s['bars']:,}")
    sizing = s.get("sizing", "fixed")
    if sizing == "risk":
        print(
            f"Capital: ${result.initial_capital:.0f} | sizing=risk "
            f"{s.get('risk_pct')}%/stop | maxLev={s.get('max_leverage')} | avgLev={s.get('avg_leverage')}"
        )
    else:
        print(f"Capital: ${result.initial_capital:.0f} | Posição fixa: ${result.position_usdc:.0f}")
    print("=" * 64)
    if result.n == 0:
        print("Nenhum trade gerado — revise zonas/tolerâncias ou período.")
        return
    print(f"Trades: {s['trades']} | Gain: {s['gains']} | Loss: {s['losses']}")
    print(f"Win rate: {s['win_rate_pct']}%")
    print(f"PnL total: ${s['pnl_usdc']:+.2f}")
    print(f"Retorno: {s.get('return_pct', 0):+.1f}% | CAGR: {s.get('cagr_pct', 0):+.1f}%")
    print(f"Equity final: ${s['equity_final']:.2f}")
    print(f"Profit factor: {s['profit_factor']}")
    print(f"Max drawdown: ${s['max_dd_usdc']:.2f} ({s.get('max_dd_pct', 0):.1f}%)")
    print(f"Veredito: {s.get('verdict', '?')}")
    print(f"Por tipo: {s['by_kind']}")
    print(f"Por ano: {s.get('by_year', {})}")
    print()
    print("Últimos 8 trades:")
    for t in result.trades[-8:]:
        lev = f" {t.leverage_used:.1f}x" if t.leverage_used else ""
        print(
            f"  {t.side:5} {t.kind:18} PnL=${t.pnl_usdc:+8.2f} "
            f"{t.result:7}{lev} | {t.reason[:44]}"
        )


def print_compare(results: dict) -> None:
    labels = list(results.keys())
    summaries = {k: results[k].summary() for k in labels}
    print()
    print("=" * 80)
    print("COMPARAÇÃO " + " vs ".join(labels))
    print("=" * 80)
    header = f"{'Métrica':<14}" + "".join(f"{k:>16}" for k in labels)
    print(header)
    metrics = [
        ("Trades", "trades"),
        ("Win rate %", "win_rate_pct"),
        ("PnL $", "pnl_usdc"),
        ("Retorno %", "return_pct"),
        ("CAGR %", "cagr_pct"),
        ("Equity $", "equity_final"),
        ("PF", "profit_factor"),
        ("Max DD %", "max_dd_pct"),
        ("Avg Lev", "avg_leverage"),
        ("Veredito", "verdict"),
    ]
    for name, key in metrics:
        row = f"{name:<14}"
        for lab in labels:
            row += f"{str(summaries[lab].get(key, '—')):>16}"
        print(row)
    for lab in labels:
        print(f"\n{lab} by_year: {summaries[lab].get('by_year')}")


def main() -> int:
    p = argparse.ArgumentParser(description="Backtest Candle Dynamics BTC")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--years", type=float, default=5.0)
    p.add_argument("--position", type=float, default=100.0, help="Notional fixo (sizing=fixed)")
    p.add_argument("--capital", type=float, default=1000.0)
    p.add_argument(
        "--version",
        choices=("v1", "v2", "v2-short"),
        default="v1",
        help="v1=baseline; v2=filtros; v2-short=só impulsão short",
    )
    p.add_argument(
        "--sizing",
        choices=("fixed", "risk", "auto"),
        default="auto",
        help="auto: risk para v2-short, fixed para demais",
    )
    p.add_argument("--risk-pct", type=float, default=2.0, help="% equity no stop (sizing=risk)")
    p.add_argument("--max-leverage", type=float, default=8.0)
    p.add_argument(
        "--compare",
        action="store_true",
        help="Compara v1/v2 (fixed $100) e v2-short (risk sizing)",
    )
    p.add_argument("--json-out", type=Path, default=None)
    p.add_argument("--cache-dir", type=Path, default=None)
    args = p.parse_args()

    logger.info("Carregando %s M5 (%.1f anos)…", args.symbol, args.years)
    df_5m = load_klines(args.symbol, "5m", years=args.years, cache_dir=args.cache_dir)
    logger.info(
        "M5: %d barras (%s → %s)",
        len(df_5m),
        df_5m["timestamps"].iloc[0],
        df_5m["timestamps"].iloc[-1],
    )

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

    common = dict(
        df_5m=df_5m,
        df_30m=df_30m,
        df_1h=df_1h,
        df_1d=df_1d,
        df_1w=df_1w,
        symbol=args.symbol,
        initial_capital=args.capital,
        position_usdc=args.position,
    )

    def resolve_sizing(version: str) -> tuple[str, float, float]:
        if args.sizing == "auto":
            if version == "v2-short":
                return "risk", args.risk_pct, args.max_leverage
            return "fixed", 0.0, 1.0
        if args.sizing == "risk":
            return "risk", args.risk_pct, args.max_leverage
        return "fixed", 0.0, 1.0

    if args.compare:
        results = {}
        for ver in ("v1", "v2", "v2-short"):
            sizing, risk, max_lev = resolve_sizing(ver)
            # No compare: v1/v2 ficam fixed $100; v2-short usa risk
            if ver != "v2-short":
                sizing, risk, max_lev = "fixed", 0.0, 1.0
            else:
                sizing, risk, max_lev = "risk", args.risk_pct, args.max_leverage
            logger.info("Rodando %s (sizing=%s)…", ver, sizing)
            results[ver] = run_backtest(
                **common,
                version=ver,
                sizing=sizing,
                risk_pct=risk or args.risk_pct,
                max_leverage=max_lev,
            )
            print_report(results[ver], ver)
        print_compare(results)
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            payload = {k: v.summary() for k, v in results.items()}
            args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            logger.info("JSON salvo em %s", args.json_out)
        return 0

    sizing, risk, max_lev = resolve_sizing(args.version)
    result = run_backtest(
        **common,
        version=args.version,
        sizing=sizing,
        risk_pct=risk or args.risk_pct,
        max_leverage=max_lev,
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
                "notional": t.notional,
                "leverage": t.leverage_used,
                "reason": t.reason,
            }
            for t in result.trades[:50]
        ]
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("JSON salvo em %s", args.json_out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
