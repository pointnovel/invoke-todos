"""comments and uploads: task and project comments, reactions, attachments (upload is here because it needs the
plan gate of state, which sits below api)."""
import sys

from invoke_todos.args import arg, sub
from invoke_todos.backends.todoist.api import call, download, new_cmd, pages, read_file, rest, write
from invoke_todos.backends.todoist.render import comment_line, is_attr_note
from invoke_todos.backends.todoist.state import (find_comment, find_project, read_state, require, resolve, resolve_user,
                                                 task_notes)
from invoke_todos.output import die, emit, need_yes, print_json
from invoke_todos.verbs import register


def upload(st, path, project_id=None):
    """POST /uploads as a raw stream (X-File-Name) -> the file_attachment object a comment carries."""
    require(st, "uploads", "an upload", "drop --file")
    blob, name, mime = read_file(path)
    cap = st.plan().get("upload_limit_mb")
    if isinstance(cap, (int, float)) and len(blob) > cap * 1024 * 1024:
        die("%s is %.1f MB; the plan's upload limit is %s MB" % (name, len(blob) / 1048576.0, cap))
    return call("POST", "/uploads", query={"project_id": project_id} if project_id else None, data=blob,
                content_type=mime, headers={"X-File-Name": name}, retry=False, timeout=300)


@register("comments")
def cmd_comments(a):
    st = read_state()
    v = sub(a)
    if v not in ("list", "add", "edit", "rm", "show", "react", "unreact", "get-file"):
        a.pos.insert(1, "list")  # todos comments <task>
        v = "list"
    if v == "list":
        if a.first("project"):
            p = find_project(st, a.first("project"))
            rows = st.project_notes.get(p["id"]) or list(pages("/comments", {"project_id": p["id"]}))
        else:
            rows = task_notes(st, resolve(st, arg(a, 2, "a task id (or --project P)"), include_done=True))
        emit(sorted(rows, key=lambda n: n.get("posted_at") or ""), a, comment_line)
        return
    if v == "add":
        if a.first("project"):
            target, text = {"project_id": find_project(st, a.first("project"))["id"]}, arg(a, 2, "the text")
        else:
            i = resolve(st, arg(a, 2, "a task id (or --project P)"), include_done=True)
            target, text = {"item_id": i.id}, arg(a, 3, "the text")
        if text == "-":
            text = sys.stdin.read()
        if not text.strip():
            die("an empty comment")
        args = dict(target, content=text.strip())
        if a.first("file"):
            args["file_attachment"] = upload(st, a.first("file"), target.get("project_id"))
        if a.first("notify"):
            args["uids_to_notify"] = [] if a.first("notify") == "none" else \
                [resolve_user(st, u.strip()) for u in a.first("notify").split(",") if u.strip()]
        c = new_cmd("note_add", args)
        print("added: comment %s" % write([[c]])[c["temp_id"]])
        return
    n = find_comment(st, arg(a, 2, "a comment id"))
    if v == "show":
        if a.has("json"):
            print_json(n, a.has("pretty"))
            return
        print(comment_line(n))
        print("")
        print(n.get("content") or "")
        return
    if v in ("edit", "rm") and is_attr_note(n) and not a.has("force"):
        die("comment %s carries the task's src and since; change them with todos edit --src/--since (--force overrides)" % n.get("id"))
    if v == "edit":
        text = arg(a, 3, "the new text")
        if text == "-":
            text = sys.stdin.read()
        write([[new_cmd("note_update", {"id": n["id"], "content": text.strip()})]])
        print("edited: comment %s" % n["id"])
        return
    if v == "rm":
        need_yes(a, ["delete comment %s: %s" % (n["id"], (n.get("content") or "").split("\n")[0][:60])], "deleting a comment")
        write([[new_cmd("note_delete", {"id": n["id"]})]])
        print("removed: comment %s" % n["id"])
        return
    if v in ("react", "unreact"):
        emoji = arg(a, 3, "an emoji")
        r = rest("POST", "/comments/%s/reactions%s" % (n["id"], "/remove" if v == "unreact" else ""), body={"reaction": emoji})
        print_json(r, True) if a.has("json") else print("%s: %s on comment %s" % (v + "ed", emoji, n["id"]))
        return
    if v == "get-file":
        fa = n.get("file_attachment") or {}
        if not fa.get("file_url"):
            die("comment %s has no attachment" % n["id"])
        download(fa["file_url"], a.first("out") or fa.get("file_name"))
        return


@register("uploads")
def cmd_uploads(a):
    st = read_state()
    v = sub(a, "add")
    if v == "add":
        pid = find_project(st, a.first("project"))["id"] if a.first("project") else None
        print_json(upload(st, arg(a, 2, "a file"), pid), True)
        return
    if v == "rm":
        url = arg(a, 2, "the file url")
        need_yes(a, ["delete the upload " + url], "deleting an upload")
        rest("DELETE", "/uploads", query={"file_url": url})
        print("removed: " + url)
        return
    die("todos uploads: add FILE [--project P] | rm URL --yes")
