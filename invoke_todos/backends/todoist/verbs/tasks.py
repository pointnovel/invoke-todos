"""The task verbs: the house model over one project (add, quick, list, show, done, undone, rm, edit, reschedule,
move, assign, order, import, export, search, overview, stats, areas)."""
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

from invoke_todos.args import attrs_from, deadline_flag, due_flag, fields_from, parse_prio, read_note, validate
from invoke_todos.backends.todoist.api import new_cmd, rest, write
from invoke_todos.backends.todoist.flags import task_extras
from invoke_todos.backends.todoist.items import Item
from invoke_todos.backends.todoist.mutations import changed_fields, check_parent, created_item, edit_plan, task_group
from invoke_todos.backends.todoist.query import server_filter
from invoke_todos.backends.todoist.render import comment_view, show_item, task_comments
from invoke_todos.backends.todoist.state import (DONE_WINDOW_DAYS, ensure, fetch_done, find_filter, find_project,
                                                 open_in, other_section, read_state, require, resolve, resolve_in,
                                                 resolve_user, subtree, task_ref, within)
from invoke_todos.config import cfg
from invoke_todos.dates import FAR, NEAR, due_view, now, parse_day, parse_due, parse_ts, parse_window, utc
from invoke_todos.exporter import STAMP_RE, export_markdown
from invoke_todos.importer import parse_json_seeds, parse_seed
from invoke_todos.model import (BRIEF_FIELDS, DEFAULT_FIELDS, FIELDS, assign_short_ids, check_lengths, compose_labels, descendants,
                                encode_note, join_description, length_problems, norm_effort, norm_mode, normalize_area,
                                session_url, top_level, uniq, with_subtasks)
from invoke_todos.output import die, err, need_yes, print_json, redact
from invoke_todos.query import apply_filters, sort_items
from invoke_todos.render import line, ref as row_ref
from invoke_todos.verbs import register


@register("add")
def cmd_add(a):
    title = " ".join(a.pos[1:]).strip()
    if not title:
        die("todos add needs a title")
    area = normalize_area(a.first("area")) if a.first("area") else None
    section = (a.first("section") or "").strip() or None  # a section name taken as it is (other projects)
    if not area and not section and a.first("parent") is None:
        die('todos add needs --area <area> (todos areas shows the existing ones), --section "<name>" or --parent <id>')
    x = attrs_from(a)
    x["since"] = x["since"] or date.today().isoformat()
    desc = read_note(a) or ""
    check_lengths(title, a.has("force"))
    due, deadline, prio = due_flag(a), deadline_flag(a), parse_prio(a)
    st = read_state()
    if deadline:
        require(st, "deadlines", "--deadline")
    extra = task_extras(a, st, st.project_id)
    parent = None
    if a.first("parent") is not None:
        parent = resolve(st, a.first("parent"))
        if parent.raw.get("project_id") != st.project_id:
            die("%s is in project %s; run under it (--in %s) to add a subtask" % (parent.short, parent.project, parent.project))
        if (area or section) and (area or section).lower() != parent.area.lower():
            die("a subtask lives in its parent's area (%s), not %s" % (parent.area, area or section))
        area = parent.area
    area = area or section
    ensure(st, [area], compose_labels(x["kinds"], x["effort"], x["mode"]))
    group, add = task_group(st, area, title, desc, x, a.first("url"), due, deadline, prio,
                            parent_id=parent.id if parent else None, extra=extra)
    item = created_item(st, add, write([group]), encode_note(x["src"], x["since"]))
    if parent:
        item.depth, item.area = parent.depth + 1, parent.area
    assign_short_ids(st.items + [item])
    if a.has("json"):
        print_json(item.as_dict(fields_from(a)), a.has("pretty"))
    else:
        print(line(item))


@register("quick")
def cmd_quick(a):
    """POST /tasks/quick: Todoist's own parser (dates, #project, /section, @label, p1..p4, +assignee, // body)."""
    text = " ".join(a.pos[1:]).strip()
    if not text:
        die('todos quick "<text as typed in the app>"')
    st = read_state()
    if re.search(r"\{[^}]*\}", text):
        require(st, "deadlines", "a {deadline} in Quick Add text", "drop the braces")
    body = {"text": text}
    if a.first("note"):
        body["note"] = read_note(a)
    if a.first("reminder") is not None:
        require(st, "reminders", "--reminder", "a due time is the reminder on this plan")
        body["reminder"] = a.first("reminder")
    if a.has("meta"):
        body["meta"] = True
    r = rest("POST", "/tasks/quick", body=body)
    if not isinstance(r, dict) or not r.get("id"):
        print_json(r, True)
        return
    names = {sid: sec.get("name") or "" for sid, sec in st.all_sections.items()}
    it = Item(r, names, [])
    it.project = st.project_names.get(r.get("project_id"))
    if a.first("src") is not None:  # the house provenance: the src/since comment and the Origin link
        src = a.first("src").strip()
        since = a.first("since") or date.today().isoformat()
        groups = [[new_cmd("note_add", {"item_id": it.id, "content": encode_note(src, since)})]]
        url = session_url(src)
        if url:
            groups.append([new_cmd("item_update", {"id": it.id, "description": join_description(it.desc, url)})])
        write(groups)
        it.src, it.since, it.url = src, since, url
    assign_short_ids(st.all_items + [it])
    if a.has("json"):
        print_json(it.as_dict(fields_from(a) if a.first("fields") else FIELDS), a.has("pretty"))
    else:
        print(line(it))
        if a.has("meta") and r.get("meta"):
            print_json(r["meta"], True)


@register("list", "ls")
def cmd_list(a):
    st = read_state()
    everywhere = a.has("all-projects")
    if a.first("area"):
        area = normalize_area(a.first("area"))
        if not st.section_id(area) and not everywhere:
            die('no section "%s" in %s (todos areas lists them; todos add creates one)' % (area, cfg.project))
    query = a.first("filter")
    if a.first("saved"):
        f = find_filter(st, a.first("saved"))
        query = f.get("query")
    if query:
        items = server_filter(st, query, a.first("lang"))  # account-wide; rows outside PROJECT show their project
    elif a.has("done"):
        since = parse_window(a.first("since") or "30d")
        until = parse_window(a.first("until")) if a.first("until") else None
        if since is None or (a.first("until") and until is None):
            die("--since and --until need 30d, 2w, 12h or YYYY-MM-DD")
        by = a.first("by") or "completion"
        if by not in ("completion", "due"):
            die("--by takes completion or due")
        items = fetch_done(st, since, until, by=by, everywhere=everywhere)
        assign_short_ids(st.all_items + items)
    elif a.has("all"):
        done = fetch_done(st, parse_window("30d"), everywhere=everywhere)
        assign_short_ids(st.all_items + done)
        items = (st.all_items if everywhere else st.items) + done
    else:
        items = st.all_items if everywhere else st.items
    if a.first("area"):
        items = [i for i in items if i.area.lower() == normalize_area(a.first("area"))]
    if a.first("assignee"):
        uid = resolve_user(st, a.first("assignee"))
        items = [i for i in items if i.assignee == uid]
    items = sort_items(apply_filters(items, a), a.first("sort") or "prio")
    if a.has("json"):
        fields = fields_from(a)
        print_json([i.as_dict(fields) for i in items], a.has("pretty"))
        return
    for i in items:
        print(line(i, indent=True))
        if a.has("desc") and i.desc:
            print("         " + "  " * i.depth + i.desc.split("\n")[0])
    sys.stdout.flush()
    if not st.project_id:
        err('no Todoist project "%s" yet (todos add creates it)' % cfg.project)
    err("%d task(s)" % len(items))


@register("show")
def cmd_show(a):
    if len(a.pos) < 2:
        die("todos show needs an id")
    st = read_state()
    i = resolve(st, a.pos[1], include_done=True)
    rows = subtree(st, i, with_done=a.has("all")) if a.has("tree") else [i]
    if a.has("json"):
        fields = fields_from(a) if a.first("fields") else FIELDS
        out = []
        for t in rows:
            d = t.as_dict(fields)
            if a.has("comments"):
                d["comments"] = [comment_view(n, st) for n in task_comments(st, t)]
            out.append(d)
        print_json(out if a.has("tree") else out[0], a.has("pretty"))  # --tree: a list, the task first
        return
    for n, t in enumerate(rows):
        if n:
            print("")
            print("# subtask %d of %d (depth %d)" % (n, len(rows) - 1, t.depth - i.depth))
        show_item(t, st, a)


@register("done")
def cmd_done(a):
    refs = a.pos[1:]
    if not refs:
        die("todos done needs at least one id")
    st = read_state()
    items = top_level([resolve(st, r) for r in refs])
    if a.first("at") is not None or a.has("forever"):
        # item_complete: completed for good (a recurring task does not advance), at a chosen moment
        args = {}
        if a.first("at") is not None:
            when = parse_due(a.first("at"))
            if not when:
                die("--at needs YYYY-MM-DD or YYYY-MM-DDTHH:MM")
            dt = parse_ts(when["date"]) if "T" in when["date"] else \
                datetime.combine(parse_day(when["date"]), datetime.min.time()).astimezone()
            args["date_completed"] = utc(dt)
        write([[new_cmd("item_complete", dict(args, id=i.id))] for i in items])
    else:
        write([[new_cmd("item_close", {"id": i.id})] for i in items])
    for i in items:
        i.done = True
        print("done: " + line(i) + with_subtasks(len(descendants(i)))
              + ("  (recurring: moved to its next occurrence)" if i.recur and not (a.first("at") or a.has("forever")) else ""))


@register("undone")
def cmd_undone(a):
    refs = a.pos[1:]
    if not refs:
        die("todos undone needs at least one id")
    st = read_state()
    done = fetch_done(st, now() - timedelta(days=DONE_WINDOW_DAYS))
    assign_short_ids(st.items + done)
    items, blind = [], []
    for r in [task_ref(r) for r in refs]:
        i = resolve_in(done, r)
        if i:
            items.append(i)
        elif re.fullmatch(r"[0-9A-Za-z]{12,}", r):
            blind.append(r)  # a full id: reopened without a lookup (any project, any age)
        else:
            die("no task completed in the last %d days with id starting %s (a full id works for older ones)"
                % (DONE_WINDOW_DAYS, r))
    write([[new_cmd("item_uncomplete", {"id": i.id})] for i in items] + [[new_cmd("item_uncomplete", {"id": r})] for r in blind])
    for i in items:
        i.done = False
        print("reopened: " + line(i))
    for r in blind:
        print("reopened: " + r)


@register("rm", "remove")
def cmd_rm(a):
    refs = a.pos[1:]
    if not refs:
        die("todos rm needs at least one id")
    st = read_state()
    items = top_level([resolve(st, r, include_done=True) for r in refs])
    total = sum(1 + len(descendants(i)) for i in items)
    if total > 5:
        need_yes(a, ["remove %s %s%s" % (i.short, i.title, with_subtasks(len(descendants(i)))) for i in items],
                 "removing %d tasks" % total)
    write([[new_cmd("item_delete", {"id": i.id})] for i in items])
    for i in items:
        print("removed: %s %s%s" % (i.short, i.title, with_subtasks(len(descendants(i)))))


@register("edit")
def cmd_edit(a):
    if len(a.pos) < 2:
        die("todos edit needs an id")
    st = read_state()
    if a.first("deadline"):
        require(st, "deadlines", "--deadline")
    i = resolve(st, a.pos[1])
    foreign = i.raw.get("project_id") != st.project_id
    if foreign and (a.first("area") or a.first("section") or a.first("parent") is not None or a.first("project")):
        die("%s is in project %s; run under it (--in %s) to move it" % (i.short, i.project, i.project))
    ch = {"x": attrs_from(a, base=i), "prio": parse_prio(a), "due": due_flag(a), "clear_due": a.has("clear-due"),
          "deadline": deadline_flag(a), "clear_deadline": a.has("clear-deadline"),
          "touch_note": a.first("src") is not None or a.first("since") is not None,
          "extra": task_extras(a, st, i.raw.get("project_id"))}
    if a.first("title") is not None:
        ch["title"] = a.first("title").strip()
    note_text = read_note(a)
    if note_text is not None:
        ch["desc"] = note_text
    if a.first("url") is not None:
        ch["url"] = a.first("url")
    check_lengths(ch.get("title") or i.title, a.has("force"))
    area = normalize_area(a.first("area")) if a.first("area") else (a.first("section") or "").strip() or None
    parent_flag = a.first("parent")
    moved = None
    if a.first("project") is not None:  # move the task into a section of another project of the account
        if parent_flag is not None:
            die("--project does not combine with --parent: a moved task becomes a root task of the target area")
        if not area:
            die("--project needs --area <area>, the section in that project")
        if i.parent:
            die("%s is a subtask; detach it first with --parent '' or move its parent" % i.short)
        ch["section"] = other_section(st, a.first("project"), area)
        moved, area = (a.first("project"), area), None
    if parent_flag:
        parent = resolve(st, parent_flag)
        check_parent(i, parent, area)
        ch["parent"], area = parent.id, None
    elif parent_flag == "":
        ch["parent"] = ""
    elif area and i.parent and area != i.area.lower():
        die("%s is a subtask and stays in its parent's area (%s); detach it first with --parent ''" % (i.short, i.area))
    if area:
        ch["area"] = area
    labels = compose_labels(ch["x"]["kinds"], ch["x"]["effort"], ch["x"]["mode"])
    ensure(st, [area] if area else [], [l for l in labels if l not in (i.raw.get("labels") or [])])
    groups, new, wait = edit_plan(st, i, ch)
    if not groups:
        print("unchanged: " + line(i))
        return
    if wait > 0:  # observed 2026-09-23: title and due changes sent in a task's first ~3 s were lost
        err("waiting %.1f s: Todoist drops title and due changes made in a task's first seconds" % wait)
        time.sleep(wait)
    write(groups)
    if moved:
        new.area = moved[1]
        err("moved to %s / %s (with its subtasks); it is no longer listed in %s" % (moved[0], moved[1], cfg.project))
    print("edited: " + line(new))


@register("reschedule")
def cmd_reschedule(a):
    """reschedule ID... DATE: the due date moves; a recurring task keeps its recurrence, a date without a
    time keeps the task's time."""
    if len(a.pos) < 3:
        die("todos reschedule ID... DATE (YYYY-MM-DD[THH:MM] or a phrase Todoist parses)")
    a.values["due"] = [a.pos[-1]]
    due = due_flag(a)
    st = read_state()
    items = uniq([resolve(st, r) for r in a.pos[1:-1]])
    if len(items) > 5:
        need_yes(a, ["reschedule %s %s" % (i.short, i.title) for i in items], "rescheduling %d tasks" % len(items))
    groups, wait, out = [], 0.0, []
    for i in items:
        g, new, w = edit_plan(st, i, {"x": attrs_from(a, base=i), "due": due})
        wait = max(wait, w)
        if g:
            groups += g
            out.append(new)
        else:
            print("unchanged: " + line(i))
    if not groups:
        return
    if wait > 0:
        err("waiting %.1f s: Todoist drops title and due changes made in a task's first seconds" % wait)
        time.sleep(wait)
    write(groups)
    for new in out:
        print("rescheduled: " + line(new))


@register("move")
def cmd_move(a):
    """move ID... --to PROJECT [--area A | --section "Name"]: root tasks into another project (subtasks follow)."""
    refs = a.pos[1:]
    if not refs or not a.first("to"):
        die('todos move ID... --to PROJECT [--area A | --section "Name"]')
    st = read_state()
    target = find_project(st, a.first("to"))
    area = normalize_area(a.first("area")) if a.first("area") else (a.first("section") or "").strip() or None
    items = top_level([resolve(st, r) for r in refs])
    for i in items:
        if i.parent:
            die("%s is a subtask; detach it first (todos edit %s --parent '')" % (i.short, i.short))
    if len(items) > 5:
        need_yes(a, ["move %s %s" % (i.short, i.title) for i in items], "moving %d tasks" % len(items))
    sid = None
    if area:
        secs = [x for x in st.all_sections.values() if x.get("project_id") == target["id"] and not x.get("is_archived")]
        hit = [x for x in secs if (x.get("name") or "").lower() == area.lower()]
        if hit:
            sid = hit[0]["id"]
        else:
            within(st, "max_sections", len(secs), "a new section")
            c = new_cmd("section_add", {"name": area, "project_id": target["id"]})
            sid = write([[c]])[c["temp_id"]]
            err('created section "%s" in %s' % (area, target.get("name")))
    dest = {"section_id": sid} if sid else {"project_id": target["id"]}
    write([[new_cmd("item_move", dict(dest, id=i.id))] for i in items])
    for i in items:
        print("moved: %s %s -> %s%s%s" % (row_ref(i), i.title, target.get("name"), "/" + area if area else "",
                                          with_subtasks(len(descendants(i)))))


@register("assign", "unassign")
def cmd_assign(a):
    """assign ID... --to USER | unassign ID...: the task's responsible collaborator (shared projects)."""
    refs = a.pos[1:]
    st = read_state()
    unassign = a.pos[0] == "unassign"
    if not refs or (not unassign and not a.first("to")):
        die("todos assign ID... --to me|USER, or todos unassign ID...")
    items = uniq([resolve(st, r) for r in refs])
    if len(items) > 5:
        need_yes(a, ["%s %s %s" % ("unassign" if unassign else "assign", i.short, i.title) for i in items],
                 "changing %d tasks" % len(items))
    groups = []
    for i in items:
        uid = None if unassign else resolve_user(st, a.first("to"), i.raw.get("project_id"))
        if uid == i.assignee:
            print("unchanged: " + line(i))
            continue
        groups.append([new_cmd("item_update", {"id": i.id, "responsible_uid": uid})])
        i.assignee = uid
    if groups:
        write(groups)
        for i in items:
            print("%s: %s" % ("unassigned" if unassign else "assigned to " + str(i.assignee), line(i)))


@register("order")
def cmd_order(a):
    """order ID ID ...: the given order among siblings (item_reorder); --day: the order in Today (day orders)."""
    refs = a.pos[1:]
    if len(refs) < 2:
        die("todos order ID ID ... [--day]")
    st = read_state()
    items = uniq([resolve(st, r) for r in refs])
    if a.has("day"):
        write([[new_cmd("item_update_day_orders", {"ids_to_orders": {i.id: n + 1 for n, i in enumerate(items)}})]])
    else:
        parents = {(i.raw.get("project_id"), i.raw.get("section_id"), i.parent) for i in items}
        if len(parents) > 1:
            die("the tasks are not siblings (same project, section and parent); reorder one group at a time")
        write([[new_cmd("item_reorder", {"items": [{"id": i.id, "child_order": n + 1} for n, i in enumerate(items)]})]])
    print("reordered: " + ", ".join(row_ref(i) for i in items))


@register("import")
def cmd_import(a):
    if len(a.pos) < 2:
        die("todos import needs a file (markdown grammar or a JSON array)")
    path = os.path.expanduser(a.pos[1])
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        die("cannot read %s: %s" % (path, e))
    seeds = parse_json_seeds(text) if text.lstrip().startswith("[") else parse_seed(text)
    dry, force, update = a.has("dry"), a.has("force"), a.has("update")
    st = read_state()
    roots = {i.title.lower(): i for i in st.items if not i.parent}
    plan, resolved, seen, problems, errors = [], {}, {}, [], []
    skipped_done = skipped_dup = 0
    for s in seeds:
        if s["done"] and not (update and s["id"]):
            skipped_done += 1
            resolved[id(s)] = ("skip", None)
            continue
        parent_item = parent_seed = None
        if s["parent"] is not None:
            kind, ref = resolved.get(id(s["parent"]), ("skip", None))
            if kind == "skip":
                skipped_done += 1
                resolved[id(s)] = ("skip", None)
                continue
            parent_item, parent_seed = (ref, None) if kind == "item" else (None, ref)
        elif s["parent_ref"]:
            parent_item = resolve_in(st.items, s["parent_ref"])
            if not parent_item:
                errors.append('no open task with id %s to put "%s" under' % (s["parent_ref"], s["title"]))
                continue
        existing = None
        if update and s["id"]:
            existing = resolve_in(st.items, s["id"])
            if not existing:
                errors.append('no open task with id %s ("%s")' % (s["id"], s["title"]))
                continue
        if not s["title"] and not existing:
            continue
        if existing:
            resolved[id(s)] = ("item", existing)
            plan.append(("close" if s["done"] else "update", s, existing, parent_item, parent_seed))
            continue
        key = s["title"].lower()
        siblings = roots if parent_item is None and parent_seed is None else \
            {c.title.lower(): c for c in parent_item.children} if parent_item else {}
        dup = siblings.get(key)
        file_key = (id(parent_seed) if parent_seed else (parent_item.id if parent_item else None), key)
        if dup or file_key in seen:
            skipped_dup += 1
            print("skip (exists%s): %s" % (" " + row_ref(dup) if dup else " in this file", s["title"]))
            resolved[id(s)] = ("item", dup) if dup else seen[file_key]
            continue
        seen[file_key] = ("seed", s)
        resolved[id(s)] = ("seed", s)
        if parent_item:
            s["area"] = parent_item.area
        elif parent_seed:
            s["area"] = parent_seed["area"]
        if not s["area"]:
            die('no area for "%s" (first #tag or an area: attribute)' % s["title"])
        s["area"] = normalize_area(s["area"])
        problems += length_problems(s["title"])
        plan.append(("add", s, None, parent_item, parent_seed))
    for e in errors:
        err(e)
    if errors:
        die("%d row(s) name ids that are not open tasks in %s; nothing written" % (len(errors), cfg.project))
    for p in problems:
        err(("warning: " if force else "") + p)
    if problems and not force:
        die("%d row(s) over the title cap; shorten them, or pass --force" % len(problems))
    with_deadline = 0
    specs = []
    for op, s, existing, parent_item, parent_seed in plan:
        if op == "close":
            specs.append((op, s, None, existing, None))
            continue
        x = {"effort": norm_effort(s["effort"]) or (s["effort"] or "").strip() or None,
             "mode": norm_mode(s["mode"]) or (s["mode"] or "").strip() or None,
             "src": s["src"], "since": s["since"], "kinds": uniq(s["kinds"])}
        if s["deadline"] and not parse_day(s["deadline"]):
            die('deadline must be YYYY-MM-DD in "%s"' % s["title"])
        if op == "add":
            x["since"] = x["since"] or date.today().isoformat()
            validate(x)
            with_deadline += bool(s["deadline"])
            specs.append((op, s, x, parent_item, parent_seed))
        else:
            x = {k: (x[k] if x[k] not in (None, []) else getattr(existing, k)) for k in x}
            validate(x, check_kinds=bool(s["kinds"]))
            with_deadline += bool(s["deadline"] and s["deadline"] != existing.deadline)
            ch = {"x": x, "title": s["title"] or None, "desc": s["desc"], "prio": s["prio"] or None,
                  "due": s["due"], "deadline": s["deadline"], "url": s["url"],
                  "touch_note": s["src"] is not None or s["since"] is not None}
            if parent_item:
                check_parent(existing, parent_item)
                ch["parent"] = parent_item.id
            elif parent_seed:
                ch["parent"] = parent_seed  # the temp id is known once the parent's command exists
            elif s["parent"] is None and s["parent_ref"] is None and s["area"] and not existing.parent:
                ch["area"] = normalize_area(s["area"])
            specs.append((op, s, ch, existing, parent_seed))
    if with_deadline:
        require(st, "deadlines", "%d row(s) with a deadline:" % with_deadline)
    if dry:
        n = {"add": 0, "update": 0, "close": 0, "unchanged": 0}
        for op, s, x, third, parent_seed in specs:
            if op == "add":
                n["add"] += 1
                prio = s["prio"]
                link = s["url"] or session_url(x["src"]) or "-"
                labels = compose_labels(x["kinds"], x["effort"], x["mode"])
                due = due_view(s["due"])[0]
                under = row_ref(third) if third else (parent_seed["title"] if parent_seed else None)
                print("would add [%s] %s%s%s  labels=%s  link=%s  %s%s" % (
                    s["area"], s["title"], " @" + due.replace(" ", "T") if due else "", " !%d" % prio if prio else "",
                    ",".join(labels) or "-", link, encode_note(x["src"], x["since"]) or "-",
                    "  under: " + under if under else ""))
            elif op == "close":
                n["close"] += 1
                print("would close %s %s" % (row_ref(third), third.title))
            else:
                ch = dict(x)
                if parent_seed:
                    ch["parent"] = "new:" + parent_seed["title"]
                groups, _, _ = edit_plan(st, third, ch)
                n["update" if groups else "unchanged"] += 1
                if groups:
                    print("would update %s %s: %s" % (row_ref(third), third.title, changed_fields(groups)))
        err("would add %d%s; skipped %d done row(s), %d duplicate(s)" % (
            n["add"], ", update %d, close %d, leave %d unchanged" % (n["update"], n["close"], n["unchanged"])
            if update else "", skipped_done, skipped_dup))
        return
    areas = [s["area"] for op, s, x, _, _ in specs if op == "add"] + \
        [x["area"] for op, s, x, _, _ in specs if op == "update" and x.get("area")]
    labels = []
    for op, s, x, _, _ in specs:
        at = x if op == "add" else x["x"] if op == "update" else None
        if at:
            labels += compose_labels(at["kinds"], at["effort"], at["mode"])
    ensure(st, areas, labels)
    groups, temp_of, log, wait = [], {}, [], 0.0
    for op, s, x, third, parent_seed in specs:
        if op == "add":
            pid = third.id if third else temp_of.get(id(parent_seed)) if parent_seed else None
            group, add = task_group(st, s["area"], s["title"], s["desc"], x, s["url"], s["due"], s["deadline"],
                                    s["prio"] or None, parent_id=pid)
            temp_of[id(s)] = add["temp_id"]
            groups.append(group)
            log.append(("added", add, encode_note(x["src"], x["since"]), (third.depth + 1 if third else 0, s["area"])))
        elif op == "close":
            groups.append([new_cmd("item_close", {"id": third.id})])
            log.append(("closed", third, None, 0))
        else:
            ch = dict(x)
            if parent_seed:
                ch["parent"] = temp_of[id(parent_seed)]
            g, new, w = edit_plan(st, third, ch)
            wait = max(wait, w)
            if g:
                groups += g
                log.append(("updated", new, changed_fields(g), 0))
            else:
                log.append(("unchanged", third, None, 0))
    if not groups:
        err("added 0%s; skipped %d done row(s), %d duplicate(s)" % (
            ", updated 0, closed 0, unchanged %d" % len(log) if update else "", skipped_done, skipped_dup))
        return
    if wait > 0:
        err("waiting %.1f s: Todoist drops title and due changes made in a task's first seconds" % wait)
        time.sleep(wait)
    mapping = write(groups)
    created = []
    counts = {"added": 0, "updated": 0, "closed": 0, "unchanged": 0}
    for what, obj, extra, depth in log:
        counts[what] += 1
        if what == "added":
            it = created_item(st, obj, mapping, extra)
            it.depth, it.area = depth
            created.append((it, it.depth))
        elif what == "updated":
            print("updated: %s  (%s)" % (line(obj), extra))
        elif what == "closed":
            print("closed: " + line(obj))
    assign_short_ids(st.items + [it for it, _ in created])
    for it, depth in created:
        print("added: " + line(it, indent=True))
    sys.stdout.flush()
    err("added %d%s; skipped %d done row(s), %d duplicate(s)" % (
        counts["added"], ", updated %d, closed %d, unchanged %d" % (counts["updated"], counts["closed"], counts["unchanged"])
        if update else "", skipped_done, skipped_dup))


@register("export")
def cmd_export(a):
    st = read_state()
    text = export_markdown(st.items)
    path = a.first("out") or cfg.export_path
    if path == "-":
        sys.stdout.write(text + "\n")
        return
    path = os.path.expanduser(path)
    try:  # a file that differs only in its GENERATED stamp is left alone: no churn, no mtime
        with open(path, encoding="utf-8") as f:
            same = STAMP_RE.sub("", f.read(), 1) == STAMP_RE.sub("", text + "\n", 1)
    except OSError:
        same = False
    if same:
        err("unchanged %s: %d open task(s)" % (path, len(st.items)))
        return
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        os.replace(tmp, path)
    except OSError as e:
        die("cannot write %s: %s" % (path, e))
    err("wrote %s: %d open task(s)" % (path, len(st.items)))


@register("search")
def cmd_search(a):
    """search TEXT: tasks (title and body), projects, sections, labels and filters, from the cache; no request
    beyond the sync. For Todoist's own search: list --filter "search: TEXT"."""
    text = " ".join(a.pos[1:]).strip().lower()
    if not text:
        die("todos search TEXT")
    st = read_state()
    tasks = [i for i in st.all_items if text in i.title.lower() or text in (i.desc or "").lower()]
    projects = [p for p in st.projects if text in (p.get("name") or "").lower()]
    sections = [x for x in st.all_sections.values() if text in (x.get("name") or "").lower() and not x.get("is_archived")]
    labels = [l for l in st.label_rows if text in (l.get("name") or "").lower()]
    filters = [f for f in st.filters if text in (f.get("name") or "").lower() or text in (f.get("query") or "").lower()]
    if a.has("json"):
        print_json({"tasks": [i.as_dict(("id", "short", "project", "area", "title")) for i in tasks],
                    "projects": [{"id": p["id"], "name": p.get("name")} for p in projects],
                    "sections": [{"id": x["id"], "name": x.get("name"), "project": st.project_names.get(x.get("project_id"))} for x in sections],
                    "labels": [{"id": l.get("id"), "name": l.get("name")} for l in labels],
                    "filters": [{"id": f.get("id"), "name": f.get("name"), "query": f.get("query")} for f in filters]},
                   a.has("pretty"))
        return
    for i in sort_items(tasks, "prio"):
        print("task     " + line(i))
    for p in projects:
        print("project  %s %s" % (p["id"], p.get("name")))
    for x in sections:
        print("section  %s %s/%s" % (x["id"], st.project_names.get(x.get("project_id")), x.get("name")))
    for l in labels:
        print("label    %s %s" % (l.get("id"), l.get("name")))
    for f in filters:
        print("filter   %s %s  %s" % (f.get("id"), f.get("name"), f.get("query")))
    err("%d task(s), %d project(s), %d section(s), %d label(s), %d filter(s)"
        % (len(tasks), len(projects), len(sections), len(labels), len(filters)))


@register("overview")
def cmd_overview(a):
    """overview: every active project with its sections and open counts; overview PROJECT: its open tasks by area."""
    st = read_state()
    if len(a.pos) > 1:
        p = find_project(st, a.pos[1])
        items = [i for i in st.all_items if i.raw.get("project_id") == p["id"]]
        if a.has("json"):
            print_json([i.as_dict(DEFAULT_FIELDS + ("project",)) for i in sort_items(items, "area")], a.has("pretty"))
            return
        groups = {}
        for i in items:
            groups.setdefault(i.area, []).append(i)
        print("# %s (%d open)" % (p.get("name"), len(items)))
        for name in sorted(groups):
            print("## " + name)
            for i in sort_items(groups[name], "prio"):
                print(line(i, indent=True))
        return
    rows = []
    for p in sorted([p for p in st.projects if not p.get("is_archived")], key=lambda p: (p.get("child_order") or 0)):
        secs = sorted([x for x in st.all_sections.values() if x.get("project_id") == p["id"] and not x.get("is_archived")],
                      key=lambda x: x.get("section_order") or 0)
        rows.append({"id": p["id"], "name": p.get("name"), "open": open_in(st, "project_id", p["id"]),
                     "sections": [{"id": x["id"], "name": x.get("name"), "open": open_in(st, "section_id", x["id"])} for x in secs]})
    if a.has("json"):
        print_json(rows, a.has("pretty"))
        return
    for r in rows:
        print("%s %s  (%d open)" % (r["id"], r["name"], r["open"]))
        for x in r["sections"]:
            print("  %s %s  (%d open)" % (x["id"], x["name"], x["open"]))


@register("stats")
def cmd_stats(a):
    if a.has("account"):
        r = rest("GET", "/tasks/completed/stats")
        if a.has("json"):
            print_json(redact(r), a.has("pretty"))
            return
        goals = r.get("goals") or {}
        print("karma %s (%s), %s completed all time" % (r.get("karma"), r.get("karma_trend"), r.get("completed_count")))
        print("goals: %s a day, %s a week; streak now %s days, best %s" % (
            goals.get("daily_goal"), goals.get("weekly_goal"),
            (goals.get("current_daily_streak") or {}).get("count"), (goals.get("max_daily_streak") or {}).get("count")))
        for d in (r.get("days_items") or [])[:7]:
            print("  %s: %s" % (d.get("date"), d.get("total_completed")))
        for w in (r.get("week_items") or [])[:4]:
            print("  week %s: %s" % (w.get("from"), w.get("total_completed")))
        return
    st = read_state()
    done30 = fetch_done(st, parse_window("30d"))

    def count(key):
        m = {}
        for i in st.items:
            k = key(i)
            m["-" if k in (None, "") else str(k)] = m.get("-" if k in (None, "") else str(k), 0) + 1
        return m

    kinds = {}
    for i in st.items:
        for k in i.kinds:
            kinds[k] = kinds.get(k, 0) + 1
    limits = ((st.data.get("user_plan_limits") or {}).get("current") or {})
    stats = {"project": cfg.project, "open": len(st.items), "done30d": len(done30),
             "overdue": len([i for i in st.items if i.overdue]), "areas": count(lambda i: i.area), "kinds": kinds,
             "mode": count(lambda i: i.mode), "effort": count(lambda i: i.effort),
             "prio": count(lambda i: i.prio or None),
             "sections": len(st.sections), "plan": limits.get("plan_name"),
             "maxTasks": limits.get("max_tasks"), "maxSections": limits.get("max_sections")}
    if a.has("json"):
        print_json(stats, a.has("pretty"))
        return
    print("%s: %d open, %d done in 30d, %d overdue" % (cfg.project, stats["open"], stats["done30d"], stats["overdue"]))
    for label in ("areas", "kinds", "mode", "effort", "prio"):
        m = stats[label]
        print("%s: %s" % (label, ", ".join("%s %d" % kv for kv in sorted(m.items(), key=lambda kv: (-kv[1], kv[0])))))
    if limits:
        print("plan %s: %d/%s open tasks, %d/%s sections (the task cap counts per project)"
              % (stats["plan"], stats["open"], stats["maxTasks"], stats["sections"], stats["maxSections"]))


def brief_row(i):
    """A row of the brief: every key of BRIEF_FIELDS present, null where the task has no value."""
    d = i.as_dict(BRIEF_FIELDS)
    return {f: d.get(f) for f in BRIEF_FIELDS}


@register("brief")
def cmd_brief(a):
    """brief: the digest an agent reads first. Counts by area; what is overdue or due today; what an agent could
    do now (the first two modes: alone, then with the user mid-way; by value, then effort, then due); the tasks one
    session filed (--src, else the first 8 characters of $CLAUDE_CODE_SESSION_ID). --limit N rows per part (10).
    --json: the same under fixed keys (todos help fields names a row's keys)."""
    st = read_state()
    everywhere = a.has("all-projects")
    items = st.all_items if everywhere else st.items
    try:
        limit = 10 if a.first("limit") is None else max(1, int(a.first("limit")))
    except ValueError:
        die("--limit needs a number")
    src = (a.first("src") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()[:8].lower() or None
    today = now().date()
    where = (lambda i: "%s/%s" % (i.project or "-", i.area)) if everywhere else (lambda i: i.area)
    areas = {}
    for i in items:
        areas[where(i)] = areas.get(where(i), 0) + 1
    overdue = [i for i in items if i.overdue]
    due_today = [i for i in items if not i.overdue and i.due_end is not None
                 and (i.due_end - timedelta(seconds=1)).astimezone().date() == today]
    rank = {e: n for n, e in enumerate(cfg.efforts)}

    def by_value(i):
        return (i.prio or 4, rank.get(i.effort, len(rank)), i.due_end or FAR, i.created or NEAR)

    def part(rows):
        return {"total": len(rows), "rows": rows[:limit]}

    modes = cfg.modes[:2]
    due = part(sort_items(overdue + due_today, "due"))
    agent = {m: part(sorted([i for i in items if i.mode == m], key=by_value)) for m in modes}
    mine = part(sort_items([i for i in items if src and (i.src or "").lower().startswith(src)], "prio"))
    if a.has("json"):
        def rows(p):
            return {"total": p["total"], "rows": [brief_row(i) for i in p["rows"]]}
        print_json({"project": None if everywhere else cfg.project, "open": len(items), "overdue": len(overdue),
                    "today": len(due_today), "areas": areas, "limit": limit, "due": rows(due),
                    "modes": {m: rows(agent[m]) for m in modes},
                    "session": dict(rows(mine), src=src)}, a.has("pretty"))
        return
    scope = "all projects" if everywhere else cfg.project
    print("%s: %d open, %d overdue, %d due today; areas: %s" % (
        scope, len(items), len(overdue), len(due_today),
        ", ".join("%s %d" % kv for kv in sorted(areas.items(), key=lambda kv: (-kv[1], kv[0]))) or "-"))
    flag = " --all-projects" if everywhere else ""

    def block(title, p, more):
        print("# %s (%d)" % (title, p["total"]))
        for i in p["rows"]:
            print(line(i))
        if p["total"] > limit:
            print("  +%d more: %s" % (p["total"] - limit, more))
        elif not p["rows"]:
            print("  none")

    block("due: overdue and today", due, "todos list --due-before %s%s" % (today.isoformat(), flag))
    for m in modes:
        meaning = cfg.mode_meaning.get(m)
        block(m + (": " + meaning if meaning else ""), agent[m], "todos list --mode %s%s" % (m, flag))
    block("this session: src %s" % (src or "unknown, pass --src"), mine, "todos list --src %s%s" % (src, flag))


@register("areas", "lists")
def cmd_areas(a):
    st = read_state()
    if not st.project_id:
        err('no Todoist project "%s" yet (todos add --area <area> creates it)' % cfg.project)
        return
    if len(a.pos) > 1 and a.pos[1] == "rename":
        if len(a.pos) != 4:
            die('todos areas rename "<old name>" <new>')
        old, new = a.pos[2], normalize_area(a.pos[3])
        sid = st.section_id(old)
        if not sid:
            die('no section "%s" in %s (todos areas lists them)' % (old, cfg.project))
        if st.section_id(new) and st.section_id(new) != sid:
            die('section "%s" exists in %s already' % (new, cfg.project))
        write([[new_cmd("section_update", {"id": sid, "name": new})]])
        print("renamed: %s -> %s  (its tasks stay; the export heading follows)" % (st.sections[sid], new))
        return
    counts = {}
    for i in st.items:
        counts[i.area] = counts.get(i.area, 0) + 1
    for name in sorted(st.sections.values()):
        print("%s  (%d open)" % (name, counts.get(name, 0)))
    if counts.get("-"):
        print("-  (%d open, no section)" % counts["-"])
