from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))


def to_ist(dt: datetime | None) -> str | None:
    """Convert a naive-UTC (or tz-aware) datetime to IST ISO string without tz suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).strftime("%Y-%m-%dT%H:%M:%S")
