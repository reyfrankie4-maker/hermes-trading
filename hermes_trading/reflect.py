#!/usr/bin/env python3
"""Reflection cycle — TWO modes.

--fallback:  deterministic rule. If return < target → loosen threshold by 2.
             If drawdown > max → tighten stop_loss by 0.2. Changes exactly ONE.
--hermes:    production mode. Reads 25 trades + strategy, calls Hermes as
             subprocess, parses hypothesis, applies it.

Both modes: bump version, save prior to history/, append to hypotheses.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
STATE = HERE.parent / "state"
HISTORY = STATE / "history"
TRADES_PATH = STATE / "trades.jsonl"
STRAT_PATH = STATE / "strategy.yaml"
GOAL_PATH = STATE / "goal.yaml"
HYPOTHESES_PATH = STATE / "hypotheses.jsonl"


# ── Helpers ──────────────────────────────────────────────────────────────


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def _load_strategy() -> dict:
    try:
        with open(STRAT_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {"version": "01", "entry": {"indicator": "rsi", "threshold": 30, "direction": "long"},
                "stop_loss_pct": 2.0, "position_size_r": 0.5}


def _load_goal() -> dict:
    try:
        with open(GOAL_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {"target_return_30d": 0.05, "max_drawdown": 0.08, "min_sharpe": 1.0}


def _save_strategy(strategy: dict) -> None:
    with open(STRAT_PATH, "w") as f:
        yaml.dump(strategy, f, default_flow_style=False, sort_keys=False)


def _save_history(strategy: dict, version: str) -> None:
    HISTORY.mkdir(parents=True, exist_ok=True)
    dst = HISTORY / f"v{version}.yaml"
    with open(dst, "w") as f:
        yaml.dump(strategy, f, default_flow_style=False, sort_keys=False)


def _next_version(current: str) -> str:
    try:
        return f"{int(current):02d}" if current.isdigit() else f"{int(current) + 1:02d}"
    except ValueError:
        return f"{int(current) + 1:02d}" if current.isdigit() else f"{int(current) + 1:02d}"


def _bump_version(strategy: dict) -> tuple[dict, str, str]:
    """Save prior version to history, return (new_strategy, old_ver, new_ver)."""
    old_ver = strategy.get("version", "00")
    new_ver = f"{int(old_ver) + 1:02d}"
    _save_history(dict(strategy), old_ver)
    strategy["version"] = new_ver
    return strategy, old_ver, new_ver


# ── Scoring ──────────────────────────────────────────────────────────────


def _score_trades(trades: list[dict], goal: dict) -> dict:
    """Score trades against goal. Returns composite score + breakdown."""
    from hermes_trading.score import score

    return score(trades, goal)


# ── Fallback mode ────────────────────────────────────────────────────────


def _fallback_reflect(trades: list[dict], goal: dict, strategy: dict) -> dict:
    """Deterministic fallback — change exactly ONE variable.

    Priority:
      1. If drawdown > max → tighten stop_loss_pct by 0.2
      2. If realised return < target → loosen entry.threshold by 2
      3. Else → tighten threshold by 1 (try to improve)
    """
    result = _score_trades(trades, goal)

    hypothesis = {"mode": "fallback", "changed": None, "from": None, "to": None, "reason": ""}

    dd = result.get("drawdown", 0)
    ret = result.get("realised_return", 0)
    target = goal.get("target_return_30d", 0.05)
    max_dd = goal.get("max_drawdown", 0.08)

    if dd > max_dd:
        # 1. Tighten stop loss
        old_sl = strategy.get("stop_loss_pct", 2.0)
        new_sl = round(max(old_sl - 0.2, 0.5), 1)
        strategy["stop_loss_pct"] = new_sl
        hypothesis.update({"changed": "stop_loss_pct", "from": old_sl, "to": new_sl,
                           "reason": f"drawdown {dd:.2%} > max {max_dd:.0%} — tightening stop"})

    elif ret < target:
        # 2. Loosen entry threshold
        old_th = strategy["entry"]["threshold"]
        new_th = min(old_th + 2, 45)
        strategy["entry"]["threshold"] = new_th
        hypothesis.update({"changed": "entry.threshold", "from": old_th, "to": new_th,
                           "reason": f"return {ret:.2%} < target {target:.0%} — loosening entry"})

    else:
        # 3. Tighten threshold incrementally
        old_th = strategy["entry"]["threshold"]
        new_th = max(old_th - 1, 15)
        strategy["entry"]["threshold"] = new_th
        hypothesis.update({"changed": "entry.threshold", "from": old_th, "to": new_th,
                           "reason": f"on track — tightening threshold to improve quality"})

    return hypothesis, strategy, result


# ── Hermes mode ──────────────────────────────────────────────────────────


def _hermes_reflect(trades: list[dict], goal: dict, strategy: dict) -> dict:
    """Call Hermes CLI as subprocess to generate a hypothesis.

    Reads last 25 trades + current strategy, formats as prompt,
    pipes to hermes, parses the JSON response, applies the change.
    """
    recent = trades[-25:] if len(trades) > 25 else trades

    prompt = f"""You are the reflection engine for a self-improving trading agent.

Current strategy:
{yaml.dump(strategy, default_flow_style=False)}

Recent trades ({len(recent)}):
{json.dumps(recent, indent=2)}

Goal:
{yaml.dump(goal, default_flow_style=False)}

Analyse the trades vs the goal. Generate exactly ONE hypothesis that
names exactly ONE variable in strategy.yaml to change, predicts the
score direction, and gives the new value.

Respond with ONLY a JSON object:
{{
  "changed": "the.variable.path",
  "from": <current_value>,
  "to": <new_value>,
  "reason": "why this change",
  "predicted_score_direction": "up" | "down"
}}
"""

    try:
        result = subprocess.run(
            ["hermes", "chat", "-q", prompt],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HERMES_MODE": "silent"},
        )
        output = result.stdout.strip()
        # Try to extract JSON from output
        import re
        json_match = re.search(r'\{[^{}]*\}', output, re.DOTALL)
        if json_match:
            hypothesis = json.loads(json_match.group())
        else:
            raise ValueError("No JSON found in Hermes response")

    except Exception as e:
        # Fallback to deterministic on failure
        print(f"[REFLECT] Hermes call failed ({e}), using fallback")
        return _fallback_reflect(trades, goal, strategy)

    # Apply the change
    path = hypothesis.get("changed", "")
    new_val = hypothesis.get("to")
    parts = path.split(".")
    target = strategy
    for part in parts[:-1]:
        target = target.get(part, {})
    old_val = target.get(parts[-1])
    if old_val is not None and new_val is not None:
        hypothesis["from"] = old_val
        target[parts[-1]] = new_val

    return hypothesis, strategy, _score_trades(trades, goal)


# ── Main ─────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Reflection cycle")
    parser.add_argument("--fallback", action="store_true", help="Use deterministic fallback")
    parser.add_argument("--hermes", action="store_true", help="Use Hermes CLI (production mode)")
    args = parser.parse_args()

    trades = _load_jsonl(TRADES_PATH)
    goal = _load_goal()
    strategy = _load_strategy()

    if not trades:
        print("[REFLECT] No trades yet — skipping reflection")
        return

    # Decide mode
    use_hermes = args.hermes or not args.fallback

    if use_hermes:
        hypothesis, new_strategy, score_result = _hermes_reflect(trades, goal, strategy)
    else:
        hypothesis, new_strategy, score_result = _fallback_reflect(trades, goal, strategy)

    # Bump version and save
    old_ver = new_strategy.get("version", "00")
    new_strategy, old_ver, new_ver = _bump_version(new_strategy)
    _save_strategy(new_strategy)

    # Record hypothesis
    hypothesis_record = {
        "ts": time.time(),
        "mode": "hermes" if use_hermes else "fallback",
        "version_from": old_ver,
        "version_to": new_ver,
        "hypothesis": hypothesis,
        "score": score_result.get("composite", 0),
    }
    _append_jsonl(HYPOTHESES_PATH, hypothesis_record)

    print(f"[REFLECT] {hypothesis_record['mode'].upper()} — v{old_ver} → v{new_ver}")
    print(f"  Changed: {hypothesis.get('changed')} ({hypothesis.get('from')} → {hypothesis.get('to')})")
    print(f"  Reason: {hypothesis.get('reason')}")
    print(f"  Score: {score_result.get('composite', 0):.3f}")


if __name__ == "__main__":
    main()
