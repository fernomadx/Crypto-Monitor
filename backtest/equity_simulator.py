"""Simulação de equity com alavancagem a partir da lista de trades."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.ema_retest_strategy import Trade


@dataclass
class EquityTradeResult:
    trade: Trade
    equity_before: float
    notional: float
    pnl_usd: float
    fee_usd: float
    equity_after: float
    pnl_pct_on_equity: float


@dataclass
class EquitySummary:
    initial_capital: float
    final_capital: float
    leverage: int
    fixed_margin_usdc: float | None
    trades_skipped: int
    total_return_pct: float
    total_return_usd: float
    max_drawdown_pct: float
    max_drawdown_usd: float
    total_trades: int
    win_rate_pct: float
    liquidated: bool
    trade_results: list[EquityTradeResult]
    equity_curve: pd.DataFrame
    monthly: pd.DataFrame


def simulate_equity(
    trades: list[Trade],
    initial_capital: float = 1000.0,
    leverage: int = 20,
    fee_rate: float = 0.0005,
    fixed_margin_usdc: float | None = None,
) -> EquitySummary:
    """
    Modo A (padrão): margem = equity; notional = equity * leverage.
    Modo B (fixed_margin_usdc): margem fixa por trade (ex. 100 USDC).
    """
    equity = initial_capital
    peak = equity
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    results: list[EquityTradeResult] = []
    curve_rows: list[dict] = []
    liquidated = False
    skipped = 0

    wins = 0

    for trade in trades:
        if trade.pnl_pct is None or trade.exit_time is None:
            continue
        if equity <= 0:
            liquidated = True
            break

        equity_before = equity
        if fixed_margin_usdc is not None:
            if equity_before < fixed_margin_usdc:
                skipped += 1
                continue
            margin = fixed_margin_usdc
        else:
            margin = equity_before
        notional = margin * leverage
        fee_usd = notional * fee_rate * 2
        pnl_usd = notional * (trade.pnl_pct / 100) - fee_usd
        equity_after = max(0.0, equity + pnl_usd)
        pnl_pct_equity = (pnl_usd / equity_before * 100) if equity_before > 0 else 0.0

        if pnl_usd > 0:
            wins += 1

        results.append(
            EquityTradeResult(
                trade=trade,
                equity_before=equity_before,
                notional=notional,
                pnl_usd=pnl_usd,
                fee_usd=fee_usd,
                equity_after=equity_after,
                pnl_pct_on_equity=pnl_pct_equity,
            )
        )

        curve_rows.append(
            {
                "timestamp": trade.exit_time,
                "equity": equity_after,
                "pnl_usd": pnl_usd,
                "side": trade.side.name,
            }
        )

        equity = equity_after
        peak = max(peak, equity)
        dd_usd = peak - equity
        dd_pct = (dd_usd / peak * 100) if peak > 0 else 0.0
        max_dd_usd = max(max_dd_usd, dd_usd)
        max_dd_pct = max(max_dd_pct, dd_pct)

        if equity <= 0:
            liquidated = True
            break

    equity_curve = pd.DataFrame(curve_rows)
    if not equity_curve.empty:
        equity_curve.set_index("timestamp", inplace=True)

    monthly = _monthly_breakdown(results, initial_capital, equity_curve)

    closed = len(results)
    return EquitySummary(
        initial_capital=initial_capital,
        final_capital=equity,
        leverage=leverage,
        fixed_margin_usdc=fixed_margin_usdc,
        trades_skipped=skipped,
        total_return_pct=((equity - initial_capital) / initial_capital * 100)
        if initial_capital > 0
        else 0.0,
        total_return_usd=equity - initial_capital,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_usd=max_dd_usd,
        total_trades=closed,
        win_rate_pct=(wins / closed * 100) if closed else 0.0,
        liquidated=liquidated,
        trade_results=results,
        equity_curve=equity_curve,
        monthly=monthly,
    )


def _monthly_breakdown(
    results: list[EquityTradeResult],
    initial_capital: float,
    equity_curve: pd.DataFrame,
) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    rows: list[dict] = []
    by_month: dict[str, list[EquityTradeResult]] = {}
    for r in results:
        month = r.trade.exit_time.strftime("%Y-%m")
        by_month.setdefault(month, []).append(r)

    running_equity = initial_capital
    global_peak = initial_capital

    for month in sorted(by_month.keys()):
        month_trades = by_month[month]
        start_eq = running_equity
        month_peak = start_eq
        month_max_dd_pct = 0.0
        month_pnl = 0.0
        month_wins = 0

        for r in month_trades:
            month_pnl += r.pnl_usd
            running_equity = r.equity_after
            month_peak = max(month_peak, running_equity)
            global_peak = max(global_peak, running_equity)
            dd = (global_peak - running_equity) / global_peak * 100 if global_peak > 0 else 0
            month_dd = (month_peak - running_equity) / month_peak * 100 if month_peak > 0 else 0
            month_max_dd_pct = max(month_max_dd_pct, month_dd, dd)
            if r.pnl_usd > 0:
                month_wins += 1

        ret_pct = (month_pnl / start_eq * 100) if start_eq > 0 else 0.0
        rows.append(
            {
                "month": month,
                "trades": len(month_trades),
                "wins": month_wins,
                "win_rate_pct": round(month_wins / len(month_trades) * 100, 1),
                "start_usdc": round(start_eq, 2),
                "end_usdc": round(running_equity, 2),
                "pnl_usdc": round(month_pnl, 2),
                "return_pct": round(ret_pct, 2),
                "max_dd_pct": round(month_max_dd_pct, 2),
                "cumulative_usdc": round(running_equity, 2),
                "cumulative_return_pct": round(
                    (running_equity - initial_capital) / initial_capital * 100, 2
                ),
            }
        )

    return pd.DataFrame(rows)
