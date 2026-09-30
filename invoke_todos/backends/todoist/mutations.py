"""From the house model to Sync commands: a new task with its comment (task_group), an edit that sends only what
differs (edit_plan), a due change that keeps a recurrence, and the view of what a run wrote."""
from datetime import date

from invoke_todos.backends.todoist.api import new_cmd
from invoke_todos.backends.todoist.items import Item, api_prio
from invoke_todos.config import cfg
from invoke_todos.dates import now, utc
from invoke_todos.model import compose_labels, descendants, encode_note, join_description, session_url, uniq
from invoke_todos.output import die


def task_group(st, area, title, desc, x, url, due, deadline, prio, parent_id=None, extra=None):
    """item_add (+ the src/since comment) for one task -> (commands, the item_add command). A subtask is
    added under its parent and inherits the parent's section. `extra` holds duration, responsible_uid,
    child_order."""
    link = url if url is not None else session_url(x["src"])
    args = {"content": title, "project_id": st.project_id,
            "labels": compose_labels(x["kinds"], x["effort"], x["mode"]), "priority": api_prio(prio or 0)}
    args.update({k: v for k, v in (extra or {}).items() if v is not None})
    if parent_id:
        args["parent_id"] = parent_id
    else:
        args["section_id"] = st.section_id(area)
    description = join_description(desc, link)
    if description:
        args["description"] = description
    if due:
        args["due"] = due
    if deadline:
        args["deadline"] = {"date": deadline}
    add = new_cmd("item_add", args)
    group = [add]
    note = encode_note(x["src"], x["since"])
    if note:
        group.append(new_cmd("note_add", {"item_id": add["temp_id"], "content": note}))
    return group, add


def check_parent(i, parent, area=None):
    """Refuse a move of `i` under `parent` that would loop, or that names another area."""
    if parent.id == i.id or parent.id in {d.id for d in descendants(i)}:
        die("cannot move %s under %s: that is the task itself or one of its subtasks" % (i.short, parent.short))
    if area and area != parent.area.lower():
        die("a subtask lives in its parent's area (%s), not %s" % (parent.area, area))


def edit_plan(st, i, ch):
    """The commands that turn task `i` into the change spec `ch` (only the keys given are applied: title,
    desc, url ("" clears), x (attributes merged with the task's), prio, due, clear_due, deadline,
    clear_deadline, area, parent ("" detaches; may be a temp id), touch_note) -> (command groups, the task
    as it will read, seconds to wait first: title and due changes to a task younger than SETTLE are lost)."""
    x = ch["x"]
    title = ch["title"] if ch.get("title") is not None else i.title
    desc = ch["desc"] if ch.get("desc") is not None else i.desc
    if ch.get("url") is not None:
        link = ch["url"].strip() or None
    elif x["src"] != i.src and i.url in (None, session_url(i.src)):
        link = session_url(x["src"])  # the link follows a new session src; a custom link stays
    else:
        link = i.url
    args = {"id": i.id}
    if title != i.title:
        args["content"] = title
    description = join_description(desc, link)
    if description != (i.raw.get("description") or "").strip():
        args["description"] = description
    labels = compose_labels(x["kinds"], x["effort"], x["mode"])
    if sorted(labels) != sorted(i.raw.get("labels") or []):  # the server stores labels sorted
        args["labels"] = labels
    if ch.get("prio") is not None and api_prio(ch["prio"]) != (i.raw.get("priority") or 1):
        args["priority"] = api_prio(ch["prio"])
    if ch.get("clear_due") and i.raw.get("due"):
        args["due"] = None
    if ch.get("due"):
        new = reschedule_due(ch["due"], i.raw.get("due"))
        if new != {"date": (i.raw.get("due") or {}).get("date")}:
            args["due"] = new
    for k in ("duration", "responsible_uid", "child_order"):
        if k in (ch.get("extra") or {}) and ch["extra"][k] != i.raw.get(k):
            args[k] = ch["extra"][k]
    if ch.get("clear_deadline") and i.raw.get("deadline"):
        args["deadline"] = None
    if ch.get("deadline") and ch["deadline"] != (i.raw.get("deadline") or {}).get("date"):
        args["deadline"] = {"date": ch["deadline"]}
    groups = []
    if len(args) > 1:
        groups.append([new_cmd("item_update", args)])
    area, parent = ch.get("area"), ch.get("parent")
    if ch.get("section"):  # a section of another project (edit --project); subtasks follow, as in the app
        if ch["section"] != i.raw.get("section_id"):
            groups.append([new_cmd("item_move", {"id": i.id, "section_id": ch["section"]})])
    elif parent:
        if parent != i.parent:
            groups.append([new_cmd("item_move", {"id": i.id, "parent_id": parent})])
    elif parent == "" or (area and area != i.area.lower()):
        if parent == "" and not i.parent and not (area and area != i.area.lower()):
            pass  # already a root task
        else:
            sid = st.section_id(area or i.area)
            dest = {"id": i.id, "section_id": sid} if sid else {"id": i.id, "project_id": st.project_id}
            groups.append([new_cmd("item_move", dest)])
    note = None
    if ch.get("touch_note"):  # a task made in the app gets a comment only when asked
        since = x["since"] or i.since or (i.created.date().isoformat() if i.created else date.today().isoformat())
        note = encode_note(x["src"], since)
    if note and note != encode_note(i.src, i.since):
        if i.note:
            groups.append([new_cmd("note_update", {"id": i.note["id"], "content": note})])
        else:
            groups.append([new_cmd("note_add", {"item_id": i.id, "content": note})])
    wait = 0.0
    if ("content" in args or "due" in args) and i.created:
        wait = max(0.0, cfg.settle - (now() - i.created).total_seconds())
    raw = dict(i.raw)
    raw.update({k: v for k, v in args.items() if k != "id"})
    if area:
        raw["section_id"] = st.section_id(area)
    if parent:
        raw["parent_id"] = parent
    elif parent == "":
        raw["parent_id"] = None
    kept = note or encode_note(i.src, i.since)
    new = Item(raw, st.sections, [{"content": kept}] if kept else [])
    new.short, new.depth, new.children = i.short, i.depth, i.children
    return groups, new, wait


def reschedule_due(new, old):
    """A due change on a recurring task keeps its recurrence: a plain date (or date-time) moves the next
    occurrence and the old `string` rides along, as the apps do; a date without a time keeps the old time."""
    old = old or {}
    if "string" in new or not old.get("is_recurring"):
        return new
    date = new["date"]
    if len(date) == 10 and old.get("date") and len(old["date"]) > 10:
        date = date + old["date"][10:]
    out = {"date": date, "string": old.get("string"), "is_recurring": True}
    for k in ("lang", "timezone"):
        if old.get(k):
            out[k] = old[k]
    if new.get("timezone"):
        out["timezone"] = new["timezone"]
    return out


def changed_fields(groups):
    """What a plan from edit_plan touches, for --dry and the log: 'title, body, labels, parent'."""
    names = {"content": "title", "description": "body", "labels": "labels", "priority": "priority", "due": "due",
             "deadline": "deadline", "duration": "duration", "responsible_uid": "assignee", "child_order": "order"}
    out = []
    for g in groups:
        for c in g:
            if c["type"] == "item_update":
                out += [names.get(k, k) for k in c["args"] if k != "id"]
            elif c["type"] == "item_move":
                out.append("parent" if "parent_id" in c["args"] else "area")
            elif c["type"].startswith("note_"):
                out.append("src/since")
    return ", ".join(uniq(out))


def created_item(st, add, mapping, note):
    """The view of a task this run created, without reading it back."""
    raw = dict(add["args"])
    raw["id"] = mapping.get(add["temp_id"], add["temp_id"])
    raw["added_at"] = utc(now())
    return Item(raw, st.sections, [{"content": note}] if note else [])
