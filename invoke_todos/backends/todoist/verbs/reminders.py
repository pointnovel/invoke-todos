"""reminders: relative, absolute and location reminders, behind the plan gate."""
import json

from invoke_todos.args import arg, due_flag, sub
from invoke_todos.backends.todoist.api import new_cmd, write
from invoke_todos.backends.todoist.render import reminder_line
from invoke_todos.backends.todoist.state import find_reminder, read_state, resolve, resolve_user, within
from invoke_todos.dates import parse_duration
from invoke_todos.output import die, emit, need_yes, print_json
from invoke_todos.render import ref
from invoke_todos.verbs import register


def reminder_args(a, st):
    args = {}
    if a.first("before") is not None:
        d = parse_duration(a.first("before"), zero=True)
        args.update(type="relative", minute_offset=d["amount"] * (1440 if d["unit"] == "day" else 1))
    elif a.first("at") is not None:
        args.update(type="absolute", due=due_flag(a, "at"))
    elif a.first("place") is not None:
        if not (a.first("lat") and a.first("lon") and a.first("on") in ("enter", "leave")):
            die("--place needs --lat, --lon and --on enter|leave")
        args.update(type="location", name=a.first("place"), loc_lat=a.first("lat"), loc_long=a.first("lon"),
                    loc_trigger="on_" + a.first("on"))
        if a.first("radius"):
            args["radius"] = int(a.first("radius"))
    if a.has("urgent"):
        args["is_urgent"] = True
    if a.first("service"):
        if a.first("service") not in ("email", "push"):
            die("--service takes email or push")
        args["service"] = a.first("service")
    if a.first("user"):
        args["notify_uid"] = resolve_user(st, a.first("user"))
    return args


def reminder_allowed(st, args):
    """The plan gate: reminders are paid, except the one at the due time where reminders_at_due holds."""
    plan = st.plan()
    if plan.get("reminders") is False:
        if args.get("type") == "relative" and args.get("minute_offset") == 0 and plan.get("reminders_at_due"):
            return
        die("reminders need a paid Todoist plan (plan %s has reminders off); on this plan a due time is the reminder "
            "(--due YYYY-MM-DDTHH:MM), and --before 0m may add one at the due time" % plan.get("plan_name"))


@register("reminders")
def cmd_reminders(a):
    st = read_state()
    v = sub(a)
    if v not in ("list", "add", "edit", "rm", "show", "locations", "clear-locations"):
        a.pos.insert(1, "list")  # todos reminders <task>
        v = "list"
    if v == "list":
        rows = st.reminders
        if len(a.pos) > 2:
            i = resolve(st, a.pos[2], include_done=True)
            rows = [r for r in rows if r.get("item_id") == i.id]
        elif not a.has("all-projects"):
            mine = {i.id for i in st.items}
            rows = [r for r in rows if r.get("item_id") in mine]
        if a.has("location"):
            rows = [r for r in rows if r.get("type") == "location"]
        emit(rows, a, lambda r: reminder_line(r, st))
        return
    if v == "locations":
        emit(st.locations, a, lambda l: json.dumps(l, ensure_ascii=False))
        return
    if v == "clear-locations":
        need_yes(a, ["clear the account's %d saved locations" % len(st.locations)], "clearing locations")
        write([[new_cmd("clear_locations", {})]])
        print("cleared")
        return
    if v == "add":
        i = resolve(st, arg(a, 2, "a task id"))
        args = reminder_args(a, st)
        if "type" not in args:
            die("todos reminders add ID --before 30m | --at WHEN | --place NAME --lat X --lon Y --on enter|leave [--radius M]")
        reminder_allowed(st, args)
        loc = args["type"] == "location"
        within(st, "max_reminders_location" if loc else "max_reminders_time",
               len([r for r in st.reminders if (r.get("type") == "location") == loc]), "a new reminder")
        if args["type"] == "relative" and len((i.raw.get("due") or {}).get("date") or "") <= 10:
            die("a relative reminder needs a due date with a time on %s (todos edit %s --due YYYY-MM-DDTHH:MM)" % (i.short, i.short))
        c = new_cmd("reminder_add", dict(args, item_id=i.id))
        print("added: reminder %s on %s %s" % (write([[c]])[c["temp_id"]], ref(i), i.title))
        return
    r = find_reminder(st, arg(a, 2, "a reminder id"))
    if v == "show":
        print_json(r, True) if a.has("json") else print(reminder_line(r, st))
        return
    if v == "edit":
        args = reminder_args(a, st)
        if not args:
            die("nothing to change: --before, --at, --place/--lat/--lon/--on/--radius, --urgent, --service, --user")
        if args.get("type", r.get("type")) != r.get("type"):
            die("a reminder keeps its type (%s); remove it and add another" % r.get("type"))
        reminder_allowed(st, dict(r, **args))
        write([[new_cmd("reminder_update", dict(args, id=r["id"]))]])
        print("edited: " + reminder_line(dict(r, **args), st))
        return
    if v == "rm":
        write([[new_cmd("reminder_delete", {"id": r["id"]})]])
        print("removed: reminder %s" % r["id"])
        return
