# -*- coding: utf-8 -*-
"""Default-disabled deterministic A-share scoring service."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from src.schemas.ashare_scoring import ASharePersistenceScore, AShareSignalScore

SCORING_VERSION = "ashare-scoring-v1"
MIN_COVERAGE_FOR_SCORE = 0.60

_POSITIVE_FEATURE_WEIGHTS = {
    "net_inflow_strength": 0.45,
    "sector_breadth": 0.30,
    "capital_persistence": 0.25,
}

_RISK_FEATURE_WEIGHTS = {
    "dragon_tiger_risk": 0.40,
    "unlock_pressure": 0.35,
    "announcement_risk": 0.15,
    "outflow_pressure": 0.10,
}


class AShareScoringService:
    """Score only structured A-share signals; LLM text is intentionally ignored."""

    def __init__(self, config: Any):
        self.config = config

    def score_signals(self, raw_features: Dict[str, Any], *, coverage: float) -> AShareSignalScore:
        if not bool(getattr(self.config, "ashare_scoring_enabled", False)):
            return AShareSignalScore(
                version=SCORING_VERSION,
                warnings=["scoring_disabled"],
            )

        coverage_value = _clamp(coverage)
        features = _extract_numeric_features(raw_features)
        warnings: List[str] = []
        if coverage_value < MIN_COVERAGE_FOR_SCORE:
            warnings.append("coverage_below_threshold")
            return AShareSignalScore(
                coverage=coverage_value,
                confidence=coverage_value,
                version=SCORING_VERSION,
                features=features,
                warnings=warnings,
            )

        positive = _weighted_average(features, _POSITIVE_FEATURE_WEIGHTS)
        risk = _weighted_average(features, _RISK_FEATURE_WEIGHTS)
        score = _clamp(0.5 + positive * 0.5 - risk * 0.5) * 100.0

        return AShareSignalScore(
            score=round(score, 2),
            confidence=coverage_value,
            coverage=coverage_value,
            version=SCORING_VERSION,
            features=features,
            warnings=warnings,
            risk_pressure_score=round(risk * 100.0, 2),
        )

    def persistence_score(self, values: Iterable[Optional[float]], *, window: int) -> ASharePersistenceScore:
        numeric_values = [
            _clamp(value)
            for value in values
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if len(numeric_values) < window:
            return ASharePersistenceScore(
                value=None,
                window=window,
                version=SCORING_VERSION,
                warnings=["insufficient_history"],
            )
        recent = numeric_values[-window:]
        return ASharePersistenceScore(
            value=round(sum(recent) / float(window), 4),
            window=window,
            version=SCORING_VERSION,
            warnings=[],
        )


def _extract_numeric_features(raw_features: Dict[str, Any]) -> Dict[str, float]:
    allowed = set(_POSITIVE_FEATURE_WEIGHTS) | set(_RISK_FEATURE_WEIGHTS)
    features: Dict[str, float] = {}
    for key, value in (raw_features or {}).items():
        if key not in allowed:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        features[key] = _clamp(value)
    return features


def _weighted_average(features: Dict[str, float], weights: Dict[str, float]) -> float:
    weighted_total = 0.0
    available_weight = 0.0
    for key, weight in weights.items():
        if key not in features:
            continue
        weighted_total += features[key] * weight
        available_weight += weight
    if available_weight <= 0.0:
        return 0.0
    return weighted_total / available_weight


def _clamp(value: Any, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return minimum
    return min(max(numeric, minimum), maximum)
