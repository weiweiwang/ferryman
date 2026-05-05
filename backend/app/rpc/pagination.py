from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional, TypeVar

from sqlalchemy import and_, or_
from sqlmodel import desc

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT")


def encode_datetime_cursor(sort_at: datetime, entity_id: str) -> str:
    if sort_at.tzinfo is None:
        sort_at = sort_at.replace(tzinfo=timezone.utc)
    normalized = sort_at.astimezone(timezone.utc).isoformat()
    return json.dumps({"sort_at": normalized, "id": entity_id}, separators=(",", ":"))


def decode_datetime_cursor(cursor: str) -> tuple[datetime, str]:
    payload = json.loads(cursor)
    if not isinstance(payload, dict):
        raise ValueError("Cursor payload must be an object.")

    sort_at = payload.get("sort_at")
    entity_id = payload.get("id")
    if not isinstance(sort_at, str) or not isinstance(entity_id, str):
        raise ValueError("Cursor must include string sort_at and id fields.")

    parsed_at = datetime.fromisoformat(sort_at)
    if parsed_at.tzinfo is None:
        parsed_at = parsed_at.replace(tzinfo=timezone.utc)

    return parsed_at, entity_id


def fetch_datetime_cursor_page(
    db_session,
    statement,
    *,
    model: type[ModelT],
    sort_field: str,
    cursor: Optional[str],
    limit: int,
) -> tuple[list[ModelT], Optional[str]]:
    limit = max(1, limit)
    sort_column = getattr(model, sort_field)
    id_column = getattr(model, "id")

    statement = statement.order_by(desc(sort_column), desc(id_column))
    if cursor:
        try:
            cursor_dt, cursor_id = decode_datetime_cursor(cursor)
            statement = statement.where(
                or_(
                    sort_column < cursor_dt,
                    and_(sort_column == cursor_dt, id_column < cursor_id),
                )
            )
        except Exception as e:
            logger.exception(f"Invalid cursor format: {cursor}, exception: {e}")

    items = list(db_session.exec(statement.limit(limit + 1)).all())
    has_more = len(items) > limit
    if not has_more:
        return items, None

    items = items[:limit]
    last_item = items[-1]
    return items, encode_datetime_cursor(getattr(last_item, sort_field), last_item.id)

