"""One Sync read of the account (State), the cache that keeps it incremental, the completed-tasks endpoint, the
plan gates, and the resolvers and lookups over the account's objects."""
import hashlib
import json
import os
import re
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from invoke_todos.backends.todoist.api import call, new_cmd, pages, write
from invoke_todos.backends.todoist.auth import token
from invoke_todos.backends.todoist.items import Item
from invoke_todos.config import cfg
from invoke_todos.dates import NEAR, now, utc
from invoke_todos.model import assign_short_ids, descendants, link_tree, reserved_label, uniq
from invoke_todos.output import SECRET_KEYS, die, err


DONE_WINDOW_DAYS = 89  # the completed-tasks endpoint takes ranges of up to 3 months
# A markdown link at the start of a reference, as --links prints a task: its text (brackets may nest once) and
# its link (up to the closing parenthesis that ends the word); anything after it, such as a title, is ignored.
MD_LINK = re.compile(r"^\[((?:[^\[\]]|\[[^\]]*\])*)\]\((\S+?)\)(?=\s|$)")
TASK_TEXT = re.compile(r"^task#([A-Za-z0-9]+)$", re.IGNORECASE)


class State(object):
    """One Sync read of the account; the task view is narrowed to PROJECT, the rest is account-wide."""

    def __init__(self, data):
        self.data = data
        self.projects = [p for p in data.get("projects") or [] if not p.get("is_deleted")]
        active = [p for p in self.projects if not p.get("is_archived")]
        want = cfg.project or ""
        mine = ([p for p in active if p.get("name") == want] or [p for p in active if p.get("id") == want]
                or [p for p in active if (p.get("name") or "").lower() == want.lower()]) if want else []
        self.project_id = mine[0]["id"] if mine else None
        if mine and mine[0].get("name"):
            cfg.project = mine[0]["name"]
        self.project_names = {p["id"]: p.get("name") or "" for p in self.projects}
        self.all_sections = {s["id"]: s for s in data.get("sections") or [] if not s.get("is_deleted")}
        names = {sid: s.get("name") or "" for sid, s in self.all_sections.items()}
        self.sections = {sid: names[sid] for sid, s in self.all_sections.items()
                         if self.project_id and s.get("project_id") == self.project_id and not s.get("is_archived")}
        self.label_rows = [l for l in data.get("labels") or [] if not l.get("is_deleted")]
        self.labels = {(l.get("name") or "").lower() for l in self.label_rows}
        self.notes = {}
        for n in data.get("notes") or []:
            if not n.get("is_deleted"):
                self.notes.setdefault(n.get("item_id"), []).append(n)
        self.project_notes = {}
        for n in data.get("project_notes") or []:
            if not n.get("is_deleted"):
                self.project_notes.setdefault(n.get("project_id"), []).append(n)
        self.filters = [f for f in data.get("filters") or [] if not f.get("is_deleted")]
        self.reminders = [r for r in data.get("reminders") or [] if not r.get("is_deleted")]
        self.collaborators = [c for c in data.get("collaborators") or [] if not c.get("is_deleted")]
        self.collaborator_states = [c for c in data.get("collaborator_states") or [] if not c.get("is_deleted")]
        self.notifications = list(data.get("live_notifications") or [])
        self.user = data.get("user") or {}
        self.settings = data.get("user_settings") or {}
        self.locations = data.get("locations") or []
        self.all_items = [Item(i, names, self.notes.get(i.get("id"), [])) for i in data.get("items") or []
                          if not i.get("checked") and not i.get("is_deleted")]
        for i in self.all_items:
            i.project = self.project_names.get(i.raw.get("project_id"))
        self.items = [i for i in self.all_items if self.project_id and i.raw.get("project_id") == self.project_id]
        assign_short_ids(self.all_items)
        assign_short_ids(self.items)  # the project's tasks keep the shorter, project-scoped prefix
        link_tree(self.all_items)

    def section_id(self, area):
        for sid, name in self.sections.items():
            if name.lower() == (area or "").lower():
                return sid
        return None

    def plan(self):
        return (self.data.get("user_plan_limits") or {}).get("current") or {}

    def project_row(self, pid):
        return next((p for p in self.projects if p["id"] == pid), None)


LISTS = ("projects", "sections", "labels", "items", "notes", "project_notes", "filters", "reminders",
         "collaborators", "collaborator_states", "live_notifications")
SINGLES = ("user", "user_settings", "user_plan_limits", "locations", "live_notifications_last_read_id")
RESOURCES = json.dumps(list(LISTS) + ["reminders_location", "user", "user_settings", "user_plan_limits", "locations"])
CACHE_VERSION = 2  # bumped when LISTS or SINGLES change: an old cache is replaced by a full sync


def cache_path():
    d = cfg.cache_dir  # paths.cache_dir, TODOIST_CACHE; None when the cache is off
    if not d:
        return None
    key = hashlib.sha256((cfg.api_base + "\n" + token()).encode()).hexdigest()[:16]  # one file per account and API
    return os.path.join(d, "state-%s.json" % key)


def obj_key(kind, obj):
    if kind == "collaborator_states":
        return "%s:%s" % (obj.get("project_id"), obj.get("user_id"))
    return obj.get("id")


def drop_secrets(obj):
    """A copy without the secret-named keys, at every depth (the user's urgent_reminder_device has a device_token)."""
    if isinstance(obj, dict):
        return {k: drop_secrets(v) for k, v in obj.items() if k not in SECRET_KEYS}
    if isinstance(obj, list):
        return [drop_secrets(x) for x in obj]
    return obj


def merge(cache, resp):
    if resp.get("full_sync"):
        cache["res"] = {k: {} for k in LISTS}
        cache["single"] = {}
    for k in LISTS:
        rows = list(resp.get(k) or [])
        if k == "reminders":
            rows += list(resp.get("reminders_location") or [])
        for obj in rows:
            if obj.get("is_deleted") or (k == "items" and obj.get("checked")):
                cache["res"][k].pop(obj_key(k, obj), None)
            else:
                cache["res"][k][obj_key(k, obj)] = obj
    for k in SINGLES:
        if resp.get(k) is not None:
            cache["single"][k] = resp[k]
    # The Sync user object carries the account's API token, and a second token in its websocket_url; neither
    # reaches the cache file, at any depth of the object (a cache written before this rule loses them the next
    # time a read opens that file; a file under another cache folder or another token is never opened).
    user = cache["single"].get("user")
    if isinstance(user, dict):
        cache["single"]["user"] = drop_secrets(user)
    # Observed live (2026-09-29): the incremental sync carries a deleted project but not its sections, tasks
    # and comments, which would linger in the cache as ghosts; drop what hangs off a project no longer here.
    projects = set(cache["res"]["projects"])
    gone = set()
    for k in ("sections", "items", "project_notes", "collaborator_states"):
        for key, obj in list(cache["res"][k].items()):
            if obj.get("project_id") not in projects:
                if k == "items":
                    gone.add(key)
                del cache["res"][k][key]
    if gone:
        for k in ("notes", "reminders"):
            for key, obj in list(cache["res"][k].items()):
                if obj.get("item_id") in gone:
                    del cache["res"][k][key]
    cache["sync_token"] = resp.get("sync_token") or cache["sync_token"]


def read_state():
    """The account as of now: the cached copy brought up to date by one incremental sync. Without a cache
    (or with --fresh) a full sync, followed at once by an incremental one, because a full sync can lag
    behind the latest writes (the API docs' "full sync data delay")."""
    path = cache_path()
    cache = None
    if path and not cfg.fresh:
        try:
            with open(path, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("version") != CACHE_VERSION or not cache.get("sync_token"):
                cache = None
        except (OSError, ValueError):
            cache = None
    if cache is None:
        cache = {"version": CACHE_VERSION, "sync_token": "*", "res": {k: {} for k in LISTS}, "single": {}}
    for _ in range(2):
        resp = call("POST", "/sync", form={"sync_token": cache["sync_token"], "resource_types": RESOURCES})
        merge(cache, resp)
        if not resp.get("full_sync"):
            break
    if path:
        try:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            tmp = "%s.%d.tmp" % (path, os.getpid())
            with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
                json.dump(cache, f)
            os.replace(tmp, path)
        except OSError as e:
            err("warning: cannot write the cache %s: %s" % (path, e))
    data = {k: list(cache["res"][k].values()) for k in LISTS}
    data.update(cache.get("single") or {})
    return State(data)


def fetch_done(st, since, until=None, by="completion", everywhere=False):
    """Completed tasks of the project (or of the account with `everywhere`), completed (or due, `by="due"`)
    in [since, until), paged by cursor, in windows the endpoints accept (3 months, 6 weeks)."""
    if not st.project_id and not everywhere:
        return []
    until = until or now() + timedelta(minutes=1)
    window = DONE_WINDOW_DAYS if by == "completion" else 41
    names = {sid: sec.get("name") or "" for sid, sec in st.all_sections.items()}
    out, start = [], since
    while start < until:
        end = min(until, start + timedelta(days=window))
        cursor = None
        while True:
            q = {"since": utc(start), "until": utc(end)}
            if not everywhere:
                q["project_id"] = st.project_id
            if cursor:
                q["cursor"] = cursor
            r = call("GET", "/tasks/completed/by_%s_date" % by, query=q)
            for raw in r.get("items") or []:
                it = Item(raw, names, st.notes.get(raw.get("id"), []))
                it.done, it.project = True, st.project_names.get(raw.get("project_id"))
                out.append(it)
            cursor = r.get("next_cursor")
            if not cursor:
                break
        start = end
    return out


def ensure(st, areas=(), labels=()):
    """Create the project, the sections for `areas` and the personal labels that are missing."""
    if not st.project_id:
        if cfg.in_project:
            die('no Todoist project "%s" (todos projects lists them; todos projects add creates one)' % cfg.project)
        within(st, "max_projects", project_count(st), "a new project")
        c = new_cmd("project_add", {"name": cfg.project})
        st.project_id = write([[c]])[c["temp_id"]]
        err('created Todoist project "%s"' % cfg.project)
    groups, pending = [], {}
    for a in uniq([a for a in areas if a]):
        if not st.section_id(a):
            within(st, "max_sections", len(st.sections) + len(pending), "a new section")
            c = new_cmd("section_add", {"name": a, "project_id": st.project_id})
            groups.append([c])
            pending[c["temp_id"]] = a
    for name in uniq(labels):
        if name.lower() not in st.labels:
            if not cfg.kinds_create_missing and not reserved_label(name):
                die('no label "%s" yet, and the config keeps kinds to the existing labels (attributes.kinds.create_missing); '
                    'todos labels add %s creates it' % (name, name))
            groups.append([new_cmd("label_add", {"name": name})])
            st.labels.add(name.lower())
    if groups:
        mapping = write(groups)
        for t, a in pending.items():
            st.sections[mapping[t]] = a
            err('created section "%s" in %s' % (a, cfg.project))


def require(st, feature, what, hint="use a due date instead"):
    """Refuse, before any write, what the account's plan cannot store (deadlines are Pro-only)."""
    cur = st.plan()
    if cur.get(feature) is False:
        die("%s needs a paid Todoist plan: this account (plan %s) has no %s; %s"
            % (what, cur.get("plan_name") or "?", feature, hint))


def project_count(st):
    """The active projects that count against the plan's max_projects: the Inbox does not (observed live: an
    account at the cap with the Inbox among its rows still creates one more)."""
    return len([p for p in st.projects if not p.get("is_archived") and not p.get("inbox_project")])


def within(st, key, count, what):
    """Refuse `what` when the plan's cap `key` (max_projects, max_sections, ...) is already reached."""
    cap = st.plan().get(key)
    if isinstance(cap, int) and count >= cap:
        die("%s would pass the plan's %s (%d on plan %s); archive or delete one first, or upgrade"
            % (what, key, cap, st.plan().get("plan_name") or "?"))


def user_id(st):
    return str(st.user.get("id") or "") or None


def resolve_user(st, ref, project_id=None):
    """"me", a user id, a name or an email -> the collaborator's user id."""
    if not ref:
        return None
    if ref.lower() == "me":
        uid = user_id(st)
        if not uid:
            die("the cache has no user record yet; run with --fresh")
        return uid
    if ref == user_id(st) or ref == (st.user.get("email") or "").lower():
        return user_id(st)
    people = st.collaborators
    if project_id:
        allowed = {c["user_id"] for c in st.collaborator_states if c.get("project_id") == project_id}
        people = [c for c in people if c.get("id") in allowed] or people
    hits = [c for c in people if c.get("id") == ref] or \
        [c for c in people if (c.get("email") or "").lower() == ref.lower()] or \
        [c for c in people if ref.lower() in (c.get("full_name") or "").lower()]
    if len(hits) > 1:
        die("ambiguous user %s: %s" % (ref, ", ".join("%s (%s)" % (c.get("full_name"), c.get("email")) for c in hits)))
    if not hits:
        die("no collaborator matching %s (todos people lists them)" % ref)
    return hits[0]["id"]


def resolve_in(items, ref):
    if not ref.strip():
        die("empty task id")
    hits = [i for i in items if i.id.startswith(ref)] or [i for i in items if i.id.lower().startswith(ref.lower())]
    if len(hits) > 1:
        die("ambiguous id %s: %s" % (ref, " | ".join("%s %s" % (i.short, i.title) for i in hits)))
    return hits[0] if hits else None


def task_ref(ref):
    """A pasted task link -> the id it carries: the last path segment, without the title slug the app may put
    before it (app/task/<id>, app/task/<slug>-<id>), or the id= of the showTask and todoist:// forms. The forms
    --links prints read back too: task#<id> is its id, and a markdown link [text](<link>) is the id its link
    carries; text after the link is ignored. The link's id wins over the short id in the text, which belongs to
    one project's listing: the text only finds the full id inside a link of any template. Anything else comes
    back as it is."""
    ref = (ref or "").strip()
    md = MD_LINK.match(ref)
    if md:
        named = TASK_TEXT.match(md.group(1).strip())
        ref = md.group(2).strip()
        if named:  # the full id in the link that starts with the short id the text names, whatever the template
            full = re.search(r"(?<![A-Za-z0-9])%s[A-Za-z0-9]*" % re.escape(named.group(1)), ref)
            if full:
                return full.group(0)
    if ref.lower().startswith("task#"):
        return ref[5:].strip()
    if "://" not in ref:
        if "todoist.com/" not in ref:
            return ref
        ref = "https://" + ref
    u = urlsplit(ref)
    by_query = parse_qs(u.query).get("id")
    if by_query:
        return by_query[0].strip()
    return u.path.rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1]


def resolve(st, ref, include_done=False):
    """A task by id prefix or by its link: the project's open tasks first, then the account's, then
    (include_done) the project's tasks completed in the last 89 days."""
    ref = task_ref(ref)
    it = resolve_in(st.items, ref) or resolve_in(st.all_items, ref)
    if it:
        return it
    if include_done:
        done = fetch_done(st, now() - timedelta(days=DONE_WINDOW_DAYS))
        assign_short_ids(st.items + done)
        it = resolve_in(done, ref)
        if it:
            return it
    die("no %stask with id starting %s in %s" % ("" if include_done else "open ", ref, cfg.project or "the account"))


def subtree(st, root, with_done=False):
    """The task and its subtasks in the app's order, each after its parent. The account state carries the open
    ones; `with_done` adds the subtasks completed in the last 89 days."""
    if with_done:
        foreign = root.raw.get("project_id") != st.project_id
        done = fetch_done(st, now() - timedelta(days=DONE_WINDOW_DAYS), everywhere=foreign)
        tree = {t.id: t for t in [root] + descendants(root)}
        added = True
        while added:
            added = [d for d in done if d.id not in tree and d.parent in tree]
            for d in added:
                p = tree[d.parent]
                p.children.append(d)
                d.depth = p.depth + 1
                if d.area == "-":
                    d.area = p.area
                tree[d.id] = d
        for t in tree.values():
            t.children.sort(key=lambda c: (c.order, c.created or NEAR, c.id))
        assign_short_ids((st.all_items if foreign else st.items) + [t for t in tree.values() if t.done])
    return [root] + descendants(root)


def task_notes(st, i):
    """A task's comments, oldest first, the src/since one among them; a completed task's come from /comments."""
    rows = list(pages("/comments", {"task_id": i.id})) if i.done else st.notes.get(i.id, [])
    return sorted(rows, key=lambda n: n.get("posted_at") or "")


def find_project(st, ref, archived=False):
    """A project by "inbox", id, unique id prefix or name (case-insensitive; active projects unless `archived`)."""
    ref = (ref or "").strip()
    if not ref:
        die("which project? give a name or id")
    rows = st.projects if archived else [p for p in st.projects if not p.get("is_archived")]
    if ref.lower() == "inbox":
        hits = [p for p in rows if p.get("inbox_project")]
    else:
        hits = [p for p in rows if p["id"] == ref] or [p for p in rows if (p.get("name") or "").lower() == ref.lower()] \
            or [p for p in rows if p["id"].startswith(ref)] or [p for p in rows if ref.lower() in (p.get("name") or "").lower()]
    if len(hits) > 1:
        die("ambiguous project %s: %s" % (ref, " | ".join(p.get("name") or p["id"] for p in hits)))
    if not hits:
        die('no project "%s" (todos projects lists them%s)' % (ref, "" if archived else "; --archived shows archived ones"))
    return hits[0]


def find_section(st, ref, project=None):
    """A section by id, unique id prefix or name, within `project` (a row) or given as project/name."""
    ref = (ref or "").strip()
    if not ref:
        die("which section? give a name or id")
    rows = list(st.all_sections.values())
    if "/" in ref and project is None:
        pname, ref = ref.split("/", 1)
        project = find_project(st, pname)
    if project is not None:
        rows = [x for x in rows if x.get("project_id") == project["id"]]
    hits = [x for x in rows if x["id"] == ref] or [x for x in rows if (x.get("name") or "").lower() == ref.lower()] \
        or [x for x in rows if x["id"].startswith(ref)]
    if len(hits) > 1:
        die("ambiguous section %s: %s" % (ref, " | ".join(
            "%s/%s" % (st.project_names.get(x.get("project_id")), x.get("name")) for x in hits)))
    if not hits:
        die('no section "%s"%s (todos sections lists them)' % (ref, " in " + (project.get("name") or "") if project else ""))
    return hits[0]


def find_label(st, ref):
    ref = (ref or "").strip()
    hits = [l for l in st.label_rows if (l.get("name") or "").lower() == ref.lower()] or \
        [l for l in st.label_rows if str(l.get("id")) == ref]
    if not hits:
        die('no personal label "%s" (todos labels lists them)' % ref)
    return hits[0]


def find_filter(st, ref):
    ref = (ref or "").strip()
    hits = [f for f in st.filters if (f.get("name") or "").lower() == ref.lower()] or \
        [f for f in st.filters if str(f.get("id")) == ref] or \
        [f for f in st.filters if ref.lower() in (f.get("name") or "").lower()]
    if len(hits) > 1:
        die("ambiguous filter %s: %s" % (ref, " | ".join(f.get("name") or "" for f in hits)))
    if not hits:
        die('no filter "%s" (todos filters lists them)' % ref)
    return hits[0]


def find_comment(st, ref):
    ref = (ref or "").strip()
    rows = [n for ns in st.notes.values() for n in ns] + [n for ns in st.project_notes.values() for n in ns]
    hits = [n for n in rows if str(n.get("id")) == ref] or [n for n in rows if str(n.get("id")).startswith(ref)]
    if len(hits) > 1:
        die("ambiguous comment id %s" % ref)
    if not hits:
        die("no comment with id %s (todos comments <task> lists a task's)" % ref)
    return hits[0]


def find_reminder(st, ref):
    ref = (ref or "").strip()
    hits = [r for r in st.reminders if str(r.get("id")) == ref] or [r for r in st.reminders if str(r.get("id")).startswith(ref)]
    if len(hits) > 1:
        die("ambiguous reminder id %s" % ref)
    if not hits:
        die("no reminder with id %s (todos reminders lists them)" % ref)
    return hits[0]


def other_section(st, project, area):
    """The id of section `area` in another project of the account, for edit --project."""
    projects = [p for p in st.data.get("projects") or [] if not p.get("is_deleted") and not p.get("is_archived")]
    mine = [p for p in projects if (p.get("name") or "").lower() == project.lower()]
    if not mine:
        die('no Todoist project "%s"' % project)
    for s in st.data.get("sections") or []:
        if s.get("project_id") == mine[0]["id"] and not s.get("is_deleted") and not s.get("is_archived") \
                and (s.get("name") or "").lower() == area:
            return s["id"]
    die('no section "%s" in %s (TODOIST_PROJECT=%s todos add --area %s ... creates it)' % (area, project, project, area))


def open_in(st, key, value):
    return len([i for i in st.all_items if i.raw.get(key) == value])
