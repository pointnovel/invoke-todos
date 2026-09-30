"""The import grammar: markdown rows (and a JSON array) into task seeds.

- [ ] <title> @YYYY-MM-DD[THH:MM] !1..3 #area #kind #kind [id 6X.., kind/kind, S, mode, src X, since D]
      <body lines, indented deeper than the bullet; markdown, blank lines and inner indentation kept>
      src: <sid8 | file#item | name>; since: YYYY-MM-DD; effort: S|M|L; mode: M; deadline: D
  - [ ] <subtask title> #kind         (a bullet indented under a task is its subtask; same area)
        <its body>
The first #tag of a root row is the area; the rest are kinds; a subtask's #tags are all kinds. A root
row without an area takes the "## <area>" heading above it (a one-word lowercase heading, as
`todos export` writes). The trailing [id ...] bracket is what `todos export` writes: the id and
the attributes; an attribute line below overrides it. Attribute separators: ";", "|" or the middle
dot. "- [x]" rows are skipped (closed with --update when they carry an id). A JSON array (the
`todo list --json` or `todos list --json` shape; `parent` = an id in the file or an open task) is
read as well.
"""
import json
import re

from invoke_todos.dates import parse_due
from invoke_todos.model import norm_effort, norm_mode, parse_attr_line, uniq
from invoke_todos.output import die


def blank_seed():
    return {"title": "", "due": None, "deadline": None, "prio": 0, "area": None, "kinds": [], "desc": [],
            "src": None, "since": None, "effort": None, "mode": None, "url": None, "done": False,
            "id": None, "parent": None, "parent_ref": None, "indent": 0}


BULLET_RE = re.compile(r"^( *)- \[( |x|X)\] (.*)$")
META_RE = re.compile(r"\s\[id ([^\]]*)\]\s*$")


def parse_meta(text):
    """The bracket a `todos export` line ends with: '6X.., decision/verify, S, owner, src X, since D,
    deadline D, overdue' -> its fields."""
    out = {"id": None, "kinds": [], "effort": None, "mode": None, "src": None, "since": None, "deadline": None}
    for n, p in enumerate(x.strip() for x in text.split(",")):
        if not p:
            continue
        low = p.lower()
        if n == 0:
            out["id"] = p
        elif norm_effort(p):
            out["effort"] = norm_effort(p)
        elif norm_mode(p):
            out["mode"] = norm_mode(p)
        elif low.startswith("src "):
            out["src"] = p[4:].strip()
        elif low.startswith("since "):
            out["since"] = p[6:].strip()
        elif low.startswith("deadline "):
            out["deadline"] = p[9:].strip()
        elif low != "overdue":
            out["kinds"] += [k.strip().lower() for k in p.split("/") if k.strip()]
    return out


def parse_seed(text):
    tasks, cur, heading_area, stack, body_indent = [], None, None, [], None
    for raw in text.split("\n"):
        t = raw.strip()
        lead = len(raw) - len(raw.lstrip(" "))
        m = BULLET_RE.match(raw)
        if m:
            cur = blank_seed()
            indent = len(m.group(1))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            cur["parent"] = stack[-1][1] if stack else None
            stack.append((indent, cur))
            cur["indent"], body_indent = indent, None
            cur["done"] = m.group(2) != " "
            head = " " + m.group(3)
            mm = META_RE.search(head)
            if mm:
                meta = parse_meta(mm.group(1))
                head = head[:mm.start()]
                cur["id"], cur["kinds"] = meta["id"], meta["kinds"]
                for k in ("effort", "mode", "src", "since", "deadline"):
                    cur[k] = meta[k]
            words = []
            for w in head.split():
                if w.startswith("@") and parse_due(w[1:]):
                    cur["due"] = parse_due(w[1:])
                elif re.fullmatch(r"![0-4]", w):
                    cur["prio"] = 0 if w == "!4" else int(w[1])
                elif w.startswith("#") and len(w) > 1:
                    if cur["area"] is None and cur["parent"] is None:
                        cur["area"] = w[1:].lower()
                    else:
                        cur["kinds"].append(w[1:].lower())
                elif w.startswith(("(done", "(id:")):
                    continue
                else:
                    words.append(w)
            cur["title"] = " ".join(words).strip()
            if cur["parent"] is None:
                cur["area"] = cur["area"] or heading_area
            tasks.append(cur)
        elif cur is not None and t and lead > cur["indent"]:
            kv = parse_attr_line(t)
            if kv:
                for k in ("src", "since", "mode", "url", "deadline"):
                    if k in kv:
                        cur[k] = (norm_mode(kv[k]) or kv[k].strip()) if k == "mode" else kv[k]
                if "effort" in kv:
                    cur["effort"] = norm_effort(kv["effort"]) or kv["effort"].strip()
                if "area" in kv and cur["parent"] is None:
                    cur["area"] = kv["area"].lower()
                kinds = kv.get("kind") or kv.get("kinds")
                if kinds:
                    cur["kinds"] += [k.strip().lower() for k in kinds.split(",") if k.strip()]
            else:
                if body_indent is None:
                    body_indent = lead
                cur["desc"].append(raw[min(lead, body_indent):].rstrip())
        elif cur is not None and not t:
            if cur["desc"]:
                cur["desc"].append("")
        else:
            if t.startswith("#") and not raw.startswith(" "):
                mh = re.fullmatch(r"#{2,3} ([a-z0-9_-]+)", t)
                heading_area = mh.group(1) if mh else None
            cur, stack = None, []
    for x in tasks:
        while x["desc"] and not x["desc"][-1]:
            x["desc"].pop()
        x["desc"] = "\n".join(x["desc"])
        x["kinds"] = uniq(x["kinds"])
    return tasks


def parse_json_seeds(text):
    try:
        rows = json.loads(text)
    except ValueError as e:
        die("not a JSON array: %s" % e)
    if not isinstance(rows, list):
        die("the JSON import must be an array of task objects")
    out = []
    for r in rows:
        s = blank_seed()
        s["title"] = (r.get("title") or "").strip()
        s["area"] = r.get("area") if r.get("area") not in (None, "-") else None
        s["desc"] = r.get("desc") or ""
        s["kinds"] = [k.lower() for k in r.get("kinds") or []]
        s["due"] = parse_due(r["due"]) if r.get("due") else None
        s["deadline"] = r.get("deadline")
        s["prio"] = int(r.get("prio") or 0)
        for k in ("effort", "mode", "src", "since", "url"):
            s[k] = r.get(k)
        s["done"] = bool(r.get("done"))
        s["id"] = r.get("id")
        s["parent_ref"] = r.get("parent")
        out.append(s)
    by_id = {x["id"]: x for x in out if x["id"]}
    for x in out:
        if x["parent_ref"] in by_id and by_id[x["parent_ref"]] is not x:
            x["parent"], x["parent_ref"] = by_id[x["parent_ref"]], None
    return out
