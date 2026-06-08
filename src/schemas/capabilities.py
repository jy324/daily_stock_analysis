# -*- coding: utf-8 -*-
"""Runtime capability response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class AShareIntelligenceCapability(BaseModel):
    enabled: bool = False
    provider_installed: bool = False
    report_enabled: bool = False
    agent_tools_enabled: bool = False
    scoring_enabled: bool = False


class RuntimeCapabilities(BaseModel):
    ashare_intelligence: AShareIntelligenceCapability
