"""views: how the apps show a view (view_options) and a project's defaults."""
import json

from invoke_todos.args import arg, onoff, picked, sub
from invoke_todos.backends.todoist.api import call, new_cmd, write
from invoke_todos.backends.todoist.state import find_filter, find_label, find_project, read_state
from invoke_todos.output import die, print_json
from invoke_todos.verbs import register


def view_target(st, a):
    vtype = arg(a, 2, "a view type: today|upcoming|assigned_to_me|project|label|filter|workspace_filter")
    obj = None
    if vtype in ("project", "label", "filter", "workspace_filter"):
        ref = arg(a, 3, "the %s" % vtype)
        obj = {"project": lambda: find_project(st, ref)["id"], "label": lambda: str(find_label(st, ref)["id"]),
               "filter": lambda: str(find_filter(st, ref)["id"])}.get(vtype, lambda: ref)()
    return vtype, obj


def view_args(a):
    args = picked((("filtered_by", a.first("filter")), ("grouped_by", a.first("group")), ("sorted_by", a.first("sort-by")),
                   ("sort_order", a.first("direction")), ("show_completed_tasks", onoff(a, "completed")),
                   ("view_mode", a.first("mode-view")), ("deadline", a.first("deadline"))))
    if a.first("calendar"):
        args["calendar_settings"] = json.loads(a.first("calendar"))
    return args


@register("views")
def cmd_views(a):
    st = read_state()
    v = sub(a)
    if v == "list":
        r = call("POST", "/sync", form={"sync_token": "*", "resource_types": json.dumps(["view_options", "project_view_options_defaults"])})
        rows = r.get("view_options") or []
        if a.has("json"):
            print_json({"view_options": rows, "project_defaults": r.get("project_view_options_defaults") or []}, a.has("pretty"))
            return
        for x in rows:
            print("%s %s  %s" % (x.get("view_type"), x.get("object_id") or "", json.dumps(
                {k: val for k, val in x.items() if k not in ("view_type", "object_id") and val not in (None, "", False)}, ensure_ascii=False)))
        for x in r.get("project_view_options_defaults") or []:
            print("project-default %s  %s" % (x.get("project_id"), json.dumps({k: val for k, val in x.items() if k != "project_id" and val}, ensure_ascii=False)))
        return
    if v == "set":
        vtype, obj = view_target(st, a)
        args = view_args(a)
        if not args:
            die("nothing to set: --filter, --group, --sort-by, --direction asc|desc, --completed on|off, --mode-view list|board|calendar, --deadline, --calendar JSON")
        args["view_type"] = vtype
        if obj:
            args["object_id"] = obj
        write([[new_cmd("view_options_set", args)]])
        print("view set: %s %s" % (vtype, obj or ""))
        return
    if v == "reset":
        vtype, obj = view_target(st, a)
        write([[new_cmd("view_options_delete", picked((("view_type", vtype), ("object_id", obj))))]])
        print("view reset: %s %s" % (vtype, obj or ""))
        return
    if v == "default":
        p = find_project(st, arg(a, 2, "a project"))
        args = view_args(a)
        if not args:
            die("nothing to set (the same flags as views set)")
        write([[new_cmd("project_view_options_defaults_set", dict(args, project_id=p["id"]))]])
        print("default view set for " + (p.get("name") or ""))
        return
    die("todos views: list | set TYPE [OBJECT] ... | reset TYPE [OBJECT] | default PROJECT ...")
