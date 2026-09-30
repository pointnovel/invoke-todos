# docs

The specifications of invoke-todos (the refactor of a one-person Todoist CLI into this project), and its change log.

| File | What |
|---|---|
| `spec-modules.md` | the split of the single-file CLI into a package: every function's new home, the verb registry, the launcher, packaging, what the tests need |
| `spec-config.md` | the account config file: location, precedence, every key with its default, the verbs that read and write it, validation |
| `spec-onboarding.md` | the archive, the installer, the plugin route, and the onboarding session an agent runs: the interview, sync with an existing account or start from scratch, wiring, verification, the report |
| `apple-reminders-backend-notes.md` | what the retired Apple Reminders tool (Swift over EventKit) learned, kept for a Reminders backend: the app-bundle route to a Reminders grant, what EventKit reaches and hides, the private ReminderKit route, how the house model maps, the launcher and signing scripts |
| `change-log.md` | what changed, newest first; public-safe from its first entry |
| `snapshots/` | the maintainer's tree only (left out of the public archive): dated ground reports, `<YYYY-MM-DD>_<subject>.md`, that a planning session reads before grounding again: a map of the tool, what the Todoist API documentation says, the live account's state; and dated folders of third-party reference files kept verbatim (`2026-09-30_doist-artifacts/`: Doist's own `td` skill and MCP server sources) |

The prompt that starts the onboarding session is `ONBOARDING.md` at the repo root.

The specs are what the refactor's phases built; its plan was the maintainer's own and is kept outside the repo. The README at the repo root is the user reference.
