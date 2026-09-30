"""The usage text `todos help` prints, filled from the config (the default project, the effort and mode values,
the title cap)."""
from invoke_todos.config import cfg


USAGE_TEXT = """todos - a task list in one Todoist project ("%s"; the config's defaults.project, TODOIST_PROJECT or --in), one section per area,
          and every other object of the account (projects, sections, labels, comments, reminders, filters, ...)

Tasks (the house model: areas = sections, kinds/effort/mode = labels, priority = value, src/since in a comment)
  todos add "<title>" (--area A | --section "Name" | --parent ID) [--kind K]... [--due D] [--prio 1..3]
          [--effort %s] [--mode %s] [--src SID8|REF] [--since YYYY-MM-DD]
          [--url URL] [--note TEXT | --note -] [--deadline YYYY-MM-DD] [--duration 90m|2h|3d]
          [--assign me|USER] [--order N] [--force] [--json]
          title <= %d chars; the body (--note) is markdown of any length, "-" reads it from stdin;
          --due takes YYYY-MM-DD[THH:MM] or any phrase Todoist parses ("tomorrow 9am", "every monday");
          priority is the task's value (p1 the most valuable, none when omitted); the Origin link defaults
          to the session URL when --src is a session id; --parent makes a subtask in the parent's area;
          --deadline and --duration need a paid plan
  todos quick "<text as typed in the app>" [--note T] [--reminder T] [--src SID8] [--meta] [--json]
          Todoist's own parser: dates, #Project, /Section, @label, p1..p4, +assignee, // body
  todos list [--area A | --section S] [--open | --all | --done [--by completion|due] [--since 30d] [--until D]]
          [--kind K] [--mode M] [--effort E] [--prio P] [--src S] [--label a,b] [--assignee U] [--grep TEXT]
          [--due-before D] [--overdue] [--filter "today & p1" | --saved NAME] [--all-projects]
          [--sort prio|due|since|title|area] [--desc] [--json [--fields a,b,...] [--pretty]]
          subtasks follow their task, indented; --filter runs a Todoist query on the server (account-wide);
          a "~" after a due date marks a recurring task; rows of other projects show project/area
  todos show ID [--comments] [--tree [--all]] [--reminders] [--json [--fields a,b,...]]
          ID = any unique prefix of the id, the task's link from the app, or what --links prints (task#<short>,
          the markdown link), on every verb; --comments: the comments in full; --tree: the subtasks after the
          task, each in full (--all: the ones completed in the last 89 days too), so show ID --tree --comments
          reads a task, its subtasks and every comment at once
  todos done ID... [--at YYYY-MM-DD[THH:MM] | --forever]   subtasks go along; a recurring task moves to its
          next occurrence, --at/--forever complete it for good (item_complete)
  todos undone ID... | rm ID... [--yes]     rm, reschedule, move or assign of more than 5 tasks (subtasks counted) need --yes
  todos edit ID [--title T] [--area A | --section S] [--parent ID | --parent ""] [--project P --area A]
          [add flags...] [--clear-due] [--clear-deadline] [--clear-duration] [--assign ""] [--url ""]
          a plain --due on a recurring task moves the next occurrence and keeps the recurrence
  todos reschedule ID... DATE          the same, for many tasks at once
  todos move ID... --to PROJECT [--area A | --section "Name"]    root tasks into another project
  todos assign ID... --to me|USER | unassign ID...               (shared projects)
  todos order ID ID ... [--day]        the given order among siblings (--day: the order in Today)
  todos import FILE [--dry] [--force] [--update]   markdown grammar (README) or a JSON array; nested
          rows are subtasks; --update applies rows that carry an [id ...] to those tasks ([x] closes them)
  todos export [--out PATH]       the generated markdown view (default stdout; TODOIST_EXPORT sets a path)
  todos search TEXT [--json]      tasks, projects, sections, labels and filters, from the cache
  todos overview [PROJECT]        every project with its sections and open counts; one project's tasks by area
  todos stats [--json] | stats --account   the project's counts; karma, streaks and goals (--account)
  todos areas | areas rename "<old>" NEW   the project's sections with open counts (= sections)
  todos brief [--src SID8] [--limit N] [--all-projects] [--json [--pretty]]   the digest an agent reads first: counts by
          area; overdue and due today; what an agent could do now (the first two modes, by value); the tasks one session
          filed (--src, else $CLAUDE_CODE_SESSION_ID); N rows per part (10). todos help fields names the JSON fields

Account objects (NAME or id or unique id prefix; --json on every list). Without --yes these print what they would
do and exit 2: deleting a project, section, label, filter, comment, upload, folder or workspace, archiving, moving
between workspaces, importing a template, inviting or removing people, and every write through api.
  todos projects [--archived | --all] [--grep T] | show P [--tasks] | add NAME [--color C] [--description T] [--parent P]
          [--view list|board|calendar] [--favorite] [--workspace W] | edit P [--name N] [--color C] [--description T|--clear-description]
          [--favorite|--no-favorite] [--view V] [--collapsed on|off] [--parent Q|--root] | archive P | unarchive P
          | rm P | move P (--workspace W [--folder F] [--visibility restricted|team|public] | --personal)
          | order P1 P2 ... | people P | roles | search Q | health P [--context] [--analyze] | insights P [--weeks N]
          | leave P | join P
  todos people [PROJECT] [--grep T]          collaborators
  todos sections [--all-projects] [--archived] [--grep T] | show S | add NAME [--description T] | edit S [--name N]
          [--description T|--clear-description] [--collapsed on|off] | rename "<old>" NEW | rm S | archive S
          | unarchive S | move S --to PROJECT | order S1 S2 ...   (S = a name in the current project, project/name, or an id)
  todos labels [--shared [--all]] [--grep T] | show L | add NAME [--color C] [--favorite] | edit L [--name N] [--color C]
          [--favorite|--no-favorite] [--order N] | rm L [--keep-on-tasks] | rename-shared OLD NEW | strip-shared NAME
          | order L1 L2 ...   (effort-* and mode labels need --force to rename or delete)
  todos comments ID | comments --project P | add ID TEXT|- [--file PATH] [--notify u,v|none]
          | add --project P TEXT | show CID | edit CID TEXT|- | rm CID | react CID EMOJI | unreact CID EMOJI
          | get-file CID [--out PATH]   (the src/since comment needs --force to edit or delete)
  todos reminders [ID] [--all-projects] [--location] | show RID | add ID (--before 30m | --at WHEN
          | --place NAME --lat X --lon Y --on enter|leave [--radius M]) [--urgent] [--service email|push] [--user U]
          | edit RID ... | rm RID | locations | clear-locations   (paid plan; --before 0m where reminders_at_due holds)
  todos filters [--grep T] | show F | add NAME "QUERY" [--color C] [--description T] [--favorite] | edit F [--name N]
          [--query Q] [--color C] [--description T|--clear-description] [--favorite|--no-favorite] | rm F | run F | order F1 F2 ...
  todos activity [--all-projects | --project P] [--task ID] [--type task|project|comment|section] [--id X]
          [--event added|updated|deleted|completed|uncompleted|archived|unarchived|shared|left|moved|!deleted]
          [--events item:completed,note:added] [--mine | --others | --by U] [--since 7d] [--until D]
          [--children] [--parents] [--notes] [--limit N] [--max PAGES]
  todos user | user info | user plan | user settings [KEY=on|off...] | user set KEY=VALUE... | user goals
          [--daily N] [--weekly N] [--vacation on|off] [--karma on|off] [--days 6,7] | user notify TYPE email|push on|off
  todos notifications [--unread] | read ID... | read --all | unread ID... | seen ID
  todos share list P | add P EMAIL [--role R] | rm P EMAIL | role P USER ROLE | accept N | reject N | uninvite ID
  todos views | set TYPE [OBJECT] [--filter Q] [--group G] [--sort-by S] [--direction asc|desc] [--completed on|off]
          [--mode-view list|board|calendar] [--deadline Q] [--calendar JSON] | reset TYPE [OBJECT] | default P ...
  todos uploads add FILE [--project P] | rm URL
  todos templates export P [--relative] [--out F.csv] | url P [--relative] | import P (--id T | --file F) [--locale L]
          | new NAME --file F [--workspace W]
  todos backups [--mfa CODE] | get URL|--latest [--out PATH]
  todos emails get|off (--task ID | --project P)
  todos folders list --workspace W | show ID | add NAME --workspace W [--projects a,b] | edit ID --workspace W
          [--name N] [--add a,b] [--remove a,b] | rm ID
  todos workspaces | show W | plan W | users W | projects W [--archived] | insights W [--projects a,b]
          | invitations W [--all] | add NAME [--description T] | edit W [--name N] [--description T] [--link-sharing on|off]
          [--guests on|off]
          | rm W | leave W | invite W EMAIL... [--role R] | reinvite W EMAIL | uninvite W EMAIL | accept CODE
          | reject CODE | join (--code C | --id W) | role W EMAIL ROLE | kick W EMAIL | sidebar W MODE
          | logo W FILE|--delete | order W --file ordering.json
  todos ids map TYPE ID,...       v1 <-> v2 id translation
  todos billing state|usage|history|subscription   (read-only)

Anything else (every endpoint, command and read type of the API; writes need --yes)
  todos api GET /path [--q k=v]... [--all-pages [--max N]] [--raw] [--out PATH] [--pretty]
  todos api POST|PUT|DELETE|PATCH /path [--q k=v]... [--body JSON|@file|-] [--form k=v]... [--file field=@path]... --yes
  todos api sync COMMAND --args JSON [--temp-id] [--dry] --yes | api sync --commands @file.json --yes
  todos api read TYPE[,TYPE...]    a Sync read (projects, items, filters, reminders, user, stats, all, ...)

  todos config path | show [--json] | check [--account] | init [--out PATH] [--from-account] [--force]
          the account config (docs/spec-config.md); check --account: drift against the live account (projects and
          areas the account lacks, labels outside the vocabulary); init --from-account: a config proposed from it
  todos setup plan | apply --yes   create what the config names and the account lacks (projects, areas, the effort
          and mode labels, the known kinds); never deletes, renames or moves; apply prints the plan and exits 2 without --yes
  todos doctor [--claude]         the config, the default project, the token source, the API and plan, the cache
          folder; --claude: the skill link ~/.claude/skills/invoke-todos and todos on PATH

  --in PROJECT (any verb)   run under another project of the account (a name or id; it must exist)
  --fresh (any verb)        read from a full sync instead of the local cache
  --links (any verb)        task rows name their task as a markdown link, [task#<short>](<link>), to paste into a
                            reply; the link is the app's web URL, or the config's todoist.task_url template
  --config PATH (any verb)  the account config (default: $TODOS_CONFIG, else ~/.config/invoke-todos/config.json)

Token: TODOIST_API_TOKEN in the environment, else the source the config names (todos config show); todos doctor checks it.
Exit: 0 ok, 1 error, 2 needs --yes, 75 rate-limited (retry later)."""


def usage():
    return USAGE_TEXT % (cfg.project or "(none)", "|".join(cfg.efforts), "|".join(cfg.modes), cfg.title_max)
