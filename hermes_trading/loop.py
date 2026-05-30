#!/usr/bin/env python3
"""24/7 reliability loop — pull data, evaluate strategy, paper trade, log.

Every minute: fetch price via adapters → evaluate entry conditions →
paper trade if conditions fire → log outcome → write heartbeat.

Per-adapter retries: 3, exponential backoff.
Circuit-break after 5 consecutive failures.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
STATE = HERE.parent / "state"

TRADES_PATH = STATE / "trades.jsonl"
STRAT_PATH = STATE / "strategy.yaml"
HEARTBEAT_PATH = STATE / "heartbeat.json"
GOAL_PATH = STATE / "goal.yaml"


class TradingLoop:
    """Async loop that runs forever: fetch → evaluate → trade → log."""

    def __init__(self, *, asset: str, goal: dict) -> None:
        self._asset = asset
        self._goal = goal
        self._running = False
        self._consecutive_failures = 0
        self._max_failures = 5
        self._tick: float = 0

    async def run(self) -> None:
        self._running = True
        self._write_heartbeat({"status": "starting", "asset": self._asset})

        print(f"Loop started — {self._asset}, tick every 60s")
        while self._running:
            try:
                await self._tick()
                self._consecutive_failures = 0
            except Exception:
                self._consecutive_failures += 1
                traceback.print_exc()
                if self._consecutive_failures >= self._max_failures:
                    print(f"CIRCUIT BREAK — {self._consecutive_failures} consecutive failures")
                    self._write_heartbeat({"status": "circuit_break", "error": str(traceback.format_exc())})
                    await asyncio.sleep(300)  # 5 min cool-off
                    self._consecutive_failures = 0

            await asyncio.sleep(60)
            self._tick += 1

    async def _tick(self) -> None:
        """One loop iteration."""
        # 1. Load current strategy
        strategy = self._load_strategy()

        # 2. Fetch data from adapters (with retries)
        data = await self._fetch_data()

        # 3. Evaluate entry conditions
        signal = self._evaluate(strategy, data)

        # 4. Paper trade if signal fires
        if signal:
            trade = self._paper_trade(signal, data)
            self._log_trade(trade)
            print(f"[TRADE] {trade['action'].upper()} {self._asset} — reason={trade.get('reason', '')}")

        # 5. Write heartbeat
        self._write_heartbeat({
            "status": "running",
            "tick": self._tick,
            "asset": self._asset,
            "price": data.get("price", 0),
            "last_trade": signal is not None,
        })

    def _load_strategy(self) -> dict:
        try:
            with open(STRAT_PATH) as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {"version": "01", "entry": {"indicator": "rsi", "threshold": 30, "direction": "long"},
                    "stop_loss_pct": 2.0, "position_size_r": 0.5}

    async def _fetch_data(self) -> dict:
        """Fetch market data with retries (3 attempts, exponential backoff)."""
        from hermes_trading.adapters.price import PriceAdapter

        last_error = None
        for attempt in range(3):
            try:
                adapter = PriceAdapter()
                result = await adapter.fetch(self._asset)
                if result and result.get("schema_version"):
                    return result
            except Exception as e:
                last_error = e
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise last_error or RuntimeError("All data fetch attempts failed")

    def _evaluate(self, strategy: dict, data: dict) -> dict | None:
        """Check if entry conditions fire. Returns signal dict or None."""
        entry = strategy.get("entry", {})
        price = data.get("price", 0)
        if not price:
            return None

        threshold = entry.get("threshold", 30)
        direction = entry.get("direction", "long")

        # RSI-based entry
        rsi = data.get("rsi", 50)
        if direction == "long" and rsi <= threshold:
            return {
                "action": "buy",
                "reason": f"RSI {rsi:.1f} <= {threshold}",
                "price": price,
                "direction": "long",
            }
        elif direction == "short" and rsi >= (100 - threshold):
            return {
                "action": "sell",
                "reason": f"RSI {rsi:.1f} >= {100 - threshold}",
                "price": price,
                "direction": "short",
            }
        return None

    def _paper_trade(self, signal: dict, data: dict) -> dict:
        """Simulate a paper trade."""
        strategy = self._load_strategy()
        sl_pct = strategy.get("stop_loss_pct", 2.0)
        size_r = strategy.get("position_size_r", 0.5)
        price = signal.get("price", data.get("price", 0))

        # Simulate outcome (in production, we'd wait for fill)
        # For paper: assume fills at current price, with random slippage ±0.1%
        import random
        slippage = price * (random.uniform(-0.001, 0.001))
        fill_price = price + slippage

        # Random P&L for simulation (in production, this comes from real fills)
        # Weighted slightly positive (55% win rate baseline)
        won = random.random() < 0.55
        pnl_pct = random.uniform(0.5, 3.0) if won else random.uniform(-1.0, -sl_pct)
        pnl = fill_price * size_r * (pnl_pct / 100)

        return {
            "ts": time.time(),
            "asset": self._asset,
            "action": signal["action"],
            "direction": signal["direction"],
            "entry_price": round(fill_price, 2),
            "size_r": size_r,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "won": won,
            "reason": signal.get("reason", ""),
            "stop_loss_pct": sl_pct,
            "strategy_version": strategy.get("version", "00"),
        }

    def _log_trade(self, trade: dict) -> None:
        """Append trade to trades.jsonl."""
        TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRADES_PATH, "a") as f:
            f.write(json.dumps(trade) + "\n")

    def _write_heartbeat(self, state: dict) -> None:
        state["_ts"] = time.time()
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HEARTBEAT_PATH, "w") as f:
            json.dump(state, f)
