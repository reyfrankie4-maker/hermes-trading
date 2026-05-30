#!/usr/bin/env python3
"""Score trades against the goal. Returns float in [-1, +1].

Composite of:
  - Realised return vs target (weight: 0.4)
  - Drawdown vs max (weight: 0.3)
  - Sharpe vs min (weight: 0.3)

Score < 0 means the agent is underperforming.
Score >= 0.7 means strong performance.
"""

from __future__ import annotations

import math
from typing import Any


def score(trades: list[dict], goal: dict) -> dict:
    """Score a set of trades against the goal.

    Args:
        trades: List of trade dicts with 'pnl', 'won', 'pnl_pct' keys.
        goal: Goal config with target_return_30d, max_drawdown, min_sharpe.

    Returns:
        Dict with 'composite', 'realised_return', 'drawdown', 'sharpe',
        'win_rate', and individual component scores.
    """
    if not trades:
        return {
            "composite": 0.0,
            "realised_return": 0.0,
            "drawdown": 0.0,
            "sharpe": 0.0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "n_trades": 0,
        }

    n = len(trades)
    pnls = [t.get("pnl", 0) or 0 for t in trades]
    pnl_pcts = [t.get("pnl_pct", 0) or 0 for t in trades]
    wins = sum(1 for t in trades if t.get("won", False))

    # Basic stats
    total_pnl = sum(pnls)
    win_rate = wins / n if n > 0 else 0.0

    # Realised return (cumulative PnL% — simulates compounding)
    realised_return = sum(pnl_pcts) / 100 if pnl_pcts else 0.0

    # Max drawdown: largest peak-to-trough in cumulative returns
    cumulative = []
    running = 0.0
    for p in pnl_pcts:
        running += p
        cumulative.append(running)
    peak = cumulative[0] if cumulative else 0.0
    dd = 0.0
    for c in cumulative:
        if c > peak:
            peak = c
        drawdown = peak - c
        if drawdown > dd:
            dd = drawdown
    drawdown = dd / 100 if dd > 0 else 0.0

    # Sharpe ratio (annualised)
    if len(pnl_pcts) > 1 and (std := _std(pnl_pcts)) > 0:
        avg = sum(pnl_pcts) / len(pnl_pcts)
        sharpe = (avg / std) * math.sqrt(365)  # daily → annualised
    else:
        sharpe = 0.0

    target_return = goal.get("target_return_30d", 0.05)
    max_dd = goal.get("max_drawdown", 0.08)
    min_sharpe = goal.get("min_sharpe", 1.0)

    # Component scores (each in [-1, +1])
    # Return score: 0 at target, +1 at 2x target, -1 at 0
    return_score = _clip(realised_return / target_return - 0.5, -1.0, 1.0) if target_return > 0 else 0.0

    # Drawdown score: +1 at 0 drawdown, 0 at max, -1 at 2x max
    dd_score = _clip(1.0 - (drawdown / max_dd) if max_dd > 0 else 0.0, -1.0, 1.0)

    # Sharpe score: +1 at min, -1 at 0
    sharpe_score = _clip(sharpe / min_sharpe - 0.5, -1.0, 1.0) if min_sharpe > 0 else 0.0

    # Composite (weighted)
    composite = 0.4 * return_score + 0.3 * dd_score + 0.3 * sharpe_score
    composite = max(-1.0, min(1.0, composite))

    return {
        "composite": round(composite, 4),
        "realised_return": round(realised_return, 4),
        "drawdown": round(drawdown, 4),
        "sharpe": round(sharpe, 4),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "n_trades": n,
        "return_score": round(return_score, 4),
        "dd_score": round(dd_score, 4),
        "sharpe_score": round(sharpe_score, 4),
    }


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _std(values: list[float]) -> float:
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)
