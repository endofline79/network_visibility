"""UTC timestamps shared by the checker and its tests."""

from datetime import datetime, timezone


def iso(value):
    if isinstance(value, str):
        value = parse_time(value)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        if "." in text:
            head, rest = text.split(".", 1)
            tz_at = max(rest.rfind("+"), rest.rfind("-"))
            frac, tz = (rest[:tz_at], rest[tz_at:]) if tz_at > 0 else (rest, "")
            text = f"{head}.{frac[:6]}{tz}"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("A timezone is required")
    return parsed.astimezone(timezone.utc)


def age_seconds(start, end):
    return max(0, int((parse_time(end) - parse_time(start)).total_seconds()))
