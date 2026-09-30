# Spec: the module split

Status: implemented by phase 2 (2026-09-28). The tree differs from sec. 2 and 3 in these places: `upload` sits in `verbs/comments.py` beside its two callers, not in `api.py`, because it needs `state.require` and `state` sits below `api` (rule 4); `exporter.py` holds `export_markdown` and `STAMP_RE` only, since `cmd_export` moved whole into `verbs/tasks.py` (rule 1) and there is no `write_view`/`export_views` split (the standing views left with decision 14); `model.py` also holds the vocabulary readers phase 1 added after this spec was written (`norm_effort`, `norm_mode`, `effort_of_label`) and `link_re()` is a function, not the constant `LINK_RE`, because it reads the config; `NEEDS_PROJECT` (the verbs that need a default project) lives beside `main` in `cli.py`; `config.py` exposes `cfg` and `reload()` (the in-place refill `--config` uses) but no `batch`, `done_window_days` or `backend_conf` attributes, which the code never needed (`BATCH` is in `api.py`, `DONE_WINDOW_DAYS` in `state.py`); the backend's `__init__.py` exposes `USAGE_TEXT` and the callable `usage()` rather than a filled `USAGE`, since the text reads the config at call time; `hooks/`, `test_view_guard.py` and `test_shell_paths.py`, once planned for phase 3, were dropped with the hooks on 2026-09-29 (the refactor plan's decision 14); the lines below that named them are gone.

What `todoist`, one 3,939-line file, becomes: a package `invoke_todos/` (the core) with `invoke_todos/backends/todoist/` (the first backend) behind a launcher `todos`, with no change in what any verb does or prints. Phase 2 of the refactor plan; the config layer it builds on is `spec-config.md`; the core/backend line is the plan's decision 13.

## 1. Rules of the split

1. Functions move whole and keep their names. A verb body is not rewritten in this phase; only the names it reaches change from module globals to imports.
2. No new behaviour, no new flags, no new output. The offline suite (`tests/test_todoist.py`), which drives the CLI as a subprocess, is the oracle: it changes only where the fixture config, the renamed literals of phase 1 and the launcher's name require.
3. Python 3.9, standard library only, no third-party packages, no build step to run from a clone.
4. No import cycles. The module order in sec. 3 is the dependency order: a module imports only modules above it.
5. The core never imports a backend. A backend imports the core freely. `cli.py` is the one place that names a backend, through `backends.load(cfg.backend)`. A test greps `invoke_todos/*.py` and `invoke_todos/hooks/` for the word `backends` and allows it in `cli.py` only.
6. Mutable run-state (today's `PROJECT`, `IN_PROJECT`, `FRESH`, `_token`) lives in one place, the `Config` instance of `config.py`, and nowhere else (the backend's `_token` cache lives in its `auth.py`).
7. One flag namespace stays: `VALUE_FLAGS` and `BOOL_FLAGS` remain two sets, owned by the backend (copied from today, verbatim) and handed to the core's `parse_args`. (Per-verb flag declarations are a possible later refinement; not in this phase, because a missed flag would change an "unknown flag" outcome.)

## 2. The tree

```
todos                           the launcher (sec. 5)
invoke_todos/                   the core
  __init__.py                   __version__ (the release version)
  __main__.py                   python3 -m invoke_todos
  output.py                     err, die, print_json, emit, redact, SECRET_KEYS, need_yes
  dates.py                      parse_day, parse_due, parse_ts, due_view, ymdhm, utc, now, FAR, NEAR, parse_window, parse_duration
  config.py                     Config, load, defaults, precedence, cfg (spec-config.md)
  model.py                      the house attributes and the tree functions (sec. 3)
  args.py                       Args, parse_args, the generic flag readers
  query.py                      apply_filters, sort_items
  render.py                     ref, line, when
  importer.py                   the import grammar: parse_meta, parse_seed, parse_json_seeds
  exporter.py                   export_markdown, STAMP_RE
  verbs.py                      HANDLERS and the register decorator
  cli.py                        main
  backends/
    __init__.py                 load(name) -> the backend package; the names it knows
    todoist/
      __init__.py               NAME, VALUE_FLAGS, BOOL_FLAGS, USAGE, register_verbs()
      auth.py                   token sources
      api.py                    HTTP, Sync commands, uploads, downloads
      items.py                  Item, api_prio, user_prio, TASK_URL, COLORS
      state.py                  State, the cache, read_state, fetch_done, ensure, the plan gates, the resolvers and lookups
      flags.py                  task_extras, color_flag
      query.py                  server_filter
      mutations.py              task_group, edit_plan, reschedule_due, check_parent, changed_fields, created_item
      render.py                 show_item and the account-object line renderers
      usage.py                  USAGE, assembled from config
      verbs/
        __init__.py             imports every verb module, in the usage text's order
        tasks.py                add, quick, list, show, done, undone, rm, edit, reschedule, move, assign, order, import, export, search, overview, stats, areas, brief
        projects.py             projects, people, share
        sections.py             sections
        labels.py               labels
        comments.py             comments, uploads
        reminders.py            reminders (+ reminder_args, reminder_allowed)
        filters.py              filters
        activity.py             activity
        user.py                 user, notifications (+ USER_KEYS, SETTING_KEYS)
        views.py                views (+ view_target, view_args)
        workspace.py            templates, backups, emails, folders, workspaces, ids, billing
        api.py                  api (+ DESTRUCTIVE_COMMANDS)
        setup.py                config, setup, doctor (new; spec-config.md sec. 6)
```

Beside the package, at the repo root: `skills/invoke-todos/SKILL.md`, `tests/`, `docs/`, `examples/`, `install.sh`, `scripts/pack.sh`, `ONBOARDING.md`, `README.md`, `LICENSE`, `pyproject.toml`, `.gitattributes`, and after 1.0 `.claude-plugin/`.

## 3. Every function's home

In dependency order. "From" is the section marker of the monolith the function sits under today. Core first, then the backend.

| Module | From | Contents |
|---|---|---|
| `output.py` | output and exit; the API; the task view | `err`, `die`, `print_json`, `emit`, `redact`, `SECRET_KEYS`, `need_yes` |
| `dates.py` | dates; argument parsing | `parse_day`, `parse_due`, `parse_ts`, `due_view`, `ymdhm`, `utc`, `now`, `FAR`, `NEAR`, `parse_window`, `parse_duration` |
| `config.py` | configuration | `Config` (every constant of the configuration block as an attribute: `backend`, `project`, `in_project`, `export_path`, `src_url_template`, `timeout`, `modes`, `efforts`, `effort_prefix`, `kinds`, `title_max`, `batch`, `done_window_days`, `max_wait`, `settle`, `cache_dir`, `state_dir`, `projects`, `fresh`, `links`, `task_url`, and the backend's own section as `cfg.backend_conf`), `load()`, `cfg` (the instance the run uses) |
| `model.py` | session links; attributes; the task view; the task verbs | `LINK_RE`, `FENCE_RE`, `BLOCK_RE`, `session_url`, `split_description`, `join_description`, `ATTR_LINE_KEYS`, `parse_attr_line`, `encode_note`, `attr_note`, `reserved_label`, `compose_labels`, `decompose_labels`, `length_problems`, `check_lengths`, `normalize_area`, `uniq`, `FIELDS`, `DEFAULT_FIELDS`, `BRIEF_FIELDS`, `FIELD_DOC`, `fields_help` (phase 4), `assign_short_ids`, `link_tree`, `descendants`, `top_level`, `with_subtasks` (the tree functions are duck-typed over `id`, `parent`, `children`, `order`, `created`, `depth`, `area`, `short`) |
| `args.py` | argument parsing; account-wide lookups | `Args`, `parse_args(argv, value_flags, bool_flags)`, `validate`, `attrs_from`, `parse_prio`, `due_flag`, `deadline_flag`, `read_text`, `read_note`, `onoff`, `favorite_flag`, `sub`, `arg`, `kv_pairs`, `picked`, `fields_from` |
| `query.py` | filtering and sorting | `apply_filters`, `sort_items` |
| `render.py` | rendering; account-wide lookups | `ref` (the short id, or the markdown link under `--links`), `line`, `when` |
| `importer.py` | import grammar | `blank_seed`, `BULLET_RE`, `META_RE`, `parse_meta`, `parse_seed`, `parse_json_seeds` |
| `exporter.py` | the task verbs | `export_markdown`, `STAMP_RE` |
| `verbs.py` | commands | `HANDLERS`, `register` (sec. 4) |
| `backends/__init__.py` | new | `load(name)`: imports `invoke_todos.backends.<name>`, refuses an unknown name with the known list |
| `backends/todoist/auth.py` | the API | `token()` and the four sources (spec-config.md sec. 4) |
| `backends/todoist/api.py` | the API; comments and uploads | `retry_after`, `call`, `rest`, `rows_of`, `pages`, `multipart`, `read_file`, `new_cmd`, `describe`, `write`, `upload`, `download` |
| `backends/todoist/items.py` | priority; the task view; configuration | `api_prio`, `user_prio`, `TASK_URL`, `COLORS`, `Item` (the raw Todoist item read into the house view) |
| `backends/todoist/state.py` | the task view; account-wide lookups; the task verbs | `LISTS`, `SINGLES`, `RESOURCES`, `CACHE_VERSION`, `State`, `cache_path`, `obj_key`, `merge`, `read_state`, `fetch_done`, `ensure`, `require`, `within`, `user_id`, `resolve_user`, `resolve_in`, `task_ref`, `resolve`, `subtree`, `task_notes`, `find_project`, `find_section`, `find_label`, `find_filter`, `find_comment`, `find_reminder`, `other_section`, `open_in` |
| `backends/todoist/flags.py` | argument parsing; account-wide lookups | `task_extras` (plan-checked, resolves users), `color_flag` (Todoist's named colors) |
| `backends/todoist/query.py` | the task verbs | `server_filter` |
| `backends/todoist/mutations.py` | mutations | `task_group`, `check_parent`, `edit_plan`, `reschedule_due`, `changed_fields`, `created_item` |
| `backends/todoist/render.py` | rendering; each account section's `*_line` | `show_item`, `project_line`, `section_line`, `label_line`, `comment_line`, `is_attr_note`, `task_comments`, `comment_block`, `comment_view`, `reminder_line`, `filter_line`, `activity_line`, `notification_line` |
| `backends/todoist/usage.py` | commands | `USAGE`, built from `cfg` (the default project name, the title cap, the mode names) |
| `backends/todoist/verbs/*.py` | the `cmd_*` functions | as listed in sec. 2, each moved whole; `cmd_import` moves whole into `verbs/tasks.py` (splitting its planning half into the core's `importer.py` is a later refinement) |
| `backends/todoist/__init__.py` | argument parsing; commands | `NAME = "todoist"`, `VALUE_FLAGS`, `BOOL_FLAGS` (today's two sets, verbatim), `USAGE` (re-exported), `register_verbs()` (imports `verbs/`, which registers every handler) |
| `cli.py` | commands | `main(argv=None)`: `--config`, `cfg` loaded, the backend loaded and its verbs registered, help, `parse_args` with the backend's sets, `cfg.fresh`, `cfg.links`, `--in`, the dispatch; the `SIGPIPE` and `KeyboardInterrupt` handling from the file's foot |

Where a verb module needs a helper that another verb module owns today (`cmd_share` and `cmd_projects` both reach `cmd_people`; `cmd_filters run` reaches `cmd_list`; `cmd_sections rename` reaches `cmd_areas`), the module imports the verb function from its sibling. None of these form a cycle: `projects` imports nothing from `filters`, `filters` imports `tasks`, `sections` imports `tasks`.

`line()` is core because it renders the house view (short id, done, priority, due, area, kinds, effort, mode, title) from attributes every backend's item view must carry; `show_item` is backend because it reaches the state for the parent, the comments and the reminders.

## 4. The registry

`verbs.py` in the core:

```python
HANDLERS = {}

def register(*names):
    def wrap(fn):
        for n in names:
            HANDLERS[n] = fn
        return fn
    return wrap
```

Each backend verb module decorates its handlers (`@register("list", "ls")`, `@register("areas", "lists")`, `@register("assign", "unassign")`, and so on, exactly the alias table of today's `HANDLERS`). The backend's `verbs/__init__.py` imports every verb module once, in the order the usage text lists them, so registration is deterministic; `register_verbs()` is what `cli.py` calls after loading the backend. An unknown verb still prints `unknown verb X` and the usage.

## 5. The launcher and packaging

`todos`, at the repo root, executable:

```python
#!/usr/bin/env python3
import os
import sys
if sys.version_info < (3, 9):
    sys.exit("todos needs Python 3.9 or later; this is %s" % sys.version.split()[0])
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from invoke_todos.cli import main  # noqa: E402
if __name__ == "__main__":
    main()
```

`realpath` makes a symlink in `~/.local/bin` resolve to the clone. `__main__.py` calls the same `main`. `pyproject.toml` declares `name = "invoke-todos"`, `requires-python = ">=3.9"`, no dependencies, `[project.scripts] todos = "invoke_todos.cli:main"`, and setuptools as the build backend, so `uv tool install .` and `pipx install .` work; nothing in the repo needs either.

## 6. What the tests need

- `tests/test_todoist.py`: `CLI` becomes `<repo>/todos`; the `cli()` helper adds `TODOS_CONFIG=<repo>/tests/fixtures/config.json` to the environment (phase 1) and keeps the `TODOIST_*` overrides it sets today (they win over the file). Literals: the maintainer's third mode label becomes `owner`, the maintainer's project name becomes `Work`, the `SESSION` template becomes `https://example.com/session?sid=%s`; fixture bodies that name the maintainer's other tools become generic sentences of the same shape.
- `tests/live_smoke.py`: replaces the `SourceFileLoader` of the file with `sys.path.insert(0, <repo>)` and `from invoke_todos.backends.todoist import api`; `HOME_PROJECT` comes from `cfg.project`.
- New: `tests/test_config.py` (spec-config.md sec. 7), `tests/test_public.py` (phase 0, in place), `tests/test_layering.py` (rule 5: the core never imports a backend).
- The mock does not change for the split; the collaborator fixture's name changes for the public-safety test.

## 7. The vendored shell parser (dropped)

Planned for the guard hook, dropped with it on 2026-09-29 (the refactor plan's decision 14). Nothing in the package parses shell.

## 8. Invariants that survive the split

From the README's maintainer notes, restated as what the modules must keep:

- Every write builds Sync commands through `api.new_cmd` and sends them through `api.write` (batches of 100, temp ids mapped across requests, a failed command ends the run after its batch).
- `mutations.edit_plan` is the one place that turns a change spec into commands and sends only what differs; `edit`, `reschedule` and `import --update` all go through it.
- Destructive or bulk writes go through `output.need_yes`; plan gates through `state.require` and `state.within`; every printer through `output.emit` or `output.print_json`, masked by `output.redact`.
- The label names (the effort prefix and values, the mode values), the comment format (`model.encode_note`), the Origin link form (`model.LINK_RE`, which still reads the two older forms) and the export bracket (`importer.parse_meta`) are what every filter, the export and `import --update` read; they read their vocabulary from `cfg`.
- `model.link_tree` builds the tree over the account's open items; `query.sort_items` walks it over any subset. Short ids are assigned over the account, then again over the project.
- The cache holds the whole account; `state.CACHE_VERSION` changes whenever `LISTS` or `SINGLES` do.
