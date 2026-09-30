"""Filtering and sorting of the house view: the list flags over any item set, and tree order."""
from datetime import datetime, timedelta

from invoke_todos.dates import FAR, NEAR, parse_day
from invoke_todos.model import norm_effort, norm_mode
from invoke_todos.output import die


def apply_filters(items, a):
    out = list(items)
    k = a.first("kind") or a.first("tag")
    if k:
        want = k.strip("# ").lower()
        out = [i for i in out if want in [x.lower() for x in i.kinds]]
    if a.first("mode"):
        out = [i for i in out if i.mode == norm_mode(a.first("mode"))]
    if a.first("effort"):
        out = [i for i in out if i.effort == norm_effort(a.first("effort"))]
    if a.first("src"):
        want = a.first("src").lower()
        out = [i for i in out if (i.src or "").lower().startswith(want)]
    if a.first("prio"):
        out = [i for i in out if str(i.prio) == a.first("prio")]
    if a.first("due-before"):
        d = parse_day(a.first("due-before"))
        if not d:
            die("--due-before needs YYYY-MM-DD")
        limit = datetime.combine(d + timedelta(days=1), datetime.min.time()).astimezone()
        out = [i for i in out if i.due_end is not None and i.due_end <= limit]
    if a.has("overdue"):
        out = [i for i in out if i.overdue]
    if a.first("grep"):
        g = a.first("grep").lower()
        out = [i for i in out if g in i.title.lower() or g in (i.desc or "").lower()]
    if a.first("label"):
        want = [l.strip().lower() for l in a.first("label").split(",") if l.strip()]
        out = [i for i in out if all(w in [x.lower() for x in i.raw.get("labels") or []] for w in want)]
    if a.first("section"):
        out = [i for i in out if i.area.lower() == a.first("section").strip().lower()]
    return out


def sort_items(items, key):
    """Tree order: root tasks by `key`, each followed by its subtasks that are in `items` (in the app's
    order); a subtask whose parent is not in `items` sorts as a root."""
    def prio_key(i):
        return (i.prio or 4, i.due_end or FAR, i.created or NEAR)
    if key == "due":
        root_key = lambda i: (i.due_end or FAR, i.prio or 4)
    elif key == "since":
        root_key = lambda i: i.since or (i.created.date().isoformat() if i.created else "9999")
    elif key == "title":
        root_key = lambda i: i.title.lower()
    elif key == "area":
        root_key = lambda i: (i.area,) + prio_key(i)
    elif key == "prio":
        root_key = prio_key
    else:
        die("--sort takes prio|due|since|title|area")
    present = {i.id for i in items}
    kids = {}
    for i in items:
        if i.parent in present:
            kids.setdefault(i.parent, []).append(i)
    out = []

    def walk(i):
        out.append(i)
        for c in sorted(kids.get(i.id, []), key=lambda c: (c.order, c.created or NEAR, c.id)):
            walk(c)

    for r in sorted([i for i in items if i.parent not in present], key=root_key):
        walk(r)
    return out
