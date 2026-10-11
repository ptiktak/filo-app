from datetime import datetime, timezone

from app import config

_DAYS = ["ma", "di", "wo", "do", "vr", "za", "zo"]
_MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def to_local(dt_utc: datetime) -> datetime:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(config.TZ)


def local_to_utc(dt_local: datetime) -> datetime:
    """Naive lokale tijd → naive UTC."""
    return dt_local.replace(tzinfo=config.TZ).astimezone(timezone.utc).replace(tzinfo=None)


def parse_local_input(value: str) -> datetime | None:
    """Waarde van een <input type=datetime-local> → naive UTC."""
    if not value:
        return None
    return local_to_utc(datetime.fromisoformat(value))


def fmt(dt_utc: datetime | None) -> str:
    if dt_utc is None:
        return ""
    d = to_local(dt_utc)
    return f"{_DAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]}, {d:%H:%M}"


def fmt_input(dt_utc: datetime | None) -> str:
    """Voor value= van een datetime-local veld."""
    if dt_utc is None:
        return ""
    return to_local(dt_utc).strftime("%Y-%m-%dT%H:%M")


def fmt_relative(dt_utc: datetime, now: datetime) -> str:
    seconds = (dt_utc - now).total_seconds()
    if seconds <= 0:
        return "nu"
    hours = seconds / 3600
    if hours < 1:
        return f"over {max(1, int(seconds // 60))} min"
    if hours < 36:
        return f"over {int(round(hours))} uur"
    return f"over {int(round(hours / 24))} dagen"
