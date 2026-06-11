# -*- coding: utf-8 -*-
"""Data-quality policy engine service (workflow C.1).

Loads policies from a YAML file and evaluates them against the read-only
data-quality overview (block statuses + overall score) plus the market phase.

Design contract:
- Deterministic and side-effect free; only produces a ``QualityPolicyDecision``.
- "No config = no constraints": a missing or unreadable policy file disables all
  policies (the analysis pipeline still runs unchanged).
- Malformed YAML or invalid policy entries degrade cleanly (logged, skipped),
  never raising into the analysis path.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any, List, Optional

import yaml

from src.schemas.quality_policy import (
    CORE_QUALITY_BLOCKS,
    DEGRADED_BLOCK_STATUSES,
    PolicyMatch,
    QualityPolicy,
    QualityPolicyDecision,
)

logger = logging.getLogger(__name__)

DEFAULT_QUALITY_POLICY_FILE = "config/quality_policies.yaml"


class QualityPolicyService:
    """Evaluate data-quality policies for a single analysis context."""

    def __init__(self, policy_file: Optional[str] = None):
        self._policy_file = policy_file or self._resolve_default_policy_file()
        self._cache_key: Optional[tuple] = None
        self._policies: List[QualityPolicy] = []

    @staticmethod
    def _resolve_default_policy_file() -> str:
        env_value = (os.getenv("QUALITY_POLICY_FILE") or "").strip()
        if env_value:
            return env_value
        try:
            from src.config import get_config

            configured = getattr(get_config(), "quality_policy_file", None)
            if configured:
                return str(configured)
        except Exception:
            # Config not available (e.g. isolated unit test); fall back to default path.
            pass
        return DEFAULT_QUALITY_POLICY_FILE

    def _load_policies(self) -> List[QualityPolicy]:
        """Load and cache policies, reloading only when the file's mtime changes."""
        path = self._policy_file
        try:
            stat = os.stat(path)
        except OSError:
            # Missing/unreadable file: all policies off.
            if self._cache_key is not None:
                logger.info("质量策略文件不可读，已关闭全部策略: %s", path)
            self._cache_key = None
            self._policies = []
            return self._policies

        cache_key = (path, stat.st_mtime_ns, stat.st_size)
        if cache_key == self._cache_key:
            return self._policies

        self._cache_key = cache_key
        self._policies = self._parse_policy_file(path)
        return self._policies

    @staticmethod
    def _parse_policy_file(path: str) -> List[QualityPolicy]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("质量策略文件解析失败，已关闭全部策略 (%s): %s", path, exc)
            return []

        if not isinstance(raw, Mapping):
            logger.warning("质量策略文件格式无效（顶层非映射），已关闭全部策略: %s", path)
            return []

        entries = raw.get("policies")
        if not isinstance(entries, list):
            return []

        policies: List[QualityPolicy] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            try:
                policy = QualityPolicy.model_validate(dict(entry))
            except Exception as exc:  # invalid single policy must not break the rest
                logger.warning(
                    "跳过无效质量策略 (%s): %s", entry.get("id", "<no-id>"), exc
                )
                continue
            if policy.enabled and not policy.trigger.is_empty():
                policies.append(policy)
        return policies

    def evaluate(
        self,
        overview: Optional[Mapping[str, Any]],
        phase: Optional[str] = None,
    ) -> QualityPolicyDecision:
        """Evaluate all policies against the overview + phase, returning a decision."""
        policies = self._load_policies()
        if not policies:
            return QualityPolicyDecision()

        block_status = self._block_status_map(overview)
        overall_score = self._overall_score(overview)
        degraded_core = self._degraded_core_count(block_status)
        normalized_phase = str(phase or "").strip().lower() or None

        matches: List[PolicyMatch] = []
        for policy in policies:
            if self._trigger_matches(
                policy.trigger,
                block_status=block_status,
                overall_score=overall_score,
                degraded_core=degraded_core,
                phase=normalized_phase,
            ):
                matches.append(
                    PolicyMatch(
                        policy_id=policy.id,
                        actions=list(policy.actions),
                        reason=policy.description or policy.id,
                    )
                )
        return QualityPolicyDecision(matched=matches)

    @staticmethod
    def _trigger_matches(
        trigger,
        *,
        block_status: dict,
        overall_score: Optional[int],
        degraded_core: int,
        phase: Optional[str],
    ) -> bool:
        if trigger.phase_in is not None:
            allowed = {str(p).strip().lower() for p in trigger.phase_in}
            if phase is None or phase not in allowed:
                return False

        if trigger.overall_score_below is not None:
            # A missing score is "unknown", not "low"; do not fire on it.
            if overall_score is None or overall_score >= trigger.overall_score_below:
                return False

        if trigger.block_status_in:
            for block_key, statuses in trigger.block_status_in.items():
                current = block_status.get(block_key)
                allowed_statuses = {str(s).strip().lower() for s in statuses}
                if current is None or current not in allowed_statuses:
                    return False

        if trigger.min_degraded_core_blocks is not None:
            if degraded_core < trigger.min_degraded_core_blocks:
                return False

        return True

    @staticmethod
    def _block_status_map(overview: Optional[Mapping[str, Any]]) -> dict:
        if not isinstance(overview, Mapping):
            return {}
        blocks = overview.get("blocks")
        if not isinstance(blocks, list):
            return {}
        result: dict = {}
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            key = block.get("key")
            status = block.get("status")
            if key is None or status is None:
                continue
            result[str(key).strip()] = str(status).strip().lower()
        return result

    @staticmethod
    def _overall_score(overview: Optional[Mapping[str, Any]]) -> Optional[int]:
        if not isinstance(overview, Mapping):
            return None
        data_quality = overview.get("data_quality")
        if not isinstance(data_quality, Mapping):
            return None
        value = data_quality.get("overall_score")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _degraded_core_count(block_status: dict) -> int:
        return sum(
            1
            for block in CORE_QUALITY_BLOCKS
            if block_status.get(block) in DEGRADED_BLOCK_STATUSES
        )


def evaluate_quality_policies(
    overview: Optional[Mapping[str, Any]],
    *,
    phase: Optional[str] = None,
    policy_file: Optional[str] = None,
) -> QualityPolicyDecision:
    """Convenience entry point: evaluate policies with a one-off service instance."""
    return QualityPolicyService(policy_file=policy_file).evaluate(overview, phase=phase)
