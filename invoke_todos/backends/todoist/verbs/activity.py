"""activity: the account's activity log, scoped to the project unless told otherwise."""
from datetime import timedelta

from invoke_todos.backends.todoist.api import pages
from invoke_todos.backends.todoist.render import activity_line
from invoke_todos.backends.todoist.state import find_project, read_state, resolve, resolve_user, user_id
from invoke_todos.dates import now, parse_window, utc, ymdhm
from invoke_todos.output import die, emit, err
from invoke_todos.verbs import register


@register("activity")
def cmd_activity(a):
    st = read_state()
    q = {"annotate_parents": "true"}
    types = {"task": "item", "comment": "note"}
    if a.first("type"):
        q["object_type"] = types.get(a.first("type"), a.first("type"))
    if a.first("id"):
        q["object_id"] = a.first("id")
    if a.first("task"):  # the task's own events and its comments' (parent_item_id alone returns only the comments')
        q.update(object_type="item", object_id=resolve(st, a.first("task"), include_done=True).id, include_child_objects="true")
    if a.first("project"):
        q["parent_project_id"] = find_project(st, a.first("project"))["id"]
    elif not a.has("all-projects") and st.project_id and not a.first("task"):
        q["parent_project_id"] = st.project_id
    if a.first("event"):
        q["event_type"] = a.first("event")
    if a.first("events"):
        q["object_event_types"] = [x.strip() for x in a.first("events").split(",") if x.strip()]
    if a.has("mine"):  # one's own events carry one's id as the initiator (initiator_id_null is not it)
        q["initiator_id"] = user_id(st)
    if a.first("by"):
        q["initiator_id"] = resolve_user(st, a.first("by"))
    edge = None  # set when --since was moved to the edge of the plan's history
    if a.first("since"):
        since = parse_window(a.first("since"))
        if since is None:
            die("--since needs 7d, 2w, 12h or YYYY-MM-DD")
        days = st.plan().get("activity_log_limit")
        if isinstance(days, int) and days > 0:
            # Observed live (2026-09-30): a date_from at or beyond the plan's history is refused whole (HTTP 403
            # PREMIUM_ONLY), --since 7d on a 7-day plan included; a date just inside it is answered.
            limit = now() - timedelta(days=days) + timedelta(minutes=5)
            if since < limit:
                err("note: plan %s keeps %d days of activity; reading from %s" % (st.plan().get("plan_name"), days, ymdhm(limit)))
                since = edge = limit
        q["date_from"] = utc(since)
    if a.first("until"):
        until = parse_window(a.first("until"))
        if until is None:
            die("--until needs 7d, 2w, 12h or YYYY-MM-DD")
        if edge is not None and until <= edge:
            die("nothing to read: --until %s is before the plan's history starts (%s)" % (a.first("until"), ymdhm(edge)))
        q["date_to"] = utc(until)
    if a.first("workspace"):
        q["workspace_id"] = a.first("workspace")
    for flag, key in (("children", "include_child_objects"), ("parents", "include_parent_object"), ("notes", "annotate_notes")):
        if a.has(flag):
            q[key] = "true"
    limit = int(a.first("limit") or 50)
    rows = list(pages("/activities", q, limit=min(limit, 200), max_pages=int(a.first("max") or 1)))
    if a.has("others"):
        rows = [e for e in rows if str(e.get("initiator_id") or "") != user_id(st)]
    emit(rows, a, lambda e: activity_line(e, st))
    err("%d event(s)" % len(rows))
