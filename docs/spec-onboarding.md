# Spec: the archive, the installer and the onboarding session

How the tool leaves the repo and lands on a stranger's machine: the archive that carries every module, the installer, and the onboarding session in which an agent interviews the user, writes the config, maps or creates the task objects, unpacks and wires everything (the skill by a symlink, with consent), and verifies it. Phases 4 and 6 of the refactor plan. The prompt that starts the session is `ONBOARDING.md` at the repo root.

## 1. The archive

`scripts/pack.sh [REF]` (POSIX sh) builds `dist/invoke-todos-<version>.tar.gz` from `git archive` of REF (default HEAD; the version is `__version__` in `invoke_todos/__init__.py` at that ref, and a tag `vX.Y.Z` must match it), with the top folder `invoke-todos-<version>/`, and writes `dist/SHA256SUMS` beside it. `.gitattributes` keeps out of it: `scripts/check_moves.py` (a proof against a commit of the private history), `docs/snapshots/` (the maintainer's dated reference reports), `dist/`, `.gitattributes` itself and editor files. `dist/` is gitignored.

What the archive contains, by folder, and why each is there:

| Path | Why |
|---|---|
| `todos`, `invoke_todos/` | the CLI: the core and the Todoist backend |
| `skills/invoke-todos/SKILL.md` | the Claude Code skill, linked into `~/.claude/skills` at onboarding |
| `tests/` | the offline suite, the mock, the live smoke, the config, layering and public-safety tests, the fixture config |
| `docs/` | the specs, the change log, this document |
| `examples/config.example.json` | the config to start from |
| `install.sh`, `scripts/pack.sh` | the installer and the packer |
| `ONBOARDING.md`, `README.md`, `LICENSE`, `pyproject.toml` | the prompt, the reference, the license, the packaging |

Checks before a release: `tar tzf` lists the top folder only; `sha256sum -c SHA256SUMS`; from the unpacked folder, `python3 todos help` prints the usage and `python3 tests/test_todoist.py` is green; `tests/test_public.py` is green on the tree the archive was made from. The GitHub release attaches the tarball and the sums file; the release notes are the change-log entry.

## 2. `install.sh`

POSIX sh, safe to re-run, modelled on the installer of a sibling tool; checked with `sh -n`, `dash -n` and `shellcheck -s sh`.

| Flag | Effect |
|---|---|
| `--bin DIR` | the folder for the command link (default `~/.local/bin`) |
| `--name NAME` | the command's name (default `todos`; for machines where that name is taken) |
| `--skills DIR` | the Claude Code skills folder (default `~/.claude/skills`) |
| `--no-skill` | leave the skill link out (CLI only, or the optional plugin route) |
| `--config` | run `todos config init` when no config exists, then print its path |
| `--force` | replace a file, or a link that points elsewhere; never a real folder |
| `--dry-run` | run the checks and print each step; change nothing |
| `--uninstall` | remove the links that point into this tree; the tree and the config stay |

Preflight: `python3` on PATH at 3.9 or later (the fix names the package manager's line for the OS), nothing else. Steps: link `todos` (the launcher) into the bin folder; link `skills/invoke-todos` into the skills folder as `invoke-todos` unless `--no-skill`; warn when the bin folder is not on PATH; run `todos help` through the launcher as the proof that the interpreter runs the tree, and print the next steps (the token, the config, `setup plan`, `brief`). Without `--force`, a file or a link to something else is left alone with a warning and the script exits 1 at the end. `--uninstall` removes only links whose target is inside this tree.

The same steps by hand are four lines in the README (`ln -s` twice, `config init`, `doctor`).

## 3. The plugin route (optional, after 1.0)

The repo can also be a Claude Code plugin marketplace with one plugin, `invoke-todos`: the same skill. It is not the default (the maintainer's call: the skill is linked from the tree) and not part of onboarding. When it ships: `./install.sh --no-skill`, `claude plugin marketplace add "$PWD"`, `claude plugin install invoke-todos@<marketplace>`; one route or the other for the skill, since both carry the same file.

## 4. The onboarding session

A fresh agent session (Claude Code, or any agent with a shell and file tools) started with `ONBOARDING.md` as its first message, on the user's machine, with the archive or a clone at hand. The agent reads this section as its protocol.

### 4.1 Preconditions

- The user has the tarball (and `SHA256SUMS`) or a clone, and knows the path.
- The user has an account with the task app (Todoist in 1.0) and can reach its API token (Todoist > Settings > Integrations > Developer). The agent never needs to see it.
- `python3` 3.9 or later on the machine. Claude Code, if the skill is wanted.

### 4.2 Rules for the agent

1. The token never enters the conversation, a file the agent writes, or a command the agent runs. The user stores it in their own terminal (the line for each source is in sec. 4.4, step 4) and says when it is done; the agent checks with `todos doctor`, which reports reachability without printing the value.
2. Every write to the task app is planned first: `setup plan` before `setup apply --yes`, `import --dry` before `import`. `--yes` is passed only after the user has seen the plan and said yes to exactly that.
3. Nothing under `~/.claude` changes but the skill link, made by default (Q2 can decline it) and shown first; `settings.json` is never edited.
4. Nothing under the user's home is overwritten: `install.sh` refuses without `--force`, and the agent asks before passing `--force`.
5. One question per turn, batched only when the answers are independent; every question carries its default so "keep the defaults" is a valid answer.
6. The rate limit is real (about a hundred requests in fifteen minutes): a sync, `config init --from-account`, `setup apply` and the first `list` fit; the offline suite runs against the mock and costs nothing; the live smoke is not part of onboarding.
7. The report (sec. 4.6) says what happened, what was skipped and why, and what the user must still do. A step that failed is reported as failed with its output, not retried into a different shape.

### 4.3 The interview

In this order. Q1 to Q3 are asked before anything is unpacked; Q4 and Q5 after the tool runs, because the "existing account" path needs the CLI.

**Q1, where.** The folder to keep the tree in (default `~/.local/share/invoke-todos`, or the clone's own path when it is a clone); the bin folder (default `~/.local/bin`); the command's name (default `todos`; the agent checks `command -v todos` first and says if it is taken).

**Q2, the agent integration.** With Claude Code present, the default is the skill linked into `~/.claude/skills/invoke-todos`; the user may decline it (CLI alone). The skills folder is asked only when it is not `~/.claude/skills`.

**Q3, the token.** How the user wants it stored: the macOS Keychain (default on macOS), a 0600 file (default elsewhere), an environment variable in their shell profile, or a command that prints it (`pass`, a secrets manager). The answer goes into the backend's `token` section; the storing line is given at step 4.

**Q4, the account.** "Sync with what is in the account" (the default: that path only reads) or "start from scratch".

- Existing account: the agent runs `config init --from-account --out <config path>` and shows the proposal: the projects found with their usable sections, the labels that look like effort values, the two default modes if present, the candidates for the third mode, the remaining labels as kinds, the guessed default project. Then asks: which projects are task lists the agent should know (the rest can stay unlisted); whether the guessed modes and efforts are right; which project is the default; whether any unusable section names (with spaces or capitals) should be renamed (`areas rename`, one at a time, with consent) or left.
- From scratch: project names (default one project, `Tasks`; offer a second for life versus work); the areas of each (the example config's defaults: `inbox`, `tools`, `writing` for the work project, `house`, `money`, `health` for a life one; one lowercase word each); the kinds (default `decision`, `verify`, `build`, `write`, `parked`); the effort values (default `S`, `M`, `L`) and the mode names (default `unattended`, `assisted`, `owner`, with their meanings read back); what priority means to them (default "value"); whether they want provenance (the src/since comment and the Origin link; a URL template only if they have a place session ids resolve to); the default project.

**Q5, preferences.** Keep or change: timeout, settle, the title cap, the cache folder (defaults from `spec-config.md`). Most users keep the defaults; the question is one line.

### 4.4 The wiring steps

1. Unpack: `sha256sum -c` (or `shasum -a 256 -c`) against `SHA256SUMS`, `tar xzf <archive> --strip-components=1 -C <the chosen folder>` (the archive's top folder is `invoke-todos-<version>/`; without `--strip-components` the tree lands one level deeper and every path below follows; a clone skips this). `python3 todos help` from the folder proves the interpreter.
2. Install: `./install.sh` with the flags from Q1 and Q2, `--dry-run` first, then for real. The refusals it prints are shown to the user before any `--force`. This makes the command link and, unless declined, the skill link.
3. Config: the file at `todos config path`, written from Q3 to Q5 (from `config init` for the scratch path, from `config init --from-account` for the existing one, then edited); `todos config check` green.
4. Token: the user runs the storing line in their own terminal (Keychain: `security add-generic-password -a "$USER" -s TODOIST_API_TOKEN -w`; file: `( umask 077; printf 'Todoist token: '; read -rs t; echo; printf '%s' "$t" > ~/.config/invoke-todos/todoist-token )`, a subshell so the umask does not stay and the token never enters the shell history; env: the `export` line in their profile; command: nothing, the command already exists). The agent waits, then `todos doctor`.
5. The account: `todos setup plan` (scratch: everything; existing: usually nothing, or the missing areas and labels), shown, then `todos setup apply --yes` on the user's yes. `todos config check --account` green.
6. First use: `todos list` (empty on a scratch account), `todos add "First task" --area <one of theirs> --kind <one> --effort S --mode <their third mode>` only if the user wants a sample task, and `todos brief`, shown.
7. `todos doctor --claude` green (the skill link).
8. The offline suite: `python3 tests/test_todoist.py` from the tree, once, as the proof that the interpreter and the tree agree; the count reported.

### 4.5 What "done" means

Every line of `todos doctor --claude` passes; `config check --account` passes; `list` works under the default project; the skill loads (Claude Code: `/invoke-todos` appears); the offline suite is green.

### 4.6 The report

The session ends with one message in this shape (an example, filled in):

```
invoke-todos installed

Tree:      ~/.local/share/invoke-todos (from invoke-todos-1.0.1.tar.gz, checksum ok)
Command:   ~/.local/bin/todos -> the tree's launcher (on PATH)
Config:    ~/.config/invoke-todos/config.json (backend todoist; config check: ok; --account: ok)
Token:     Keychain item TODOIST_API_TOKEN (doctor: reachable; plan: free)
Account:   existing; projects Tasks (default) and Home mapped; 2 areas and 3 labels created by setup apply
Claude:    skill linked at ~/.claude/skills/invoke-todos
Tests:     tests/test_todoist.py: 75 passed
Skipped:   nothing
Next:      todos add "..." --area inbox; read skills/invoke-todos/SKILL.md for the vocabulary
```

Skipped steps name the reason and the command to run later.

## 5. Rehearsal protocol (for the maintainer)

Before each release, twice:

- Offline: a scratch `HOME` (`HOME=/tmp/onb-$$`), the mock server from `tests/mock_todoist.py` on a port, `TODOIST_API_BASE` pointing at it and `TODOIST_API_TOKEN=test-token` exported in that shell only (the mock's token), a fresh Claude Code session in the scratch HOME with `ONBOARDING.md` pasted, the "from scratch" path. Pass: the report of sec. 4.6 with no hand fix.
- Live (optional, once per release): a second, free Todoist account, the "existing account" path, on a real HOME kept separate from the maintainer's config (`TODOS_CONFIG`). Not on the same afternoon as the live smoke.

A rehearsal that needed a hand fix is a bug in this document or in `ONBOARDING.md`; fix the document before the next run.
