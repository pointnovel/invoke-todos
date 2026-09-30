"""Argument parsing: the flag grammar (--key value, --key=value, boolean switches) over the flag sets a backend
hands in, and the generic flag readers."""
import json
import re
import sys

from invoke_todos.config import cfg
from invoke_todos.dates import parse_day, parse_due
from invoke_todos.model import DEFAULT_FIELDS, FIELDS, norm_effort, norm_mode, reserved_label, uniq
from invoke_todos.output import die


class Args(object):
    def __init__(self):
        self.pos, self.values, self.bools = [], {}, set()

    def first(self, k):
        v = self.values.get(k)
        return v[0] if v else None

    def all(self, k):
        return self.values.get(k, [])

    def has(self, k):
        return k in self.bools or k in self.values


def parse_args(argv, value_flags, bool_flags):
    a = Args()
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--"):
            body = tok[2:]
            if "=" in body:
                k, v = body.split("=", 1)
                if k not in value_flags:
                    die("unknown flag --%s (todos help)" % k)
                a.values.setdefault(k, []).append(v)
            elif body in value_flags:
                if i + 1 >= len(argv):
                    die("--%s needs a value" % body)
                a.values.setdefault(body, []).append(argv[i + 1])
                i += 1
            elif body in bool_flags:
                a.bools.add(body)
            else:
                die("unknown flag --%s (todos help)" % body)
        else:
            a.pos.append(tok)
        i += 1
    return a


def validate(x, check_kinds=True):
    if x["effort"] and x["effort"] not in cfg.efforts:
        die("effort must be one of %s, got %s" % ("|".join(cfg.efforts), x["effort"]))
    if x["mode"] and x["mode"] not in cfg.modes:
        die("mode must be one of %s, got %s" % ("|".join(cfg.modes), x["mode"]))
    if x["since"] and not parse_day(x["since"]):
        die("since must be YYYY-MM-DD, got %s" % x["since"])
    for k in x["kinds"] if check_kinds else ():
        if reserved_label(k) or " " in k:
            die("kind %s is not allowed (one word, not an effort or mode label)" % k)


def attrs_from(a, base=None):
    x = {"effort": base.effort if base else None, "mode": base.mode if base else None,
         "src": base.src if base else None, "since": base.since if base else None,
         "kinds": list(base.kinds) if base else []}
    if a.first("effort") is not None:
        x["effort"] = norm_effort(a.first("effort")) or a.first("effort").strip() or None
    if a.first("mode") is not None:
        x["mode"] = norm_mode(a.first("mode")) or a.first("mode").strip() or None
    if a.first("src") is not None:
        x["src"] = a.first("src").strip() or None
    if a.first("since") is not None:
        x["since"] = a.first("since").strip() or None
    kinds = [k.strip("# ").lower() for v in a.all("kind") + a.all("tag") for k in v.split(",")]
    if kinds:
        x["kinds"] = uniq([k for k in kinds if k])
    validate(x, check_kinds=bool(kinds) or base is None)  # labels added in the app pass through untouched
    return x


def parse_prio(a):
    p = a.first("prio")
    if p is None:
        return None
    try:
        n = int(p)
    except ValueError:
        n = -1
    if n not in (0, 1, 2, 3, 4):
        die("--prio needs 1..3 (0 clears)")
    return 0 if n == 4 else n


def due_flag(a, key="due"):
    """--due: an ISO date or date-time, or any text Todoist parses ("tomorrow 9am", "every monday")."""
    d = a.first(key)
    if d is None:
        return None
    c = parse_due(d)
    if c:
        if a.first("tz"):
            c["timezone"] = a.first("tz")
        return c
    if re.match(r"^\d{4}-\d{2}", d.strip()):
        die("--%s needs YYYY-MM-DD or YYYY-MM-DDTHH:MM (or a phrase Todoist parses, such as 'every monday 9am')" % key)
    c = {"string": d.strip()}
    if a.first("tz"):
        c["timezone"] = a.first("tz")
    if a.first("lang"):
        c["lang"] = a.first("lang")
    return c


def deadline_flag(a):
    d = a.first("deadline")
    if d is None:
        return None
    if not parse_day(d):
        die("--deadline needs YYYY-MM-DD")
    return d.strip()


def read_text(a, key):
    """A text flag whose value "-" reads stdin."""
    v = a.first(key)
    if v == "-":
        return sys.stdin.read()
    return v


def read_note(a):
    n = a.first("note")
    if n == "-":
        return sys.stdin.read()
    return n


def onoff(a, key):
    v = a.first(key)
    if v is None:
        return None
    if v.lower() in ("on", "true", "yes", "1"):
        return True
    if v.lower() in ("off", "false", "no", "0"):
        return False
    die("--%s takes on or off" % key)


def favorite_flag(a):
    if a.has("favorite"):
        return True
    if a.has("no-favorite"):
        return False
    return None


def sub(a, default="list"):
    return a.pos[1] if len(a.pos) > 1 else default


def arg(a, n, what):
    if len(a.pos) <= n:
        die("todos %s needs %s" % (" ".join(a.pos[:n]), what))
    return a.pos[n]


def kv_pairs(pairs, allowed=None):
    out = {}
    for kv in pairs:
        if "=" not in kv:
            die("expected KEY=VALUE, got %s" % kv)
        k, v = kv.split("=", 1)
        k = k.strip()
        if allowed is not None and k not in allowed:
            die("%s is not one of: %s" % (k, ", ".join(sorted(allowed))))
        low = v.strip().lower()
        if low in ("on", "true", "yes"):
            v = True
        elif low in ("off", "false", "no"):
            v = False
        elif re.fullmatch(r"-?\d+", v.strip()):
            v = int(v)
        elif v.strip().startswith(("[", "{")):
            v = json.loads(v)
        out[k] = v
    return out


def picked(pairs):
    return {k: v for k, v in pairs if v is not None}


def fields_from(a):
    f = a.first("fields")
    if not f:
        return DEFAULT_FIELDS
    out = [x.strip() for x in f.split(",") if x.strip()]
    bad = [x for x in out if x not in FIELDS]
    if bad:
        die("unknown field(s) %s; fields: %s" % (",".join(bad), ",".join(FIELDS)))
    return tuple(out)
