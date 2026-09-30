"""The raw Todoist item read into the house view (Item), the priority mapping (the task's value: user 1..3 =
p1..p3, 0 = none; API 4..1), the app's task URL and the API's named colors."""
from invoke_todos.config import cfg
from invoke_todos.dates import due_view, now, parse_ts, ymdhm
from invoke_todos.model import DEFAULT_FIELDS, attr_note, decompose_labels, split_description


TASK_URL = "https://app.todoist.com/app/task/%s"


COLORS = ("berry_red", "red", "orange", "yellow", "olive_green", "lime_green", "green", "mint_green", "teal",
          "sky_blue", "light_blue", "blue", "grape", "violet", "lavender", "magenta", "salmon", "charcoal", "grey",
          "taupe")  # the API's named colors, ids 30..49 in that order


def api_prio(user):
    """API priority 4 is p1 (the most valuable) in the apps, 1 is none."""
    return {1: 4, 2: 3, 3: 2}.get(user, 1)


def user_prio(api):
    return {4: 1, 3: 2, 2: 3}.get(api, 0)


class Item(object):
    def __init__(self, raw, sections, notes=()):
        self.raw = raw
        self.id = raw.get("id") or ""
        self.short = self.id
        self.area = sections.get(raw.get("section_id")) or "-"
        self.title = (raw.get("content") or "").strip()
        self.desc, self.url = split_description(raw.get("description"))
        self.kinds, self.effort, self.mode = decompose_labels(sorted(raw.get("labels") or [], key=str.lower))
        self.prio = user_prio(raw.get("priority") or 1)
        self.due, self.due_end = due_view(raw.get("due"))
        self.recur = (raw.get("due") or {}).get("string") if (raw.get("due") or {}).get("is_recurring") else None
        self.deadline = (raw.get("deadline") or {}).get("date")
        d = raw.get("duration") or {}
        self.duration = "%s%s" % (d.get("amount"), "d" if d.get("unit") == "day" else "m") if d.get("amount") else None
        self.assignee = raw.get("responsible_uid") or None
        self.project = None  # the project's name, set by State
        self.note, kv = attr_note(notes)
        self.src, self.since = kv.get("src"), kv.get("since")
        self.parent = raw.get("parent_id") or None
        self.order = raw.get("child_order") or 0
        self.depth = 0       # set by link_tree
        self.children = []   # open subtasks, set by link_tree
        self.done = bool(raw.get("checked") or raw.get("completed_at"))
        self.done_at = parse_ts(raw.get("completed_at"))
        self.created = parse_ts(raw.get("added_at"))
        self.modified = parse_ts(raw.get("updated_at"))

    @property
    def overdue(self):
        return not self.done and self.due_end is not None and self.due_end < now()

    @property
    def link(self):
        """The task's link: the config's todoist.task_url template, else the app's web URL."""
        return (cfg.task_url or TASK_URL).replace("%s", self.id)

    def as_dict(self, fields=DEFAULT_FIELDS):
        full = {
            "id": self.id, "short": self.short, "parent": self.parent, "area": self.area, "title": self.title,
            "desc": self.desc, "kinds": self.kinds, "due": self.due, "recur": self.recur, "deadline": self.deadline,
            "prio": self.prio, "effort": self.effort, "mode": self.mode, "src": self.src,
            "since": self.since, "url": self.url, "duration": self.duration, "assignee": self.assignee,
            "subtasks": [c.id for c in self.children], "done": self.done,
            "doneAt": ymdhm(self.done_at), "created": ymdhm(self.created), "modified": ymdhm(self.modified),
            "project": self.project, "link": self.link,
        }
        return {f: full[f] for f in fields if full[f] not in (None, "", []) or f in ("id", "title", "kinds")}
