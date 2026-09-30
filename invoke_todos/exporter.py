"""The generated markdown view: one heading per area, one row per task ending in the [id ...] bracket that
the importer reads back, bodies indented under their row."""
import re

from invoke_todos.config import cfg
from invoke_todos.dates import now, ymdhm
from invoke_todos.query import sort_items


def export_markdown(items):
    groups = {}
    for i in items:
        groups.setdefault(i.area, []).append(i)
    out = ["# %s - open tasks (GENERATED %s by `todos export`; edit through the CLI, or edit a copy of this "
           "file and `todos import <copy> --update`, not here)" % (cfg.project, ymdhm(now())), "",
           'Store: Todoist project "%s", one section per area; subtasks nest under their task; priority is the %s '
           '(p1 the most valuable). Query: `todos list ...` (`--area`, `--mode %s`, `--effort %s --prio 1`, '
           '`--kind`, `--due-before`, `--json --fields id,title`). %d open; done tasks are not listed here (`todos list --done --since 30d`). Ids are unique '
           'prefixes of the Todoist task id; src is the origin.'
           % (cfg.project, cfg.priority_meaning, cfg.modes[0], cfg.efforts[0], len(items)), ""]
    for name in sorted(groups):
        out.append("## " + name)
        for i in sort_items(groups[name], "prio"):
            pad = "  " * i.depth
            head = pad + "- [ ] " + i.title
            if i.due:
                head += " @" + i.due.replace(" ", "T")
            if i.prio:
                head += " !%d" % i.prio
            meta = ["id " + i.short]
            if i.kinds:
                meta.append("/".join(i.kinds))
            meta += [m for m in (i.effort, i.mode) if m]
            if i.src:
                meta.append("src " + i.src)
            if i.since:
                meta.append("since " + i.since)
            if i.deadline:
                meta.append("deadline " + i.deadline)
            if i.overdue:
                meta.append("overdue")
            out.append(head + " [" + ", ".join(meta) + "]")
            if i.desc:
                out += [(pad + "      " + l).rstrip() for l in i.desc.split("\n")]
        out.append("")
    return "\n".join(out)


STAMP_RE = re.compile(r"GENERATED \d{4}-\d{2}-\d{2} \d{2}:\d{2}")
