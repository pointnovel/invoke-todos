# Spec: the account config file

One JSON file per account that holds everything personal: which backend (task app) it drives and where that backend's token comes from, the default project, the projects that are task lists, the house vocabulary (areas, kinds, effort, modes, what priority means), provenance settings and paths. The code carries no person's names, projects or labels; the config does. Phase 1 of the refactor plan.

Status: implemented in phase 1 (2026-09-28) as `invoke_todos/config.py` (the loader, validation, `check`, `example`) and the verbs `config path|show|check|init` and `doctor` in the CLI. Phase 4 (2026-09-29) added `config init --from-account`, `config check --account`, `setup plan|apply` and `doctor --claude`; `tests/test_install.py` and `tests/test_todoist.py` cover them. The `projects.*.view`, `export.note`, `hooks` and `paths.state_dir` keys left on 2026-09-29 with the generated views and the hooks (the refactor plan's decision 14); a file that still carries them gets an `unknown key` warning and works.

## 1. Location and precedence

The file in use, first match:

1. `--config PATH` on the command line (any verb).
2. `$TODOS_CONFIG`.
3. `$XDG_CONFIG_HOME/invoke-todos/config.json`, else `~/.config/invoke-todos/config.json`.

No file is not an error: the built-in defaults and the environment apply (this is how the tests run). A task verb that then has no default project stops with `no default project: set defaults.project in <path> (todos config init writes one), set TODOIST_PROJECT, or pass --in PROJECT` (exit 1); the account verbs run without one. A file that does not parse, or fails validation (sec. 7), stops every verb but `config` and `help` with the reason and the path.

Precedence for every value, highest first: the command-line flag (`--in`, `--config`), the environment variable named beside the key below, the file, the built-in default. The backend's environment variables keep the names they have today (`TODOIST_*`), so a script that sets `TODOIST_PROJECT` keeps working, and the test harness needs no file for the knobs it sets.

One file per account. A second account is a second file, chosen with `--config` or `TODOS_CONFIG`; the cache is already keyed by token and API base, so the two never mix.

## 2. Schema

Every key with its type, its default and the environment variable that overrides it. Keys whose name starts with `_` are ignored everywhere (comments in the example file). Unknown keys are reported by `config check` and otherwise ignored.

### `version` (int, required)

`1`. A file with another version is refused.

### `backend` (string)

`"todoist"`, the default and the only backend in 1.0. An unknown name is refused with the list the package knows (`invoke_todos.backends`). The backend's own settings live under a top-level key of the same name (below).

### `account`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | `"default"` | a label for messages and `config show`; not sent anywhere |

### `todoist` (the backend's section)

| Key | Type | Default | Env | Meaning |
|---|---|---|---|---|
| `api_base` | string | `"https://api.todoist.com/api/v1"` | `TODOIST_API_BASE` | the API root; another host is refused by `api` |
| `task_url` | string or null | `null` | `TODOIST_TASK_URL` | a `%s` template turning a task id into the task's link (`show`, the `link` field, `--links`); `null` means the app's web URL, `https://app.todoist.com/app/task/<id>`; `"todoist://task?id=%s"` is the scheme the desktop and mobile apps open a task from |
| `token.source` | `env`, `keychain`, `file`, `command` | `keychain` on macOS, `file` elsewhere | | where the token comes from (sec. 4); `$TODOIST_API_TOKEN`, when set, wins over every source |
| `token.env` | string | `"TODOIST_API_TOKEN"` | | the variable read for `env` and as the override |
| `token.item` | string | `"TODOIST_API_TOKEN"` | | the Keychain service name (the account is the login user) |
| `token.path` | path | `"~/.config/invoke-todos/todoist-token"` | | the token file; refused unless its mode is 0600 |
| `token.command` | list of strings | none | | a program that prints the token on stdout |

A `token.value` key is refused with `the token does not belong in the config file` and the three ways to store it. A second backend gets its own section with its own auth keys; the core reads none of them.

### `defaults`

| Key | Type | Default | Env | Meaning |
|---|---|---|---|---|
| `project` | string | none | `TODOIST_PROJECT` | the project the task verbs run under; `--in` overrides per run. Created on first `add` when missing (as today); `--in` never creates |
| `export` | path or `-` | `"-"` | `TODOIST_EXPORT` | where `export` writes without `--out` |
| `timeout` | number | `30` | `TODOIST_TIMEOUT` | seconds per request |
| `settle` | number | `6` | `TODOIST_SETTLE` | seconds a new task must age before its title or due changes |
| `max_wait` | int | `20` | `TODOIST_MAX_WAIT` | the longest `Retry-After` waited out (beyond it, exit 75) |
| `title_max` | int | `60` | | the title cap (`--force` makes it a warning) |

### `paths`

| Key | Type | Default | Env | Meaning |
|---|---|---|---|---|
| `cache_dir` | path or `off` | `$XDG_CACHE_HOME/invoke-todos`, else `~/.cache/invoke-todos` | `TODOIST_CACHE` | the account cache, one 0600 file per token and API base |

### `projects`

An object keyed by project name as it is in the task app (matched without regard to case). The task verbs do not need a project listed here to work on it; listing one is what gives it an expected set of areas and a place in `setup` and in the skill's vocabulary.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `areas` | list of strings | `[]` | the sections the project is expected to have: one lowercase word each; `setup apply` creates the missing ones, `config check --account` reports drift |
| `role` | string | none | free text the skill may quote (`"work"`, `"life"`) |

### `attributes`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `effort.prefix` | string | `"effort-"` | the label prefix |
| `effort.values` | list | `["S", "M", "L"]` | the values, matched without regard to case, stored as given |
| `effort.meaning` | object | S under an hour, M a session, L several | text for the skill and `help` |
| `mode.values` | list | `["unattended", "assisted", "owner"]` | the mode labels, lowercase single words, in the order: an agent alone, a human mid-way, only the human |
| `mode.meaning` | object | as above | text for the skill and `help` |
| `kinds.known` | list | `["decision", "verify", "build", "write", "parked"]` | kinds the skill suggests and `setup apply` pre-creates; any other kind is still accepted and created on first use when `create_missing` holds |
| `kinds.create_missing` | bool | `true` | today's behaviour; `false` refuses a kind that has no label yet |
| `kinds.meaning` | object | none | text for the skill |
| `priority.meaning` | string | `"value"` | what `--prio 1..3` stands for, for the skill and the export header; the mapping to the app's own scale does not change |

The CLI reads modes and efforts by membership in these lists: `--mode` validation, `reserved_label`, `decompose_labels`, `parse_meta` and the `labels edit|rm` guard all use `cfg.modes` and `cfg.efforts`. Renaming a value in the config after tasks exist means relabelling those tasks (`labels rename-shared` or an `export`, edit, `import --update` loop); `config check --account` says which labels in use are not in the config.

### `provenance`

| Key | Type | Default | Env | Meaning |
|---|---|---|---|---|
| `comment` | bool | `true` | | keep `src` and `since` in one task comment (`src: X; since: D`); `false` drops both fields from `add` and the export bracket |
| `origin_link` | string | `"Origin"` | | the link text ending the description; the two older forms are always read |
| `src.url_template` | string or null | `null` | `TODOIST_SESSION_URL` | a `%s` template turning a session id (8 hex characters, or a UUID) into the Origin link; `null` means no link from `--src`, only from `--url` |

## 3. Example

`examples/config.example.json` ships with the repo; this is its shape (the `_` keys are its comments):

```json
{
  "version": 1,
  "_": "invoke-todos account config. Keys starting with _ are comments. Paths may start with ~.",
  "backend": "todoist",
  "account": {"name": "personal"},
  "todoist": {
    "token": {"source": "keychain", "item": "TODOIST_API_TOKEN"}
  },
  "defaults": {"project": "Tasks"},
  "projects": {
    "Tasks": {"role": "work", "areas": ["inbox", "tools", "writing"]},
    "Home": {"role": "life", "areas": ["house", "money", "health"]}
  },
  "attributes": {
    "effort": {"values": ["S", "M", "L"]},
    "mode": {"values": ["unattended", "assisted", "owner"],
             "meaning": {"unattended": "an agent finishes it alone",
                         "assisted": "an agent starts it and needs you mid-way",
                         "owner": "only you can: pay, sign, call"}},
    "kinds": {"known": ["decision", "verify", "build", "write", "parked"]}
  },
  "provenance": {"src": {"url_template": null}}
}
```

Everything omitted takes its default from sec. 2.

## 4. Token sources

`backends/todoist/auth.py`'s `token()` returns the token once per run and never prints it.

1. `$TODOIST_API_TOKEN` (or `token.env`) when set: used as is, whatever `token.source` says. This is the override for one command and the test harness's route.
2. `keychain`: `security find-generic-password -a "$USER" -s <item> -w` through `/usr/bin/security`; only on macOS. The message on a miss names the line that stores it: `security add-generic-password -a "$USER" -s TODOIST_API_TOKEN -w` (typed in the user's own terminal; the `-w` without a value prompts). `TODOIST_NO_KEYCHAIN=1` turns the source off for one command.
3. `file`: the file's content, stripped; refused when the file's mode has group or other bits, with the `chmod 600` line.
4. `command`: `subprocess.run(token.command, capture_output=True, timeout=15)`; the first line of stdout. The README says this runs a program of the user's choosing from the user's own config file.

A miss on the chosen source (and no env override) stops with one message naming the source and the three ways to store the token. A 401 keeps today's message, with the storing line for the chosen source instead of the private helper.

## 5. What reads the config

- `config.py` at startup: defaults, the file, the environment, then `--config` and `--in`; validation (sec. 7) before any verb runs. `cli.py` reads `backend` and loads that package.
- The vocabulary readers in the core's `model.py` (`reserved_label`, `compose_labels`, `decompose_labels`), `args.py` (`validate`) and `importer.py` (`parse_meta`), and the backend's `usage.py`.
- The backend's `auth.py` and `api.py`: its own section (`todoist.token`, `todoist.api_base`) and the `defaults` it needs (`timeout`, `settle`, `max_wait`); `items.py` reads `todoist.task_url` (`Item.link`).
- The skill: it does not read the file; it tells the agent to run `todos config show` once per session and use the project names and vocabulary it prints.
- `install.sh`: nothing; it links files and, with `--config`, runs `config init` when no file exists.

## 6. Verbs

All under `todos config ...`, `todos setup ...` and `todos doctor`; the backend's `verbs/setup.py`, calling the core's `config.py` for the generic parts (path, show, validation) and the backend for what needs the account.

| Verb | What |
|---|---|
| `config path` | the path in use (sec. 1) and whether it exists |
| `config show [--json]` | the effective config (defaults, file and environment merged, with the path, the warnings and the error if any; the token source shown, never the token), as pretty JSON, compact with `--json` |
| `config check [--account]` | validation (sec. 7): every error and warning, exit 1 on an error; with `--account` (phase 4), drift against the live account: configured projects and areas that do not exist, labels in use that are not in the config's vocabulary |
| `config init [--out PATH] [--from-account] [--force]` | writes a config: without `--from-account`, the example (sec. 3, every section spelled out with its defaults and comments, a placeholder project `Tasks`); with it (phase 4), one built from the account by the backend (below). Refuses to overwrite without `--force` |
| `setup plan` | what `setup apply` would create: projects named in `projects` that do not exist, their listed areas, the effort and mode labels, the known kinds; each checked against the plan's caps (`max_projects`, `max_sections`, `max_labels`) before anything is sent |
| `setup apply --yes` | creates it (Sync commands through `write`, batched); never deletes, renames or moves anything; exit 2 without `--yes` after printing the plan |
| `doctor [--claude]` | one line per check (`ok:` or `FAIL:`), exit 1 on a failure: Python version, config path and validation, the default project, the token source reachable (the token itself unread beyond a length check), the API reachable (`user` from a sync), the plan name and the caps that matter (projects, sections, labels), the cache dir writable; with `--claude`, the skill link `~/.claude/skills/invoke-todos` pointing into this tree and `todos` on PATH resolving to this tree's launcher |

`config init --from-account` reads one full sync (projects, sections, labels, items) and proposes:

- `projects`: every active project but the inbox, each with `areas` set to its section names that are one lowercase word (others are listed in the output as "sections not usable as areas").
- `defaults.project`: the project with the most open tasks.
- `attributes.effort`: labels matching `<prefix><value>` for the default prefix; if none, the defaults.
- `attributes.mode`: the written file keeps the defaults; the output says which of the first two default modes exist as labels, and lists as third-mode candidates the one-word labels that appear on tasks but never on a task carrying one of those two (a mode excludes the others), for the user (or the onboarding agent) to pick.
- `attributes.kinds.known`: the remaining labels that are one lowercase word.

It prints what it wrote, what it could not decide, and the `config check --account` line to run after editing.

## 7. Validation

`config check`, and the loader before any verb:

- `version` is 1; `backend` is a known name; the top-level keys are known (unknown ones are named, with a warning, not an error).
- `attributes.mode.values`: one or more lowercase single words, distinct, none starting with the effort prefix. `attributes.effort.values`: distinct, none empty, matched without regard to case. `kinds.known`: single words.
- `projects`: names non-empty; `areas` one lowercase word each.
- `defaults.project`, when set, is a non-empty string (it need not appear in `projects`).
- `todoist.token.source` is one of the four; `file` names a path; `command` is a non-empty list.
- `todoist.task_url`, when not null, is a string containing `%s`; so are `TODOIST_TASK_URL` and `TODOIST_SESSION_URL` in the environment.
- `paths.*` expand to absolute paths; `cache_dir` may be `off`.
- Numbers are numbers and positive; `title_max` at least 20.

The first error stops the run with the key path and the value, as in `attributes.mode.values[2]: "Big Rock" is not one lowercase word`.

## 8. Known limits

- The export bracket carries modes by name. An export written under one config and imported under another whose modes differ reads those words as kinds. `import --dry` shows it (`labels=...`); the fix is to run both under the same config.
- `config init --from-account` cannot know which labels are modes beyond the two default names; the third is proposed, not chosen.
- `setup apply` creates; it never fixes drift the other way (an account section that the config does not list stays).
- The Keychain source is macOS only; on another OS the loader treats `keychain` as a validation error naming `file` and `command`.
