# -*- coding: utf-8 -*-
"""Data-quality policy schema (workflow C.1).

Turns the read-only data-quality overview (block statuses + overall score) and the
market phase into structured decision constraints. The engine is deterministic and
side-effect free: it only *produces* a :class:`QualityPolicyDecision`; consumers
(prompt injection, decision guardrail, signal generation, alerts) are wired
separately so the framework can ship and be reviewed in isolation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Action vocabulary. Kept as a closed Literal so consumers can switch exhaustively.
PolicyActionType = Literal[
    "prohibit_precise_entry",
    "cap_confidence",
    "downgrade_event_signal",
    "observation_only",
    "require_alert_confirmation",
]

# Confidence levels, ordered from tightest (low) to loosest (high).
ConfidenceCap = Literal["high", "medium", "low"]
_CONFIDENCE_RANK: Dict[str, int] = {"low": 0, "medium": 1, "high": 2}

# Core data blocks whose simultaneous degradation forces observation-only output.
CORE_QUALITY_BLOCKS = ("quote", "daily_bars", "technical")
# Statuses that count as "degraded" for a block (mirrors the prompt/guardrail layer).
DEGRADED_BLOCK_STATUSES = frozenset(
    {"stale", "fallback", "missing", "fetch_failed", "partial", "estimated"}
)


class PolicyAction(BaseModel):
    """One action a policy applies when its trigger fires."""

    model_config = ConfigDict(extra="forbid")

    type: PolicyActionType
    params: Dict[str, Any] = Field(default_factory=dict)


class PolicyTrigger(BaseModel):
    """Conditions under which a policy fires.

    All *specified* conditions must hold (logical AND). A trigger with no
    conditions never fires, to avoid an accidental match-all footgun.
    """

    model_config = ConfigDict(extra="forbid")

    overall_score_below: Optional[int] = None
    block_status_in: Dict[str, List[str]] = Field(default_factory=dict)
    min_degraded_core_blocks: Optional[int] = None
    phase_in: Optional[List[str]] = None

    def is_empty(self) -> bool:
        return (
            self.overall_score_below is None
            and not self.block_status_in
            and self.min_degraded_core_blocks is None
            and not self.phase_in
        )


class QualityPolicy(BaseModel):
    """A single named policy: trigger + actions."""

    model_config = ConfigDict(extra="forbid")

    id: str
    description: str = ""
    enabled: bool = True
    trigger: PolicyTrigger
    actions: List[PolicyAction] = Field(default_factory=list)


class PolicyMatch(BaseModel):
    """A policy that fired, with the actions and the human-readable reason."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str
    actions: List[PolicyAction]
    reason: str


class QualityPolicyDecision(BaseModel):
    """The resolved outcome of evaluating all policies against one analysis context."""

    model_config = ConfigDict(extra="forbid")

    matched: List[PolicyMatch] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.matched

    @property
    def matched_policy_ids(self) -> List[str]:
        return [m.policy_id for m in self.matched]

    @property
    def reasons(self) -> List[str]:
        return [m.reason for m in self.matched if m.reason]

    def _all_actions(self) -> List[PolicyAction]:
        return [action for match in self.matched for action in match.actions]

    @property
    def action_types(self) -> List[str]:
        seen: List[str] = []
        for action in self._all_actions():
            if action.type not in seen:
                seen.append(action.type)
        return seen

    def has_action(self, action_type: str) -> bool:
        return action_type in self.action_types

    @property
    def prohibit_precise_entry(self) -> bool:
        return self.has_action("prohibit_precise_entry")

    @property
    def observation_only(self) -> bool:
        return self.has_action("observation_only")

    @property
    def downgrade_event_signal(self) -> bool:
        return self.has_action("downgrade_event_signal")

    @property
    def require_alert_confirmation(self) -> bool:
        return self.has_action("require_alert_confirmation")

    @property
    def confidence_cap(self) -> Optional[str]:
        """The tightest confidence cap requested across all matched policies."""
        tightest: Optional[str] = None
        for action in self._all_actions():
            if action.type != "cap_confidence":
                continue
            level = str(action.params.get("max_level", "")).strip().lower()
            if level not in _CONFIDENCE_RANK:
                continue
            if tightest is None or _CONFIDENCE_RANK[level] < _CONFIDENCE_RANK[tightest]:
                tightest = level
        return tightest

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe projection for persistence into the context snapshot / API."""
        return {
            "matched": [
                {
                    "policy_id": m.policy_id,
                    "reason": m.reason,
                    "actions": [{"type": a.type, "params": a.params} for a in m.actions],
                }
                for m in self.matched
            ],
            "action_types": self.action_types,
            "confidence_cap": self.confidence_cap,
            "reasons": self.reasons,
        }
