"""labels: the personal labels (the effort and mode labels need --force to rename or delete) and the shared ones."""
from invoke_todos.args import arg, favorite_flag, picked, sub
from invoke_todos.backends.todoist.api import new_cmd, pages, write
from invoke_todos.backends.todoist.flags import color_flag
from invoke_todos.backends.todoist.render import label_line
from invoke_todos.backends.todoist.state import find_label, read_state, within
from invoke_todos.model import reserved_label
from invoke_todos.output import die, emit, need_yes, print_json
from invoke_todos.verbs import register


@register("labels")
def cmd_labels(a):
    st = read_state()
    v = sub(a)
    counts = {}
    for i in st.all_items:
        for n in i.raw.get("labels") or []:
            counts[n.lower()] = counts.get(n.lower(), 0) + 1
    if v == "list":
        if a.has("shared"):
            rows = list(pages("/labels/shared", None if a.has("all") else {"omit_personal": "true"}))
            emit(rows, a, lambda n: "%s  tasks:%d" % (n, counts.get(str(n).lower(), 0)))
            return
        rows = sorted(st.label_rows, key=lambda l: (l.get("item_order") or 0, (l.get("name") or "").lower()))
        if a.first("grep"):
            rows = [l for l in rows if a.first("grep").lower() in (l.get("name") or "").lower()]
        emit(rows, a, lambda l: label_line(l, counts))
        return
    if v == "add":
        name = arg(a, 2, "a name")
        if name.lower() in st.labels:
            die('label "%s" exists' % name)
        within(st, "max_labels", len(st.label_rows), "a new label")
        c = new_cmd("label_add", picked((("name", name), ("color", color_flag(a)), ("is_favorite", favorite_flag(a)))))
        print("added: %s %s" % (write([[c]])[c["temp_id"]], name))
        return
    if v == "rename-shared":
        old, new = arg(a, 2, "the old name"), arg(a, 3, "the new name")
        need_yes(a, ["rename the shared label %s to %s on every task" % (old, new)], "renaming a shared label")
        write([[new_cmd("label_rename", {"name_old": old, "name_new": new})]])
        print("renamed: %s -> %s" % (old, new))
        return
    if v == "strip-shared":
        name = arg(a, 2, "a label name")
        need_yes(a, ["remove the shared label %s from every task (%d here)" % (name, counts.get(name.lower(), 0))], "stripping a label")
        write([[new_cmd("label_delete_occurrences", {"name": name})]])
        print("stripped: " + name)
        return
    if v == "order":
        rows = [find_label(st, r) for r in a.pos[2:]]
        if len(rows) < 2:
            die("todos labels order L1 L2 ...")
        write([[new_cmd("label_update_orders", {"id_order_mapping": {str(l["id"]): n + 1 for n, l in enumerate(rows)}})]])
        print("reordered: " + ", ".join(l.get("name") or "" for l in rows))
        return
    l = find_label(st, arg(a, 2, "a label"))
    if v == "show":
        print_json(l, True) if a.has("json") else print(label_line(l, counts))
        return
    if v == "edit":
        if a.first("name") and reserved_label(l.get("name") or "") and not a.has("force"):
            die("%s is a label the CLI reads (effort-*, the modes); renaming it breaks the filters and the export; --force overrides"
                % l.get("name"))
        args = picked((("name", a.first("name")), ("color", color_flag(a)), ("is_favorite", favorite_flag(a))))
        if a.first("order"):
            args["item_order"] = int(a.first("order"))
        if not args:
            die("nothing to change: --name, --color, --favorite, --no-favorite, --order")
        write([[new_cmd("label_update", dict(args, id=l["id"]))]])
        print("edited: " + label_line(dict(l, **args), counts))
        return
    if v == "rm":
        if reserved_label(l.get("name") or "") and not a.has("force"):
            die("%s is a label the CLI reads; deleting it strips it from every task; --force overrides" % l.get("name"))
        keep = a.has("keep-on-tasks")
        need_yes(a, ["delete label %s (%d tasks %s)" % (l.get("name"), counts.get((l.get("name") or "").lower(), 0),
                                                        "keep it as a shared label" if keep else "lose it")], "deleting a label")
        write([[new_cmd("label_delete", {"id": l["id"], "cascade": "none" if keep else "all"})]])
        print("removed: %s %s" % (l.get("id"), l.get("name")))
        return
    die("todos labels: list|show|add|edit|rm|rename-shared|strip-shared|order")
