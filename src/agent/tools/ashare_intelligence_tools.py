# -*- coding: utf-8 -*-
"""Agent tools for optional A-share intelligence."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict

from src.agent.tools.registry import ToolDefinition, ToolParameter
from src.config import get_config
from src.services.ashare_intelligence_service import AShareIntelligenceService

MARKET_LIMIT_MAX = 50
STOCK_LOOKBACK_MAX = 120


def _handle_get_ashare_market_intelligence(
    capability: str = "sector_fund_flow",
    trade_date: str | None = None,
    limit: int = 10,
    refresh: bool = False,
) -> Dict[str, Any]:
    query_date = trade_date or _default_ashare_trade_date()
    safe_limit = max(1, min(int(limit or 10), MARKET_LIMIT_MAX))
    result = AShareIntelligenceService(get_config()).get_capability(
        capability,
        trade_date=query_date,
        as_of_bucket=f"{query_date}-agent",
        limit=safe_limit,
        refresh=False,
    )
    return _tool_result(result, query={"trade_date": query_date, "limit": safe_limit, "refresh": False})


def _handle_get_ashare_stock_capital_flow(
    code: str,
    trade_date: str | None = None,
    lookback: int = 120,
    refresh: bool = False,
) -> Dict[str, Any]:
    query_date = trade_date or _default_ashare_trade_date()
    safe_lookback = max(1, min(int(lookback or STOCK_LOOKBACK_MAX), STOCK_LOOKBACK_MAX))
    result = AShareIntelligenceService(get_config()).get_capability(
        "capital_flow_daily",
        code=code,
        trade_date=query_date,
        as_of_bucket=f"{query_date}-agent",
        lookback=safe_lookback,
        refresh=False,
    )
    return _tool_result(
        result,
        query={
            "code": code,
            "trade_date": query_date,
            "lookback": safe_lookback,
            "refresh": False,
        },
    )


def _handle_get_ashare_stock_risk_events(
    code: str,
    trade_date: str | None = None,
    lookback: int = 30,
    refresh: bool = False,
) -> Dict[str, Any]:
    query_date = trade_date or _default_ashare_trade_date()
    safe_lookback = max(1, min(int(lookback or 30), STOCK_LOOKBACK_MAX))
    result = AShareIntelligenceService(get_config()).get_risk_events(
        code=code,
        trade_date=query_date,
        as_of_bucket=f"{query_date}-agent",
        lookback=safe_lookback,
        refresh=False,
    )
    return _tool_result(
        result,
        query={
            "code": code,
            "trade_date": query_date,
            "lookback": safe_lookback,
            "refresh": False,
        },
    )


def _tool_result(result: Any, *, query: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "snapshot_id": getattr(result, "snapshot_id", None),
        "cache_hit": bool(getattr(result, "cache_hit", False)),
        "data_status": getattr(result, "status", "unavailable"),
        "coverage": getattr(result, "coverage", {}) or {},
        "provider": getattr(result, "provider", None),
        "source": _source_dict(getattr(result, "source", None)),
        "data": getattr(result, "data", None),
        "query": query,
    }


def _source_dict(source: Any) -> Dict[str, Any]:
    if source is None:
        return {}
    if hasattr(source, "model_dump"):
        return source.model_dump(mode="json")
    if isinstance(source, dict):
        return dict(source)
    return {
        "provider": getattr(source, "provider", None),
        "status": getattr(source, "status", None),
        "as_of": getattr(source, "as_of", None),
        "is_partial": getattr(source, "is_partial", None),
    }


def _default_ashare_trade_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


get_ashare_market_intelligence_tool = ToolDefinition(
    name="get_ashare_market_intelligence",
    description=(
        "Get A-share market intelligence from the configured provider. "
        "Agent refresh requests are ignored; provider gate, cache and status metadata are preserved."
    ),
    parameters=[
        ToolParameter(
            name="capability",
            type="string",
            description="Market capability to query.",
            required=False,
            default="sector_fund_flow",
            enum=["sector_fund_flow", "dragon_tiger_market"],
        ),
        ToolParameter(
            name="trade_date",
            type="string",
            description="Trade date in YYYY-MM-DD format. Defaults to today.",
            required=False,
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description="Maximum rows to return. Hard capped at 50.",
            required=False,
            default=10,
        ),
        ToolParameter(
            name="refresh",
            type="boolean",
            description="Ignored for agent tools; always treated as false.",
            required=False,
            default=False,
        ),
    ],
    handler=_handle_get_ashare_market_intelligence,
    category="market",
)


get_ashare_stock_capital_flow_tool = ToolDefinition(
    name="get_ashare_stock_capital_flow",
    description=(
        "Get A-share stock capital-flow intelligence with status, source, cache and coverage metadata. "
        "Agent refresh requests are ignored."
    ),
    parameters=[
        ToolParameter(
            name="code",
            type="string",
            description="A-share stock code, for example 600519.",
            required=True,
        ),
        ToolParameter(
            name="trade_date",
            type="string",
            description="Trade date in YYYY-MM-DD format. Defaults to today.",
            required=False,
        ),
        ToolParameter(
            name="lookback",
            type="integer",
            description="Daily capital-flow lookback. Hard capped at 120.",
            required=False,
            default=120,
        ),
        ToolParameter(
            name="refresh",
            type="boolean",
            description="Ignored for agent tools; always treated as false.",
            required=False,
            default=False,
        ),
    ],
    handler=_handle_get_ashare_stock_capital_flow,
    category="market",
)


get_ashare_stock_risk_events_tool = ToolDefinition(
    name="get_ashare_stock_risk_events",
    description=(
        "Get deterministic A-share stock risk events including announcements, lockup events, "
        "and dragon-tiger activity. Agent refresh requests are ignored."
    ),
    parameters=[
        ToolParameter(
            name="code",
            type="string",
            description="A-share stock code, for example 600519.",
            required=True,
        ),
        ToolParameter(
            name="trade_date",
            type="string",
            description="Trade date in YYYY-MM-DD format. Defaults to Asia/Shanghai today.",
            required=False,
        ),
        ToolParameter(
            name="lookback",
            type="integer",
            description="Risk-event lookback in days. Hard capped at 120.",
            required=False,
            default=30,
        ),
        ToolParameter(
            name="refresh",
            type="boolean",
            description="Ignored for agent tools; always treated as false.",
            required=False,
            default=False,
        ),
    ],
    handler=_handle_get_ashare_stock_risk_events,
    category="market",
)


ALL_ASHARE_INTELLIGENCE_TOOLS = [
    get_ashare_market_intelligence_tool,
    get_ashare_stock_capital_flow_tool,
    get_ashare_stock_risk_events_tool,
]
