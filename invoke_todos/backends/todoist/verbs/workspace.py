"""templates, backups, emails, folders, workspaces, ids and billing: the rest of the account."""
import json
import os
import sys
import urllib.parse

from invoke_todos.args import arg, onoff, picked, read_text, sub
from invoke_todos.backends.todoist.api import call, multipart, new_cmd, pages, read_file, rest, rows_of, write
from invoke_todos.backends.todoist.state import find_project, project_count, read_state, require, resolve, within
from invoke_todos.config import cfg
from invoke_todos.output import die, emit, err, need_yes, print_json, redact
from invoke_todos.verbs import register


@register("templates")
def cmd_templates(a):
    st = read_state()
    v = sub(a, "export")
    if v in ("export", "url"):
        p = find_project(st, arg(a, 2, "a project"))
        q = {"project_id": p["id"]}
        if a.has("relative"):
            q["use_relative_dates"] = "true"
        require(st, "templates", "templates " + v, "export the house view instead (todos export)")
        if v == "url":
            r = rest("GET", "/templates/url", query=q)
            print(r.get("file_url") if isinstance(r, dict) and r.get("file_url") else json.dumps(r))
            return
        csv = call("GET", "/templates/file", query=q, raw=True)
        if a.first("out"):
            with open(os.path.expanduser(a.first("out")), "wb") as f:
                f.write(csv)
            print("wrote %s: %d bytes" % (a.first("out"), len(csv)))
        else:
            sys.stdout.buffer.write(csv)
        return
    if v == "import":
        p = find_project(st, arg(a, 2, "a project"))
        require(st, "templates", "templates import")
        if a.first("id"):
            need_yes(a, ["import template %s into %s (cannot be undone)" % (a.first("id"), p.get("name"))], "importing a template")
            r = rest("POST", "/templates/import_into_project_from_template_id",
                     body=picked((("project_id", p["id"]), ("template_id", a.first("id")), ("locale", a.first("locale")))))
        elif a.first("file"):
            blob, name, _ = read_file(a.first("file"))
            need_yes(a, ["import %s (%d bytes) into %s (cannot be undone)" % (name, len(blob), p.get("name"))], "importing a template")
            data, ctype = multipart({"project_id": p["id"]}, [("file", name, blob, "text/csv")])
            r = call("POST", "/templates/import_into_project_from_file", data=data, content_type=ctype, retry=False, timeout=300)
        else:
            die("todos templates import PROJECT (--id TEMPLATE | --file F.csv) [--locale L] --yes")
        print_json(r, True) if a.has("json") else print("imported into " + (p.get("name") or ""))
        return
    if v == "new":
        name = arg(a, 2, "a project name")
        if not a.first("file"):
            die("todos templates new NAME --file F.csv [--workspace W] --yes")
        require(st, "templates", "templates new")
        within(st, "max_projects", project_count(st), "a new project")
        blob, fname, _ = read_file(a.first("file"))
        need_yes(a, ["create project %s from %s (%d bytes)" % (name, fname, len(blob))], "creating a project from a template")
        fields = picked((("name", name), ("workspace_id", a.first("workspace"))))
        data, ctype = multipart(fields, [("file", fname, blob, "text/csv")])
        r = call("POST", "/templates/create_project_from_file", data=data, content_type=ctype, retry=False, timeout=300)
        print_json(r, True) if a.has("json") else print("created project %s" % name)
        return
    die("todos templates: export P [--relative] [--out F.csv] | url P [--relative] | import P (--id T | --file F) --yes | new NAME --file F --yes")


@register("backups")
def cmd_backups(a):
    st = read_state()
    v = sub(a)
    if v == "list":
        rows = rows_of(rest("GET", "/backups", query={"mfa_token": a.first("mfa")} if a.first("mfa") else None))
        emit(rows, a, lambda b: "%s %s" % (b.get("version"), b.get("url")))
        if not rows and st.plan().get("automatic_backups") is False:
            err("no backups; plan %s lists automatic_backups off" % st.plan().get("plan_name"))
        return
    if v == "get":
        if a.has("latest"):
            rows = rows_of(rest("GET", "/backups", query={"mfa_token": a.first("mfa")} if a.first("mfa") else None))
            if not rows:
                die("no backups")
            url = sorted(rows, key=lambda b: b.get("version") or "")[-1].get("url")
        else:
            url = arg(a, 2, "a backup url (todos backups list) or --latest")
        q = {"file": url}
        if url.startswith(cfg.api_base + "/backups/download"):  # the listed url already names the file
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        blob = call("GET", "/backups/download", query=q, raw=True)
        out = os.path.expanduser(a.first("out") or (os.path.basename(urllib.parse.urlparse(url).path) or "todoist-backup.zip"))
        with open(out, "wb") as f:
            f.write(blob)
        print("wrote %s: %d bytes" % (out, len(blob)))
        return
    die("todos backups: list [--mfa CODE] | get URL|--latest [--out PATH]")


def email_target(st, a):
    if a.first("task"):
        return {"obj_type": "item", "obj_id": resolve(st, a.first("task")).id}
    if a.first("project"):
        return {"obj_type": "project", "obj_id": find_project(st, a.first("project"))["id"]}
    die("todos emails get|off (--task ID | --project P)")


@register("emails")
def cmd_emails(a):
    st = read_state()
    v = sub(a, "get")
    t = email_target(st, a)
    if v == "get":
        require(st, "email_forwarding", "emails get")
        r = rest("PUT", "/emails", body=t)
        print_json(r, True) if a.has("json") else print((r.get("email") if isinstance(r, dict) else None) or json.dumps(r))
        return
    if v == "off":
        need_yes(a, ["disable the forwarding address of %s %s" % (t["obj_type"], t["obj_id"])], "disabling an address")
        rest("DELETE", "/emails", query=t)
        print("disabled")
        return
    die("todos emails: get|off (--task ID | --project P)")


@register("folders")
def cmd_folders(a):
    v = sub(a)
    ws = a.first("workspace")
    if v == "list":
        if not ws:
            die("todos folders list --workspace W")
        emit(list(pages("/folders", {"workspace_id": ws})), a, lambda f: "%s %s" % (f.get("id"), f.get("name")))
        return
    if v == "add":
        name = arg(a, 2, "a name")
        if not ws:
            die("todos folders add NAME --workspace W [--projects a,b]")
        args = {"name": name, "workspace_id": ws}
        if a.first("projects"):
            args["add_project_ids"] = a.first("projects").split(",")
        c = new_cmd("folder_add", args)
        print("added: folder %s %s" % (write([[c]])[c["temp_id"]], name))
        return
    fid = arg(a, 2, "a folder id")
    if v == "show":
        print_json(rest("GET", "/folders/%s" % fid), True)
        return
    if v == "edit":
        if not ws:
            die("todos folders edit ID --workspace W [--name N] [--add a,b] [--remove a,b]")
        args = picked((("id", fid), ("workspace_id", ws), ("name", a.first("name"))))
        if a.first("add"):
            args["add_project_ids"] = a.first("add").split(",")
        if a.first("remove"):
            args["remove_project_ids"] = a.first("remove").split(",")
        write([[new_cmd("folder_update", args)]])
        print("edited: folder " + fid)
        return
    if v == "rm":
        need_yes(a, ["delete folder %s (its projects stay)" % fid], "deleting a folder")
        rest("DELETE", "/folders/%s" % fid)
        print("removed: folder " + fid)
        return
    die("todos folders: list --workspace W | show ID | add NAME --workspace W | edit ID --workspace W ... | rm ID --yes")


@register("workspaces")
def cmd_workspaces(a):
    v = sub(a)
    if v == "list":
        emit(rows_of(rest("GET", "/workspaces")), a, lambda w: "%s %s  plan:%s role:%s" % (
            w.get("id"), w.get("name"), w.get("plan"), w.get("role")))
        return
    if v == "add":
        st = read_state()
        within(st, "max_free_workspaces_created", 0, "a new workspace") if st.plan().get("max_free_workspaces_created") == 0 else None
        args = picked((("name", arg(a, 2, "a name")), ("description", read_text(a, "description"))))
        c = new_cmd("workspace_add", args)
        print("added: workspace %s %s" % (write([[c]])[c["temp_id"]], args["name"]))
        return
    if v == "join":
        body = picked((("invite_code", a.first("code")), ("workspace_id", a.first("id"))))
        if not body:
            die("todos workspaces join --code CODE | --id W")
        print_json(rest("POST", "/workspaces/join", body=body), True)
        return
    if v in ("accept", "reject"):
        print_json(rest("PUT", "/workspaces/invitations/%s/%s" % (arg(a, 2, "an invite code"), v)), True)
        return
    w = arg(a, 2, "a workspace id")
    if v == "show":
        print_json(redact(rest("GET", "/workspaces/%s" % w)), True)
    elif v == "plan":
        print_json(rest("GET", "/workspaces/plan_details", query={"workspace_id": w}), True)
    elif v == "users":
        emit(list(pages("/workspaces/users", {"workspace_id": w})), a, lambda u: "%s %s <%s> %s" % (
            u.get("user_id") or u.get("id"), u.get("full_name"), u.get("user_email") or u.get("email"), u.get("role")))
    elif v == "projects":
        emit(list(pages("/workspaces/%s/projects/%s" % (w, "archived" if a.has("archived") else "active"))), a,
             lambda p: "%s %s" % (p.get("id"), p.get("name")))
    elif v == "insights":
        q = {"project_ids": a.first("projects").split(",")} if a.first("projects") else None
        print_json(rest("GET", "/workspaces/%s/insights" % w, query=q), True)
    elif v == "invitations":
        print_json(rest("GET", "/workspaces/invitations" + ("/all" if a.has("all") else ""), query={"workspace_id": w}), True)
    elif v == "edit":
        args = picked((("id", w), ("name", a.first("name")), ("description", read_text(a, "description"))))
        for flag, key in (("link-sharing", "is_link_sharing_enabled"), ("guests", "is_guest_allowed")):
            if a.first(flag) is not None:
                args[key] = onoff(a, flag)
        if len(args) < 2:
            die("nothing to change: --name, --description, --link-sharing on|off, --guests on|off")
        write([[new_cmd("workspace_update", args)]])
        print("edited: workspace " + w)
    elif v == "rm":
        need_yes(a, ["delete workspace %s and everything in it" % w], "deleting a workspace")
        write([[new_cmd("workspace_delete", {"id": w})]])
        print("removed: workspace " + w)
    elif v == "leave":
        need_yes(a, ["leave workspace %s" % w], "leaving a workspace")
        write([[new_cmd("workspace_leave", {"id": w})]])
        print("left: workspace " + w)
    elif v == "invite":
        emails = a.pos[3:] or die("todos workspaces invite W EMAIL... [--role R] --yes")
        need_yes(a, ["invite %s to workspace %s (Todoist emails them)" % (", ".join(emails), w)], "inviting users")
        write([[new_cmd("workspace_invite", picked((("id", w), ("email_list", emails), ("role", a.first("role")))))]])
        print("invited: " + ", ".join(emails))
    elif v == "reinvite":
        write([[new_cmd("workspace_resend_invite", {"id": w, "email": arg(a, 3, "an email")})]])
        print("invitation resent")
    elif v == "uninvite":
        print_json(rest("POST", "/workspaces/invitations/delete", body={"workspace_id": w, "user_email": arg(a, 3, "an email")}), True)
    elif v == "role":
        write([[new_cmd("workspace_update_user", {"id": w, "user_email": arg(a, 3, "an email"), "role": arg(a, 4, "GUEST|MEMBER|ADMIN").upper()})]])
        print("role changed")
    elif v == "kick":
        email = arg(a, 3, "an email")
        need_yes(a, ["remove %s from workspace %s" % (email, w)], "removing a member")
        write([[new_cmd("workspace_delete_user", {"id": w, "user_email": email})]])
        print("removed: " + email)
    elif v == "sidebar":
        write([[new_cmd("workspace_update_user_sidebar_preference", {"workspace_id": w, "sidebar_preference": arg(a, 3, "MANUAL|A_TO_Z|Z_TO_A").upper()})]])
        print("sidebar preference set")
    elif v == "logo":
        if a.has("delete"):
            data, ctype = multipart({"workspace_id": w, "delete": "true"}, [])
        else:
            blob, name, mime = read_file(arg(a, 3, "an image file (or --delete)"))
            data, ctype = multipart({"workspace_id": w}, [("file", name, blob, mime)])
        print_json(redact(rest("POST", "/workspaces/logo", data=data, content_type=ctype, timeout=300)), True)
    elif v == "order":
        blob, _, _ = read_file(a.first("file") or die("todos workspaces order W --file ordering.json ({projects: [...], folders: [...]})"))
        spec = json.loads(blob.decode("utf-8"))
        write([[new_cmd("workspace_set_default_project_ordering", {"workspace_id": w, "projects": spec.get("projects") or [],
                                                                    "folders": spec.get("folders") or []})]])
        print("ordering set")
    else:
        die("todos workspaces: list|show|plan|users|projects|insights|invitations|add|edit|rm|leave|invite|reinvite|uninvite|"
            "accept|reject|join|role|kick|sidebar|logo|order")


@register("ids")
def cmd_ids(a):
    """ids map TYPE ID[,ID...]: translate ids between the API's v1 and v2 forms."""
    if sub(a, "map") != "map":
        die("todos ids map TYPE ID,...")
    print_json(rest("GET", "/id_mappings/%s/%s" % (arg(a, 2, "an object type (items, projects, ...)"), arg(a, 3, "ids"))), True)


@register("billing")
def cmd_billing(a):
    v = sub(a, "state")
    paths = {"state": ("GET", "/usage_billing/state"), "usage": ("GET", "/usage_billing/usage_summary"),
             "history": ("GET", "/usage_billing/history"), "subscription": ("POST", "/payments/get_subscription_info")}
    if v not in paths:
        die("todos billing: state|usage|history|subscription (read-only; top-ups and cancellations only through todos api)")
    method, path = paths[v]
    print_json(redact(rest(method, path, retry=True)), True)
