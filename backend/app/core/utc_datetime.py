from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.types import String, TypeDecorator


def ensure_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_utc_datetime(value: datetime) -> str:
    return ensure_utc_datetime(value).isoformat().replace("+00:00", "Z")


def parse_utc_datetime(value: object) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return ensure_utc_datetime(value)

    if not isinstance(value, str):
        raise TypeError(f"Unsupported datetime payload: {type(value)!r}")

    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    parsed = datetime.fromisoformat(normalized)
    return ensure_utc_datetime(parsed)


class UTCDateTime(TypeDecorator):
    """Persist datetimes as explicit ISO 8601 UTC strings and restore aware UTC values."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> str | None:
        if value is None:
            return None
        return format_utc_datetime(value)

    def process_result_value(self, value: object, dialect: object) -> datetime | None:
        return parse_utc_datetime(value)
