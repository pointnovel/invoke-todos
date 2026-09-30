---
name: invoke-todos
description: The user's task lists live in Todoist and are read and changed only through the todos CLI (invoke-todos). Use whenever tasks come up, even mid-sentence, before answering from memory: "add a task", "put this on my list", "todo", "remind me to", "what's open", "what's on my plate", "what's overdue", "what's due today", "what could an agent do alone", "what should I do next", "plan X into steps", "make a checklist for", "break this down", "mark that done", "close it", "what did I complete this week", a session's leftover items, or any question about the user's tasks, projects, areas or anything in Todoist. Use it instead of a Todoist MCP connector or the official td CLI. Carries the brief (the digest an agent reads first), the house vocabulary (areas, kinds, effort, priority, mode, src), the plan-as-subtasks pattern and the tool's gotchas. Not for calendar events, a reminders app, or plans kept as documents.
---

# invoke-todos

`todos` is on PATH; `todos help` lists every verb and flag. `<sid8>` is this session's id, first 8
characters (`${CLAUDE_CODE_SESSION_ID:0:8}`); `brief` reads it from the environment by itself. Exit 2 means the CLI
printed what it would do and wants `--yes` (bulk and destructive writes, every `api` write): rerun with
`--yes` only when the user asked for exactly that change. Exit 75 = rate limited; retry later.

## Start with the brief

Whenever tasks come up, run `todos brief` before listing, adding or answering:

```
todos brief                     # the default project: counts by area, overdue and due today,
                                # what an agent could do now, the tasks this session filed
todos brief --in PROJECT        # another project of the account
todos brief --all-projects      # every project; rows show project/area
todos brief --json              # the same under fixed keys
```

One call, one partial sync. Its parts are fixed: the header line with the counts, `# due`,
one block per agent mode (the first two modes of the vocabulary: alone, then with the user mid-way),
`# this session`. Each part is capped (`--limit N`, default 10) and ends with the `list` query that
shows the rest. A row reads `<id> <x|-> <!prio|--> [due] [area:kinds] effort/mode title`.

## Name a task by its link

The apps cannot search a task by its id, so a bare id in a reply leads the user nowhere. Whenever you
name a task to the user (a row, a table, "filed as", a still-open line), write it as the link the CLI
prints, `[task#<short>](<link>)`, then the title:

```
todos list --area <area> --links      # every row starts with [task#<short>](<link>)
todos add "<title>" --area <area> --links   # the confirmation carries the link of the new task
todos list --json --fields short,link,title
```

`--links` works on any verb that prints task rows (`brief`, `list`, `add`, `done`, `edit`, `move`,
`import`, `show` for the parent and subtasks; `show`'s id line always has the link). Copy the link, never build
one from a short id: a link needs the full id. Read without `--links` when you are not about to cite:
a link makes every row several times longer. `task#<short>` and a pasted markdown link (quote it) work wherever an `<id>`
does. Which link is printed (the web URL, or one that opens the app) is the config's `todoist.task_url`.

## The vocabulary

Once per session, `todos config show` prints the projects (the default one and any others, each with a
role such as work or life and its areas), the effort and mode values with their meanings, the known
kinds, and what priority means. The rest of this file uses the defaults: efforts `S` (under an hour),
`M` (a session), `L` (several); modes `unattended` (an agent finishes it alone), `assisted` (an agent
starts it and needs the user mid-way), `owner` (only the user can: pay, sign, call); priority is the
task's value, p1 the most valuable, none when omitted.

- **project**: one Todoist project per list; `--in PROJECT` on any verb runs under another one (never
  `TODOIST_PROJECT`, which would create a project on a typo).
- **area**: the section; `todos areas` lists them with open counts. `--area` ignores case and creates a
  section it does not find, so reuse a listed one; a section whose name has a space goes by
  `--section "Name"`.
- **kind**: free tags such as `decision`, `verify`, `build`, `write`, `parked` (`--kind a,b`).
- **src**: where the task came from, a session id (8 hex characters, becomes the Origin link) or a file
  reference; **since**: first seen, defaults to today.

## Capture one task

```
todos add "<title, at most 60 chars by default; the mass goes in --note>" --area <area> --kind build --effort S \
    --prio 2 --mode unattended --src <sid8> --note "<body: markdown, any length>"
```

Long bodies through stdin (`--note -` with a heredoc). `--due` takes `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM`
or a phrase Todoist parses (`"tomorrow 9am"`; `"every monday"` makes the task recurring). `todos user
plan` shows what the account's plan allows (deadlines, durations, reminders); the CLI refuses the rest
before writing.

Text as the user would type it in the app goes through Todoist's own parser: `todos quick "Pay the
water bill friday #Home /money p1 @effort-S @owner" --src <sid8>`; effort and mode go in the text as
labels (only labels that exist apply, unknown ones stay as text), or through `edit` after.

## Session leftovers

At the end of a session, each item that outlives it (not a question awaiting the user's reply here)
becomes a task with `--src <sid8>`; the Origin link fills in. Work items go to the work project, life
items to the life one (`--in`). `todos brief` shows under `# this session` what is already filed, and
`add` does not check for duplicates. Group steps under one task with `--parent <id>` rather than adding
five siblings.

## Plan into steps

Write the plan as an import file and apply it, dry run first:

```
- [ ] <the task> #area #kind
      <why, pointers, in markdown>
      src: <sid8>; effort: M; mode: assisted
  - [ ] <step one> #verify
        src: <sid8>; effort: S; mode: unattended
  - [ ] <step two>
```

```
todos import plan.md --dry && todos import plan.md
```

A nested row is a subtask (same area as its parent). To restructure existing tasks: `todos export --out
copy.md`, edit the copy (retitle, rewrite bodies, nest rows, mark `[x]`), then `import copy.md --dry
--update` and, when the diff reads right, `--update`. Rows keep their `[id ...]` bracket.

## Query for specifics

After the brief, filter at the source: one `list --json --fields` beats a loop of `show`, and a filtered
query beats the whole list. The house flags read the cache; `--filter` asks the server.

```
todos list --mode unattended --effort S          # what an agent could do now (--prio 1: the most valuable)
todos list --area money --json --fields id,title,prio,due
todos list --filter "today | overdue"            # a Todoist query, every project; ~ marks recurring
todos list --done --since 7d --all-projects      # what was completed
todos show <id> --comments                       # body, parent, subtasks, comments in full, app link
todos show <id> --tree --comments                # the task, then each subtask in full, every comment: one call
todos show <id> --tree --all --comments --json   # the same as a list, with the subtasks completed in 89 days
todos done <id>                                  # subtasks go along; a recurring task moves on
todos activity --task <id>                       # who changed what, when
```

An `<id>` is the short id a row starts with, any unique prefix of it, the task's link pasted from the
app, or what `--links` prints (`task#<short>`, the markdown link). Read a task the user points at with `show <id> --tree --comments` before acting on it: the plan is in
the subtasks and the history in the comments (a flat list per task, no replies).

Before reading `--json` output, `todos help fields`: which fields are always present, which are left out
when empty, and the fixed keys of a brief row.

## Everything else in the account

Every other account object (projects, sections, labels, comments, reminders, filters, people, sharing,
templates, the user, notifications, views, backups, emails, workspaces) has a verb; `todos help` lists
them with their actions. For anything without one: `todos api GET /path`, `todos api sync <command>
--args '{...}'`, `todos api read <types>`.

## Gotchas

- A task captured in the wrong list moves with `todos move <id> --to PROJECT --area <a>` (subtasks
  follow). A section renames with `todos areas rename "<old>" <new>`.
- A body line that starts with `- [ ]` reads back as a subtask on import; write plain `- ` lists inside
  bodies.
- `edit` pauses on a task a few seconds old (Todoist loses early title and due changes); let it, never
  route around it through `api`.
- The effort and mode labels and the `src: ...; since: ...` comment are what the filters, the brief and
  the export read: `labels rm`, `labels edit --name` and `comments rm` refuse them without `--force`; do
  not strip or rename them through `api` either.
- Add and edit tasks only through this CLI, never through a Todoist MCP connector or the official `td`
  CLI: they skip the labels and the src/since comment the filters read.
- The CLI may run as an account of its own, not the user's: a second Todoist account kept for agents, a
  collaborator on the user's projects (`todos user` prints who the CLI is, `todos people` the
  collaborators). Everything it writes then carries that account's user id, which is how the user tells
  an agent's tasks and comments from their own, and `me` (`--assign me`, `activity --mine`) is that
  account: `--assign <the user's name>` hands a task to the user.
- Under such an account only the projects shared with it exist. The Inbox it sees is its own, which the
  user never opens, and the user's Inbox is out of reach: never file there, and put a task with no
  obvious home in the default project instead.
- The Inbox does not count against the plan's `max_projects` (`todos user plan`). Never count projects
  yourself to decide whether a new one fits: `projects add` and `setup apply` check the cap and refuse
  only when it is really reached.
