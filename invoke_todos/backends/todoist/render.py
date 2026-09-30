"""The full view of one task (show_item), its comments (task_comments, comment_block, comment_view) and the
one-line renderers of the account objects."""
import json

from invoke_todos.backends.todoist.state import open_in, resolve_in, task_notes, user_id
from invoke_todos.config import cfg
from invoke_todos.dates import due_view, ymdhm
from invoke_todos.model import attr_note, parse_attr_line
from invoke_todos.render import ref, when


def show_item(i, st=None, a=None):
    print("id:       %s  (%s)" % (i.id, i.link))
    print("title:    " + i.title)
    if i.project and i.project != cfg.project:
        print("project:  " + i.project)
    print("area:     " + i.area)
    parent = resolve_in(st.items, i.parent) if st and i.parent else None
    if parent:
        print("parent:   %s %s" % (ref(parent), parent.title))
    elif i.parent:
        print("parent:   " + i.parent)
    if i.kinds:
        print("kind:     " + ", ".join(i.kinds))
    if i.due:
        print("due:      " + i.due + (" (overdue)" if i.overdue else "") + ("  repeats: " + i.recur if i.recur else ""))
    if i.deadline:
        print("deadline: " + i.deadline)
    if i.prio:
        print("priority: %d" % i.prio)
    for label, v in (("effort", i.effort), ("mode", i.mode), ("src", i.src), ("since", i.since), ("url", i.url),
                     ("duration", i.duration), ("assignee", i.assignee)):
        if v:
            print("%-9s %s" % (label + ":", v))
    print("status:   " + ("done" + (" " + ymdhm(i.done_at) if i.done_at else "") if i.done else "open"))
    if i.created:
        print("created:  " + ymdhm(i.created))
    if i.modified:
        print("modified: " + ymdhm(i.modified))
    if i.children:
        done = len([c for c in i.children if c.done])
        print("subtasks: %d open%s" % (len(i.children) - done, ", %d done" % done if done else ""))
        for c in i.children:
            print("  %s %s %s" % (ref(c), "x" if c.done else "-", c.title))
    if i.desc:
        print("")
        print(i.desc)
    if a is not None and a.has("comments") and st is not None:
        notes = task_comments(st, i)
        print("")
        print("comments: %d" % len(notes))
        for n in notes:
            print(comment_block(n))
    if a is not None and a.has("reminders") and st is not None:
        rem = [r for r in st.reminders if r.get("item_id") == i.id]
        print("")
        print("reminders: %d" % len(rem))
        for r in rem:
            print("  " + reminder_line(r, st))


def project_line(st, p):
    tags = [t for t, on in (("inbox", p.get("inbox_project")), ("shared", p.get("shared")),
                            ("archived", p.get("is_archived")), ("favorite", p.get("is_favorite")),
                            ("workspace:%s" % p.get("workspace_id"), p.get("workspace_id")),
                            ("under:%s" % st.project_names.get(p.get("parent_id")), p.get("parent_id"))) if on]
    secs = len([x for x in st.all_sections.values() if x.get("project_id") == p["id"] and not x.get("is_archived")])
    return "%s %s%s  open:%d sections:%d" % (p["id"], p.get("name"), " [" + ", ".join(tags) + "]" if tags else "",
                                             open_in(st, "project_id", p["id"]), secs)


def section_line(st, x):
    return "%s %s/%s%s  open:%d" % (x["id"], st.project_names.get(x.get("project_id")), x.get("name"),
                                    " [archived]" if x.get("is_archived") else "", open_in(st, "section_id", x["id"]))


def label_line(l, counts):
    tags = [t for t, on in (("favorite", l.get("is_favorite")), (l.get("color"), l.get("color") not in (None, "charcoal"))) if on]
    return "%s %s%s  tasks:%d" % (l.get("id"), l.get("name"), " [" + ", ".join(tags) + "]" if tags else "",
                                  counts.get((l.get("name") or "").lower(), 0))


def comment_line(n):
    fa = n.get("file_attachment") or {}
    tags = []
    kv = parse_attr_line(n.get("content"))
    if kv and set(kv) <= {"src", "since"}:
        tags.append("attr")
    if fa:
        tags.append("file:" + (fa.get("file_name") or fa.get("file_url") or "?"))
    if n.get("reactions"):
        tags.append("reactions:" + ",".join("%s x%d" % (k, len(v)) for k, v in n["reactions"].items()))
    first = (n.get("content") or "").strip().split("\n")[0]
    return "%s %s%s %s" % (n.get("id"), when(n.get("posted_at")), " [" + ", ".join(tags) + "]" if tags else "", first)


def is_attr_note(n):
    kv = parse_attr_line(n.get("content"))
    return bool(kv) and set(kv) <= {"src", "since"}


def task_comments(st, i):
    """A task's comments as show gives them: oldest first, without the one that carries src and since."""
    rows = task_notes(st, i)
    attr = attr_note(rows)[0]
    return [n for n in rows if n is not attr]


def comment_block(n, pad="  "):
    """A comment in full: its line, then the rest of its text under it."""
    rest = (n.get("content") or "").strip().split("\n")[1:]
    return "\n".join([pad + comment_line(n)] + [(pad + "  " + l).rstrip() for l in rest])


def comment_view(n, st):
    """A comment in show --json: id, posted (local time), the whole content; file, reactions (name -> count) and
    by (the author's user id, when it is someone else) only when there is one."""
    fa = n.get("file_attachment") or {}
    out = {"id": n.get("id"), "posted": when(n.get("posted_at")), "content": (n.get("content") or "").strip()}
    if fa:
        out["file"] = fa.get("file_name") or fa.get("file_url") or "?"
    if n.get("reactions"):
        out["reactions"] = {k: len(v) for k, v in n["reactions"].items()}
    who = n.get("posted_uid")
    if who and str(who) != user_id(st):
        out["by"] = str(who)
    return out


def reminder_line(r, st):
    task = resolve_in(st.all_items, r.get("item_id") or "") if r.get("item_id") else None
    t = r.get("type")
    if t == "relative":
        how = "%s min before the due time" % r.get("minute_offset")
    elif t == "absolute":
        how = "at " + (due_view(r.get("due"))[0] or (r.get("due") or {}).get("string") or "?")
    elif t == "location":
        how = "%s %s (%s, %s, radius %s)" % (r.get("loc_trigger"), r.get("name"), r.get("loc_lat"), r.get("loc_long"), r.get("radius"))
    else:
        how = json.dumps({k: v for k, v in r.items() if k not in ("id", "item_id", "type")})
    tags = [x for x, on in (("urgent", r.get("is_urgent")), (r.get("service"), r.get("service") not in (None, "push"))) if on]
    return "%s %s %s %s%s" % (r.get("id"), ref(task) if task else r.get("item_id"), t, how,
                              " [" + ", ".join(tags) + "]" if tags else "")


def filter_line(f):
    tags = [t for t, on in (("favorite", f.get("is_favorite")), ("frozen", f.get("is_frozen"))) if on]
    return "%s %s%s  %s" % (f.get("id"), f.get("name"), " [" + ", ".join(tags) + "]" if tags else "", f.get("query"))


def activity_line(e, st):
    ed = e.get("extra_data") or {}
    what = ed.get("content") or ed.get("name") or ""
    tags = []
    if ed.get("parent_project_name") or ed.get("parent_item_content"):
        tags.append("in " + (ed.get("parent_project_name") or "") + ("/" + ed["parent_item_content"] if ed.get("parent_item_content") else ""))
    who = e.get("initiator_id")
    if who and str(who) != user_id(st):
        tags.append("by %s" % who)
    return "%s %s %s %s %s%s" % (when(e.get("event_date")), e.get("event_type"), e.get("object_type"), e.get("object_id") or "",
                                 what, " [" + ", ".join(tags) + "]" if tags else "")


def notification_line(n):
    extra = {k: v for k, v in n.items() if k not in ("id", "created_at", "notification_type", "is_unread", "from_uid",
                                                     "seq_no", "notification_key", "invitation_secret")}
    return "%s %s %s%s from:%s %s" % (n.get("id"), when(n.get("created_at")), n.get("notification_type"),
                                      " [unread]" if n.get("is_unread") else "", n.get("from_uid"),
                                      json.dumps(extra, ensure_ascii=False) if extra else "")
