"""sections: the same objects as areas, account-wide (rename keeps the house spelling through cmd_areas)."""
from invoke_todos.args import arg, onoff, picked, read_text, sub
from invoke_todos.backends.todoist.api import new_cmd, write
from invoke_todos.backends.todoist.render import section_line
from invoke_todos.backends.todoist.state import find_project, find_section, open_in, read_state, within
from invoke_todos.backends.todoist.verbs.tasks import cmd_areas
from invoke_todos.config import cfg
from invoke_todos.output import die, emit, need_yes, print_json
from invoke_todos.query import sort_items
from invoke_todos.render import line
from invoke_todos.verbs import register


@register("sections")
def cmd_sections(a):
    st = read_state()
    v = sub(a)
    here = st.project_row(st.project_id) if st.project_id else None
    if v == "list":
        rows = list(st.all_sections.values())
        if not a.has("all-projects"):
            rows = [x for x in rows if x.get("project_id") == st.project_id]
        if not a.has("archived"):
            rows = [x for x in rows if not x.get("is_archived")]
        if a.first("grep"):
            rows = [x for x in rows if a.first("grep").lower() in (x.get("name") or "").lower()]
        rows.sort(key=lambda x: (st.project_names.get(x.get("project_id")) or "", x.get("section_order") or 0))
        emit(rows, a, lambda x: section_line(st, x))
        return
    if v == "add":
        name = arg(a, 2, "a name")
        if not here:
            die('no project "%s" (todos projects add creates one)' % cfg.project)
        if any((x.get("name") or "").lower() == name.lower() for x in st.all_sections.values()
               if x.get("project_id") == here["id"] and not x.get("is_archived")):
            die('section "%s" exists in %s' % (name, cfg.project))
        within(st, "max_sections", len(st.sections), "a new section")
        args = picked((("name", name), ("project_id", here["id"]), ("description", read_text(a, "description"))))
        c = new_cmd("section_add", args)
        print("added: %s %s/%s" % (write([[c]])[c["temp_id"]], cfg.project, name))
        return
    if v == "order":
        rows = [find_section(st, r, here) for r in a.pos[2:]]
        if len(rows) < 2:
            die("todos sections order S1 S2 ... (the new order within the project)")
        write([[new_cmd("section_reorder", {"sections": [{"id": x["id"], "section_order": n + 1} for n, x in enumerate(rows)]})]])
        print("reordered: " + ", ".join(x.get("name") or "" for x in rows))
        return
    if v == "rename":  # the house spelling, kept: areas rename "<old>" NEW
        return cmd_areas(a)
    ref = arg(a, 2, "a section")
    x = find_section(st, ref, None if "/" in ref else here)
    n_open = open_in(st, "section_id", x["id"])
    if v == "show":
        if a.has("json"):
            print_json(x, a.has("pretty"))
            return
        print(section_line(st, x))
        if x.get("description"):
            print(x["description"])
        for i in sort_items([i for i in st.all_items if i.raw.get("section_id") == x["id"]], "prio"):
            print(line(i, indent=True))
        return
    if v == "edit":
        args = picked((("name", a.first("name")), ("description", read_text(a, "description")), ("is_collapsed", onoff(a, "collapsed"))))
        if a.has("clear-description"):
            args["description"] = ""
        if not args:
            die("nothing to change: --name, --description, --clear-description, --collapsed on|off")
        write([[new_cmd("section_update", dict(args, id=x["id"]))]])
        print("edited: " + section_line(st, dict(x, **args)))
        return
    if v == "rm":
        need_yes(a, ["delete section %s/%s and its %d open tasks (completed ones too)"
                     % (st.project_names.get(x.get("project_id")), x.get("name"), n_open)], "deleting a section")
        write([[new_cmd("section_delete", {"id": x["id"]})]])
        print("removed: %s %s" % (x["id"], x.get("name")))
        return
    if v in ("archive", "unarchive"):
        if v == "archive":
            need_yes(a, ["archive section %s (%d open tasks hidden with it)" % (x.get("name"), n_open)], "archiving a section")
        write([[new_cmd("section_" + v, {"id": x["id"]})]])
        print("%sd: %s %s" % (v, x["id"], x.get("name")))
        return
    if v == "move":
        target = find_project(st, a.first("to") or die("todos sections move S --to PROJECT"))
        need_yes(a, ["move section %s with its %d open tasks into %s" % (x.get("name"), n_open, target.get("name"))], "moving a section")
        write([[new_cmd("section_move", {"id": x["id"], "project_id": target["id"]})]])
        print("moved: %s %s -> %s" % (x["id"], x.get("name"), target.get("name")))
        return
    die("todos sections: list|show|add|edit|rename|rm|archive|unarchive|move|order")
