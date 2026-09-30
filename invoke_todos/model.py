"""The house model: the Origin link and the description, the attributes (the effort and mode labels, the kinds,
the src/since comment), the title cap, areas, the task tree (duck-typed over id, parent, children, order, created,
depth, area, short) and the field list of the JSON view. Every vocabulary reader takes its values from the config."""
import re

from invoke_todos.config import cfg
from invoke_todos.dates import NEAR
from invoke_todos.output import die, err


# The origin link ends the description: "[Origin](<url>)" after the last line of prose, or on its own
# paragraph after a heading, list, quote, table or code fence. Older tasks end in "[session <sid8>](<url>)"
# or "[link](<url>)" on a line of their own; they read back the same and are rewritten on the next edit.


def link_re():
    """The Origin link (the config's text, `Origin`, or the two older forms) ending a description."""
    return re.compile(r"(?:^|\s)\[(?:%s|Origin|session [0-9a-f]{8}|link)\]\((\S+)\)\s*$" % re.escape(cfg.origin_link))


FENCE_RE = re.compile(r"^\s*(```|~~~)")
BLOCK_RE = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|~~~)")


def session_url(src):
    """A session id (8 hex chars, or a full UUID) -> the Origin link the config's url template names, or None."""
    s = (src or "").lower()
    head, rest = s[:8], s[8:]
    hexd = set("0123456789abcdef")
    if len(head) == 8 and set(head) <= hexd and set(rest) <= hexd | {"-"}:
        return cfg.src_url_template % head if cfg.src_url_template else None
    return None


def split_description(text):
    """Description -> (body without the origin link, the link's url or None)."""
    text = (text or "").strip()
    m = link_re().search(text)
    if m:
        return text[:m.start()].rstrip(), m.group(1)
    return text, None


def join_description(desc, url):
    """Body + origin url -> the stored description. The link rides on the last prose line; after a block
    element (or an unclosed code fence) it takes a paragraph of its own."""
    d = (desc or "").strip()
    if not url:
        return d
    link = "[%s](%s)" % (cfg.origin_link, url)
    if not d:
        return link
    lines = d.split("\n")
    fences = len([l for l in lines if FENCE_RE.match(l)])
    if fences % 2 == 0 and not BLOCK_RE.match(lines[-1]):
        return d + " " + link
    return d + "\n\n" + link


ATTR_LINE_KEYS = ("src", "since", "effort", "mode", "area", "kind", "kinds", "url", "deadline")


def parse_attr_line(s):
    """'src: x; since: y' (separators ';', '|' or the middle dot) -> dict, or None when it is not one."""
    parts = [p.strip() for p in re.split("[;|\u00b7]", s or "") if p.strip()]
    if not parts:
        return None
    out = {}
    for p in parts:
        if ":" not in p:
            return None
        k, v = p.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k not in ATTR_LINE_KEYS:
            return None
        out[k] = "https:" + v if k == "url" and v.startswith("//") else v
    return out


def encode_note(src, since):
    if not cfg.provenance_comment:
        return None
    parts = (["src: " + src] if src else []) + (["since: " + since] if since else [])
    return "; ".join(parts) or None


def attr_note(notes):
    """The task comment that carries src and since -> (comment, {src, since})."""
    for n in notes:
        kv = parse_attr_line(n.get("content"))
        if kv and set(kv) <= {"src", "since"}:
            return n, kv
    return None, {}


def norm_effort(value):
    """'s' -> 'S': the configured spelling of an effort value, or None when it is not one."""
    low = (value or "").strip().lower()
    return next((e for e in cfg.efforts if e.lower() == low), None) if low else None


def norm_mode(value):
    """The configured spelling of a mode, or None when the value is not one."""
    low = (value or "").strip().lower()
    return next((m for m in cfg.modes if m.lower() == low), None) if low else None


def effort_of_label(name):
    """'effort-s' -> 'S' when the label is an effort label (the config's prefix and values), else None."""
    p = cfg.effort_prefix
    return norm_effort(name[len(p):]) if name[:len(p)].lower() == p.lower() else None


def reserved_label(name):
    return norm_mode(name) is not None or effort_of_label(name) is not None


def compose_labels(kinds, effort, mode):
    out = []
    for k in kinds:
        if k not in out:
            out.append(k)
    if effort:
        out.append(cfg.effort_prefix + effort)
    if mode:
        out.append(mode)
    return out


def decompose_labels(labels):
    kinds, effort, mode = [], None, None
    for name in labels or []:
        e, m = effort_of_label(name), norm_mode(name)
        if e:
            effort = e
        elif m:
            mode = m
        else:
            kinds.append(name)
    return kinds, effort, mode


def length_problems(title):
    if len(title) > cfg.title_max:
        return ["title is %d characters; the cap is %d (about eight words): %s" % (len(title), cfg.title_max, title)]
    return []


def check_lengths(title, force):
    probs = length_problems(title)
    for p in probs:
        err(("warning: " if force else "") + p)
    if probs and not force:
        die("shorten it, or pass --force")


def normalize_area(s):
    a = (s or "").strip("# ").lower()
    if not a or " " in a:
        die('area must be one lowercase word, got "%s"' % s)
    return a


def uniq(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


FIELDS = ("id", "short", "parent", "area", "title", "desc", "kinds", "due", "recur", "deadline", "prio", "effort",
          "mode", "src", "since", "url", "duration", "assignee", "subtasks", "done", "doneAt", "created", "modified",
          "project", "link")
DEFAULT_FIELDS = tuple(f for f in FIELDS if f not in ("link", "project"))
BRIEF_FIELDS = ("id", "title", "area", "project", "prio", "effort", "mode", "kinds", "due", "src")  # a brief row, every key present
FIELD_DOC = (  # (field, type, when present, meaning): what list --json, show --json and the brief rows carry
    ("id", "string", "always", "the task's id in the app"),
    ("short", "string", "always", "the shortest unique prefix of id over the listed tasks (8 characters or more); any verb takes it as the ID"),
    ("parent", "string", "a subtask", "the parent task's id"),
    ("area", "string", "always", "the section; \"-\" when the task has none"),
    ("title", "string", "always", "the title"),
    ("desc", "string", "a body", "the body, markdown, without the Origin link"),
    ("kinds", "list of strings", "always (may be empty)", "the kind labels"),
    ("due", "string", "a due", "YYYY-MM-DD, or YYYY-MM-DD HH:MM for a timed due"),
    ("recur", "string", "a recurring due", "the recurrence phrase (\"every monday\")"),
    ("deadline", "string", "a deadline", "YYYY-MM-DD"),
    ("prio", "integer", "always", "the value: 1 the most valuable, 3 the least, 0 none"),
    ("effort", "string", "an effort label", "one of the config's effort values"),
    ("mode", "string", "a mode label", "one of the config's modes"),
    ("src", "string", "a src", "the origin: a session id (8 hex characters) or a reference"),
    ("since", "string", "a since", "YYYY-MM-DD, first seen"),
    ("url", "string", "an Origin link", "the link's URL"),
    ("duration", "string", "a duration", "minutes as 90m, days as 3d"),
    ("assignee", "string", "an assignee", "the user's id"),
    ("subtasks", "list of strings", "open subtasks", "their ids (show --tree --all: the completed ones too)"),
    ("done", "boolean", "always", "completed"),
    ("doneAt", "string", "a completed task", "YYYY-MM-DD HH:MM, local time"),
    ("created", "string", "always", "YYYY-MM-DD HH:MM, local time"),
    ("modified", "string", "always", "YYYY-MM-DD HH:MM, local time"),
    ("project", "string", "asked for, or a brief row", "the project's name"),
    ("link", "string", "asked for", "the task's link: the app's web URL, or the config's todoist.task_url"),
)


def fields_help():
    """todos help fields: the JSON fields, one line each."""
    w = max(len(f) for f, _, _, _ in FIELD_DOC)
    out = ["The JSON fields: list --json and overview PROJECT --json carry the default set (every field but project and",
           "link; --fields a,b,... picks and orders them), show --json all %d, brief --json rows the %d named last. A field"
           % (len(FIELD_DOC), len(BRIEF_FIELDS)),
           "with no value is left out, except id, title, kinds, prio and done, which are always there; a brief row carries",
           "every one of its keys, null where there is no value.", ""]
    for f, t, when, what in FIELD_DOC:
        out.append("  %-*s  %-16s %-26s %s" % (w, f, t, when, what))
    out += ["", "show --comments --json adds comments: a list of objects, oldest first, without the src/since comment, each",
            "with id, posted (YYYY-MM-DD HH:MM, local time) and content (the whole text), and file (its name), reactions",
            "(name to count) and by (the author's user id, when it is someone else) where there is one. show --tree --json",
            "is a list: the task, then its subtasks in the app's order, each after its parent."]
    out += ["", "brief rows: " + ", ".join(BRIEF_FIELDS)]
    return "\n".join(out)


def assign_short_ids(items, minimum=8):
    """Shortest unique id prefix (at least 8) over the given set; ids created together share a prefix."""
    ids = sorted({i.id for i in items})
    need = {}
    for a, b in zip(ids, ids[1:]):
        k = 0
        while k < min(len(a), len(b)) and a[k] == b[k]:
            k += 1
        need[a] = max(need.get(a, 0), k + 1)
        need[b] = max(need.get(b, 0), k + 1)
    for it in items:
        it.short = it.id[:max(minimum, need.get(it.id, 0))]


def link_tree(items):
    """Set each task's open subtasks (in the app's order) and its depth; a subtask without a section of
    its own takes its parent's area."""
    by_id = {i.id: i for i in items}
    for i in items:
        i.children, i.depth = [], 0
    for i in items:
        p = by_id.get(i.parent)
        if p is not None:
            p.children.append(i)
    for i in items:
        i.children.sort(key=lambda c: (c.order, c.created or NEAR, c.id))

    def walk(i, depth):
        i.depth = depth
        for c in i.children:
            if c.area == "-":
                c.area = i.area
            walk(c, depth + 1)

    for i in items:
        if i.parent not in by_id:
            walk(i, 0)


def descendants(i):
    out = []
    for c in i.children:
        out.append(c)
        out += descendants(c)
    return out


def top_level(items):
    """Drop the tasks whose parent is also in the list: the API takes subtasks along."""
    covered = {d.id for i in items for d in descendants(i)}
    return uniq([i for i in items if i.id not in covered])


def with_subtasks(n):
    return " (+%d subtask%s)" % (n, "" if n == 1 else "s") if n else ""
