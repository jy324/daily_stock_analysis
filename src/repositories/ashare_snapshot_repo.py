# -*- coding: utf-8 -*-
"""A-share intelligence snapshot repository."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy import and_, func, select

from src.storage import AShareIntelligenceSnapshot, DatabaseManager


class AShareSnapshotRepository:
    """Read/write repository for A-share intelligence snapshots."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def save_snapshot(
        self,
        *,
        snapshot_type: str,
        trade_date: str | date,
        as_of: str | datetime,
        as_of_bucket: str,
        run_id: Optional[str],
        provider_set: str,
        is_final: bool,
        coverage_ratio: Optional[float],
        payload: Dict[str, Any],
        schema_version: str,
        config_hash: Optional[str],
    ) -> AShareIntelligenceSnapshot:
        trade_day = _parse_date(trade_date)
        as_of_dt = _parse_datetime(as_of)
        payload_json = _canonical_json(payload)
        source_hash = _sha256(payload_json)
        provider_set_json, provider_set_hash, normalized_provider_set = _normalize_provider_set(provider_set)
        revision = self._next_revision(
            snapshot_type=snapshot_type,
            trade_date=trade_day,
            as_of_bucket=as_of_bucket,
            schema_version=schema_version,
            provider_set_hash=provider_set_hash,
        )
        snapshot_id = _snapshot_id(
            snapshot_type=snapshot_type,
            trade_date=trade_day,
            as_of_bucket=as_of_bucket,
            schema_version=schema_version,
            provider_set_hash=provider_set_hash,
            revision=revision,
        )

        session = self.db.get_session()
        try:
            row = AShareIntelligenceSnapshot(
                snapshot_id=snapshot_id,
                snapshot_type=snapshot_type,
                trade_date=trade_day,
                as_of=as_of_dt,
                as_of_bucket=as_of_bucket,
                run_id=run_id,
                provider_set=normalized_provider_set,
                provider_set_json=provider_set_json,
                provider_set_hash=provider_set_hash,
                is_final=is_final,
                revision=revision,
                coverage_ratio=coverage_ratio,
                payload_json=payload_json,
                schema_version=schema_version,
                source_hash=source_hash,
                config_hash=config_hash,
                generated_at=datetime.now(),
            )
            session.add(row)

            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_snapshot(
        self,
        *,
        snapshot_type: str,
        trade_date: str | date,
        as_of_bucket: str,
        schema_version: str,
        provider_set: str,
    ) -> Optional[Dict[str, Any]]:
        trade_day = _parse_date(trade_date)
        _, provider_set_hash, _ = _normalize_provider_set(provider_set)
        with self.db.get_session() as session:
            row = session.execute(
                _slot_query(
                    snapshot_type=snapshot_type,
                    trade_date=trade_day,
                    as_of_bucket=as_of_bucket,
                    schema_version=schema_version,
                    provider_set_hash=provider_set_hash,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return _row_to_dict(row)

    def _next_revision(
        self,
        *,
        snapshot_type: str,
        trade_date: date,
        as_of_bucket: str,
        schema_version: str,
        provider_set_hash: str,
    ) -> int:
        with self.db.get_session() as session:
            current = session.execute(
                select(func.max(AShareIntelligenceSnapshot.revision)).where(
                    and_(
                        AShareIntelligenceSnapshot.snapshot_type == snapshot_type,
                        AShareIntelligenceSnapshot.trade_date == trade_date,
                        AShareIntelligenceSnapshot.as_of_bucket == as_of_bucket,
                        AShareIntelligenceSnapshot.schema_version == schema_version,
                        AShareIntelligenceSnapshot.provider_set_hash == provider_set_hash,
                    )
                )
            ).scalar_one_or_none()
        return int(current or 0) + 1


def _slot_query(
    *,
    snapshot_type: str,
    trade_date: date,
    as_of_bucket: str,
    schema_version: str,
    provider_set_hash: str,
) -> Any:
    return select(AShareIntelligenceSnapshot).where(
        and_(
            AShareIntelligenceSnapshot.snapshot_type == snapshot_type,
            AShareIntelligenceSnapshot.trade_date == trade_date,
            AShareIntelligenceSnapshot.as_of_bucket == as_of_bucket,
            AShareIntelligenceSnapshot.schema_version == schema_version,
            AShareIntelligenceSnapshot.provider_set_hash == provider_set_hash,
        )
    ).order_by(
        AShareIntelligenceSnapshot.revision.desc(),
        AShareIntelligenceSnapshot.generated_at.desc(),
    ).limit(1)


def _row_to_dict(row: AShareIntelligenceSnapshot) -> Dict[str, Any]:
    return {
        "snapshot_id": row.snapshot_id,
        "snapshot_type": row.snapshot_type,
        "trade_date": row.trade_date,
        "as_of": row.as_of,
        "as_of_bucket": row.as_of_bucket,
        "run_id": row.run_id,
        "provider_set": row.provider_set,
        "provider_set_json": row.provider_set_json,
        "provider_set_hash": row.provider_set_hash,
        "is_final": row.is_final,
        "revision": row.revision,
        "coverage_ratio": row.coverage_ratio,
        "payload": json.loads(row.payload_json),
        "schema_version": row.schema_version,
        "source_hash": row.source_hash,
        "config_hash": row.config_hash,
        "generated_at": row.generated_at,
    }


def _parse_date(value: str | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    normalized = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed.replace(tzinfo=None)


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_provider_set(provider_set: str) -> tuple[str, str, str]:
    providers = sorted(
        {
            part.strip()
            for part in str(provider_set or "").split(",")
            if part.strip()
        }
    )
    if not providers:
        providers = ["unknown"]
    provider_set_json = json.dumps(providers, ensure_ascii=False, separators=(",", ":"))
    return provider_set_json, _sha256(provider_set_json), ",".join(providers)


def _snapshot_id(
    *,
    snapshot_type: str,
    trade_date: date,
    as_of_bucket: str,
    schema_version: str,
    provider_set_hash: str,
    revision: int,
) -> str:
    raw = "|".join(
        [
            snapshot_type,
            trade_date.isoformat(),
            as_of_bucket,
            schema_version,
            provider_set_hash,
            str(revision),
        ]
    )
    return f"ashare_{_sha256(raw)[:24]}"
