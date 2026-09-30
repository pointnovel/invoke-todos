"""The entry point: the config of the run, the backend it names, that backend's flag sets and verbs, the dispatch.
`todos`, `python3 -m invoke_todos` and the console script all call main()."""
import signal
import sys

from invoke_todos import backends
from invoke_todos.args import parse_args
from invoke_todos.config import cfg, reload
from invoke_todos.model import fields_help
from invoke_todos.output import die
from invoke_todos.verbs import HANDLERS

NEEDS_PROJECT = ("add", "list", "ls", "edit", "import", "export", "areas", "lists", "stats", "brief")


def run(argv):
    """One invocation: help, the flags, --config, --fresh, --in, then the verb. The backend is the one the
    startup config names; a file given with --config may only name the same one (the config validates it)."""
    backend = backends.load(cfg.backend)
    backend.register_verbs()
    if not argv or argv[0] in ("help", "--help", "-h"):
        print(fields_help() if argv[1:2] == ["fields"] else backend.usage())
        return
    a = parse_args(argv, backend.VALUE_FLAGS, backend.BOOL_FLAGS)
    if a.first("config") is not None:
        reload(a.first("config"))
    if a.has("help"):
        print(backend.usage())
        return
    verb = a.pos[0] if a.pos else ""
    if cfg.error and verb != "config":
        die("config: %s (todos config check)" % cfg.error)
    cfg.fresh = a.has("fresh")
    cfg.links = a.has("links")
    if a.first("in") is not None:
        cfg.in_project = cfg.project = a.first("in").strip() or die("--in needs a project name or id")
    if verb not in HANDLERS:
        die("unknown verb %s\n\n%s" % (verb or '""', backend.usage()))
    if verb in NEEDS_PROJECT and not cfg.project and not (verb == "stats" and a.has("account")) \
            and not (verb == "brief" and a.has("all-projects")):
        die("no default project: set defaults.project in %s (todos config init writes one), set TODOIST_PROJECT, "
            "or pass --in PROJECT" % cfg.path)
    HANDLERS[verb](a)


def main(argv=None):
    """The process entry: a closed pipe ends the run quietly (SIGPIPE's default), Ctrl-C exits 130."""
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    try:
        run(sys.argv[1:] if argv is None else argv)
    except KeyboardInterrupt:
        die("interrupted", 130)
