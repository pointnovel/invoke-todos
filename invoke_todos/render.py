"""The one-line rendering of a task in the house view, and timestamps as the CLI prints them."""
from invoke_todos.config import cfg
from invoke_todos.dates import parse_ts, ymdhm


def ref(i):
    """How a row names its task: the short id, or under --links the markdown link [task#<short>](<link>)."""
    link = getattr(i, "link", None) if cfg.links else None
    return "[task#%s](%s)" % (i.short, link) if link else i.short


def line(i, indent=False):
    cols = [ref(i), "x" if i.done else "-", "!%d" % i.prio if i.prio else "--"]
    if i.due:
        cols.append(i.due.replace(" ", "T") + ("~" if i.recur else "") + ("!" if i.overdue else ""))
    if i.deadline:
        cols.append("deadline:" + i.deadline)
    where = i.area if not i.project or i.project == cfg.project else i.project + "/" + i.area
    cols.append("[" + where + (":" + ",".join(i.kinds) if i.kinds else "") + "]")
    compact = "/".join(x for x in (i.effort, i.mode) if x)
    if compact:
        cols.append(compact)
    cols.append(i.title)
    return ("  " * i.depth if indent else "") + " ".join(cols)


def when(ts):
    dt = parse_ts(ts)
    return ymdhm(dt) if dt else (ts or "")
