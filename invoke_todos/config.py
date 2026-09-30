"""The account config of invoke-todos: built-in defaults, then the JSON file, then the environment.

One Config per run: `cfg`, created at import by safe_load() and shared by every module through
`from invoke_todos.config import cfg`; reload(path) refills that same object when --config names a file.
Precedence, highest first: the command-line flag (--config, --in), the environment variable named
beside each key in docs/spec-config.md, the file, the built-in default. This module carries no
person's names, projects or labels: they live in the file. Keys whose name starts with "_" are
comments and are dropped before anything else looks at the file.

Python 3.9, standard library only.
"""
import json
import os
import re
import sys

VERSION = 1
BACKENDS = ("todoist",)
TOKEN_SOURCES = ("env", "keychain", "file", "command")
DEFAULT_MODES = ("unattended", "assisted", "owner")
DEFAULT_MODE_MEANING = {"unattended": "an agent finishes it alone",
                        "assisted": "an agent starts it and needs you mid-way",
                        "owner": "only you can: pay, sign, call"}
DEFAULT_EFFORTS = ("S", "M", "L")
DEFAULT_EFFORT_MEANING = {"S": "under an hour", "M": "a session", "L": "several sessions"}
DEFAULT_KINDS = ("decision", "verify", "build", "write", "parked")
WORD = re.compile(r"^[a-z0-9][a-z0-9_-]*$")  # one lowercase word: an area, a mode, a kind
KNOWN = {  # every key the file may carry; anything else is a warning, not an error
    "version": (), "backend": (), "account": ("name",), "todoist": ("api_base", "token", "task_url"),
    "defaults": ("project", "export", "timeout", "settle", "max_wait", "title_max"),
    "paths": ("cache_dir",), "projects": None, "attributes": ("effort", "mode", "kinds", "priority"),
    "provenance": ("comment", "origin_link", "src"),
}


class ConfigError(Exception):
    """A config that does not parse or does not validate; str() is the message with the key path."""


def home(env):
    return env.get("HOME") or os.path.expanduser("~")


def expand(path, env):
    """~ and ~/x against the environment's HOME (not the process's), then absolute."""
    if path == "~":
        path = home(env)
    elif path.startswith("~/"):
        path = os.path.join(home(env), path[2:])
    return os.path.abspath(path)


def config_dir(env):
    return os.path.join(env.get("XDG_CONFIG_HOME") or os.path.join(home(env), ".config"), "invoke-todos")


def config_path(explicit=None, env=None):
    """The file in use: --config, else $TODOS_CONFIG, else the XDG config folder."""
    env = os.environ if env is None else env
    p = explicit or env.get("TODOS_CONFIG")
    if p:
        return expand(p, env)
    return os.path.join(config_dir(env), "config.json")


def strip_comments(obj):
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(x) for x in obj]
    return obj


class Config(object):
    """Every value the CLI reads, as an attribute; the defaults of docs/spec-config.md sec. 2."""

    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.path = None
        self.exists = False
        self.error = None
        self.warnings = []
        self.raw = {}
        self.backend = "todoist"
        self.account_name = "default"
        self.api_base = "https://api.todoist.com/api/v1"
        self.token_source = "keychain" if sys.platform == "darwin" else "file"
        self.token_env = "TODOIST_API_TOKEN"
        self.token_item = "TODOIST_API_TOKEN"
        self.token_path = os.path.join(config_dir(env), "todoist-token")
        self.token_command = None
        self.task_url = None  # a %s template for a task's link; None = the app's web URL
        self.project = None
        self.in_project = None
        self.fresh = False
        self.links = False    # --links: task rows name their task as a markdown link
        self.export_path = "-"
        self.timeout = 30.0
        self.settle = 6.0
        self.max_wait = 20
        self.title_max = 60
        self.cache_dir = os.path.join(env.get("XDG_CACHE_HOME") or os.path.join(home(env), ".cache"), "invoke-todos")
        self.projects = {}  # name -> {"areas": [...], "role": str or None}
        self.effort_prefix = "effort-"
        self.efforts = list(DEFAULT_EFFORTS)
        self.effort_meaning = dict(DEFAULT_EFFORT_MEANING)
        self.modes = list(DEFAULT_MODES)
        self.mode_meaning = dict(DEFAULT_MODE_MEANING)
        self.kinds = list(DEFAULT_KINDS)
        self.kinds_create_missing = True
        self.kinds_meaning = {}
        self.priority_meaning = "value"
        self.provenance_comment = True
        self.origin_link = "Origin"
        self.src_url_template = None

    def effective(self):
        """The merged config as a plain dict (config show); the token itself is never part of it."""
        return {
            "path": self.path, "exists": self.exists, "error": self.error, "warnings": list(self.warnings),
            "backend": self.backend,
            "account": {"name": self.account_name},
            "todoist": {"api_base": self.api_base, "task_url": self.task_url,
                        "token": {"source": self.token_source, "env": self.token_env, "item": self.token_item,
                                  "path": self.token_path, "command": self.token_command}},
            "defaults": {"project": self.project, "export": self.export_path, "timeout": self.timeout,
                         "settle": self.settle, "max_wait": self.max_wait, "title_max": self.title_max},
            "paths": {"cache_dir": self.cache_dir},
            "projects": {name: dict(p) for name, p in self.projects.items()},
            "attributes": {"effort": {"prefix": self.effort_prefix, "values": list(self.efforts), "meaning": dict(self.effort_meaning)},
                           "mode": {"values": list(self.modes), "meaning": dict(self.mode_meaning)},
                           "kinds": {"known": list(self.kinds), "create_missing": self.kinds_create_missing,
                                     "meaning": dict(self.kinds_meaning)},
                           "priority": {"meaning": self.priority_meaning}},
            "provenance": {"comment": self.provenance_comment, "origin_link": self.origin_link,
                           "src": {"url_template": self.src_url_template}},
        }


# ---------------------------------------------------------------- validation


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _nonempty(v):
    return isinstance(v, str) and v.strip() != ""


def validate(raw):
    """(errors, warnings) for a parsed file (comments already stripped): every error, in file order."""
    errors, warnings = [], []

    def bad(path, msg):
        errors.append("%s: %s" % (path, msg))

    def obj(path, v):
        if v is None:
            return {}
        if not isinstance(v, dict):
            bad(path, "must be an object")
            return {}
        return v

    def words(path, v):
        if not isinstance(v, list):
            bad(path, "must be a list of words")
            return []
        for n, w in enumerate(v):
            if not isinstance(w, str) or not WORD.match(w):
                bad("%s[%d]" % (path, n), '"%s" is not one lowercase word' % w)
        return [w for w in v if isinstance(w, str)]

    def meaning(path, v):
        m = obj(path, v)
        for k, t in m.items():
            if not isinstance(t, str):
                bad("%s.%s" % (path, k), "must be a string")

    if raw.get("version") != VERSION:
        bad("version", "must be %d, got %r" % (VERSION, raw.get("version")))
    if "backend" in raw and raw["backend"] not in BACKENDS:
        bad("backend", "must be one of %s, got %r" % ("|".join(BACKENDS), raw["backend"]))
    for k in raw:
        if k not in KNOWN:
            warnings.append("unknown key %s (ignored)" % k)
    for section, keys in KNOWN.items():
        if keys and isinstance(raw.get(section), dict):
            for k in raw[section]:
                if k not in keys:
                    warnings.append("unknown key %s.%s (ignored)" % (section, k))

    acc = obj("account", raw.get("account"))
    if "name" in acc and not _nonempty(acc["name"]):
        bad("account.name", "must be a non-empty string")

    td = obj("todoist", raw.get("todoist"))
    if "api_base" in td and not (isinstance(td["api_base"], str) and td["api_base"].startswith(("http://", "https://"))):
        bad("todoist.api_base", "must be an http(s) URL")
    if td.get("task_url") is not None and not (_nonempty(td["task_url"]) and "%s" in td["task_url"]):
        bad("todoist.task_url", "must contain %s (the task id), or be null")
    tok = obj("todoist.token", td.get("token"))
    if "value" in tok:
        bad("todoist.token.value", "the token does not belong in the config file; store it in the environment, "
                                   "the Keychain, a 0600 file or a command (docs/spec-config.md sec. 4)")
    src = tok.get("source")
    if src is not None and src not in TOKEN_SOURCES:
        bad("todoist.token.source", "must be one of %s, got %r" % ("|".join(TOKEN_SOURCES), src))
    elif src == "keychain" and sys.platform != "darwin":
        bad("todoist.token.source", "keychain is macOS only; use file or command")
    elif src == "command" and not (isinstance(tok.get("command"), list) and tok["command"]
                                   and all(isinstance(x, str) and x for x in tok["command"])):
        bad("todoist.token.command", "must be a non-empty list of strings")
    for k in ("env", "item", "path"):
        if k in tok and not _nonempty(tok[k]):
            bad("todoist.token.%s" % k, "must be a non-empty string")
    for k in tok:
        if k not in ("source", "env", "item", "path", "command", "value"):
            warnings.append("unknown key todoist.token.%s (ignored)" % k)

    d = obj("defaults", raw.get("defaults"))
    for k in ("project", "export"):
        if k in d and not _nonempty(d[k]):
            bad("defaults.%s" % k, "must be a non-empty string")
    for k in ("timeout", "settle", "max_wait"):
        if k in d and not (_is_num(d[k]) and d[k] > 0):
            bad("defaults.%s" % k, "must be a positive number")
    if "title_max" in d and not (_is_int(d["title_max"]) and d["title_max"] >= 20):
        bad("defaults.title_max", "must be an integer of at least 20")

    p = obj("paths", raw.get("paths"))
    if "cache_dir" in p and not _nonempty(p["cache_dir"]):
        bad("paths.cache_dir", "must be a path or off")

    projects = raw.get("projects")
    if projects is not None and not isinstance(projects, dict):
        bad("projects", "must be an object keyed by project name")
        projects = {}
    for name, spec in (projects or {}).items():
        if not _nonempty(name):
            bad("projects", "a project name must be a non-empty string")
            continue
        spec = obj("projects.%s" % name, spec)
        for k in spec:
            if k not in ("areas", "role"):
                warnings.append("unknown key projects.%s.%s (ignored)" % (name, k))
        if "areas" in spec:
            words("projects.%s.areas" % name, spec["areas"])
        if "role" in spec and not isinstance(spec["role"], str):
            bad("projects.%s.role" % name, "must be a string")

    attrs = obj("attributes", raw.get("attributes"))
    effort = obj("attributes.effort", attrs.get("effort"))
    prefix = effort.get("prefix", "effort-")
    if "prefix" in effort and not _nonempty(prefix):
        bad("attributes.effort.prefix", "must be a non-empty string")
    if "values" in effort:
        vals = effort["values"]
        if not isinstance(vals, list) or not vals:
            bad("attributes.effort.values", "must be a non-empty list")
        else:
            low = []
            for n, v in enumerate(vals):
                if not _nonempty(v) or " " in v:
                    bad("attributes.effort.values[%d]" % n, "%r is not a value (one word)" % (v,))
                elif v.lower() in low:
                    bad("attributes.effort.values", "duplicate %s" % v)
                else:
                    low.append(v.lower())
    if "meaning" in effort:
        meaning("attributes.effort.meaning", effort["meaning"])
    mode = obj("attributes.mode", attrs.get("mode"))
    if "values" in mode:
        vals = mode["values"]
        if not isinstance(vals, list) or not vals:
            bad("attributes.mode.values", "must be a non-empty list")
        else:
            seen = []
            for n, v in enumerate(vals):
                if not isinstance(v, str) or not WORD.match(v):
                    bad("attributes.mode.values[%d]" % n, '"%s" is not one lowercase word' % (v,))
                elif isinstance(prefix, str) and v.lower().startswith(prefix.lower()):
                    bad("attributes.mode.values[%d]" % n, "starts with the effort prefix %s" % prefix)
                elif v in seen:
                    bad("attributes.mode.values", "duplicate %s" % v)
                else:
                    seen.append(v)
    if "meaning" in mode:
        meaning("attributes.mode.meaning", mode["meaning"])
    kinds = obj("attributes.kinds", attrs.get("kinds"))
    if "known" in kinds:
        words("attributes.kinds.known", kinds["known"])
    if "create_missing" in kinds and not isinstance(kinds["create_missing"], bool):
        bad("attributes.kinds.create_missing", "must be true or false")
    if "meaning" in kinds:
        meaning("attributes.kinds.meaning", kinds["meaning"])
    prio = obj("attributes.priority", attrs.get("priority"))
    if "meaning" in prio and not _nonempty(prio["meaning"]):
        bad("attributes.priority.meaning", "must be a non-empty string")

    prov = obj("provenance", raw.get("provenance"))
    if "comment" in prov and not isinstance(prov["comment"], bool):
        bad("provenance.comment", "must be true or false")
    if "origin_link" in prov and not _nonempty(prov["origin_link"]):
        bad("provenance.origin_link", "must be a non-empty string")
    psrc = obj("provenance.src", prov.get("src"))
    if "url_template" in psrc and psrc["url_template"] is not None:
        t = psrc["url_template"]
        if not _nonempty(t) or "%s" not in t:
            bad("provenance.src.url_template", "must contain %s (the session id), or be null")
    return errors, warnings


# ---------------------------------------------------------------- loading


def apply_file(cfg, raw, env):
    """Copy a validated file into the Config (the file wins over the defaults)."""
    if "backend" in raw:
        cfg.backend = raw["backend"]
    acc = raw.get("account") or {}
    if "name" in acc:
        cfg.account_name = acc["name"]
    td = raw.get("todoist") or {}
    if "api_base" in td:
        cfg.api_base = td["api_base"].rstrip("/")
    if "task_url" in td:
        cfg.task_url = td["task_url"] or None
    tok = td.get("token") or {}
    if "source" in tok:
        cfg.token_source = tok["source"]
    if "env" in tok:
        cfg.token_env = tok["env"]
    if "item" in tok:
        cfg.token_item = tok["item"]
    if "path" in tok:
        cfg.token_path = expand(tok["path"], env)
    if "command" in tok:
        cfg.token_command = list(tok["command"])
    d = raw.get("defaults") or {}
    if "project" in d:
        cfg.project = d["project"]
    if "export" in d:
        cfg.export_path = d["export"]
    if "timeout" in d:
        cfg.timeout = float(d["timeout"])
    if "settle" in d:
        cfg.settle = float(d["settle"])
    if "max_wait" in d:
        cfg.max_wait = int(d["max_wait"])
    if "title_max" in d:
        cfg.title_max = int(d["title_max"])
    p = raw.get("paths") or {}
    if "cache_dir" in p:
        cfg.cache_dir = None if p["cache_dir"] == "off" else expand(p["cache_dir"], env)
    cfg.projects = {}
    for name, spec in (raw.get("projects") or {}).items():
        spec = spec or {}
        cfg.projects[name] = {"areas": list(spec.get("areas") or []), "role": spec.get("role")}
    attrs = raw.get("attributes") or {}
    effort = attrs.get("effort") or {}
    if "prefix" in effort:
        cfg.effort_prefix = effort["prefix"]
    if "values" in effort:
        cfg.efforts = list(effort["values"])
        cfg.effort_meaning = {}
    if "meaning" in effort:
        cfg.effort_meaning = dict(effort["meaning"])
    mode = attrs.get("mode") or {}
    if "values" in mode:
        cfg.modes = list(mode["values"])
        cfg.mode_meaning = {}
    if "meaning" in mode:
        cfg.mode_meaning = dict(mode["meaning"])
    kinds = attrs.get("kinds") or {}
    if "known" in kinds:
        cfg.kinds = list(kinds["known"])
    if "create_missing" in kinds:
        cfg.kinds_create_missing = kinds["create_missing"]
    if "meaning" in kinds:
        cfg.kinds_meaning = dict(kinds["meaning"])
    prio = attrs.get("priority") or {}
    if "meaning" in prio:
        cfg.priority_meaning = prio["meaning"]
    prov = raw.get("provenance") or {}
    if "comment" in prov:
        cfg.provenance_comment = prov["comment"]
    if "origin_link" in prov:
        cfg.origin_link = prov["origin_link"]
    psrc = prov.get("src") or {}
    if "url_template" in psrc:
        cfg.src_url_template = psrc["url_template"] or None


ENV_KEYS = (  # (variable, attribute, conversion): the environment wins over the file
    ("TODOIST_API_BASE", "api_base", lambda v: v.rstrip("/")),
    ("TODOIST_TASK_URL", "task_url", str),
    ("TODOIST_PROJECT", "project", str),
    ("TODOIST_EXPORT", "export_path", str),
    ("TODOIST_TIMEOUT", "timeout", float),
    ("TODOIST_SETTLE", "settle", float),
    ("TODOIST_MAX_WAIT", "max_wait", int),
    ("TODOIST_SESSION_URL", "src_url_template", str),
)


def apply_env(cfg, env):
    for var, attr, conv in ENV_KEYS:
        v = env.get(var)
        if v is None or v == "":
            continue
        try:
            setattr(cfg, attr, conv(v))
        except ValueError:
            raise ConfigError("%s: %r is not a number" % (var, v))
    c = env.get("TODOIST_CACHE")
    if c:
        cfg.cache_dir = None if c == "off" else expand(c, env)
    for var, what in (("TODOIST_TASK_URL", "the task id"), ("TODOIST_SESSION_URL", "the session id")):
        v = env.get(var)  # the same rule as the file's keys: a template without %s would name nothing
        if v and "%s" not in v:
            raise ConfigError("%s: must contain %%s (%s)" % (var, what))


def read_file(path):
    """The parsed, comment-stripped file, or None when there is none. Raises ConfigError."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except ValueError as e:
        raise ConfigError("%s: not JSON: %s" % (path, e))
    except OSError as e:
        raise ConfigError("%s: %s" % (path, e))
    if not isinstance(raw, dict):
        raise ConfigError("%s: the top level must be an object" % path)
    return strip_comments(raw)


def load(explicit=None, env=None):
    """Defaults, then the file, then the environment. Raises ConfigError on the first problem."""
    env = os.environ if env is None else env
    cfg = Config(env)
    cfg.path = config_path(explicit, env)
    raw = read_file(cfg.path)
    if raw is not None:
        cfg.exists = True
        errors, warnings = validate(raw)
        cfg.warnings = warnings
        if errors:
            raise ConfigError("%s: %s" % (cfg.path, errors[0]))
        apply_file(cfg, raw, env)
        cfg.raw = raw
    apply_env(cfg, env)
    return cfg


def safe_load(explicit=None, env=None):
    """load(), but a problem lands in cfg.error and the defaults (with the environment) stand."""
    env = os.environ if env is None else env
    try:
        return load(explicit, env)
    except ConfigError as e:
        cfg = Config(env)
        cfg.path = config_path(explicit, env)
        cfg.exists = os.path.exists(cfg.path)
        cfg.error = str(e)
        try:
            apply_env(cfg, env)
        except ConfigError:
            pass
        return cfg


def check(path, env=None):
    """(errors, warnings) for the file at path: every validation error, plus a parse or environment error."""
    env = os.environ if env is None else env
    try:
        raw = read_file(path)
    except ConfigError as e:
        return [str(e)], []
    errors, warnings = validate(raw) if raw is not None else ([], [])
    try:
        cfg = Config(env)
        apply_env(cfg, env)
    except ConfigError as e:
        errors.append(str(e))
    return errors, warnings


def reload(explicit=None, env=None):
    """safe_load() into the shared `cfg`, in place, so every module that imported it sees the named file."""
    new = safe_load(explicit, env)
    cfg.__dict__.clear()
    cfg.__dict__.update(new.__dict__)
    return cfg


def example(project="Tasks"):
    """The file config init writes: every section, the defaults spelled out, comments in _ keys."""
    return {
        "version": VERSION,
        "_": "invoke-todos account config (docs/spec-config.md). Keys starting with _ are comments. "
             "Paths may start with ~. Everything omitted takes its default.",
        "backend": "todoist",
        "account": {"name": "personal"},
        "todoist": {
            "_": "where the API token comes from: env (TODOIST_API_TOKEN), keychain (macOS), file (mode 0600) or "
                 "command (a program that prints it); the token itself never goes in this file",
            "token": {"source": "keychain" if sys.platform == "darwin" else "file", "item": "TODOIST_API_TOKEN"},
        },
        "defaults": {"_": "the project the task verbs run under; --in PROJECT overrides it per run",
                     "project": project},
        "projects": {
            "_": "the projects that are task lists and the areas (sections, one lowercase word each) they are "
                 "expected to have",
            project: {"role": "work", "areas": ["inbox", "tools", "writing"]},
        },
        "attributes": {
            "_": "the house vocabulary: labels for effort and mode, free kinds, what priority means",
            "effort": {"prefix": "effort-", "values": list(DEFAULT_EFFORTS), "meaning": dict(DEFAULT_EFFORT_MEANING)},
            "mode": {"values": list(DEFAULT_MODES), "meaning": dict(DEFAULT_MODE_MEANING)},
            "kinds": {"known": list(DEFAULT_KINDS), "create_missing": True},
            "priority": {"meaning": "value"},
        },
        "provenance": {
            "_": "src and since ride in one task comment; a session id in src becomes an Origin link through "
                 "url_template (a %s template), or no link when null",
            "comment": True, "origin_link": "Origin", "src": {"url_template": None},
        },
    }


# The config of this run: the defaults, the file, the environment. cli.main reloads it when --config is given.
cfg = safe_load()
