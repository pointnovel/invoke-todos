"""config, setup and doctor: the account config (docs/spec-config.md sec. 6), what the account lacks, the health check."""
import json
import os
import shutil
import sys

import invoke_todos
from invoke_todos import config as _config
from invoke_todos.args import sub
from invoke_todos.backends.todoist.api import call, new_cmd, write
from invoke_todos.backends.todoist.auth import find_token
from invoke_todos.backends.todoist.state import project_count, read_state
from invoke_todos.config import DEFAULT_EFFORTS, WORD, cfg
from invoke_todos.output import die, err, need_yes, print_json
from invoke_todos.verbs import register

REPO = os.path.dirname(os.path.dirname(os.path.abspath(invoke_todos.__file__)))  # the tree the package runs from


def active_projects(st):
    return [p for p in st.projects if not p.get("is_archived")]


def project_by_name(st, name):
    for p in active_projects(st):
        if (p.get("name") or "").lower() == name.lower():
            return p
    return None


def sections_of(st, pid):
    return [s for s in st.all_sections.values() if s.get("project_id") == pid and not s.get("is_archived")]


def vocabulary_labels():
    """Every label the config's vocabulary names: the effort labels, the modes, the known kinds."""
    return [cfg.effort_prefix + e for e in cfg.efforts] + list(cfg.modes) + list(cfg.kinds)


def propose(st):
    """config init --from-account: a config built from the account, and the notes to print with it."""
    notes = []
    projects, open_by = {}, {}
    for p in active_projects(st):
        if p.get("inbox_project"):
            continue
        secs = sections_of(st, p["id"])
        usable = [s["name"] for s in secs if WORD.match(s.get("name") or "")]
        other = [s["name"] for s in secs if not WORD.match(s.get("name") or "")]
        projects[p["name"]] = {"areas": usable}
        open_by[p["name"]] = len([i for i in st.all_items if i.raw.get("project_id") == p["id"]])
        notes.append("project %s: %d open; areas: %s%s" % (
            p["name"], open_by[p["name"]], ", ".join(usable) or "none",
            '; sections not usable as areas: %s' % ", ".join('"%s"' % x for x in other) if other else ""))
    default = max(sorted(open_by), key=open_by.get) if open_by else None
    labels = [l.get("name") or "" for l in st.label_rows]
    prefix = cfg.effort_prefix.lower()
    effort_set = {l.lower() for l in labels if l.lower().startswith(prefix) and len(l) > len(prefix)}
    efforts = [l[len(prefix):] for l in labels if l.lower() in effort_set]
    two = set(cfg.modes[:2])
    used, with_mode = set(), set()
    for i in st.all_items:
        ls = [x.lower() for x in i.raw.get("labels") or []]
        used.update(ls)
        if two & set(ls):
            with_mode.update(ls)
    candidates = sorted(l for l in used if WORD.match(l) and l not in effort_set and l not in two and l not in with_mode)
    kinds = sorted(l for l in labels if WORD.match(l) and l not in effort_set and l not in two and l not in candidates)
    raw = _config.example(default or "Tasks")
    if projects:
        raw["projects"] = dict([("_", raw["projects"]["_"])] + sorted(projects.items()))
        notes.append("default project: %s (the most open tasks)" % default)
    else:
        notes.append("no project besides the inbox: the placeholder project Tasks and its areas stay; rename them "
                     "(todos setup apply creates what is missing)")
    if efforts:
        raw["attributes"]["effort"]["values"] = efforts
        if sorted(e.lower() for e in efforts) != sorted(e.lower() for e in DEFAULT_EFFORTS):
            raw["attributes"]["effort"].pop("meaning", None)
        notes.append("effort: %s (from the labels %s)" % ("|".join(efforts), ", ".join(cfg.effort_prefix + e for e in efforts)))
    else:
        notes.append("effort: the defaults %s (no %s* labels in the account)" % ("|".join(cfg.efforts), cfg.effort_prefix))
    found = [m for m in cfg.modes[:2] if m in {l.lower() for l in labels}]
    notes.append("modes: the defaults %s written; in the account: %s; third-mode candidates (labels never on a task with %s): %s"
                 % ("|".join(cfg.modes), ", ".join(found) or "none", " or ".join(cfg.modes[:2]), ", ".join(candidates) or "none"))
    if kinds:
        raw["attributes"]["kinds"]["known"] = kinds
        notes.append("kinds: %s (the other one-word labels)" % ", ".join(kinds))
    return raw, notes


def account_drift(st):
    """config check --account: (drift, notes): configured projects and areas the account lacks; labels in use the
    vocabulary does not name; labels the vocabulary names that do not exist yet."""
    drift, notes = [], []
    for name, spec in cfg.projects.items():
        p = project_by_name(st, name)
        if not p:
            drift.append("project %s: not in the account" % name)
            continue
        have = {(s.get("name") or "").lower() for s in sections_of(st, p["id"])}
        for area in spec.get("areas") or []:
            if area.lower() not in have:
                drift.append("project %s: no section %s" % (name, area))
    used = set()
    for i in st.all_items:
        used.update(x.lower() for x in i.raw.get("labels") or [])
    vocab = {x.lower() for x in vocabulary_labels()}
    outside = sorted(used - vocab)
    if outside:
        notes.append("labels in use outside the vocabulary: %s (kinds not in attributes.kinds.known; fine while "
                     "kinds.create_missing holds)" % ", ".join(outside))
    missing = [x for x in vocabulary_labels() if x.lower() not in st.labels]
    if missing:
        notes.append("labels the vocabulary names but the account lacks: %s (todos setup apply creates them)" % ", ".join(missing))
    return drift, notes


def build_plan(st):
    """What setup apply would create: {"projects": [name], "sections": [(project, area)], "labels": [name], "caps": [why]}."""
    plan = {"projects": [], "sections": [], "labels": [], "caps": []}
    for name, spec in cfg.projects.items():
        p = project_by_name(st, name)
        have = {(s.get("name") or "").lower() for s in sections_of(st, p["id"])} if p else set()
        if not p:
            plan["projects"].append(name)
        for area in spec.get("areas") or []:
            if area.lower() not in have:
                plan["sections"].append((name, area))
    seen = set()
    for label in vocabulary_labels():
        if label.lower() not in st.labels and label.lower() not in seen:
            plan["labels"].append(label)
            seen.add(label.lower())
    limits = st.plan()

    def cap(key, count, what):
        top = limits.get(key)
        if isinstance(top, int) and count > top:
            plan["caps"].append("%s would pass the plan's %s (%d on plan %s)" % (what, key, top, limits.get("plan_name") or "?"))

    if plan["projects"]:
        cap("max_projects", project_count(st) + len(plan["projects"]), "%d new project(s)" % len(plan["projects"]))
    for name in sorted({n for n, _ in plan["sections"]}):
        p = project_by_name(st, name)
        have = len(sections_of(st, p["id"])) if p else 0
        new = len([1 for n, _ in plan["sections"] if n == name])
        cap("max_sections", have + new, "%d new section(s) in %s" % (new, name))
    if plan["labels"]:
        cap("max_labels", len(st.label_rows) + len(plan["labels"]), "%d new label(s)" % len(plan["labels"]))
    return plan


def plan_lines(plan):
    return (["create project %s" % n for n in plan["projects"]]
            + ["create section %s in %s" % (a, n) for n, a in plan["sections"]]
            + ["create label %s" % l for l in plan["labels"]])


@register("config")
def cmd_config(a):
    """config path | show [--json] | check [--account] | init [--out PATH] [--from-account] [--force]."""
    v = sub(a, "show")
    if v == "path":
        print("%s%s" % (cfg.path, "" if cfg.exists else "  (no file: the defaults and the environment apply)"))
        return
    if v == "show":
        if cfg.error:
            die("config: %s (todos config check)" % cfg.error)
        print_json(cfg.effective(), pretty=not a.has("json") or a.has("pretty"))
        return
    if v == "check":
        errors, warnings = _config.check(cfg.path)
        for w in warnings:
            err("warning: " + w)
        for e in errors:
            err("error: " + e)
        if errors:
            die("%d error(s) in %s" % (len(errors), cfg.path))
        print("ok: %s%s" % (cfg.path, "" if cfg.exists else " (no file: the defaults and the environment apply)"))
        if a.has("account"):
            drift, notes = account_drift(read_state())
            for d in drift:
                print("drift: " + d)
            for n in notes:
                print("note: " + n)
            if drift:
                die("%d drift item(s); todos setup plan shows what setup apply would create" % len(drift))
            print("ok: the account has every configured project and area")
        return
    if v == "init":
        out = os.path.abspath(os.path.expanduser(a.first("out") or cfg.path))
        if os.path.exists(out) and not a.has("force"):
            die("%s exists; --force overwrites it" % out)
        if a.has("from-account"):
            raw, notes = propose(read_state())
            then = "then: edit the modes and whatever the notes could not decide, and run: todos config check --account"
        else:
            raw, notes = _config.example(), []
            then = "then: set defaults.project and projects, and run: todos config check"
        try:
            os.makedirs(os.path.dirname(out), mode=0o700, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
        except OSError as e:
            die("cannot write %s: %s" % (out, e))
        print("wrote %s" % out)
        for n in notes:
            print("  " + n)
        print(then)
        return
    die("todos config: path | show [--json] | check [--account] | init [--out PATH] [--from-account] [--force]")


@register("setup")
def cmd_setup(a):
    """setup plan | apply [--yes]: create what the config names and the account lacks (projects, their areas, the
    effort and mode labels, the known kinds); never deletes, renames or moves anything."""
    v = sub(a, "plan")
    if v not in ("plan", "apply"):
        die("todos setup: plan | apply [--yes]")
    st = read_state()
    plan = build_plan(st)
    lines = plan_lines(plan)
    if not lines:
        print("nothing to create: the account has every project, area and label the config names")
        return
    if v == "plan":
        for l in lines:
            print("would " + l)
        for c in plan["caps"]:
            print("cap: " + c)
        print("%d project(s), %d section(s), %d label(s) to create; todos setup apply --yes creates them"
              % (len(plan["projects"]), len(plan["sections"]), len(plan["labels"])))
        if plan["caps"]:
            die("the plan's caps stop it (above); archive or delete something first, or upgrade")
        return
    need_yes(a, lines, "setup apply")
    if plan["caps"]:
        for c in plan["caps"]:
            err("cap: " + c)
        die("the plan's caps stop it; archive or delete something first, or upgrade")
    ids = {(p.get("name") or "").lower(): p["id"] for p in active_projects(st)}
    if plan["projects"]:
        cmds = [new_cmd("project_add", {"name": n}) for n in plan["projects"]]
        mapping = write([[c] for c in cmds])
        for n, c in zip(plan["projects"], cmds):
            ids[n.lower()] = mapping[c["temp_id"]]
    groups = [[new_cmd("section_add", {"name": area, "project_id": ids[n.lower()]})] for n, area in plan["sections"]]
    groups += [[new_cmd("label_add", {"name": l})] for l in plan["labels"]]
    if groups:
        write(groups)
    print("created: %d project(s), %d section(s), %d label(s)" % (len(plan["projects"]), len(plan["sections"]), len(plan["labels"])))


def writable_dir(d):
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        probe = os.path.join(d, ".doctor-%d" % os.getpid())
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


@register("doctor")
def cmd_doctor(a):
    """doctor [--claude]: one line per check (python, config, default project, token source, API and plan, the cache
    folder; --claude: the skill link and todos on PATH); exit 1 when any fails. The token is never printed."""
    fails = []

    def report(ok, what):
        print(("ok:   " if ok else "FAIL: ") + what)
        if not ok:
            fails.append(what)

    report(sys.version_info >= (3, 9), "python %s" % sys.version.split()[0])
    if cfg.error:
        report(False, "config %s: %s" % (cfg.path, cfg.error))
    else:
        report(True, "config %s%s" % (cfg.path, "" if cfg.exists else " (no file: the defaults and the environment apply)"))
    for w in cfg.warnings:
        err("warning: " + w)
    report(bool(cfg.project), "default project: %s" % (cfg.project or "none (defaults.project, TODOIST_PROJECT or --in)"))
    t, why = find_token()
    if t:
        via = "the environment" if os.environ.get(cfg.token_env, "").strip() else "the %s source" % cfg.token_source
        report(True, "token: %d characters from %s" % (len(t), via))
        try:
            r = call("POST", "/sync", form={"sync_token": "*", "resource_types": json.dumps(["user", "user_plan_limits"])})
            plan = (r.get("user_plan_limits") or {}).get("current") or {}
            report(bool(r.get("user")), "api %s: user %s, plan %s (caps: %s projects, %s sections, %s labels)" % (
                cfg.api_base, (r.get("user") or {}).get("id"), plan.get("plan_name"), plan.get("max_projects"),
                plan.get("max_sections"), plan.get("max_labels")))
        except SystemExit:
            report(False, "api %s: unreachable or refused (the message is above)" % cfg.api_base)
    else:
        report(False, "token: " + why)
    if cfg.cache_dir is None:
        report(True, "cache dir: off")
    else:
        ok = writable_dir(cfg.cache_dir)
        report(ok, "cache dir %s%s" % (cfg.cache_dir, "" if ok else ": not writable"))
    if a.has("claude"):
        link = os.path.join(os.path.expanduser("~"), ".claude", "skills", "invoke-todos")
        want = os.path.join(REPO, "skills", "invoke-todos")
        ok = os.path.islink(link) and os.path.realpath(link) == os.path.realpath(want) and os.path.isfile(os.path.join(link, "SKILL.md"))
        report(ok, "skill link %s -> %s%s" % (link, want, "" if ok else ": missing or pointing elsewhere (install.sh links it)"))
        found = shutil.which("todos")
        ok = bool(found) and os.path.realpath(found) == os.path.realpath(os.path.join(REPO, "todos"))
        report(ok, "todos on PATH: %s" % ((found + ("" if ok else " (another todos, not this tree's)")) if found
                                          else "not found (install.sh links it into ~/.local/bin)"))
    if fails:
        die("%d check(s) failed" % len(fails))
