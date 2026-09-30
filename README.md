# invoke-todos

Task lists in Todoist, driven from the shell by people and coding agents alike. `todos` is the command.
It keeps a task list in a Todoist project: one section per area, native labels for the attributes
(effort, mode, kind), subtasks for the steps of a task, a body in markdown as the app renders it, and an
Origin link back to the session or page a task came from. It reads and writes every other object of
the account too (projects, sections, labels, comments, reminders, filters, the activity log, the user,
templates, backups, sharing, workspaces), and reaches any endpoint of the Todoist API through `api`. A
Claude Code skill in the tree teaches an agent the vocabulary and the digest it reads first. Python 3.9
or later, standard library only, nothing to build.

```zsh
todos help                                                       # every verb and flag
todos brief                                                      # the digest: counts, what is due, what an agent could do, this session's tasks
todos list --mode unattended --effort S                          # what an agent could do alone, cheaply
todos add "Renew the passport" --area papers --kind verify --due 2026-10-01 --prio 1 \
    --effort S --mode owner --src <sid8> --note "Where the old one is, what to bring."
todos add "Book the appointment" --parent <id> --effort S --mode owner        # a subtask
todos quick "Renew the parking permit next friday #Home /car p2"             # Todoist's own parser
todos list --filter "today | overdue"                                        # a Todoist query, account-wide
todos api GET /projects                                                      # any endpoint
```

`todos help` prints every verb and flag; this file covers what the help does not: install and setup, the
config, the model, the semantics of the verbs, the import grammar, how the tool talks to Todoist, the
tests, the skill, and the invariants a maintainer keeps. `docs/` holds the specifications and the change
log (`docs/README.md` lists them).

## Install

Requirements: `python3` 3.9 or later on PATH; a Todoist account and its API token (Todoist > Settings >
Integrations > Developer); Claude Code, if the skill is wanted.

From a clone:

```zsh
git clone https://github.com/pointnovel/invoke-todos    # any folder you keep: the links point into it
cd invoke-todos
./install.sh --config
```

From the release archive:

```zsh
shasum -a 256 -c SHA256SUMS                             # sha256sum -c SHA256SUMS on Linux
tar xzf invoke-todos-1.0.1.tar.gz
cd invoke-todos-1.0.1
./install.sh --config
```

`install.sh` (POSIX sh) checks `python3`, links the launcher `todos` into `~/.local/bin` and the skill
`skills/invoke-todos` into `~/.claude/skills`, warns when the bin folder is not on PATH, writes a starting
config with `--config` when none exists, and ends with the next steps. Re-running it is safe: links that
are already right stay as they are.

| Flag | Effect |
|---|---|
| `--bin DIR` | the folder for the command link (default `~/.local/bin`) |
| `--name NAME` | the command's name (default `todos`; for machines where that name is taken) |
| `--skills DIR` | the Claude Code skills folder (default `~/.claude/skills`) |
| `--no-skill` | leave the skill link out (CLI only) |
| `--config` | run `todos config init` when no config exists, and print its path |
| `--force` | replace a file, or a link that points elsewhere; a real folder is never replaced |
| `--dry-run` | run the checks and print each step; change nothing |
| `--uninstall` | remove the links that point into this tree; the tree and the config stay |

Without `--force`, a file or a link to something else stays where it is: the script says why and exits 1
at the end. The same steps by hand:

```zsh
mkdir -p ~/.local/bin ~/.claude/skills
ln -s "$PWD/todos" ~/.local/bin/todos
ln -s "$PWD/skills/invoke-todos" ~/.claude/skills/invoke-todos
todos config init
todos doctor
```

`python3 todos ...` from the clone works with no install at all; `python3 -m invoke_todos` and the
`pyproject.toml` console script (`uv tool install .`, `pipx install .`) are the same entry.

With an agent: paste `ONBOARDING.md` as the first message of a fresh Claude Code session on the machine
where the tool should live. The agent interviews you, writes the config, creates or maps the projects and
labels, wires the links and verifies the result; `docs/spec-onboarding.md` is its protocol.

### The token

`todos` reads `TODOIST_API_TOKEN` from the environment, else the source the config names
(`todoist.token.source`): the login Keychain item `TODOIST_API_TOKEN` through `/usr/bin/security` on
macOS (the default there), a file with mode 0600 (`~/.config/invoke-todos/todoist-token`, the default
elsewhere), or a command that prints it (`pass show todoist`, any secrets manager; the command comes from
your own config file, so its trust is yours). The token is never printed; every miss names the line that
stores it for the chosen source, typed in your own terminal:

```zsh
security add-generic-password -a "$USER" -s TODOIST_API_TOKEN -w    # macOS Keychain; -w alone prompts
```

```zsh
( umask 077; printf 'Todoist token: '; read -rs t; echo; printf '%s' "$t" > ~/.config/invoke-todos/todoist-token )    # the file source; typed unseen, kept out of the history
```

`TODOIST_NO_KEYCHAIN=1` skips the Keychain for one command. `todos doctor` checks Python, the config, the
default project, the token source, the API, the plan's caps and the cache folder, one line per check;
`doctor --claude` adds the skill link and `todos` on PATH.

## Configure

Everything personal lives in one file, `~/.config/invoke-todos/config.json` (`$XDG_CONFIG_HOME` is
honoured; `TODOS_CONFIG` or `--config PATH` names another): the default project, the projects that are
task lists with their areas, the effort and mode labels, the known kinds, what priority means,
provenance, paths and timeouts. `docs/spec-config.md` is its reference and `examples/config.example.json`
a full example with its comments in `_` keys.

- `todos config init` writes that example (`--out PATH`, `--force` to overwrite); `todos config init
  --from-account` proposes one from the account instead: its projects with their one-word sections as
  areas, the project with the most open tasks as the default, the effort labels it finds, the third-mode
  candidates named in the output, the other one-word labels as kinds.
- `todos config check` validates the file (every error with its key path); `config check --account` adds
  the drift against the live account (configured projects and areas it lacks, labels in use outside the
  vocabulary). `todos config show` prints the effective values; `config path` the file in use.
- `todos setup plan` lists what the config names and the account lacks (projects, sections, labels), and
  `todos setup apply --yes` creates it; it never deletes, renames or moves anything, and the plan's caps
  are checked first.

Without a file the defaults and the environment apply, and the task verbs need a project from
`TODOIST_PROJECT` or `--in`. The environment knobs win over the file: `TODOIST_PROJECT` (the default
project), `TODOIST_EXPORT` (the default `export` path), `TODOIST_TIMEOUT` (seconds per request, default
30), `TODOIST_SETTLE`, `TODOIST_MAX_WAIT`, `TODOIST_CACHE`, `TODOIST_API_BASE`, `TODOIST_TASK_URL`, `TODOIST_SESSION_URL`,
`TODOIST_DEBUG`, each explained where it matters below.

## Model

- **Project:** the config's `defaults.project` (`TODOIST_PROJECT` or `--in PROJECT` overrides it; the
  default project is created on first use, `--in` must name an existing project, by name or id). **Areas**
  are its sections, created by `todos add --area x` on first use, matched without regard to case. A second
  project (life beside work, say) is driven the same way through `--in`; the config lists each with its
  areas and a role, and the skill reads them from `config show`. The export's H1 names the project. A
  section whose name has a space goes by `--section "Name"` instead of `--area` (in any project).
- **Native fields:** content = the title (at most 60 characters by default; `defaults.title_max`),
  description = the body (markdown, any length: bold, H1/H2, bulleted and numbered lists, quotes, code
  fences, links are what the app renders; `--note -` reads it from stdin), priority = the task's value
  (`--prio 1..3` = p1, p2, p3 in the apps, p1 the most valuable; none when omitted), due date (`--due
  2026-09-25` or `2026-09-25T18:00`, a floating time, or any phrase Todoist parses: `"tomorrow 9am"`,
  `"every monday"`), deadline (`--deadline`), duration (`--duration 90m|2h|1.5h|3d`), assignee (`--assign
  me|USER`, shared projects), parent task, completion. Deadlines, durations and reminders exist only on
  plans that include them; the CLI reads the account's plan and refuses them before writing (`todos user
  plan` prints the limits). On a plan without reminders a due time is the reminder, and `reminders add
  --before 0m` adds the one at the due time.
- **Recurring tasks** come from a due phrase (`--due "every monday 9am"`); `list` marks them with `~`
  after the date, `show` prints `repeats:`, JSON carries `recur`. A plain `--due DATE` or `reschedule`
  on a recurring task moves its next occurrence and keeps the recurrence (and the time, when the date
  has none); a new phrase replaces it. `done` moves a recurring task to its next occurrence, as the
  apps do; `done --forever` (or `done --at WHEN`, a backdated completion) completes it for good.
- **Labels:** the kinds as given (`decision`, `verify`, `build`, ...), plus the effort labels
  (`effort-S|M|L` by default) and the three modes (`unattended|assisted|owner` by default: an agent alone,
  an agent that needs you mid-way, only you); the config renames any of them (`attributes` in
  `docs/spec-config.md`), and the CLI matches them without regard to case and stores the configured
  spelling. Missing labels are created on first use (as personal, not shared, labels;
  `kinds.create_missing: false` refuses a kind that has no label yet). Labels added in the app become
  kinds; the CLI leaves ones it did not set alone.
- **Origin link:** `[Origin](<url>)` ends the description: on the last line of prose, or on a paragraph
  of its own after a list, heading, quote, table or code fence. The url is `--url`, or the one
  `provenance.src.url_template` (`TODOIST_SESSION_URL`) makes from `--src` when that is a session id: a
  `%s` template pointing at wherever your sessions can be opened; unset, `--src` makes no link. Two older
  forms, `[session <sid8>](<url>)` and `[link](<url>)` on a line of their own, read back the same and are
  rewritten on the task's next edit.
- **Subtasks:** `--parent ID` on `add` and `edit` puts a task under another; it lives in the parent's
  section (so `--area` on a subtask is refused; `--parent ""` detaches it back to its area). `done`
  and `rm` on a parent take the subtasks along, as the app does; reopening a parent leaves its
  completed subtasks done. Any depth.
- **src and since** ride in one task comment, `src: 7e57ab1e; since: 2026-09-22`: out of the
  description, readable when opened. `src` is where the task came from (a session id, a file, a page);
  `since` defaults to the day the task was added. `comments` marks that comment `[attr]` and refuses to
  edit or delete it without `--force`. `provenance.comment: false` drops both.
- **Ids** are Todoist's 16-character task ids; the CLI prints the shortest unique prefix (at least 8
  characters) and accepts any unique prefix: the project's open tasks first, then the whole account's,
  then the project's tasks completed in the last 89 days. `show` prints the app link,
  `https://app.todoist.com/app/task/<id>`, and a task's link works wherever a task id does: the id is
  read from the last path segment (after a title slug, `app/task/<slug>-<id>`) or from `id=`
  (`showTask?id=`, `todoist://task?id=`). Other objects are addressed by name (case-insensitive), id
  or unique id prefix; a section of another project as `project/name`.
- **Links:** the apps cannot search a task by its id, so a bare id in a reply leads nowhere. `--links`
  on any verb makes every task row name its task as a markdown link, `[task#<short>](<link>)`, ready to
  paste into a reply (`list`, `brief`, the lines `add`, `done`, `edit`, `move`, `order`, `import` and
  `reminders add` print, the parent and subtask lines of `show`); without it rows are unchanged, and
  `rm` names a removed task by its id alone. The link is the app's web URL unless
  `todoist.task_url` (`TODOIST_TASK_URL`) names another `%s` template: `todoist://task?id=%s` is the
  scheme Todoist's desktop and mobile apps open a task from. `show`'s id line and the `link` JSON
  field carry the same link. Both forms read back as an id: `task#<short>` and the whole markdown link
  (quoted in a shell; the id is the one its link carries, which the text `task#<short>` finds inside
  a link of any template, and a title after the link is ignored). A template in `TODOIST_TASK_URL` or the file must contain `%s`.

## The task verbs

`quick` sends the text to Todoist's own parser (`POST /tasks/quick`): dates and recurrences in words,
`#Project` (`#My\ Project` with spaces), `/Section`, `@label` (only labels that exist; an unknown one
stays in the title as text), `p1`..`p4`, `+assignee`, `{deadline}`, `!30m` reminders, `// body` at the
end. `--src` adds the src/since comment and the Origin link afterwards. Effort and mode go in the text
as `@effort-S @unattended`, or through `edit` after.

`list --filter` runs a Todoist filter query on the server (`GET /tasks/filter`: `today`, `overdue`,
`p1`, `@label`, `#Project`, `search: text`, `&`, `|`, `!`, parentheses) over the whole account; the
house filters (`--kind`, `--mode`, ...) then narrow the result, and a row outside the current project
shows `project/area`. `--saved NAME` runs a saved filter. `--all-projects` lists the account from the
cache (no extra request). `--grep` searches titles and bodies locally. `--done --by due` reads the
completed-by-due-date endpoint. `search` looks through the cached tasks, projects, sections, labels
and filters at once.

`show ID` is the full view of one task. `--comments` adds its comments, oldest first and in full, without
the src/since one; `--tree` prints the subtasks after the task, each in full under a `# subtask N of M
(depth D)` line, in the app's order; `--tree --all` adds the subtasks completed in the last 89 days. So
`show ID --tree --comments` reads a task, its subtasks and every comment in one call. With `--json`,
`--comments` adds a `comments` list to the task (`id`, `posted`, `content`; `file`, `reactions` and `by`
where there is one) and `--tree` makes the output a list, the task first. Todoist's comments are a flat
list per task: the tree is the subtasks', not replies.

`edit --project P --area A` moves a root task (its subtasks follow) into section A of another project of
the account, run under the project the task is in; `move ID... --to P [--area A]` is the same for many
tasks and creates the section when it is missing. A task of another project resolves by id for `show`,
`done`, `edit` of its fields, `rm`; a move or an area change needs the run under its project (`--in`).
`areas rename` renames a section (the new name one lowercase word); its tasks stay and the export
heading follows. `order` sets the given order among siblings (`--day`: the order in the Today view).

`export` prints the project as markdown in the import grammar below, every row with an `[id ...]`
bracket, to stdout or to `--out PATH` (`defaults.export`, `TODOIST_EXPORT`). `export --out` rewrites the
file only when its tasks changed (a file that differs only in its GENERATED stamp is left alone and the
CLI says `unchanged`), so the stamp is the time of the last change. A standing file mirror of a list, if
you want one, is one cron line, `*/15 * * * * ~/.local/bin/todos export --out ~/notes/tasks.md`; the
file is a copy to read, and `import --update` is the way an edited copy goes back.

`brief` is the digest an agent reads first: a header with the open, overdue and due-today counts and
the open count per area; `# due` (overdue and today, by date); one block per agent mode (the first two
modes of the vocabulary, by value, then effort, then due); `# this session` (the tasks whose src is
`--src`, else the first 8 characters of `$CLAUDE_CODE_SESSION_ID`). Each part is capped (`--limit N`,
default 10) and ends with the `list` query that shows the rest; `--all-projects` covers the account.
`--json` prints the same under fixed keys, every row with the same ten keys (null where the task has
no value). `todos help fields` documents every JSON field of `list`, `show` and `brief`: type, when it
is present, meaning.

`--force` turns the title cap into a warning. Exit status: 0 success, 1 error (message on stderr), 2 a
write that needs `--yes` (the plan was printed, nothing written), 75 rate-limited beyond a short wait
(retry later). `list` prints one line per task, subtasks after their task and indented two spaces per
level: `<id> <x|-> <!prio|--> [due[~][!]] [area:kinds] effort/mode title` (`~` recurring, `!` overdue);
`--desc` adds the first body line. Root tasks sort by the `--sort` key, subtasks in the app's order. A
filter that matches a subtask but not its parent prints the subtask alone, still indented. JSON rows
carry `parent` (the parent's id), `subtasks` (the open subtasks' ids), `recur`, `duration`, `assignee`
and, outside the current project, `project`. Completed tasks (`--done`, `--all`) come from a separate
endpoint and carry no src or since.

## The account verbs and api

Every list takes `--json` (`--pretty`); objects are named by name, id or unique id prefix. Without
`--yes` these writes print what they would do and exit 2: `rm`, `reschedule`, `move` or `assign` of
more than five tasks (subtasks counted); deleting a project, section, label, filter, comment, upload,
folder or workspace; archiving; moving a project between workspaces; importing a template; inviting or
removing people; every write through `api`. Single-object edits, `reminders rm` and task `import` run at
once.

The guards that keep the house model intact: `labels edit --name` and `labels rm` refuse the labels the
CLI reads (`effort-*`, the three modes) without `--force`; `comments edit` and `comments rm` refuse the
src/since comment without `--force`; `--in` never creates a project. Plan gates run before any write,
from the account's `user_plan_limits`: the features (deadlines, durations, reminders, filters, uploads
and their size, templates, email forwarding) and the caps (projects, sections, labels, filters,
reminders, collaborators). Workspace, folder and team verbs are thin: without a Teams plan the API
answers 403 and the CLI prints its message. `projects health` and `projects insights` are endpoints of
Todoist's MCP connector, not in the public API docs; the server may refuse them by plan or for
personal projects, and the refusal is printed.

`api` reaches every REST endpoint under the API base (a path starting with `/`; another host is
refused), every Sync command (`sync`: uuid and temp id filled in, batched through the same code as the
verbs; `--dry` prints the commands) and every Sync resource type (`read`: a full read, not cached; `all`
for everything). Output is the JSON response, compact unless `--pretty`, with token-like keys masked;
`--raw` returns the reply's bytes as they came, nothing masked (CSV templates, backup archives), `--out`
writes the output (the masked JSON, or with `--raw` the bytes) to a file. `--file field=@path`
sends multipart/form-data, `--form` alone urlencoded, `--body` JSON.

## Import grammar

```
## <area>                                                (optional; the area of the root rows below)
- [ ] <title> @YYYY-MM-DD[THH:MM] !1..3 #area #kind #kind
      <body, indented deeper than the bullet: markdown, blank lines and inner indentation kept>
      src: 7e57ab1e; since: 2026-09-22; effort: S; mode: assisted; deadline: 2026-10-01
  - [ ] <subtask> #kind                                  (a bullet indented under a task; same area)
        <its body>
        effort: S; mode: unattended
```

The first `#tag` of a root row is the area, the rest are kinds; a subtask's `#tags` are all kinds.
`area:`, `kind:` and `url:` also work on the attribute line; separators may be `;`, `|` or the middle
dot. A root row without a `#tag` takes the area of the `## <area>` heading above it. A body line that
starts with `- [ ]` is read as a subtask, so bodies use plain `- ` lists. A JSON array is read too: the
`todos list --json` shape, where `parent` names an open task's id or the `id` of another row.

Every row is checked (title cap, attributes, plan, ids) before anything is written; `--dry` prints the
plan. Without `--update`, the file only adds: `[x]` rows are skipped, a title that already exists (in
the project for root rows, under the same parent for subtasks) is skipped as a duplicate, and any
`[id ...]` bracket only contributes its attributes. So a `todos export` file reads back whole: its
brackets carry the id, kinds, effort, mode, src, since and deadline.

With `--update`, a row with an `[id ...]` bracket is applied to that task: title, body, attributes,
priority, due, deadline; nested under another row, it moves under that task (a new parent may be
another row of the same file); `[x]` closes it. A root-level row never detaches a subtask (use
`edit --parent ""`). An id that is not an open task refuses the whole file. Only what differs is
sent. So the editing loop for a re-org is: `todos export --out copy.md`, edit the copy, `todos
import copy.md --dry --update`, then without `--dry`.

The export bracket carries modes by name: a file written under one config and imported under another
whose modes differ reads those words as kinds (`import --dry` shows it). Run both under the same config.

## How it talks to Todoist

API v1 (`https://api.todoist.com/api/v1`, `TODOIST_API_BASE` overrides it). Reads go through the Sync
endpoint: the first read is a full sync, cached in `~/.cache/invoke-todos/state-<hash>.json`
(`$XDG_CACHE_HOME` honoured; mode 0600; one file per token and API base; `paths.cache_dir` or
`TODOIST_CACHE` sets the directory, `off` disables it); every later read is one incremental sync merged
into that cache. The cache holds projects, sections, labels, items, task and project comments, filters,
reminders (both kinds), collaborators and their states, live notifications, the user, the user
settings, the plan limits and the saved locations; a cache of an older layout is replaced by a full
sync. A full sync is always followed by one incremental sync, as the docs advise (a full sync of a big
account can lag behind the latest writes). Writes are Sync commands, at most 100 per request; a task
and its comment travel in one request, tied by a temp id; a subtask of a task added in the same run
names the parent's temp id. REST is used only where Sync has no command or resource: the completed-task
lists (windows of 89 days by completion date, 41 by due date), the filter query, Quick Add, activity,
productivity stats, the user object, comment reactions, uploads (a raw stream with `X-File-Name`),
templates (multipart), backups, emails, id mappings, folders and the workspace endpoints.

Todoist rate-limits per user; in practice about a hundred requests in fifteen minutes bring 429s with a
short `Retry-After`, on Sync and REST alike. A 429 asking for a wait of at most `TODOIST_MAX_WAIT`
seconds (default 20) is waited out, twice at most; beyond that, exit 75. A 5xx or a network error is
retried twice on Sync requests and GETs, never on a REST write (the docs do not promise deduplication).
A 401 is a bad token; a 403 is the server's refusal (a plan or permission limit) and is printed as
such. The token rides as an unredirected header, so a redirect to another host (a backup download goes
to a CDN) does not carry it; `comments get-file` sends it only to `todoist.com` hosts, over https. Every
printer masks keys named `token`, `*_secret`, `password` and the like, and `websocket_url`, at any depth
(`api --raw` alone passes a reply's bytes through untouched). The `user` object carries the account's
token, a second token in the query of its `websocket_url` and a device token one level down; none
reaches the cache file. A cache file an earlier version wrote loses them the next time a read opens it;
one left under another cache folder or another token is never opened, so delete it. `TODOIST_DEBUG=1`
prints each request (never the token, secret-named values masked).

API behaviour the code depends on, not in Todoist's docs:

- Every `*_add` needs a `temp_id`; `label_add` without one is refused.
- The server stores a task's labels sorted.
- Title and due changes in a task's first seconds are accepted and lost; `edit`, `reschedule` and
  `import --update` wait until the task is `TODOIST_SETTLE` seconds old (default 6) before changing
  its title or due date.
- `GET /activities` with `parent_item_id` returns only the task's comments' events;
  `object_type=item&object_id=ID&include_child_objects=true` returns the task's own as well
  (`activity --task`). One's own events carry one's user id as `initiator_id`. The log can lag a
  task made seconds ago. A `date_from` at or beyond the plan's history (`activity_log_limit` days) is
  refused whole with HTTP 403 `PREMIUM_ONLY`, `--since 7d` on a 7-day plan included; `activity` reads
  from the history's edge instead and says so.
- The default filters of a new account count against `max_filters`. The Inbox does not count against
  `max_projects`: an account with the Inbox and four more projects on a five-project plan still creates a
  fifth, so the cap checks (and the mock) leave it out.
- `GET /backups` lists backups on a plan whose `automatic_backups` is false.
- `is_uncompletable: true` (the connector's "header task") is accepted by `item_add` and by `POST /tasks`
  and reads back without the field: not supported through the API, as far as the accounts seen show.
- The template CSV starts with a byte-order mark.
- The incremental sync carries a deleted project but not its sections, tasks and comments; the cache
  drops whatever hangs off a project it no longer holds, or the ghosts stay until the next full sync.

## Tests

```zsh
python3 tests/test_todoist.py     # offline: every verb as a subprocess, against tests/mock_todoist.py
python3 tests/test_install.py     # install.sh and the setup verbs in a scratch HOME, against the mock
python3 tests/test_config.py      # the config loader: precedence, validation, the example
python3 tests/test_layering.py    # the core never imports a backend; no import cycles
python3 tests/test_public.py      # no private marker in any file the archive would carry
python3 tests/live_smoke.py       # the real account, in a throwaway project or section
```

The offline suite runs every verb as a subprocess against a local stand-in for the API subset the CLI
uses (Sync reads of every resource type and the commands of every verb, the REST endpoints listed
above, a redirecting backup download, a small filter-query and Quick Add parser), under the fixture
config `tests/fixtures/config.json`. The live smoke test makes a project `todoist-selftest-<random>`,
runs every verb there, then deletes the project and every label the run created, and checks the
account's project and label lists against the ones taken before; when the plan's project cap is reached
it skips the task verbs and runs the account-wide verbs in a throwaway section of the default project,
deleted at the end with its tasks. It spends a large share of the fifteen-minute rate limit, so do not
run it back to back. All of it runs on the system `python3`, 3.9 or later.

## The skill

`skills/invoke-todos/SKILL.md` is a Claude Code skill: its description triggers on task talk ("add a
task", "what's on my plate", "what's overdue", "plan X into steps", "mark that done", ...), and its body
tells the agent to run `todos brief` first, to read the vocabulary from `todos config show` once per
session, how to capture a task, file a session's leftovers and write a plan as an import file, how to
query for specifics (`list --json --fields`, `todos help fields` for the schema), and the gotchas (never
edit tasks through another Todoist client, since the labels and the src/since comment are what the
filters read). `install.sh` links the folder into `~/.claude/skills/invoke-todos`; Claude Code follows the
link, and `doctor --claude` checks it. The skill runs `todos` from PATH, so the command link matters to
it too.

## Maintainer notes

- A package, `invoke_todos/`, Python 3.9, standard library only; the tests run on the system interpreter
  to keep it so. The core (`config`, `output`, `dates`, `model`, `args`, `query`, `render`, `importer`,
  `exporter`, `verbs`, `cli`) speaks the house model (the vocabulary, dates, the attribute and description
  functions, the tree, the import grammar, the export, the verb registry) and never imports a backend
  (`tests/test_layering.py` checks it); the Todoist backend, `invoke_todos/backends/todoist/` (`auth`,
  `api`, `items`, `state`, `flags`, `query`, `mutations`, `render`, `usage`, `verbs/` with one module per
  verb family), is everything that speaks the API or reads its raw objects. A backend registers its verbs
  and its flag sets; `cli.main` loads the backend the config names (`backend: "todoist"`) and dispatches
  through the registry in `verbs.py`. There is no abstract backend interface yet: it is written when a
  second backend arrives and shows which seams are real; `docs/apple-reminders-backend-notes.md` is what
  an Apple Reminders backend would start from. The launcher `todos` at the repo root runs it from a
  clone with no install (`python3 -m invoke_todos` and the `pyproject.toml` console script do the
  same). `docs/spec-modules.md` names every function's module. A new verb is a function in the right
  `verbs/` module decorated with `@register("name", "alias")`; its flags go in `VALUE_FLAGS` or
  `BOOL_FLAGS` in `backends/todoist/__init__.py` (one namespace for every verb: `--desc` is the list
  switch, so descriptions are `--description`), and its line in `USAGE_TEXT` in
  `backends/todoist/usage.py`, which is the reference `todos help` prints. `tests/test_config.py` is the
  config module's unit suite and `tests/fixtures/config.json` the suite's config. The skill is
  `skills/invoke-todos/SKILL.md`, one copy, linked from the user's skills folder; its `name:` is the
  folder's name.
- Every write builds Sync commands through `new_cmd` (a uuid each, so a retried request is not applied
  twice; a temp id on every `*_add`) and sends them through `write`, which batches at 100 and maps temp
  ids across requests. A command that fails ends the run after its batch; the others in the batch stay
  applied. `edit`, `reschedule` and `import --update` share `edit_plan`, which sends only what differs.
  REST goes through `rest` or `call` (JSON body, raw bytes, multipart through `multipart`); paginated
  GETs through `pages`.
- Destructive or bulk writes go through `need_yes`; plan gates through `require` (a feature flag) and
  `within` (a count against a cap); output through `emit` (lines or JSON, masked by `redact`).
- The label names (the effort prefix and values, the modes), the comment format, the Origin link form
  (`link_re()`, which still reads the two older forms) and the export bracket (`parse_meta`) are what
  every filter, the export and `import --update` read; they take their vocabulary from the config, so
  renaming a value there means relabelling existing tasks.
- The tree is built by `link_tree` over the open items of the account (parent, depth, subtasks in
  `child_order`); `sort_items` walks it over any subset, so a filtered list and the completed list
  keep parents before their subtasks. Short ids are assigned over the account, then again over the
  project, so the project's tasks keep the shorter prefixes.
- The cache holds the whole account, not only the project. Delete the file, or pass `--fresh`, if it is
  ever suspect; `CACHE_VERSION` changes whenever `LISTS` or `SINGLES` do.
- `tests/mock_todoist.py` encodes the API behaviour the CLI relies on; when the live API disagrees,
  fix the mock first, then the CLI. Its filter-query and Quick Add parsers know only the subset the
  tests use. `tests/test_public.py` is a release condition: no private marker in any file the archive
  carries. Changes go in `docs/change-log.md`, newest first; a release is a tag `vX.Y.Z` matching
  `invoke_todos.__version__`, and `scripts/pack.sh` builds its archive. `CONTRIBUTING.md` has the short
  form.
- `docs/snapshots/` (the maintainer's tree only, left out of the public archive) holds dated ground
  reports, `<YYYY-MM-DD>_<subject>.md`: a map of the tool, what the Todoist API documentation says,
  the live account's state. Before a session grounds itself for a planning or investigation pass, it
  reads the newest snapshot of each subject first and re-grounds only what is stale or missing; every
  fact there is a dated claim with its source, to be re-read before a decision rests on it. A new
  grounding pass is saved there as a new dated file. A dated folder beside them,
  `<YYYY-MM-DD>_<subject>/`, holds third-party reference files kept verbatim, each with its URL and
  commit on the first line and an `INDEX.txt`.

## License

MIT; see `LICENSE`.
