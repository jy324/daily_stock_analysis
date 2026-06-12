# -*- coding: utf-8 -*-
"""Version-attribution helpers (workflow D.2).

Small, pure utilities for attributing an analysis to the prompt template and
strategy version that produced it, so backtest/evaluation can later group results
by model / prompt version / strategy.
"""

from __future__ import annotations

import hashlib
from typing import Optional

DEFAULT_STRATEGY_VERSION = "v1"


def compute_prompt_version_hash(prompt_text: Optional[str]) -> Optional[str]:
    """Return the first 16 hex chars of the SHA-256 of ``prompt_text``.

    Returns ``None`` for empty/None input so callers persist a clean NULL rather
    than a hash of the empty string. The hash captures the prompt *template*
    actually used (market role + skills + language), not per-stock substitutions.
    """
    if not prompt_text:
        return None
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
