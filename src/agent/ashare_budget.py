# -*- coding: utf-8 -*-
"""Request-scoped A-share intelligence query budgets for Agent runs."""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass
class AShareQueryBudget:
    market_limit: int
    stock_limit: int
    market_used: int = 0
    stock_used: int = 0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def consume(self, kind: str) -> Optional[Dict[str, Any]]:
        if kind not in {"market", "stock"}:
            kind = "stock"
        with self._lock:
            limit = self.market_limit if kind == "market" else self.stock_limit
            used = self.market_used if kind == "market" else self.stock_used
            if used >= limit:
                return {
                    "error": "ashare_query_budget_exceeded",
                    "budget_type": kind,
                    "limit": limit,
                    "used": used,
                }
            if kind == "market":
                self.market_used += 1
            else:
                self.stock_used += 1
        return None


_BUDGET_CONTEXT: contextvars.ContextVar[Optional[AShareQueryBudget]] = contextvars.ContextVar(
    "ashare_query_budget",
    default=None,
)


def activate_ashare_query_budget(config: Any) -> contextvars.Token:
    """Activate one Agent-run budget context from ashare_intelligence.yaml."""
    market_budget, stock_budget = _load_budget_limits(config)
    return _BUDGET_CONTEXT.set(
        AShareQueryBudget(
            market_limit=market_budget,
            stock_limit=stock_budget,
        )
    )


def reset_ashare_query_budget(token: contextvars.Token) -> None:
    _BUDGET_CONTEXT.reset(token)


def consume_ashare_query_budget(kind: str) -> Optional[Dict[str, Any]]:
    budget = _BUDGET_CONTEXT.get()
    if budget is None:
        return None
    return budget.consume(kind)


def _load_budget_limits(config: Any) -> tuple[int, int]:
    config_file = Path(str(getattr(config, "ashare_config_file", "") or ""))
    raw: Dict[str, Any] = {}
    if config_file.exists():
        try:
            loaded = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, yaml.YAMLError):
            raw = {}
    section = raw.get("agent_tools") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        section = {}
    return (
        _safe_budget(section.get("market_query_budget"), default=3),
        _safe_budget(section.get("stock_query_budget"), default=10),
    )


def _safe_budget(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, parsed)
