#!/usr/bin/env python3
# Live smoke test against the real Todoist account: every verb of ../todos in a throwaway project
# ("todoist-selftest-<random>"), then the project and every label the run created are deleted, and
# the account's project and label lists are compared with the ones taken before. When the plan's
# project cap leaves no room for another project, the task verbs are skipped and the account-wide
# verbs run in a throwaway section of the default project (TODOIST_PROJECT), deleted at the end with
# its tasks. Needs the token (TODOIST_API_TOKEN or the Keychain item). About 80 API requests.
# python3 tests/live_smoke.py

import json
import os
import random
import string
import subprocess
import sys
import tempfile
import uuid
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "todos")
SUFFIX = "".join(random.choice(string.ascii_lowercase) for _ in range(6))
PROJECT = "todoist-selftest-" + SUFFIX
for k in ("TODOIST_API_BASE", "TODOIST_EXPORT", "TODOIST_SESSION_URL"):
    os.environ.pop(k, None)
sys.path.insert(0, ROOT)
from invoke_todos.backends.todoist import api, state  # noqa: E402  (the config is read on this import: after the pops)
from invoke_todos.config import cfg, reload  # noqa: E402
HOME_PROJECT = cfg.project  # the config's default project (the environment was cleared above)
# Every in-process state.read_state() below must see the project the subprocess runs see: after each change
# to TODOIST_PROJECT, reload() refills cfg from the environment (a stale cfg once read the default project's
# items, added the "Selftest header" tasks there, and failed the body check with an empty description).

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  " + detail) if detail and not ok else ""))


def run(*args, stdin=None):
    p = subprocess.run([sys.executable, CLI] + list(args), input=stdin, capture_output=True, text=True, timeout=120)
    return p


def snapshot():
    data = api.call("POST", "/sync", form={"sync_token": "*", "resource_types": json.dumps(["projects", "labels"])})
    projects = {p["id"]: p["name"] for p in data.get("projects") or [] if not p.get("is_deleted")}
    labels = {l["id"]: l["name"] for l in data.get("labels") or [] if not l.get("is_deleted")}
    return projects, labels


def rows(*args):
    p = run("list", "--json", *args)
    return json.loads(p.stdout) if p.returncode == 0 else []




def extended(area, project_name):
    """The verbs beyond the task list, in a throwaway area of `project_name` (the classic project, or the
    default project when the plan's project cap leaves no room for another). Cleans up what it makes."""
    d3 = (date.today() + timedelta(days=3)).isoformat()
    made_labels = []
    p = run("add", "Selftest recurring", "--area", area, "--due", "every monday 9am", "--json")
    check("add --due as a phrase", p.returncode == 0, p.stderr.strip())
    rec = json.loads(p.stdout) if p.returncode == 0 else {}
    [r] = [x for x in rows("--area", area) if x.get("title") == "Selftest recurring"] or [{}]
    check("a phrase due reads back recurring", r.get("recur") == "every monday 9am" and (r.get("due") or "").endswith("09:00"), json.dumps(r))
    short = r.get("short") or rec.get("short", "")
    p = run("reschedule", short, d3)
    [r] = [x for x in rows("--area", area) if x.get("title") == "Selftest recurring"] or [{}]
    check("reschedule keeps the recurrence and the time", p.returncode == 0 and r.get("recur") == "every monday 9am"
          and r.get("due") == d3 + " 09:00", json.dumps(r) + p.stderr.strip())
    print("      observed: a plain date sent with the old string %s the recurrence" % ("kept" if r.get("recur") else "DROPPED"))
    p = run("done", short)
    [r] = [x for x in rows("--area", area) if x.get("title") == "Selftest recurring"] or [{}]
    check("done on a recurring task moves it on", p.returncode == 0 and "next occurrence" in p.stdout and r.get("recur"), p.stdout + json.dumps(r))
    p = run("done", short, "--forever")
    check("done --forever completes it", p.returncode == 0 and not [x for x in rows("--area", area) if x.get("title") == "Selftest recurring"], p.stderr.strip())
    run("labels", "add", "selftestquick")  # Quick Add applies only labels that exist; unknown ones stay as text
    made_labels.append("selftestquick")
    p = run("quick", "Selftest quick add tomorrow #%s /%s p3 @selftestquick // from quick add" % (project_name.replace(" ", "\\ "), area), "--src", "7e57ab1e", "--json")
    q = json.loads(p.stdout) if p.returncode == 0 and p.stdout.startswith("{") else {}
    check("quick add lands in the area with priority, label, body and the src comment",
          q.get("area") == area and q.get("prio") == 3 and "selftestquick" in (q.get("kinds") or []) and q.get("src") == "7e57ab1e"
          and q.get("desc", "").startswith("from quick add"), p.stdout[:300] + p.stderr.strip())
    qshort = q.get("short", "")
    p = run("comments", "add", qshort, "A selftest comment")
    check("comments add", p.returncode == 0, p.stderr.strip())
    p = run("comments", qshort, "--json")
    notes = json.loads(p.stdout) if p.returncode == 0 else []
    mine = [n for n in notes if n.get("content") == "A selftest comment"]
    check("comments list shows it beside the attr comment", len(mine) == 1 and any("src: 7e57ab1e" in (n.get("content") or "") for n in notes), p.stdout[:300])
    if mine:
        cid = mine[0]["id"]
        p = run("comments", "edit", cid, "A selftest comment, edited")
        p2 = run("comments", "rm", cid, "--yes")
        check("comments edit and rm", p.returncode == 0 and p2.returncode == 0 and not [n for n in json.loads(run("comments", qshort, "--json").stdout) if n["id"] == cid], p.stderr + p2.stderr)
    p = run("edit", qshort, "--due", d3 + "T18:00")
    [r] = [x for x in rows("--area", area) if x.get("short") == qshort] or [{}]
    check("edit --due with a time on the quick-added task", p.returncode == 0 and r.get("due") == d3 + " 18:00", p.stderr.strip()[:160] + json.dumps(r.get("due")))
    p = run("reminders", "add", qshort, "--before", "0m")
    print("      observed: reminder_add at the due time (minute_offset 0) on this plan: %s" % ("accepted" if p.returncode == 0 else p.stderr.strip()[:160]))
    if p.returncode == 0:
        rem = json.loads(run("reminders", qshort, "--json").stdout)
        check("reminders list shows it", len(rem) == 1, json.dumps(rem))
        for x in rem:
            run("reminders", "rm", str(x["id"]))
    p = run("api", "sync", "filter_add", "--args", json.dumps({"name": "selftest-filter", "query": "@selftestquick"}), "--temp-id", "--yes")
    print("      observed: filter_add with %d filters present (plan max_filters %s): %s" % (
        len(json.loads(run("filters", "--json").stdout)), state.read_state().plan().get("max_filters"),
        "accepted" if p.returncode == 0 else p.stderr.strip()[:160]))
    if p.returncode == 0:
        fid = json.loads(run("filters", "--json").stdout)
        for f in fid:
            if f.get("name") == "selftest-filter":
                run("filters", "rm", str(f["id"]), "--yes")
    p = run("labels", "add", "selftestlabel", "--color", "teal")
    check("labels add", p.returncode == 0, p.stderr.strip())
    made_labels.append("selftestlabel")
    p = run("labels", "edit", "selftestlabel", "--name", "selftestlabel2", "--favorite")
    check("labels edit", p.returncode == 0 and "selftestlabel2" in run("labels").stdout, p.stderr.strip())
    made_labels[-1] = "selftestlabel2"
    p = run("list", "--filter", "@selftestquick")
    check("list --filter (GET /tasks/filter) finds the quick-added task", p.returncode == 0 and "Selftest quick add" in p.stdout, p.stdout[:200] + p.stderr.strip())
    p = run("activity", "--task", qshort, "--json")
    ev = json.loads(p.stdout) if p.returncode == 0 else []
    check("activity --task answers", p.returncode == 0, p.stderr.strip()[:200])
    print("      observed: the activity log lists %d event(s) for a task made seconds ago (the log can lag)" % len(ev))
    p = run("api", "sync", "item_add", "--args", json.dumps({"content": "Selftest header", "project_id": state.read_state().project_id,
                                                              "section_id": state.read_state().section_id(area), "is_uncompletable": True}), "--temp-id", "--yes")
    if p.returncode == 0:
        hdr = [x for x in state.read_state().items if x.title == "Selftest header"]
        print("      observed: item_add with is_uncompletable=true: accepted; reads back is_uncompletable=%r" % (hdr[0].raw.get("is_uncompletable") if hdr else "?"))
    else:
        print("      observed: item_add with is_uncompletable=true: %s" % p.stderr.strip()[:160])
    st = state.read_state()
    p = run("api", "POST", "/tasks", "--body", json.dumps({"content": "Selftest header REST", "project_id": st.project_id,
                                                          "section_id": st.section_id(area), "is_uncompletable": True}), "--yes")
    if p.returncode == 0:
        hdr = [x for x in state.read_state().items if x.title == "Selftest header REST"]
        print("      observed: POST /tasks with is_uncompletable=true: accepted; reads back is_uncompletable=%r"
              % (hdr[0].raw.get("is_uncompletable") if hdr else "?"))
    else:
        print("      observed: POST /tasks with is_uncompletable=true: %s" % p.stderr.strip()[:160])
    p = run("api", "read", "user,user_settings,stats")
    o = json.loads(p.stdout) if p.returncode == 0 else {}
    check("api read masks the token", p.returncode == 0 and o.get("user", {}).get("token") == "***" and "stats" in o, p.stderr.strip()[:200])
    p = run("user")
    check("user", p.returncode == 0 and "plan " in p.stdout and "secret" not in p.stdout.lower(), p.stdout[:200] + p.stderr.strip())
    p = run("stats", "--account")
    check("stats --account (GET /tasks/completed/stats)", p.returncode == 0 and "karma" in p.stdout, p.stderr.strip()[:200])
    p = run("projects")
    check("projects", p.returncode == 0 and project_name in p.stdout, p.stderr.strip()[:200])
    p = run("sections")
    check("sections", p.returncode == 0 and area in p.stdout, p.stderr.strip()[:200])
    p = run("templates", "export", project_name)
    check("templates export (CSV)", p.returncode == 0 and p.stdout.lstrip("\ufeff").startswith("TYPE,"), p.stdout[:100] + p.stderr.strip()[:200])
    p = run("labels", "--shared")
    check("labels --shared (GET /labels/shared)", p.returncode == 0, p.stderr.strip()[:200])
    p = run("notifications")
    check("notifications (Sync live_notifications)", p.returncode == 0, p.stderr.strip()[:200])
    p = run("views")
    check("views (Sync view_options)", p.returncode == 0, p.stderr.strip()[:200])
    p = run("workspaces")
    check("workspaces (GET /workspaces)", p.returncode == 0, p.stderr.strip()[:200])
    p = run("backups")
    print("      observed: GET /backups on this plan: %s" % (("ok, %d line(s)" % len(p.stdout.strip().split("\n")) if p.stdout.strip() else "ok, empty") if p.returncode == 0 else p.stderr.strip()[:160]))
    p = run("emails", "get", "--task", qshort)
    print("      observed: PUT /emails for a task: %s" % (p.stdout.strip()[:80] if p.returncode == 0 else p.stderr.strip()[:160]))
    if p.returncode == 0:
        run("emails", "off", "--task", qshort, "--yes")
    return made_labels


def main():
    d3 = (date.today() + timedelta(days=3)).isoformat()
    d4 = (date.today() + timedelta(days=4)).isoformat()
    d10 = (date.today() + timedelta(days=10)).isoformat()
    before_projects, before_labels = snapshot()
    plan = api.call("POST", "/sync", form={"sync_token": "*", "resource_types": '["user_plan_limits", "projects"]'})
    limits = (plan.get("user_plan_limits") or {}).get("current") or {}
    deadlines = limits.get("deadlines") is not False
    active = len([p for p in plan.get("projects") or []
                  if not p.get("is_deleted") and not p.get("is_archived") and not p.get("inbox_project")])  # the Inbox does not count
    room = not isinstance(limits.get("max_projects"), int) or active < limits["max_projects"]
    if not room:
        print("the plan's max_projects (%s) is reached with %d active projects: the task verbs are skipped and the "
              "account-wide verbs run in a throwaway section of %s" % (limits.get("max_projects"), active, HOME_PROJECT))
        return section_mode(before_projects, before_labels)
    os.environ["TODOIST_PROJECT"] = PROJECT
    reload()
    print("project %s; account has %d projects and %d personal labels before; deadlines %s" %
          (PROJECT, len(before_projects), len(before_labels), "on" if deadlines else "off (free plan)"))
    try:
        if not deadlines:
            p = run("add", "Selftest refused", "--area", "alpha", "--deadline", d10)
            check("add --deadline refused on this plan", p.returncode == 1 and "needs a paid Todoist plan" in p.stderr
                  and snapshot()[0] == before_projects, p.stderr.strip())
        p = run("add", "Selftest task", "--area", "alpha", "--kind", "selftestkind", "--due", d3,
                *(["--deadline", d10] if deadlines else []), "--effort", "S", "--prio", "1", "--mode", "unattended",
                "--src", "7e57ab1e", "--note", "Created by tests/live_smoke.py.", "--json")
        check("add", p.returncode == 0, p.stderr.strip())
        added = json.loads(p.stdout) if p.returncode == 0 else {}
        [r] = rows() or [{}]
        check("list after add", r.get("title") == "Selftest task" and r.get("area") == "alpha" and r.get("prio") == 1
              and r.get("kinds") == ["selftestkind"] and (r.get("effort"), r.get("mode")) == ("S", "unattended")
              and r.get("due") == d3 and r.get("deadline") == (d10 if deadlines else None) and r.get("src") == "7e57ab1e"
              and r.get("since") == date.today().isoformat() and r.get("url", "").endswith("sid=7e57ab1e")
              and r.get("desc") == "Created by tests/live_smoke.py.", json.dumps(r))
        short = r.get("short") or added.get("short", "")
        p = run("show", short)
        check("show", p.returncode == 0 and "title:    Selftest task" in p.stdout, p.stderr.strip())
        p = run("edit", short, "--title", "Selftest task, edited", "--area", "beta", "--kind", "selftestkind,selftestother",
                "--prio", "2", "--src", "0facbdc3", "--due", d4 + "T09:30", "--note", "Edited text.")
        check("edit", p.returncode == 0 and p.stdout.startswith("edited: "), p.stderr.strip())
        [r] = rows() or [{}]
        check("list after edit", r.get("title") == "Selftest task, edited" and r.get("area") == "beta"
              and r.get("prio") == 2 and r.get("kinds") == ["selftestkind", "selftestother"]
              and r.get("due") == d4 + " 09:30" and r.get("src") == "0facbdc3" and r.get("url", "").endswith("sid=0facbdc3")
              and r.get("desc") == "Edited text.", json.dumps(r))
        body = "# Why\n\nBecause.\n\n- one\n- two\n\n```\n  kept indent\n```"
        p = run("add", "Selftest subtask", "--parent", short, "--kind", "selftestkind", "--effort", "S", "--note", "-",
                "--src", "7e57ab1e", "--json", stdin=body + "\n")
        check("add --parent", p.returncode == 0, p.stderr.strip())
        sub = json.loads(p.stdout) if p.returncode == 0 else {}
        all_rows = rows()
        by = {x["title"]: x for x in all_rows}
        parent_row, sub_row = by.get("Selftest task, edited", {}), by.get("Selftest subtask", {})
        check("list after add --parent: nested, parent's area, body and link read back",
              [x["title"] for x in all_rows] == ["Selftest task, edited", "Selftest subtask"]
              and sub_row.get("parent") == parent_row.get("id") and sub_row.get("area") == "beta"
              and parent_row.get("subtasks") == [sub_row.get("id")] and sub_row.get("desc") == body
              and sub_row.get("url", "").endswith("sid=7e57ab1e"), json.dumps(all_rows))
        st = state.read_state()
        raw = {i.id: i.raw for i in st.items}
        inherited = raw.get(sub_row.get("id"), {}).get("section_id") == raw.get(parent_row.get("id"), {}).get("section_id")
        print("      observed: a subtask added with parent_id and no section_id reads back with section_id %s"
              % ("equal to the parent's" if inherited else repr(raw.get(sub_row.get("id"), {}).get("section_id"))))
        stored = raw.get(sub_row.get("id"), {}).get("description", "")
        check("markdown body stored verbatim, Origin link on its own paragraph after the fence",
              stored == body + "\n\n" + "[Origin](%s)" % (cfg.src_url_template % "7e57ab1e"), repr(stored))
        p = run("show", sub.get("short", sub_row.get("short", "")))
        check("show names the parent", p.returncode == 0 and "parent:   %s" % parent_row.get("short") in p.stdout, p.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "seed.md")
            with open(path, "w") as f:
                f.write("- [ ] Selftest import one #alpha #selftestkind\n"
                        "      One line of text.\n"
                        "      src: todo-selftest#1; since: 2026-09-01; effort: M; mode: assisted\n"
                        "  - [ ] Selftest import sub #selftestother\n"
                        "        Nested body.\n"
                        "- [ ] Selftest import two @%s !1 #gamma\n" % d3)
            p = run("import", path)
            check("import with a nested row", p.returncode == 0 and "added 3;" in p.stderr, p.stderr.strip())
            by = {x["title"]: x for x in rows()}
            check("imported subtask under its parent", by.get("Selftest import sub", {}).get("parent") == by.get("Selftest import one", {}).get("id")
                  and by.get("Selftest import sub", {}).get("area") == "alpha", json.dumps(by.get("Selftest import sub")))
            # the export reads back whole; an edited copy applies through --update
            out = os.path.join(tmp, "export.md")
            p = run("export", "--out", out)
            p = run("import", out, "--dry", "--update")
            check("export round trip: nothing to update", p.returncode == 0 and "would add 0, update 0, close 0, leave 5 unchanged" in p.stderr, p.stderr.strip())
            text = open(out).read().replace("- [ ] Selftest import two", "- [ ] Selftest import two, retitled")
            text = text.replace("  - [ ] Selftest import sub", "  - [x] Selftest import sub")
            with open(out, "w") as f:
                f.write(text)
            p = run("import", out, "--update")
            check("import --update: retitle and close by id", p.returncode == 0 and "updated 1, closed 1" in p.stderr, p.stderr.strip())
            by = {x["title"]: x for x in rows()}
            check("update read back", "Selftest import two, retitled" in by and "Selftest import sub" not in by, json.dumps(sorted(by)))
        check("list count 4", len(rows()) == 4)
        p = run("done", short)
        check("done takes the subtask along", p.returncode == 0 and "(+1 subtask)" in p.stdout and len(rows()) == 2, p.stdout + p.stderr.strip())
        done = rows("--done", "--since", "1d")
        check("list --done (completed endpoint) lists the task and its subtask",
              [x.get("title") for x in done] == ["Selftest task, edited", "Selftest subtask", "Selftest import sub"] or
              [x.get("title") for x in done] == ["Selftest task, edited", "Selftest import sub", "Selftest subtask"], json.dumps(done))
        p = run("undone", short)
        n = len(rows())
        check("undone", p.returncode == 0 and n in (3, 4), p.stderr.strip())
        print("      observed: reopening a task with a completed subtask leaves %d open (the subtask %s)"
              % (n, "came back too" if n == 4 else "stayed done"))
        p = run("export")
        check("export", p.returncode == 0 and "\n## beta\n" in p.stdout and "Selftest import one" in p.stdout
              and ("\n  - [ ] Selftest subtask" in p.stdout or n == 3), p.stderr.strip())
        p = run("stats", "--json")
        s = json.loads(p.stdout) if p.returncode == 0 else {}
        check("stats", s.get("open") == n and s.get("sections") == 3, json.dumps(s))
        print("      plan %s, maxTasks %s, maxSections %s" % (s.get("plan"), s.get("maxTasks"), s.get("maxSections")))
        p = run("areas")
        check("areas", p.returncode == 0 and p.stdout.split("\n")[:3] == ["alpha  (1 open)", "beta  (%d open)" % (n - 2), "gamma  (1 open)"], p.stdout)
        p = run("rm", *[x["id"] for x in rows() if not x.get("parent")])
        check("rm", p.returncode == 0 and rows() == [], p.stderr.strip())
        extended("alpha", PROJECT)
    finally:
        after_projects, after_labels = snapshot()
        cmds = [{"type": "project_delete", "uuid": str(uuid.uuid4()), "args": {"id": pid}}
                for pid, name in after_projects.items() if name == PROJECT]
        cmds += [{"type": "label_delete", "uuid": str(uuid.uuid4()), "args": {"id": lid, "cascade": "all"}}
                 for lid in after_labels if lid not in before_labels]
        if cmds:
            r = api.call("POST", "/sync", form={"commands": json.dumps(cmds)})
            bad = [c["type"] for c in cmds if (r.get("sync_status") or {}).get(c["uuid"]) != "ok"]
            print("cleanup: deleted the project and %d label(s) this run created%s" %
                  (len(cmds) - 1, "; FAILED: " + ", ".join(bad) if bad else ""))
        final_projects, final_labels = snapshot()
        check("account restored", final_projects == before_projects and final_labels == before_labels,
              "projects %s, labels %s" % (sorted(set(final_projects.values()) ^ set(before_projects.values())),
                                          sorted(set(final_labels.values()) ^ set(before_labels.values()))))
    finish()


def finish():
    failed = [n for n, ok in results if not ok]
    print("%d/%d checks passed" % (len(results) - len(failed), len(results)))
    sys.exit(1 if failed else 0)


def section_mode(before_projects, before_labels):
    """The account-wide verbs in a throwaway section of the default project; the section goes at the end."""
    os.environ["TODOIST_PROJECT"] = HOME_PROJECT
    reload()
    area = "selftest-" + SUFFIX
    st = state.read_state()
    before_items = len(st.items)
    before_sections = set(st.sections.values())
    made = []
    try:
        made = extended(area, HOME_PROJECT)
    finally:
        st = state.read_state()
        cmds = []
        sid = st.section_id(area)
        if sid:
            cmds.append({"type": "section_delete", "uuid": str(uuid.uuid4()), "args": {"id": sid}})
        for l in st.label_rows:
            if (l.get("name") or "").lower() in [m.lower() for m in made] or (l.get("name") or "").startswith("selftest"):
                cmds.append({"type": "label_delete", "uuid": str(uuid.uuid4()), "args": {"id": l["id"], "cascade": "all"}})
        if cmds:
            r = api.call("POST", "/sync", form={"commands": json.dumps(cmds)})
            bad = [c["type"] for c in cmds if (r.get("sync_status") or {}).get(c["uuid"]) != "ok"]
            print("cleanup: deleted the section %s with its tasks and %d label(s)%s" %
                  (area, len(cmds) - bool(sid), "; FAILED: " + ", ".join(bad) if bad else ""))
        st = state.read_state()
        final_projects, final_labels = snapshot()
        check("account restored", final_projects == before_projects and final_labels == before_labels
              and set(st.sections.values()) == before_sections and len(st.items) == before_items,
              "projects %s, labels %s, sections %s, items %d -> %d" % (
                  sorted(set(final_projects.values()) ^ set(before_projects.values())),
                  sorted(set(final_labels.values()) ^ set(before_labels.values())),
                  sorted(set(st.sections.values()) ^ before_sections), before_items, len(st.items)))
    finish()


if __name__ == "__main__":
    main()
