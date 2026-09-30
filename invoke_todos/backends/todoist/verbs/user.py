"""user and notifications: the profile, plan, settings and goals; the live notifications."""
from invoke_todos.args import arg, kv_pairs, onoff, picked, sub
from invoke_todos.backends.todoist.api import new_cmd, rest, write
from invoke_todos.backends.todoist.render import notification_line
from invoke_todos.backends.todoist.state import read_state
from invoke_todos.output import die, emit, print_json, redact
from invoke_todos.verbs import register


USER_KEYS = ("full_name", "timezone", "start_page", "start_day", "next_week", "time_format", "date_format", "sort_order",
             "auto_reminder", "theme", "weekend_start_day", "beta")
SETTING_KEYS = ("reminder_push", "reminder_desktop", "reminder_email", "completed_sound_desktop", "completed_sound_mobile")


@register("user", "me")
def cmd_user(a):
    st = read_state()
    v = sub(a, "show")
    if v == "show":
        u = redact(st.user)
        if a.has("json"):
            print_json({"user": u, "settings": st.settings, "plan": st.plan()}, a.has("pretty"))
            return
        if not u:
            die("the cache has no user record yet; run again with --fresh")
        print("%s <%s>  id %s  tz %s  plan %s%s" % (u.get("full_name"), u.get("email"), u.get("id"),
                                                    (u.get("tz_info") or {}).get("timezone"), st.plan().get("plan_name"),
                                                    "  premium" if u.get("is_premium") else ""))
        print("goals: %s a day, %s a week; karma %s (%s); week starts on day %s; days off %s"
              % (u.get("daily_goal"), u.get("weekly_goal"), u.get("karma"), u.get("karma_trend"), u.get("start_day"), u.get("days_off")))
        print("inbox project: %s; settings: %s" % (st.project_names.get(u.get("inbox_project_id")),
                                                   ", ".join("%s=%s" % kv for kv in sorted(st.settings.items())) or "-"))
        return
    if v == "info":
        print_json(redact(rest("GET", "/user")), True)
        return
    if v == "plan":
        plan = st.plan()
        if a.has("json"):
            print_json(plan, a.has("pretty"))
            return
        for k in sorted(plan):
            print("%s: %s" % (k, plan[k]))
        return
    if v == "settings":
        if len(a.pos) > 2:
            args = kv_pairs(a.pos[2:], SETTING_KEYS)
            write([[new_cmd("user_settings_update", args)]])
            print("settings: " + ", ".join("%s=%s" % kv for kv in args.items()))
        else:
            emit([st.settings], a, lambda s: ", ".join("%s=%s" % kv for kv in sorted(s.items())) or "-")
        return
    if v == "set":
        args = kv_pairs(a.pos[2:], USER_KEYS)
        if not args:
            die("todos user set KEY=VALUE... (keys: %s); email and password are not taken on the command line" % ", ".join(USER_KEYS))
        write([[new_cmd("user_update", args)]])
        print("updated: " + ", ".join("%s=%s" % kv for kv in args.items()))
        return
    if v == "goals":
        args = picked((("daily_goal", a.first("daily")), ("weekly_goal", a.first("weekly"))))
        args = {k: int(v) for k, v in args.items()}
        if a.first("vacation") is not None:
            args["vacation_mode"] = 1 if onoff(a, "vacation") else 0
        if a.first("karma") is not None:
            args["karma_disabled"] = 0 if onoff(a, "karma") else 1
        if a.first("days"):
            args["ignore_days"] = [int(x) for x in a.first("days").split(",") if x.strip()]
        if not args:
            die("todos user goals [--daily N] [--weekly N] [--vacation on|off] [--karma on|off] [--days 6,7]")
        write([[new_cmd("update_goals", args)]])
        print("goals: " + ", ".join("%s=%s" % kv for kv in args.items()))
        return
    if v == "notify":
        ntype, service, state = arg(a, 2, "a notification type"), arg(a, 3, "email or push"), arg(a, 4, "on or off")
        if state not in ("on", "off"):
            die("todos user notify TYPE email|push on|off")
        r = rest("PUT", "/notification_setting", body={"notification_type": ntype, "service": service, "dont_notify": state == "off"})
        print_json(r, True) if a.has("json") else print("%s by %s: %s" % (ntype, service, state))
        return
    die("todos user: show|info|plan|settings [KEY=on|off...]|set KEY=VALUE...|goals|notify TYPE SERVICE on|off")


@register("notifications")
def cmd_notifications(a):
    st = read_state()
    v = sub(a)
    if v == "list":
        rows = sorted(st.notifications, key=lambda n: n.get("created_at") or "", reverse=True)
        if a.has("unread"):
            rows = [n for n in rows if n.get("is_unread")]
        emit(rows, a, notification_line)
        return
    if v == "read" and a.has("all"):
        write([[new_cmd("live_notifications_mark_read_all", {})]])
        print("all read")
        return
    if v in ("read", "unread"):
        ids = a.pos[2:] or die("todos notifications %s ID... (or read --all)" % v)
        write([[new_cmd("live_notifications_mark_" + v, {"ids": ids})]])
        print("%s: %s" % (v, ", ".join(ids)))
        return
    if v == "seen":
        write([[new_cmd("live_notifications_set_last_read", {"id": arg(a, 2, "a notification id (0 = all)")})]])
        print("last read set")
        return
    die("todos notifications: list [--unread] | read ID... | read --all | unread ID... | seen ID")
