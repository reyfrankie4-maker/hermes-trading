#!/usr/bin/env python3
"""Entrypoint — starts the 24/7 trading loop.

Usage:
    python -m hermes_trading.run              # uses asset from goal.yaml
    python -m hermes_trading.run --asset ETH/USDC  # override asset
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
STATE = HERE.parent / "state"
GOAL_PATH = STATE / "goal.yaml"


def load_goal() -> dict:
    with open(GOAL_PATH) as f:
        return yaml.safe_load(f) or {}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Hermes Trading Worker")
    p.add_argument("--asset", default=None, help="Override asset from goal.yaml")
    return p.parse_args(argv)


async def main() -> None:
    args = parse_args()
    goal = load_goal()
    asset = args.asset or goal.get("asset", "BTC/USDC")

    print(f"Booting hermes-trading worker — asset={asset}")

    from hermes_trading.loop import TradingLoop

    loop = TradingLoop(asset=asset, goal=goal)
    await loop.run()


if __name__ == "__main__":
    asyncio.run(main())
