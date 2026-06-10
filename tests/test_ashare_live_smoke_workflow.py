# -*- coding: utf-8 -*-
"""Static checks for the A-share live smoke workflow."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ashare_live_smoke_fails_provider_step_on_unhealthy_status() -> None:
    workflow_text = (REPO_ROOT / ".github" / "workflows" / "ashare-live-smoke.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    steps = workflow["jobs"]["smoke"]["steps"]
    smoke_step = next(step for step in steps if step.get("name") == "Run A-share provider live smoke")

    assert smoke_step.get("continue-on-error") is not True
    assert 'result.status == "ok"' in smoke_step["run"]
    assert 'result.status == "stale"' in smoke_step["run"]
    assert 'result.status == "empty"' in smoke_step["run"]
    assert 'coverage_ratio >= 0.5' in smoke_step["run"]


def test_ashare_live_smoke_always_uploads_artifact() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "ashare-live-smoke.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["smoke"]["steps"]
    upload_step = next(step for step in steps if step.get("name") == "Upload live smoke logs")

    assert upload_step.get("if") == "always()"
    assert upload_step["with"]["path"] == "ashare-live-smoke.json"
