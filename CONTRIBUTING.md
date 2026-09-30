# Contributing

Short, because the README's maintainer notes carry the invariants. Before a pull request:

1. **Run the suite on Python 3.9.** The floor is 3.9 and the standard library; the tests run on the
   system `python3` to keep it so. `python3 tests/test_todoist.py` (offline, against the mock),
   `tests/test_config.py`, `tests/test_layering.py`, `tests/test_install.py` and `tests/test_public.py`
   must all be green. No new dependency; no build step.
2. **When the live API disagrees with the mock, fix the mock first.** `tests/mock_todoist.py` encodes the
   API behaviour the CLI relies on; a change in the CLI comes with the mock change and a test that shows
   it. Run `tests/live_smoke.py` once against a real account when the change touches a request; it
   spends a large share of the rate limit, so not back to back.
3. **The core never imports a backend.** `invoke_todos/*.py` speaks the house model; everything that
   speaks Todoist's API lives under `invoke_todos/backends/todoist/`. `tests/test_layering.py` enforces
   it. A second backend is a new folder there that registers its verbs and flag sets; the interface
   between the two is written when that backend shows which seams are real.
4. **No behaviour change without a test change.** The offline suite drives the CLI as a subprocess and
   checks stdout, stderr, exit codes and the mock's store; a change in what a verb prints is a change in
   the suite, in the same commit.
5. **Nothing personal in the tree.** No names, project names, hostnames or home paths; the config file
   carries those. `tests/test_public.py` names every hit.
6. **A change goes in `docs/change-log.md`**, newest first, in a sentence or two: what changed and what
   the tests say.
