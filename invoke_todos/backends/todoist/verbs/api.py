"""api: any endpoint, Sync command or Sync read of the API; writes need --yes."""
import json
import os
import sys
import uuid

from invoke_todos.args import arg
from invoke_todos.backends.todoist.api import call, multipart, new_cmd, pages, read_file, write
from invoke_todos.config import cfg
from invoke_todos.output import die, need_yes, print_json, redact
from invoke_todos.verbs import register


DESTRUCTIVE_COMMANDS = ("_delete", "_leave", "delete_collaborator", "label_delete_occurrences", "clear_locations",
                        "workspace_delete_user", "user_update", "_archive")


@register("api")
def cmd_api(a):
    """api GET|POST|PUT|DELETE /path [--q k=v]... [--body JSON|@file|-] [--form k=v]... [--file field=@path]...
    api sync COMMAND --args JSON | --commands @file.json; api read TYPE[,TYPE...]. Writes need --yes."""
    what = (a.pos[1] if len(a.pos) > 1 else "").lower()
    if what == "read":
        types = [t.strip() for t in arg(a, 2, "resource types (comma-separated, or all)").split(",") if t.strip()]
        r = call("POST", "/sync", form={"sync_token": "*", "resource_types": json.dumps(types)})
        print_json(redact(r), a.has("pretty"))
        return
    if what == "sync":
        if a.first("commands"):
            spec = a.first("commands")
            text = sys.stdin.read() if spec == "-" else read_file(spec[1:] if spec.startswith("@") else spec)[0].decode("utf-8")
            rows = json.loads(text)
            if not isinstance(rows, list):
                die("--commands needs a JSON array of {type, args[, temp_id]}")
            cmds = []
            for x in rows:
                c = new_cmd(x["type"], x.get("args") or {})
                if x.get("temp_id"):
                    c["temp_id"] = x["temp_id"]
                cmds.append(c)
        else:
            kind = arg(a, 2, "a command type, e.g. item_update")
            try:
                args = json.loads(a.first("args") or "{}")
            except ValueError as e:
                die("--args must be JSON: %s" % e)
            c = new_cmd(kind, args)
            if a.has("temp-id") and "temp_id" not in c:
                c["temp_id"] = str(uuid.uuid4())
            cmds = [c]
        if a.has("dry"):
            print_json(cmds, True)
            return
        need_yes(a, ["send %s %s" % (c["type"], json.dumps(c["args"], ensure_ascii=False)) for c in cmds], "a sync command")
        mapping = write([[c] for c in cmds])
        print_json({"ok": len(cmds), "temp_id_mapping": mapping}, a.has("pretty"))
        return
    method = what.upper()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        die("todos api GET|POST|PUT|DELETE /path ... | api sync COMMAND --args JSON | api read TYPES")
    path = arg(a, 2, "a path under %s, e.g. /projects" % cfg.api_base)
    if "://" in path or not path.startswith("/"):
        die("the path is relative to %s and starts with /" % cfg.api_base)
    query = {}
    for kv in a.all("q"):
        if "=" not in kv:
            die("--q needs key=value")
        k, v = kv.split("=", 1)
        query.setdefault(k, []).append(v)
    query = {k: (v[0] if len(v) == 1 else v) for k, v in query.items()}
    body = data = ctype = form = None
    if a.first("body") is not None:
        spec = a.first("body")
        text = sys.stdin.read() if spec == "-" else read_file(spec[1:])[0].decode("utf-8") if spec.startswith("@") else spec
        try:
            body = json.loads(text)
        except ValueError as e:
            die("--body must be JSON (or @file, or - for stdin): %s" % e)
    files = []
    for spec in a.all("file"):
        if "=@" not in spec:
            die("--file needs field=@path")
        field, fpath = spec.split("=@", 1)
        blob, name, mime = read_file(fpath)
        files.append((field, name, blob, mime))
    if a.all("form") or files:
        form = {}
        for kv in a.all("form"):
            if "=" not in kv:
                die("--form needs key=value")
            k, v = kv.split("=", 1)
            form[k] = v
        if files:
            data, ctype = multipart(form, files)
            form = None
    if method != "GET":
        need_yes(a, ["%s %s%s" % (method, path, " " + json.dumps(body, ensure_ascii=False) if body is not None else "")], "a write through api")
    if a.has("all-pages") and method == "GET":
        rows = list(pages(path, query, max_pages=int(a.first("max")) if a.first("max") else None))
        print_json(redact(rows), a.has("pretty"))
        return
    r = call(method, path, query=query or None, form=form, body=body, data=data, content_type=ctype,
             raw=a.has("raw"), retry=(method == "GET"), timeout=300 if data else None)
    if a.first("out"):
        with open(os.path.expanduser(a.first("out")), "wb") as f:
            f.write(r if isinstance(r, bytes) else (r if isinstance(r, str) else json.dumps(redact(r), ensure_ascii=False, indent=2)).encode("utf-8"))
        print("wrote " + a.first("out"))
    elif isinstance(r, bytes):
        sys.stdout.buffer.write(r)
    elif isinstance(r, str):
        print(r)
    else:
        print_json(redact(r), a.has("pretty"))
