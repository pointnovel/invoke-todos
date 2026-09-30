"""Dates and durations: the ISO forms the CLI reads and prints, the API's timestamps, look-back windows."""
import re
from datetime import datetime, timedelta, timezone

from invoke_todos.output import die


def parse_day(s):
    """'YYYY-MM-DD' -> date, else None."""
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_due(s):
    """'2026-09-24', '2026-09-24T18:00' or '2026-09-24 18:00' -> a Todoist due object (a time is floating)."""
    parts = (s or "").strip().replace("T", " ").split()
    d = parse_day(parts[0]) if parts else None
    if d is None or len(parts) > 2:
        return None
    if len(parts) == 1:
        return {"date": d.isoformat()}
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", parts[1])
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return {"date": "%sT%02d:%02d:00" % (d.isoformat(), int(m.group(1)), int(m.group(2)))}


def parse_ts(s):
    """An API timestamp ('...Z', '+00:00', or floating 'YYYY-MM-DDTHH:MM:SS') -> aware local datetime."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone()  # a naive (floating) value is taken as local wall time


def due_view(due):
    """Todoist due object -> (display 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM', the moment it becomes overdue)."""
    s = (due or {}).get("date")
    if not s:
        return ((due or {}).get("string") or None), None  # a due sent as a phrase, before the server parsed it
    if len(s) == 10:
        d = parse_day(s)
        return s, (datetime.combine(d + timedelta(days=1), datetime.min.time()).astimezone() if d else None)
    dt = parse_ts(s)
    return (dt.strftime("%Y-%m-%d %H:%M"), dt) if dt else (s, None)


def ymdhm(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None


def utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now():
    return datetime.now().astimezone()


FAR = datetime(9999, 1, 1, tzinfo=timezone.utc)
NEAR = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_window(s):
    """'30d', '2w', '12h' or 'YYYY-MM-DD' -> the start of a look-back window."""
    m = re.fullmatch(r"(\d+)([hdw])", (s or "").strip())
    if m:
        n = int(m.group(1))
        return now() - {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n)}[m.group(2)]
    d = parse_day(s)
    return datetime.combine(d, datetime.min.time()).astimezone() if d else None


def parse_duration(s, zero=False):
    """'90m', '2h', '2h30m', '1.5h' or '3d' -> {"amount", "unit"} (the API's minute or day units)."""
    t = (s or "").strip().lower()
    m = re.fullmatch(r"(\d+)d", t)
    if m:
        return {"amount": int(m.group(1)), "unit": "day"}
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+)m)?", t)
    if not m or not t:
        die("--duration needs 90m, 2h, 2h30m, 1.5h or 3d")
    minutes = int(round(float(m.group(1) or 0) * 60)) + int(m.group(2) or 0)
    if minutes <= 0 and not zero:
        die("--duration must be positive")
    return {"amount": minutes, "unit": "minute"}
