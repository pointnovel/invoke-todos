"""projects, people and share: the account's projects and the people they are shared with."""
from invoke_todos.args import arg, favorite_flag, onoff, picked, read_text, sub
from invoke_todos.backends.todoist.api import new_cmd, pages, rest, write
from invoke_todos.backends.todoist.flags import color_flag
from invoke_todos.backends.todoist.render import project_line
from invoke_todos.backends.todoist.state import find_project, open_in, project_count, read_state, resolve_user, user_id, within
from invoke_todos.output import die, emit, need_yes, print_json
from invoke_todos.query import sort_items
from invoke_todos.render import line
from invoke_todos.verbs import register


@register("projects")
def cmd_projects(a):
    st = read_state()
    v = sub(a)
    if v == "list":
        rows = st.projects if a.has("all") else [p for p in st.projects if bool(p.get("is_archived")) == a.has("archived")]
        if a.first("grep"):
            rows = [p for p in rows if a.first("grep").lower() in (p.get("name") or "").lower()]
        if a.first("workspace"):
            rows = [p for p in rows if str(p.get("workspace_id")) == a.first("workspace")]
        rows = sorted(rows, key=lambda p: (p.get("child_order") or 0, (p.get("name") or "").lower()))
        emit(rows, a, lambda p: project_line(st, p))
        return
    if v == "roles":
        print_json(rest("GET", "/projects/permissions"), True)
        return
    if v == "search":
        emit(list(pages("/projects/search", {"query": arg(a, 2, "a query")})), a, lambda p: "%s %s" % (p.get("id"), p.get("name")))
        return
    if v == "add":
        name = arg(a, 2, "a name")
        if any((p.get("name") or "").lower() == name.lower() for p in st.projects if not p.get("is_archived")):
            die('project "%s" exists' % name)
        within(st, "max_projects", project_count(st), "a new project")
        args = picked((("name", name), ("color", color_flag(a)), ("is_favorite", favorite_flag(a)), ("view_style", a.first("view")),
                       ("description", read_text(a, "description")), ("workspace_id", a.first("workspace")), ("folder_id", a.first("folder"))))
        if a.first("parent"):
            args["parent_id"] = find_project(st, a.first("parent"))["id"]
        c = new_cmd("project_add", args)
        pid = write([[c]])[c["temp_id"]]
        print("added: %s %s" % (pid, name))
        return
    if v == "order":
        rows = [find_project(st, r) for r in a.pos[2:]]
        if len(rows) < 2:
            die("todos projects order P1 P2 ... (the new order of sibling projects)")
        write([[new_cmd("project_reorder", {"projects": [{"id": x["id"], "child_order": n + 1} for n, x in enumerate(rows)]})]])
        print("reordered: " + ", ".join(x.get("name") or "" for x in rows))
        return
    if v in ("people", "collaborators"):
        a.pos = [a.pos[0]] + a.pos[2:]
        return cmd_people(a)
    p = find_project(st, arg(a, 2, "a project"), archived=v in ("show", "unarchive", "rm"))
    n_open = open_in(st, "project_id", p["id"])
    if v == "show":
        if a.has("json"):
            print_json(p, a.has("pretty"))
            return
        print(project_line(st, p))
        for k in ("description", "color", "view_style", "created_at", "updated_at", "collaborator_role_default"):
            if p.get(k):
                print("%s: %s" % (k, p[k]))
        secs = [x for x in st.all_sections.values() if x.get("project_id") == p["id"] and not x.get("is_archived")]
        for x in sorted(secs, key=lambda x: x.get("section_order") or 0):
            print("  section %s %s  (%d open)" % (x["id"], x.get("name"), open_in(st, "section_id", x["id"])))
        if a.has("tasks"):
            for i in sort_items([i for i in st.all_items if i.raw.get("project_id") == p["id"]], "area"):
                print(line(i, indent=True))
        return
    if v == "edit":
        args = picked((("name", a.first("name")), ("color", color_flag(a)), ("is_favorite", favorite_flag(a)),
                       ("view_style", a.first("view")), ("description", read_text(a, "description")), ("is_collapsed", onoff(a, "collapsed"))))
        if a.has("clear-description"):
            args["description"] = ""
        groups = []
        if args:
            groups.append([new_cmd("project_update", dict(args, id=p["id"]))])
        if a.first("parent") or a.has("root"):
            parent = None if a.has("root") else find_project(st, a.first("parent"))["id"]
            groups.append([new_cmd("project_move", {"id": p["id"], "parent_id": parent})])
        if not groups:
            die("nothing to change: --name, --color, --description, --clear-description, --favorite, --no-favorite, --view, --collapsed, --parent, --root")
        write(groups)
        print("edited: %s %s" % (p["id"], args.get("name") or p.get("name")))
        return
    if v in ("archive", "unarchive"):
        if v == "archive":
            need_yes(a, ["archive %s (%d open tasks go with it)" % (p.get("name"), n_open)], "archiving a project")
        write([[new_cmd("project_" + v, {"id": p["id"]})]])
        print("%sd: %s %s" % (v, p["id"], p.get("name")))
        return
    if v == "rm":
        need_yes(a, ["delete project %s with its sections, %d open tasks and the completed ones" % (p.get("name"), n_open)],
                 "deleting a project")
        write([[new_cmd("project_delete", {"id": p["id"]})]])
        print("removed: %s %s" % (p["id"], p.get("name")))
        return
    if v == "leave":
        need_yes(a, ["leave the shared project %s" % p.get("name")], "leaving a project")
        write([[new_cmd("project_leave", {"project_id": p["id"]})]])
        print("left: " + (p.get("name") or ""))
        return
    if v == "join":
        print_json(rest("POST", "/projects/%s/join" % p["id"]), True)
        return
    if v == "move":
        if a.first("workspace"):
            args = picked((("project_id", p["id"]), ("workspace_id", a.first("workspace")), ("folder_id", a.first("folder"))))
            if a.first("visibility"):
                args["is_invite_only"] = a.first("visibility") == "restricted"
            need_yes(a, ["move %s into workspace %s" % (p.get("name"), a.first("workspace"))], "moving a project")
            write([[new_cmd("project_move_to_workspace", args)]])
        elif a.has("personal"):
            need_yes(a, ["move %s out of its workspace" % p.get("name")], "moving a project")
            write([[new_cmd("project_move_to_personal", {"project_id": p["id"]})]])
        else:
            die("todos projects move P --workspace W [--folder F] [--visibility restricted|team|public] | --personal")
        print("moved: %s %s" % (p["id"], p.get("name")))
        return
    if v == "health":  # the connector's insight endpoints; not in the public docs, workspace projects only
        path = "/projects/%s/insights/health" % p["id"]
        if a.has("analyze"):
            need_yes(a, ["start a health analysis of %s" % p.get("name")], "starting an analysis")
            print_json(rest("POST", path + "/analyze"), True)
            return
        print_json(rest("GET", path + ("/context" if a.has("context") else "")), True)
        return
    if v == "insights":
        print_json(rest("GET", "/projects/%s/insights/activity_stats" % p["id"], query={"weeks": a.first("weeks") or "2"}), True)
        return
    die("todos projects: list|show|add|edit|archive|unarchive|rm|move|order|people|roles|search|health|insights|leave|join")


@register("people")
def cmd_people(a):
    """people [PROJECT] [--grep T]: collaborators of the shared projects (or of one)."""
    st = read_state()
    rows = st.collaborators
    if len(a.pos) > 1:
        p = find_project(st, a.pos[1])
        allowed = {c.get("user_id") for c in st.collaborator_states if c.get("project_id") == p["id"]}
        rows = [c for c in rows if c.get("id") in allowed]
        if not rows:
            rows = list(pages("/projects/%s/collaborators" % p["id"]))
    if a.first("grep"):
        g = a.first("grep").lower()
        rows = [c for c in rows if g in (c.get("full_name") or "").lower() or g in (c.get("email") or "").lower()]
    emit(rows, a, lambda c: "%s %s <%s>%s" % (c.get("id"), c.get("full_name"), c.get("email"),
                                                "  (me)" if str(c.get("id")) == user_id(st) else ""))


@register("share")
def cmd_share(a):
    st = read_state()
    v = sub(a)
    if v == "list":
        a.pos = [a.pos[0]] + a.pos[2:]
        return cmd_people(a)
    if v in ("accept", "reject"):
        ref = arg(a, 2, "a notification id")
        n = next((x for x in st.notifications if str(x.get("id")) == ref), None)
        if not n or not n.get("invitation_id"):
            die("no share invitation in notification %s (todos notifications lists them)" % ref)
        write([[new_cmd(v + "_invitation", {"invitation_id": n["invitation_id"], "invitation_secret": n.get("invitation_secret")})]])
        print("%sed invitation %s" % (v, n["invitation_id"]))
        return
    if v == "uninvite":
        write([[new_cmd("delete_invitation", {"invitation_id": arg(a, 2, "an invitation id")})]])
        print("invitation withdrawn")
        return
    p = find_project(st, arg(a, 2, "a project"))
    if v == "add":
        email = arg(a, 3, "an email")
        within(st, "max_collaborators", len([c for c in st.collaborator_states if c.get("project_id") == p["id"]]), "another collaborator")
        need_yes(a, ["invite %s to %s (Todoist emails them)" % (email, p.get("name"))], "sharing a project")
        args = picked((("project_id", p["id"]), ("email", email), ("role", a.first("role"))))
        write([[new_cmd("share_project", args)]])
        print("invited: %s to %s" % (email, p.get("name")))
        return
    if v == "rm":
        email = arg(a, 3, "an email")
        need_yes(a, ["remove %s from %s" % (email, p.get("name"))], "removing a collaborator")
        write([[new_cmd("delete_collaborator", {"project_id": p["id"], "email": email})]])
        print("removed: %s from %s" % (email, p.get("name")))
        return
    if v == "role":
        uid, role = resolve_user(st, arg(a, 3, "a user"), p["id"]), arg(a, 4, "a role (CREATOR|ADMIN|READ_WRITE|EDIT_ONLY|COMPLETE_ONLY)")
        write([[new_cmd("project_change_role", {"id": p["id"], "user_id": uid, "role": role.upper()})]])
        print("role: %s is %s in %s" % (uid, role.upper(), p.get("name")))
        return
    die("todos share: list P | add P EMAIL [--role R] --yes | rm P EMAIL --yes | role P USER ROLE | accept N | reject N | uninvite ID")
