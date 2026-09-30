"""Todoist-specific flag readers: the item fields beyond the house model (plan-checked), the named colors."""
from invoke_todos.backends.todoist.items import COLORS
from invoke_todos.backends.todoist.state import require, resolve_user
from invoke_todos.dates import parse_duration
from invoke_todos.output import die


def task_extras(a, st, project_id=None):
    """The item fields beyond the house model: duration, assignee, order (plan-checked)."""
    extra = {}
    if a.first("duration") is not None:
        require(st, "durations", "--duration", "drop it")
        extra["duration"] = parse_duration(a.first("duration"))
    if a.has("clear-duration"):
        extra["duration"] = None
    if a.first("assign") is not None:
        extra["responsible_uid"] = resolve_user(st, a.first("assign"), project_id) if a.first("assign") else None
    if a.first("order") is not None:
        try:
            extra["child_order"] = int(a.first("order"))
        except ValueError:
            die("--order needs a number")
    return extra


def color_flag(a):
    c = a.first("color")
    if c is None:
        return None
    c = c.strip().lower().replace(" ", "_")
    if c not in COLORS:
        die("--color takes one of: " + ", ".join(COLORS))
    return c
