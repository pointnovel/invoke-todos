# Apple Reminders as a backend: what the retired EventKit tool learned

Notes for whoever builds an Apple Reminders backend for invoke-todos. They preserve what a
standalone predecessor found out: `todo`, a Swift command-line tool over EventKit that kept a task
list in Apple Reminders from 2026-09-22 to 2026-09-29 (six commits, macOS 27, Swift 6.4 toolchain,
Swift 5 language mode). Its tasks were moved into Todoist through `import` on 2026-09-23 with every
field read back equal, and its repository was deleted on 2026-09-29 after this note was written. The
observations below are dated where the date qualifies them; nothing here has been re-checked since.

## 1. Summary

- Reminders is reachable from the shell with public APIs only (EventKit), but only from a process
  that macOS treats as its own app: a signed app bundle with a Reminders usage string, launched
  through LaunchServices. A plain command-line process inherits its parent's permission identity
  and, under an app without a usage string, is refused without a prompt. Section 2.
- EventKit carries title, notes, due date (with an alarm), priority, completion and dates. It does
  not reach what the Reminders app calls tags, the URL field the app shows, sections inside a list,
  flags, subtasks or list groups. The house attributes (kinds, effort, mode, src, since) therefore
  rode in a trailer line inside the notes, which made the notes hard to read in the app. Section 3.
- Apple's private ReminderKit reaches tags, the visible URL, flags and sections. Every selector
  needed was present at runtime on macOS 27, but no call was made; whether `remindd` accepts them
  from a non-Apple app is the one open question. Section 6.
- A Python backend cannot do this from the standard library. The realistic shape is a small
  signed helper app (Swift or Objective-C) that speaks JSON over stdout, driven by the Python
  backend the way the launcher in Appendix A drove the old tool. Section 5.
- AppleScript to the Reminders app reaches the same public fields from any process that holds an
  Automation grant for Reminders, with no helper app: observed once, when the old lists were
  removed, not measured. Section 5.

## 2. Getting a Reminders grant from the shell

What was observed on macOS 27 (2026-09-22):

- `EKEventStore.requestFullAccessToReminders` (macOS 14 and later) prompts only when the calling
  process is its own "responsible process" and its bundle carries a usage string
  (`NSRemindersFullAccessUsageDescription`; `NSRemindersUsageDescription` for older readers). A
  child process of a GUI app inherits that app's permission identity; an app without the usage
  string (the Claude desktop app, for one) is refused with no prompt at all.
- The fix, with public APIs only: build the tool as an app bundle (`Contents/MacOS/<exe>`,
  `Contents/Info.plist`, `Contents/PkgInfo` = `APPL????`) and start it through LaunchServices:
  `open -n --stdin IN --stdout OUT --stderr ERR -a <app> --args ...`. Launched that way the app is
  its own responsible process, the prompt is shown once, and the grant belongs to the app.
- Output and the exit status come back through temp files. The app writes its exit code to the
  path given as `--exit-file` when it ends (every exit path, including an `atexit` handler, must
  write it), and the launcher polls for that file. `open -W` is not usable: it fails with "Unable
  to block on applications" when the app exits quickly.
- Standard input is forwarded only when an argument asks for it (`--note -`); otherwise `/dev/null`
  is passed, so an idle stdin pipe never blocks a call.
- The grant is keyed to the code signature. An ad-hoc signature changes with every build and loses
  the grant each time. A self-signed code-signing certificate in the login keychain, trusted for
  code signing (Appendix C), keeps the identity stable across rebuilds; `codesign --force --sign
  <identity> --identifier <bundle id> --timestamp=none <app>`. The old tool used the identity
  `todo-local` and the bundle id `local.tools.todo`. macOS asks for the login password once for the
  trust setting and once more the first time `codesign` uses the key ("Always Allow").
- `LSUIElement` true in the plist keeps the app out of the Dock. `LSMinimumSystemVersion` 14.0.
- Cost: about 0.15 s per call for the LaunchServices launch, before any EventKit work.
- The permission prompt can go unanswered; the tool gave up after 120 s inside the app and the
  launcher after `TODO_TIMEOUT` seconds (default 300) with exit status 124.
- Reading the Reminders SQLite store directly was refused ("Operation not permitted") inside and
  outside the Claude Code Bash sandbox; it would need Full Disk Access for the helper app. Not
  pursued.

## 3. What EventKit exposes and what it does not

Reachable through `EKReminder` and `EKCalendar`, all used by the old tool:

| Field | EventKit | Notes |
|---|---|---|
| list | `EKCalendar` of type `.reminder`; `title`, `source` | one list per area, named `<prefix> - <area>`; lists are flat, EventKit cannot see the app's list groups |
| title | `title` | |
| description | `notes` | free text; the trailer line lived at its end |
| due | `dueDateComponents` | date only, or date and time; a time was paired with `EKAlarm(absoluteDate:)`, alarms cleared and re-added on every due change |
| priority | `priority` 0..9 | 0 none; the app shows three levels; mapping in section 4 |
| completion | `isCompleted`, `completionDate` | setting `isCompleted` alone is not enough for a date: set both |
| URL | `url` | stored and read back through EventKit; not shown by the Reminders app on the Mac or the iPhone (observed 2026-09-22). It is not the URL field the app displays |
| ids | `calendarItemIdentifier`, `calendarItemExternalIdentifier` | observed equal (the same UUID) on iCloud lists; the first 8 characters served as the short id, any unique prefix resolved |
| dates | `creationDate`, `lastModifiedDate` | |

Not reachable through EventKit, and not reachable through the Reminders AppleScript dictionary
either (checked with `sdef` on macOS 27, whose dictionary has only `flagged` of these): tags
(hashtags), the URL attachment the app shows, sections inside a list, flags, subtasks, list groups.
The Reminders app showed these of the tool's data (2026-09-22): title, notes, priority and
completion; the due date only when set; tags never; the URL never.

## 4. The calls that worked (Swift, EventKit)

- Access: `store.requestFullAccessToReminders { granted, error in ... }` waited on with a
  `DispatchSemaphore`, since the tool had no run loop. Swift 5 language mode kept the global
  `EKEventStore` and the completion-handler pattern quiet; under Swift 6 mode the globals need
  `nonisolated(unsafe)`.
- Lists: `store.calendars(for: .reminder)`; create with `EKCalendar(for: .reminder, eventStore:)`,
  a `source` taken from `defaultCalendarForNewReminders()?.source`, else the first `.calDAV`
  source, else the first `.local` one, then `saveCalendar(_, commit: true)`. `removeCalendar` deletes
  a list; reminders in it were removed first with `commit: false` and one `commit()`.
- Fetching is asynchronous: `store.fetchReminders(matching: predicate) { reminders in ... }`. The
  three predicates used: `predicateForReminders(in:)` (all), `predicateForIncompleteReminders(
  withDueDateStarting: nil, ending: nil, calendars:)` (open), `predicateForCompletedReminders(
  withCompletionDateStarting: since, ending: nil, calendars:)` (done since a date). The default
  "done" window was 30 days.
- Writes: `store.save(reminder, commit: true)`; `store.remove(reminder, commit: true)`. Moving a
  reminder between lists is an assignment to `reminder.calendar` followed by a save.
- Priority mapping (three levels in the app, 0..9 in the API): user 1, 2, 3 (high, medium, low)
  written as 1, 5, 9; read back 1..4 as high, 5 as medium, 6..9 as low, 0 as none. When no
  priority was given the tool derived one from the value attribute (3 high, 2 medium, 1 low).
- Due parsing accepted `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM` and `YYYY-MM-DD HH:MM`; a date-only due
  counted as overdue from the start of the following day.

## 5. Carrying the house model, then and in a backend here

How the old tool mapped the vocabulary, and what a backend in this package would meet:

| House attribute | Old tool (Reminders) | This package (Todoist backend) | For a Reminders backend |
|---|---|---|---|
| project | the list prefix (`TODO_PREFIX`, default a fixed word) | a Todoist project | the prefix, from the config |
| area | one list per area, `<prefix> - <area>` | a section | one list per area; groups are invisible to EventKit, so the prefix is the only grouping |
| kinds | `kind=a,b` in the trailer | labels | trailer again, or ReminderKit hashtags (section 6) |
| effort, mode | trailer | labels `effort-S`, mode labels | same choice as kinds |
| value | trailer `value=N`, and the native priority derived from it | the native priority (p1 most valuable) | the native priority (three levels plus none, so p4 has no home) |
| src, since | trailer | one task comment | trailer, or the notes' last line; Reminders has no comments |
| origin link | `url` (invisible in the app) | an `[Origin](<url>)` link ending the body | the notes body, since `url` is not shown; ReminderKit's URL attachment would show |
| subtasks | none | native | none through EventKit |
| description | notes above the trailer, capped at 30 words | a markdown body of any length | notes; the app renders plain text |

The trailer format, for reading old data: the last non-empty line of the notes, beginning with
`[todo]`, then space-separated `key=value` pairs: `effort=S value=3 mode=unattended src=7e57ab1e
since=2026-09-22 kind=decision,verify`. Lines above it, trimmed, were the description; a notes
field with no trailer was all description. The title cap was 60 characters (about eight words) and
`--force` turned the caps into warnings.

The import grammar of the old tool is the root-row subset of this package's (`README.md`, Import
grammar): `- [ ] <title> @YYYY-MM-DD !1..3 #area #kind #kind`, an indented description, and an
indented attribute line `src: ...; since: ...; effort: ...; value: ...; mode: ...` with `;`, `|` or
the middle dot as separators; `area:`, `kind:` and `url:` accepted on that line; `[x]` rows
skipped; a title already present in any area list skipped as a duplicate. Its `export` wrote the
same generated markdown view this package's `export` writes, with the meta bracket `[id ...,
kinds, effort, vN, mode, src ..., since ..., overdue]`.

Shape of a backend here, given the above:

- The Python core stays standard-library only (the plan's decision 11), so EventKit is reached
  through a helper executable, not a Python binding. The helper is the app bundle of section 2,
  built from a small Swift or Objective-C target kept beside the backend, speaking JSON on stdout
  and taking one command per launch (about 0.15 s each). Batch what can be batched: one `list
  --json` and local filtering beat a launch per task.
- The backend's `Item` view reads the trailer (or the ReminderKit tags) into the house attributes,
  so `list`, `show`, `export` and the filters see the same fields as the Todoist backend's.
- No comments, no subtasks, no sections: the plan gates that this package already runs before a
  write (`require`, `within`) are the place to refuse `--parent` and `comments` with a clear name.
- Whether Python itself (PyObjC, or ctypes over the EventKit framework) can hold a grant when run
  from a terminal was not tried; the route that is known to work is the helper app.
- A third route, observed on 2026-09-29 while the old lists were removed: AppleScript to the
  Reminders app (`osascript`, `tell application "Reminders" ...`) read the list names, counted
  reminders and deleted five lists from the same Claude Code Bash tool that EventKit had refused,
  with no prompt; the desktop app evidently holds an Automation grant for Reminders (System
  Settings, Privacy and Security, Automation), which is what Apple Events need, unlike the
  Reminders data grant EventKit needs. The dictionary (`sdef /System/Applications/Reminders.app`,
  macOS 27) has the classes `account`, `list` and `reminder`; a reminder carries `name`, `body`,
  `due date`, `allday due date`, `remind me date`, `priority`, `completed`, `completion date`,
  `flagged`, `container`, `id`, `creation date` and `modification date`; a list carries `name`,
  `color`, `emblem`, `container` and `id`; the one command is `show`. No tags, URL, sections or
  subtasks, as in EventKit. So a backend could run on `osascript` alone (JXA for JSON output) for
  the public fields, without a helper app. Not measured: the cost of a call, its behaviour on
  hundreds of reminders, and whether and how a fresh machine prompts for the Automation grant.

## 6. Beyond EventKit: the ReminderKit route

Apple's private ReminderKit framework backs the Reminders app and reaches everything EventKit
hides. What was established on macOS 27 (2026-09-22), by a runtime check only, no call made:

- Read side. From a process that holds the Reminders grant, `EKReminder.backingObject` gives the
  ReminderKit object; its hashtags are readable as `valueForKey:@"hashtags"` and the visible URL as
  `attachmentContext.urlAttachments`. This is how the open-source go-eventkit does it
  (github.com/BRO3886/go-eventkit, `reminders/bridge_darwin.m`). Doing this read first settles the
  open question below without writing anything.
- Write side, per reminder: `REMSaveRequest initWithStore:`, `updateReminder:`, the change, then
  `saveSynchronouslyWithError:`. The changes:
  - tags: `hashtagContext`, `removeAllHashtags`, `addHashtagWithType:name:` (type 0), one tag per
    kind and for `effort-S`, the value and the mode;
  - the URL the app shows: `attachmentContext`, `setURLAttachmentWithURL:` and
    `removeURLAttachments`;
  - flag: `flaggedContext`, `setFlagged:`;
  - sections inside one list: `REMListSectionContextChangeItem
    setUnsavedMembershipsOfRemindersInSections:` exists; no prior art was found for it, so it needs
    its own probe.
  `backingObject` and every write selector above existed on that Mac; all but the section one are
  the ones go-eventkit uses.
- Guards: check `respondsToSelector:` before every private call and refuse by name when one is
  missing, so a macOS update degrades to "tags not written" and never to a half-applied change.
  Title, notes, due and priority stay on public EventKit.
- The open question: whether `remindd` accepts ReminderKit calls from a non-Apple app on macOS 27.
  Nothing observed answers it either way.
- Once tags and the visible URL carry the attributes, the trailer can go, and existing reminders
  are migrated trailer to tags (src and since as one readable line if tags cannot carry them).

## 7. Costs measured

On the 37 tasks the old tool held, counted with the Anthropic token counter (2026-09-22):

| Query | Tokens |
|---|---|
| `list --json` | 12,491 |
| `list` | 3,745 |
| `list --no-desc` | 1,588 |
| `list --mode unattended --effort S` | 180 |

The lesson carried into this package's `brief` and its skill: an agent should read a filtered
query, not the whole list, and JSON only when it is going to parse it.

## 8. What a machine keeps after the tool is gone

Deleting the tool's folder removes none of these; they are harmless and reusable by a successor:

- the Reminders lists `<prefix> - <area>` in the iCloud account, with the tasks they held (they
  drifted from the Todoist project from the day the move happened; treat them as stale);
- the Reminders permission grant, keyed to the bundle id `local.tools.todo` and its signing
  identity (System Settings, Privacy and Security, Reminders);
- the self-signed code-signing identity `todo-local` in the login keychain (`security
  find-identity -v -p codesigning`), reusable for a successor's bundle if the bundle id and
  identifier are kept.

Removing them (done once, 2026-09-29), in this order:

1. The grant, while the app bundle still exists: `tccutil reset Reminders <bundle id>`. The
   command resolves the id through LaunchServices and fails with "No such bundle identifier"
   once the app is gone; the record then stays, inert, and only a reset of the whole Reminders
   service or System Settings would clear it.
2. The lists: `osascript -e 'tell application "Reminders" to delete list "<name>"'` deletes a
   list with its reminders; count first with `count of reminders of list "<name>"`.
3. The identity: export the certificate (`security find-certificate -c <name> -p > cert.pem`),
   remove its trust setting by that file (`security remove-trusted-cert cert.pem`), then delete
   certificate and key (`security delete-identity -c <name> -t <keychain>`). The trust setting is
   addressed by certificate, so export before deleting.

## Appendix A: the launcher (zsh)

```zsh
#!/bin/zsh
# Launcher for todo.app. The app is started through LaunchServices (open) so macOS charges the
# Reminders permission to the app itself, not to whatever process runs this script. Output and the
# exit code come back through temp files (the app writes --exit-file when it ends; waiting on that
# file avoids the "Unable to block on applications" race of open -W); stdin is forwarded only for
# --note -, so an idle stdin pipe never blocks a call. Rebuilds and re-signs when the sources are newer.
set -euo pipefail
here="${0:A:h}"
app="$here/build/todo.app"
bin="$app/Contents/MacOS/todo"
if [[ ! -x "$bin" || "$here/Sources/todo/main.swift" -nt "$bin" || "$here/Package.swift" -nt "$bin" || "$here/bundle/Info.plist" -nt "$app/Contents/Info.plist" ]]; then
  "$here/build.sh"
fi
if [[ $# -eq 0 || "$1" == help || "$1" == --help || "$1" == -h ]]; then
  exec "$bin" "$@"
fi
tmp=$(mktemp -d /tmp/todo.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
in=/dev/null
for a in "$@"; do
  if [[ "$a" == "-" || "$a" == "--note=-" ]]; then in="$tmp/in"; cat > "$in"; break; fi
done
: > "$tmp/out"; : > "$tmp/err"
if ! open -n --stdin "$in" --stdout "$tmp/out" --stderr "$tmp/err" -a "$app" --args --exit-file "$tmp/code" "$@"; then
  cat "$tmp/err" 1>&2
  echo "todo: open failed for $app" 1>&2
  exit 1
fi
deadline=$(( $(date +%s) + ${TODO_TIMEOUT:-300} ))
while [[ ! -s "$tmp/code" ]]; do
  if (( $(date +%s) > deadline )); then
    cat "$tmp/out"; cat "$tmp/err" 1>&2
    echo "todo: no exit status after ${TODO_TIMEOUT:-300} s (permission prompt unanswered, or the app crashed)" 1>&2
    exit 124
  fi
  sleep 0.05
done
cat "$tmp/out"
cat "$tmp/err" 1>&2
exit "$(cat "$tmp/code")"
```

Inside the app, the exit-file protocol was: strip `--exit-file PATH` from the arguments before
parsing; every exit goes through one `die` function or an `atexit` handler that flushes stdout and
writes the status to the path.

## Appendix B: build.sh

```zsh
#!/bin/zsh
# Build the release binary, assemble build/todo.app, sign it with a stable identity.
# Identity: $TODO_SIGN_IDENTITY, else the "todo-local" certificate (make-identity.sh), else ad-hoc
# (the Reminders grant then dies with every rebuild).
set -euo pipefail
here="${0:A:h}"
cd "$here"
swift build -c release 1>&2
app="$here/build/todo.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp "$here/.build/release/todo" "$app/Contents/MacOS/todo"
cp "$here/bundle/Info.plist" "$app/Contents/Info.plist"
printf 'APPL????' > "$app/Contents/PkgInfo"
identity="${TODO_SIGN_IDENTITY:-}"
if [[ -z "$identity" ]] && security find-identity -v -p codesigning 2>/dev/null | grep -q '"todo-local"'; then
  identity="todo-local"
fi
if [[ -z "$identity" ]]; then
  echo "build.sh: no signing identity (run make-identity.sh once); signing ad-hoc, the Reminders grant will not survive rebuilds" 1>&2
  identity="-"
fi
codesign --force --sign "$identity" --identifier local.tools.todo --timestamp=none "$app" 1>&2
codesign --verify --strict "$app"
echo "built $app (signed: $identity)" 1>&2
```

The Swift package: `swift-tools-version: 6.4`, `platforms: [.macOS(.v14)]` (for
`requestFullAccessToReminders`), one `executableTarget` with `swiftSettings:
[.swiftLanguageMode(.v5)]`. Build products (`.build`, `build`) were gitignored.

## Appendix C: make-identity.sh

```zsh
#!/bin/zsh
# One-time: create a self-signed code-signing certificate "todo-local" in the login keychain and
# trust it for code signing, so build.sh can sign todo.app with a stable identity. macOS may ask for
# the login password once (trust settings) and once more the first time codesign uses the key
# (choose "Always Allow"). Nothing leaves the machine.
set -euo pipefail
name="todo-local"
if security find-identity -v -p codesigning 2>/dev/null | grep -q "\"$name\""; then
  echo "identity $name already exists" 1>&2; exit 0
fi
tmp=$(mktemp -d /tmp/todo-identity.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
  -keyout "$tmp/key.pem" -out "$tmp/cert.pem" -subj "/CN=$name" \
  -addext "keyUsage=critical,digitalSignature" -addext "extendedKeyUsage=critical,codeSigning" \
  -addext "basicConstraints=critical,CA:false" 1>&2
openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -name "$name" -out "$tmp/$name.p12" -passout pass:todo -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1 1>&2
keychain="$HOME/Library/Keychains/login.keychain-db"
security import "$tmp/$name.p12" -k "$keychain" -P todo -T /usr/bin/codesign -T /usr/bin/security 1>&2
security add-trusted-cert -r trustRoot -p codeSign -k "$keychain" "$tmp/cert.pem" 1>&2
security find-identity -v -p codesigning | grep "\"$name\"" 1>&2
echo "identity $name ready" 1>&2
```

The legacy PKCS#12 algorithms (`PBE-SHA1-3DES`, `-macalg sha1`) are what `security import`
accepted; the modern defaults of OpenSSL 3 were not tried after this worked.

## Appendix D: Info.plist keys

```xml
<key>CFBundleExecutable</key>            <string>todo</string>
<key>CFBundleIdentifier</key>            <string>local.tools.todo</string>
<key>CFBundleName</key>                  <string>todo</string>
<key>CFBundlePackageType</key>           <string>APPL</string>
<key>CFBundleShortVersionString</key>    <string>0.2</string>
<key>CFBundleVersion</key>               <string>2</string>
<key>CFBundleInfoDictionaryVersion</key> <string>6.0</string>
<key>CFBundleDevelopmentRegion</key>     <string>en</string>
<key>LSMinimumSystemVersion</key>        <string>14.0</string>
<key>LSUIElement</key>                   <true/>
<key>NSRemindersFullAccessUsageDescription</key> <string>todo reads and writes the task lists kept in Reminders.</string>
<key>NSRemindersUsageDescription</key>           <string>todo reads and writes the task lists kept in Reminders.</string>
```

Bump `CFBundleVersion` when the plist changes; the launcher rebuilt when the plist was newer than
the copy inside the app.
