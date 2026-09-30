You are setting up `invoke-todos` on this machine for me: a command-line tool for task lists (Todoist in this version) that people and coding agents drive from a shell, with a Claude Code skill. The tool is in the archive or clone at:

    <PATH TO invoke-todos-<version>.tar.gz, or to the unpacked or cloned folder>

Start by reading, in this order, from that tree: `docs/spec-onboarding.md` (your protocol; follow its section 4 exactly), `docs/spec-config.md` (the config file you will write), `README.md` (what the tool does), `skills/invoke-todos/SKILL.md` (the vocabulary the tool expects). Do not run anything before you have read the protocol.

Then interview me, one question at a time, each with its default, in the protocol's order:

1. Where to keep the tree, which folder for the command, and what to call the command (default `todos`).
2. Whether to link the Claude Code skill into `~/.claude/skills` (the default when Claude Code is present), or to install the CLI alone.
3. How I want the API token stored: macOS Keychain, a 0600 file, an environment variable, or a command that prints it.
4. Whether to sync with what is already in my account or to start from scratch. For an existing account, run the tool's `config init --from-account` and walk me through its proposal (which projects are task lists, whether the effort and mode labels it found are right, which project is the default). From scratch, ask me for project names, the areas of each, the kinds, the effort and mode names with their meanings, what priority means to me, whether I want provenance (the src/since comment and the Origin link), and the default project.
5. Whether to keep the default timeouts, the title cap and the cache folder.

Then wire everything: verify and unpack the archive, run `install.sh` (dry run first; it links the command and the skill), write the config and check it, wait for me to store the token in my own terminal (give me the exact line for the source I chose), run the tool's `doctor`, show me `setup plan` and apply it only when I say yes, run the first `list` and `brief`, run the offline test suite once, and finish with `doctor --claude`.

Rules, no exceptions:

- Never ask me to paste the token, never print it, never write it into a file or a command. I store it myself; you check reachability with `doctor`.
- Every write to my account is shown as a plan first and applied only after I say yes to that plan. Nothing in the account is deleted, renamed or moved during onboarding unless I ask for it by name.
- Nothing under my home folder is overwritten; when the installer refuses, show me why and ask.
- Stay within the API's rate limit: one sync, the init and the setup are enough; do not run the live smoke test.
- End with the report in the protocol's section 4.6: what was installed where, the config path, what was created or mapped in the account, whether the skill is wired, the test count, what was skipped and why, and what I should do next. Report a failed step as failed, with its output.
