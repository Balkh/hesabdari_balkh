"""Central date boundary: ISO/Gregorian persistence, Jalali presentation."""
from datetime import date, datetime
import jdatetime


def gregorian_to_jalali(value: date | datetime) -> str:
    value = value.date() if isinstance(value, datetime) else value
    return jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d")


def jalali_to_gregorian(value: str) -> date:
    year, month, day = (int(part) for part in value.replace("-", "/").split("/"))
    return jdatetime.date(year, month, day).togregorian()


def utc_timestamp(value: datetime | None = None) -> datetime:
    """Return an aware UTC timestamp for audit/persistence boundaries."""
    from datetime import timezone
    now = value or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc)
