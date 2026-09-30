"""filters: the saved queries; run hands the query to cmd_list."""
from invoke_todos.args import arg, favorite_flag, picked, read_text, sub
from invoke_todos.backends.todoist.api import new_cmd, write
from invoke_todos.backends.todoist.flags import color_flag
from invoke_todos.backends.todoist.render import filter_line
from invoke_todos.backends.todoist.state import find_filter, read_state, require, within
from invoke_todos.backends.todoist.verbs.tasks import cmd_list
from invoke_todos.output import die, emit, need_yes, print_json
from invoke_todos.verbs import register


@register("filters")
def cmd_filters(a):
    st = read_state()
    v = sub(a)
    if v == "list":
        rows = sorted(st.filters, key=lambda f: (f.get("item_order") or 0, (f.get("name") or "").lower()))
        if a.first("grep"):
            g = a.first("grep").lower()
            rows = [f for f in rows if g in (f.get("name") or "").lower() or g in (f.get("query") or "").lower()]
        emit(rows, a, filter_line)
        return
    if v == "add":
        name, query = arg(a, 2, "a name"), arg(a, 3, "a query")
        require(st, "filters", "filters add", "run the query with todos list --filter instead")
        within(st, "max_filters", len(st.filters), "a new filter")
        args = picked((("name", name), ("query", query), ("color", color_flag(a)), ("description", read_text(a, "description")),
                       ("is_favorite", favorite_flag(a))))
        c = new_cmd("filter_add", args)
        print("added: %s %s  %s" % (write([[c]])[c["temp_id"]], name, query))
        return
    if v == "order":
        rows = [find_filter(st, r) for r in a.pos[2:]]
        if len(rows) < 2:
            die("todos filters order F1 F2 ...")
        write([[new_cmd("filter_update_orders", {"id_order_mapping": {str(f["id"]): n + 1 for n, f in enumerate(rows)}})]])
        print("reordered: " + ", ".join(f.get("name") or "" for f in rows))
        return
    f = find_filter(st, arg(a, 2, "a filter"))
    if v == "show":
        print_json(f, True) if a.has("json") else print(filter_line(f))
        return
    if v == "run":
        a.values["filter"] = [f.get("query")]
        return cmd_list(a)
    if v == "edit":
        args = picked((("name", a.first("name")), ("query", a.first("query")), ("color", color_flag(a)),
                       ("description", read_text(a, "description")), ("is_favorite", favorite_flag(a))))
        if a.has("clear-description"):
            args["description"] = ""
        if not args:
            die("nothing to change: --name, --query, --color, --description, --clear-description, --favorite, --no-favorite")
        write([[new_cmd("filter_update", dict(args, id=f["id"]))]])
        print("edited: " + filter_line(dict(f, **args)))
        return
    if v == "rm":
        need_yes(a, ["delete filter %s (%s)" % (f.get("name"), f.get("query"))], "deleting a filter")
        write([[new_cmd("filter_delete", {"id": f["id"]})]])
        print("removed: %s %s" % (f.get("id"), f.get("name")))
        return
    die("todos filters: list|show|add|edit|rm|run|order")
