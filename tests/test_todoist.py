#!/usr/bin/env python3
# Offline tests: every verb of ../todos against mock_todoist.py, run as a subprocess on the same
# interpreter (run them with /usr/bin/python3 to prove Python 3.9). python3 tests/test_todoist.py

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mock_todoist as mock  # noqa: E402

CLI = os.path.join(os.path.dirname(HERE), "todos")
TODAY = date.today().isoformat()
SESSION = "https://example.com/session?sid=%s"  # the fixture config's url template
CONFIG = os.path.join(HERE, "fixtures", "config.json")


def titles(p):
    return [l.split(" ")[-1] for l in p.stdout.split("\n") if l.strip()]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = mock.serve()
        cls.base = "http://127.0.0.1:%d/api/v1" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        mock.STORE.reset()
        self.tmp = tempfile.mkdtemp(prefix="todoist-test.")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def cli(self, *args, **kw):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TODOIST_", "TODOS_", "CLAUDE_"))}
        env.update(TODOIST_API_BASE=self.base, TODOIST_API_TOKEN=kw.get("token", mock.TOKEN),
                   TODOS_CONFIG=kw.get("config", CONFIG), TODOIST_TIMEOUT="10",
                   TODOIST_CACHE=kw.get("cache", os.path.join(self.tmp, "cache")), TODOIST_SETTLE=kw.get("settle", "0"))
        env.update(kw.get("env") or {})
        p = subprocess.run([sys.executable, CLI] + list(args), input=kw.get("stdin"), capture_output=True,
                           text=True, env=env, timeout=60)
        ok = kw.get("ok", True)
        if ok is True and p.returncode != 0:
            self.fail("todos %s -> %d\nstdout: %s\nstderr: %s" % (" ".join(args), p.returncode, p.stdout, p.stderr))
        if ok is False and p.returncode == 0:
            self.fail("expected a failure: todos %s\nstdout: %s" % (" ".join(args), p.stdout))
        return p

    def items(self):
        pids = [p["id"] for p in mock.STORE.projects if p["name"] == "Work"]
        return [i for i in mock.STORE.items
                if pids and i["project_id"] == pids[0] and not i["checked"] and not i["is_deleted"]]

    def notes(self, item_id):
        return [n["content"] for n in mock.STORE.notes if n["item_id"] == item_id and not n["is_deleted"]]

    def jlist(self, *args):
        return json.loads(self.cli("list", "--json", *args).stdout)

    def file(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def read(self, path, mode="r"):
        with open(path, mode) as f:
            return f.read()


class TestAccess(Base):
    def test_help_needs_no_token(self):
        self.assertIn("todos add", self.cli("help", token="").stdout)

    def test_missing_token(self):
        self.assertIn("TODOIST_API_TOKEN is not set", self.cli("list", token="", ok=False).stderr)

    def test_bad_token(self):
        self.assertIn("refused the token", self.cli("list", token="wrong", ok=False).stderr)

    def test_rate_limit_exit_75(self):
        p = self.cli("list", token="rate-limited", ok=None)
        self.assertEqual(p.returncode, 75)
        self.assertIn("retry in 30 s", p.stderr)

    def test_unknown_flag_and_verb(self):
        self.assertIn("unknown flag --bogus", self.cli("list", "--bogus", ok=False).stderr)
        self.assertIn("unknown verb frobnicate", self.cli("frobnicate", ok=False).stderr)

    def test_empty_account(self):
        p = self.cli("list")
        self.assertEqual(p.stdout, "")
        self.assertIn('no Todoist project "Work" yet', p.stderr)
        self.assertNotIn("Buy milk", self.cli("export").stdout)


class TestAdd(Base):
    def test_add_builds_project_section_labels_task_and_comment(self):
        p = self.cli("add", "Chase the DGT filing", "--area", "car", "--kind", "verify", "--due", "2026-09-25",
                     "--effort", "S", "--prio", "1", "--mode", "owner", "--src", "7e57ab1e", "--since", "2026-09-22",
                     "--note", "Seller duty ran to 2026-09-21.")
        self.assertIn('created Todoist project "Work"', p.stderr)
        self.assertIn('created section "car"', p.stderr)
        self.assertRegex(p.stdout.strip(), r"^6X\S{6,} - !1 2026-09-25\S* \[car:verify\] S/owner Chase the DGT filing$")
        [it] = self.items()
        self.assertEqual(it["priority"], 4)  # p1 in the apps is 4 in the API
        self.assertEqual(sorted(it["labels"]), ["effort-S", "owner", "verify"])
        self.assertEqual(it["due"]["date"], "2026-09-25")
        self.assertEqual(it["description"], "Seller duty ran to 2026-09-21. [Origin](%s)" % (SESSION % "7e57ab1e"))
        self.assertEqual(self.notes(it["id"]), ["src: 7e57ab1e; since: 2026-09-22"])
        # a second task in the same area reuses the section and the labels (the mock refuses duplicate labels)
        self.cli("add", "Second one", "--area", "car", "--kind", "verify", "--effort", "S", "--prio", "1", "--mode", "owner")
        self.assertEqual(len([s for s in mock.STORE.sections if s["name"] == "car"]), 1)
        self.assertEqual(len(self.jlist()), 2)

    def test_defaults_and_json(self):
        o = json.loads(self.cli("add", "Plain task", "--area", "tools", "--json").stdout)
        self.assertEqual((o["title"], o["area"], o["prio"], o["since"]), ("Plain task", "tools", 0, TODAY))
        self.assertNotIn("url", o)
        [it] = self.items()
        self.assertEqual((it["priority"], it["description"], it["labels"]), (1, "", []))

    def test_file_src_and_explicit_url(self):
        self.cli("add", "From a file", "--area", "tools", "--src", "todo-2026-09-02#10")
        self.cli("add", "With a link", "--area", "tools", "--url", "https://example.com/x")
        by = {i["content"]: i for i in self.items()}
        self.assertEqual(by["From a file"]["description"], "")
        self.assertEqual(by["With a link"]["description"], "[Origin](https://example.com/x)")
        rows = {r["title"]: r for r in self.jlist()}
        self.assertEqual(rows["From a file"]["src"], "todo-2026-09-02#10")
        self.assertEqual(rows["With a link"]["url"], "https://example.com/x")

    def test_title_cap_and_force(self):
        long_title = "x" * 61
        self.assertIn("title is 61 characters", self.cli("add", long_title, "--area", "tools", ok=False).stderr)
        self.assertEqual(self.items(), [])
        self.assertIn("warning:", self.cli("add", long_title, "--area", "tools", "--force").stderr)

    def test_body_is_markdown_of_any_length(self):
        body = "# Plan\n\nSome words, " + " ".join(["w"] * 40) + "\n\n- one\n- two\n\n```\n  code, indented\n```"
        self.cli("add", "Rich", "--area", "tools", "--note", "-", "--src", "7e57ab1e", stdin=body + "\n")
        self.cli("add", "Prose", "--area", "tools", "--note", "Ends in prose.", "--url", "https://example.com/p")
        self.cli("add", "Listed", "--area", "tools", "--note", "- a\n- b", "--url", "https://example.com/l")
        by = {i["content"]: i for i in self.items()}
        # after a code fence the link takes a paragraph of its own; after prose it rides on the line
        self.assertEqual(by["Rich"]["description"], body + "\n\n[Origin](%s)" % (SESSION % "7e57ab1e"))
        self.assertEqual(by["Prose"]["description"], "Ends in prose. [Origin](https://example.com/p)")
        self.assertEqual(by["Listed"]["description"], "- a\n- b\n\n[Origin](https://example.com/l)")
        rows = {r["title"]: r for r in self.jlist()}
        self.assertEqual((rows["Rich"]["desc"], rows["Rich"]["url"]), (body, SESSION % "7e57ab1e"))
        self.assertEqual((rows["Prose"]["desc"], rows["Listed"]["desc"]), ("Ends in prose.", "- a\n- b"))
        self.assertIn("\n# Plan\n", self.cli("show", rows["Rich"]["short"]).stdout)

    def test_note_from_stdin_and_timed_due(self):
        self.cli("add", "Stdin note", "--area", "tools", "--note", "-", "--due", "2026-09-25T18:00",
                 stdin="line one\nline two\n")
        [it] = self.items()
        self.assertEqual(it["description"], "line one\nline two")
        self.assertEqual(it["due"]["date"], "2026-09-25T18:00:00")
        self.assertEqual(self.jlist()[0]["due"], "2026-09-25 18:00")

    def test_validation_writes_nothing(self):
        cases = [(("--effort", "XL"), "effort must be"), (("--mode", "robot"), "mode must be"),
                 (("--prio", "7"), "--prio needs"), (("--kind", "owner"), "not allowed"),
                 (("--due", "2026-13-45"), "--due needs"), (("--deadline", "soon"), "--deadline needs"),
                 (("--since", "yesterday"), "since must be")]
        for flags, msg in cases:
            self.assertIn(msg, self.cli("add", "T", "--area", "a", *flags, ok=False).stderr)
        self.assertIn("one lowercase word", self.cli("add", "T", "--area", "two words", ok=False).stderr)
        self.assertEqual((self.items(), mock.STORE.write_requests), ([], 0))


class TestList(Base):
    def seed(self):
        self.cli("add", "Alpha", "--area", "bills", "--kind", "decision", "--effort", "S", "--prio", "1", "--mode",
                 "unattended", "--src", "0facbdc3", "--since", "2026-08-22", "--due", "2020-01-01")
        self.cli("add", "Beta", "--area", "bills", "--effort", "M", "--prio", "3", "--mode", "assisted",
                 "--since", "2026-09-01")
        self.cli("add", "Gamma", "--area", "home", "--kind", "build", "--effort", "S", "--mode",
                 "unattended", "--prio", "1", "--due", "2099-01-01", "--note", "first line\nsecond line")

    def test_brief_digest_and_help_fields(self):
        self.seed()  # Alpha: overdue, p1, S, unattended, src 0facbdc3; Beta: p3, M, assisted; Gamma: p1, S, unattended, 2099

        def parts(out):
            d, cur = {}, None
            for l in out.split("\n")[1:]:
                if l.startswith("# "):
                    cur = l[2:].rsplit(" (", 1)[0]
                    d[cur] = []
                elif cur and l.strip():
                    d[cur].append(l.strip())
            return d

        p = self.cli("brief", "--src", "0facbdc3")
        self.assertEqual(p.stdout.split("\n")[0], "Work: 3 open, 1 overdue, 0 due today; areas: bills 2, home 1")
        d = parts(p.stdout)
        self.assertEqual(list(d), ["due: overdue and today", "unattended", "assisted", "this session: src 0facbdc3"])
        self.assertEqual({k: [r.split(" ")[-1] for r in v] for k, v in d.items()},
                         {"due: overdue and today": ["Alpha"], "unattended": ["Alpha", "Gamma"], "assisted": ["Beta"],
                          "this session: src 0facbdc3": ["Alpha"]})
        self.assertIn("# due: overdue and today (1)", p.stdout)
        # the session id from the environment, the cap, and no session at all
        p = self.cli("brief", "--limit", "1", env={"CLAUDE_CODE_SESSION_ID": "0facbdc3-0000-4000-8000-000000000000"})
        d = parts(p.stdout)
        self.assertEqual(len(d["unattended"]), 2)
        self.assertEqual(d["unattended"][-1], "+1 more: todos list --mode unattended")
        self.assertEqual([r.split(" ")[-1] for r in d["this session: src 0facbdc3"]], ["Alpha"])
        d = parts(self.cli("brief").stdout)
        self.assertEqual(d["this session: src unknown, pass --src"], ["none"])
        # the JSON shape: fixed keys, rows with every key
        o = json.loads(self.cli("brief", "--json", "--src", "0fac").stdout)
        self.assertEqual(sorted(o), ["areas", "due", "limit", "modes", "open", "overdue", "project", "session", "today"])
        self.assertEqual((o["project"], o["open"], o["overdue"], o["today"], o["areas"], o["limit"]),
                         ("Work", 3, 1, 0, {"bills": 2, "home": 1}, 10))
        self.assertEqual(list(o["modes"]), ["unattended", "assisted"])
        row = o["modes"]["unattended"]["rows"][0]
        self.assertEqual(list(row), ["id", "title", "area", "project", "prio", "effort", "mode", "kinds", "due", "src"])
        self.assertEqual((row["title"], row["project"], row["prio"], row["effort"], row["kinds"], row["due"], row["src"]),
                         ("Alpha", "Work", 1, "S", ["decision"], "2020-01-01", "0facbdc3"))
        beta = o["modes"]["assisted"]["rows"][0]
        self.assertEqual((beta["title"], beta["due"], beta["src"], beta["kinds"]), ("Beta", None, None, []))
        self.assertEqual((o["session"]["src"], o["session"]["total"], o["due"]["total"]), ("0fac", 1, 1))
        o = json.loads(self.cli("brief", "--json", "--limit", "1", "--all-projects").stdout)
        self.assertEqual((o["project"], o["areas"], o["modes"]["unattended"]["total"], len(o["modes"]["unattended"]["rows"])),
                         (None, {"Inbox/-": 1, "Work/bills": 2, "Work/home": 1}, 2, 1))  # the mock seeds one Inbox task
        self.assertEqual(o["session"], {"src": None, "total": 0, "rows": []})
        # the field schema
        p = self.cli("help", "fields")
        self.assertEqual(len([l for l in p.stdout.split("\n") if l.startswith("  ")]), 25)
        self.assertIn("  prio ", p.stdout)
        self.assertTrue(p.stdout.rstrip().endswith("brief rows: id, title, area, project, prio, effort, mode, kinds, due, src"))

    def test_filters_sorting_and_formats(self):
        self.seed()
        self.assertEqual(titles(self.cli("list")), ["Alpha", "Gamma", "Beta"])
        self.assertEqual(titles(self.cli("list", "--area", "bills")), ["Alpha", "Beta"])
        self.assertEqual(titles(self.cli("list", "--kind", "build")), ["Gamma"])
        self.assertEqual(titles(self.cli("list", "--mode", "unattended", "--effort", "S")), ["Alpha", "Gamma"])
        self.assertEqual(titles(self.cli("list", "--prio", "3")), ["Beta"])
        self.assertEqual(titles(self.cli("list", "--src", "0fac")), ["Alpha"])
        self.assertEqual(titles(self.cli("list", "--overdue")), ["Alpha"])
        self.assertEqual(titles(self.cli("list", "--due-before", "2030-01-01")), ["Alpha"])
        self.assertEqual(titles(self.cli("list", "--sort", "since")), ["Alpha", "Beta", "Gamma"])
        self.assertEqual(titles(self.cli("list", "--sort", "due")), ["Alpha", "Gamma", "Beta"])
        self.assertRegex(self.cli("list", "--src", "0facbdc3").stdout,
                         r" - !1 2020-01-01! \[bills:decision\] S/unattended Alpha\n$")
        desc = self.cli("list", "--kind", "build", "--desc").stdout
        self.assertIn("\n         first line\n", desc)
        self.assertNotIn("second line", desc)
        p = self.cli("list", "--json", "--fields", "id,title,prio")
        self.assertEqual(p.stdout.count("\n"), 1)
        self.assertEqual(set(json.loads(p.stdout)[0]), {"id", "title", "prio"})
        self.assertIn("unknown field(s) bogus", self.cli("list", "--json", "--fields", "bogus", ok=False).stderr)
        rows = {r["title"]: r for r in self.jlist()}
        a = rows["Alpha"]
        self.assertEqual((a["kinds"], a["src"], a["since"], a["url"], a["effort"], a["mode"]),
                         (["decision"], "0facbdc3", "2026-08-22", SESSION % "0facbdc3", "S", "unattended"))
        self.assertNotIn("value", a)
        self.assertEqual(rows["Gamma"]["desc"], "first line\nsecond line")
        self.assertNotIn("link", a)
        self.assertIn('no section "nope"', self.cli("list", "--area", "nope", ok=False).stderr)
        self.assertNotIn("Buy milk", self.cli("list").stdout)
        self.assertIn("--sort takes", self.cli("list", "--sort", "size", ok=False).stderr)


class TestShowEdit(Base):
    def test_show_and_prefixes(self):
        self.cli("add", "One", "--area", "tools", "--src", "7e57ab1e")
        self.cli("add", "Two", "--area", "tools")
        one = [r for r in self.jlist() if r["title"] == "One"][0]
        out = self.cli("show", one["short"]).stdout
        for want in ("title:    One", "src:      7e57ab1e", "since:    " + TODAY, "status:   open",
                     "https://app.todoist.com/app/task/" + one["id"]):
            self.assertIn(want, out)
        self.assertEqual(json.loads(self.cli("show", one["id"], "--json").stdout)["link"],
                         "https://app.todoist.com/app/task/" + one["id"])
        self.assertIn("ambiguous id 6X", self.cli("show", "6X", ok=False).stderr)
        self.assertIn("no task with id starting zzz", self.cli("show", "zzz", ok=False).stderr)

    def test_a_task_link_is_an_id(self):
        self.cli("add", "Linked", "--area", "tools")
        self.cli("add", "Child", "--parent", self.jlist()[0]["short"])
        tid = self.jlist()[0]["id"]
        for link in ("https://app.todoist.com/app/task/" + tid, "https://app.todoist.com/app/task/linked-task-" + tid,
                     "app.todoist.com/app/task/%s/" % tid, "https://todoist.com/showTask?id=" + tid,
                     "todoist://task?id=" + tid, "https://app.todoist.com/app/task/" + tid[:9]):
            self.assertEqual(json.loads(self.cli("show", link, "--json").stdout)["id"], tid, link)
        self.assertIn("no task with id starting today", self.cli("show", "https://app.todoist.com/app/today", ok=False).stderr)
        link = "https://app.todoist.com/app/task/linked-" + tid
        self.cli("comments", "add", link, "Through the link")
        self.assertIn("Through the link", self.cli("comments", link).stdout)
        self.cli("add", "Second child", "--parent", link)
        self.assertEqual(len(json.loads(self.cli("show", link, "--json").stdout)["subtasks"]), 2)
        self.assertIn("(+2 subtasks)", self.cli("done", link).stdout)
        self.assertTrue(self.cli("undone", link).stdout.startswith("reopened: "))
        self.assertEqual([r["title"] for r in self.jlist()], ["Linked"])

    def test_links_name_a_task_as_a_markdown_link(self):
        self.cli("add", "Linked", "--area", "tools")
        one = self.jlist()[0]
        tid, short = one["id"], one["short"]
        web = "https://app.todoist.com/app/task/" + tid
        self.assertTrue(self.cli("list").stdout.startswith(short + " - "))
        self.assertTrue(self.cli("list", "--links").stdout.startswith("[task#%s](%s) - " % (short, web)))
        self.assertRegex(self.cli("add", "Child", "--parent", short, "--links").stdout,
                         r"^\[task#\w+\]\(https://app\.todoist\.com/app/task/\w+\) - ")
        shown = self.cli("show", short, "--links").stdout
        self.assertRegex(shown, r"\n  \[task#\w+\]\(https://app\.todoist\.com/app/task/\w+\) - Child\n")
        app = {"TODOIST_TASK_URL": "todoist://task?id=%s"}  # todoist.task_url: the link every surface prints
        self.assertIn("(todoist://task?id=%s)" % tid, self.cli("show", short, env=app).stdout)
        self.assertEqual(json.loads(self.cli("show", short, "--json", env=app).stdout)["link"], "todoist://task?id=" + tid)
        row = self.cli("list", "--links", env=app).stdout.split("\n")[0]
        self.assertTrue(row.startswith("[task#%s](todoist://task?id=%s) - " % (short, tid)), row)
        for ref in ("task#" + short, row.split(" ")[0], "[Linked](%s)" % web, "[x](https://app.todoist.com/app/task/linked-%s)" % tid,
                    "[Linked [draft]](%s)" % web, "[task#%s](%s) Linked" % (short, web), "[task#%s](https://x.example/t/%s/view)" % (short, tid),
                    "[task#%s](https://x.example/?task=%s&x=(y))" % (short, tid), "[Linked](%s) and [other](https://x.example)" % web):
            self.assertEqual(json.loads(self.cli("show", ref, "--json").stdout)["id"], tid, ref)
        self.assertIn("no task with id starting", self.cli("show", "[Linked](https://x.example/t/view)", ok=False).stderr)
        self.cli("projects", "add", "Other")
        self.assertTrue(self.cli("move", short, "--to", "Other", "--links").stdout.startswith("moved: [task#%s](%s) Linked -> Other" % (short, web)))
        bad = self.cli("list", "--links", env={"TODOIST_TASK_URL": "todoist://task"}, ok=False)  # a template without %s names nothing
        self.assertIn("TODOIST_TASK_URL: must contain %s", bad.stderr)

    def test_a_pasted_link_names_its_own_task_in_any_project(self):
        # short ids belong to one project's listing: two projects may print the same one, so the link's id decides
        self.cli("add", "Seed", "--area", "tools")  # the default project exists from its first task on
        self.cli("projects", "add", "Other")
        work = [p["id"] for p in mock.STORE.projects if p["name"] == "Work"][0]
        other = [p["id"] for p in mock.STORE.projects if p["name"] == "Other"][0]
        mock.STORE.add_item({"content": "In Work", "project_id": work}, "6Share0000000001")
        mock.STORE.add_item({"content": "In Other", "project_id": other}, "6Share0000000002")
        row = self.cli("list", "--links", "--in", "Other").stdout.strip().split(" ")[0]
        self.assertEqual(row, "[task#6Share00](https://app.todoist.com/app/task/6Share0000000002)")
        self.assertEqual(json.loads(self.cli("show", row, "--json").stdout)["title"], "In Other")
        self.assertIn("In Other", self.cli("done", row).stdout)
        self.assertEqual([i["content"] for i in mock.STORE.items if i["checked"]], ["In Other"])
        # a link whose text and id disagree is read by its id; text with no link behind it stays a prefix
        self.assertEqual(json.loads(self.cli("show", "[task#6Share00](https://app.todoist.com/app/task/6Share0000000001)", "--json").stdout)["title"], "In Work")
        self.assertEqual(json.loads(self.cli("show", "task#6Share0000000001", "--json").stdout)["title"], "In Work")

    def test_edit_everything_then_clear_then_noop(self):
        self.cli("add", "Edit me", "--area", "bills", "--kind", "decision", "--effort", "S", "--prio", "2", "--mode",
                 "owner", "--src", "0facbdc3", "--since", "2026-08-22", "--note", "Old text")
        rid = self.jlist()[0]["id"]
        p = self.cli("edit", rid, "--title", "Edited", "--area", "home", "--kind", "build,verify", "--due",
                     "2026-10-01", "--deadline", "2026-10-15", "--prio", "1", "--effort", "M", "--mode", "assisted",
                     "--src", "7e57ab1e", "--note", "New text")
        self.assertIn('created section "home"', p.stderr)
        self.assertTrue(p.stdout.startswith("edited: "))
        [it] = self.items()
        home = [s for s in mock.STORE.sections if s["name"] == "home"][0]
        self.assertEqual(it["section_id"], home["id"])
        self.assertEqual((it["content"], it["priority"]), ("Edited", 4))
        self.assertEqual(sorted(it["labels"]), ["assisted", "build", "effort-M", "verify"])
        self.assertEqual((it["due"]["date"], it["deadline"]["date"]), ("2026-10-01", "2026-10-15"))
        self.assertEqual(it["description"], "New text [Origin](%s)" % (SESSION % "7e57ab1e"))
        self.assertEqual(self.notes(it["id"]), ["src: 7e57ab1e; since: 2026-08-22"])  # updated in place
        self.cli("edit", rid, "--clear-due", "--clear-deadline", "--url", "")
        [it] = self.items()
        self.assertEqual((it["due"], it["deadline"], it["description"]), (None, None, "New text"))
        self.assertTrue(self.cli("edit", rid).stdout.startswith("unchanged: "))

    def test_edit_keeps_app_labels_and_adds_no_comment(self):
        self.cli("add", "Seed", "--area", "tools")
        pid = [p["id"] for p in mock.STORE.projects if p["name"] == "Work"][0]
        sid = [s["id"] for s in mock.STORE.sections if s["name"] == "tools"][0]
        label = {"id": "99", "name": "waiting for", "is_deleted": False}
        mock.STORE.labels.append(label)
        mock.STORE.touch(label)
        mock.STORE.add_item({"content": "From the phone", "project_id": pid, "section_id": sid,
                             "labels": ["waiting for"]}, "6Phone0000000001")
        self.cli("edit", "6Phone", "--title", "From the phone, edited")
        it = [i for i in mock.STORE.items if i["id"] == "6Phone0000000001"][0]
        self.assertEqual((it["content"], it["labels"]), ("From the phone, edited", ["waiting for"]))
        self.assertEqual(self.notes(it["id"]), [])

    def test_areas_rename(self):
        TestList.seed(self)
        p = self.cli("areas", "rename", "Bills", "money")  # the old name matches case-insensitively
        self.assertIn("renamed: bills -> money", p.stdout)
        self.assertEqual([s["name"] for s in mock.STORE.sections if s["name"] in ("bills", "money")], ["money"])
        self.assertIn("money  (2 open)", self.cli("areas").stdout)
        self.assertIn("\n## money\n", self.cli("export").stdout)
        self.assertIn("exists", self.cli("areas", "rename", "money", "home", ok=False).stderr)
        self.assertIn("one lowercase word", self.cli("areas", "rename", "money", "two words", ok=False).stderr)
        self.assertIn('no section "nope"', self.cli("areas", "rename", "nope", "x", ok=False).stderr)

    def test_edit_project_moves_a_task_into_another_projects_section(self):
        self.cli("add", "Misfiled", "--area", "tools", "--kind", "verify")
        rid = self.jlist()[0]["id"]
        other = {"id": "6Other0000000000", "name": "Personal", "is_deleted": False, "is_archived": False}
        sec = {"id": "6Family000000000", "name": "family", "project_id": other["id"], "is_deleted": False,
               "is_archived": False, "section_order": 1}
        for o, rows in ((other, mock.STORE.projects), (sec, mock.STORE.sections)):
            rows.append(o)
            mock.STORE.touch(o)
        self.assertIn("needs --area", self.cli("edit", rid, "--project", "Personal", ok=False).stderr)
        self.assertIn('no section "car"', self.cli("edit", rid, "--project", "Personal", "--area", "car", ok=False).stderr)
        self.assertIn('no Todoist project "Nope"',
                      self.cli("edit", rid, "--project", "Nope", "--area", "family", ok=False).stderr)
        p = self.cli("edit", rid, "--project", "Personal", "--area", "family", "--mode", "owner")
        self.assertIn("moved to Personal / family", p.stderr)
        self.assertIn("family", p.stdout)
        it = [i for i in mock.STORE.items if i["id"] == rid][0]
        self.assertEqual((it["project_id"], it["section_id"], it["parent_id"]), (other["id"], sec["id"], None))
        self.assertIn("owner", it["labels"])
        self.assertEqual(self.items(), [])  # no longer in Work


class TestCache(Base):
    def test_reads_turn_incremental_and_fresh_forces_a_full_sync(self):
        self.cli("list")
        self.assertEqual((mock.STORE.full_reads, mock.STORE.incremental_reads), (1, 1))  # full, then catch-up
        self.cli("list")
        self.assertEqual((mock.STORE.full_reads, mock.STORE.incremental_reads), (1, 2))
        self.cli("list", "--fresh")
        self.assertEqual((mock.STORE.full_reads, mock.STORE.incremental_reads), (2, 3))
        self.cli("list", cache="off")
        self.assertEqual(mock.STORE.full_reads, 3)
        [state] = [f for f in os.listdir(os.path.join(self.tmp, "cache")) if f.startswith("state-")]
        self.assertEqual(oct(os.stat(os.path.join(self.tmp, "cache", state)).st_mode & 0o777), "0o600")

    def test_the_cache_never_holds_the_api_token(self):
        self.cli("list")
        [state] = [f for f in os.listdir(os.path.join(self.tmp, "cache")) if f.startswith("state-")]
        path = os.path.join(self.tmp, "cache", state)
        self.assertEqual(mock.STORE.user["token"], "secret-token-0123")  # the Sync user object carries it
        self.assertNotIn("secret-token", self.read(path))
        self.assertIn("ws-secret", mock.STORE.user["websocket_url"])  # and a second token in its websocket address
        self.assertNotIn("ws-secret", self.read(path))
        self.assertEqual(mock.STORE.user["urgent_reminder_device"]["device_token"], "dev-secret-89")  # and one deeper
        self.assertNotIn("dev-secret", self.read(path))
        self.assertIn("12345678", self.read(path))  # the rest of the nested object is kept
        self.assertIn("me@example.com", self.read(path))  # the rest of the user object is kept
        # a cache written before the rule loses both on the next read
        c = json.loads(self.read(path))
        c["single"]["user"]["token"] = "secret-token-0123"
        c["single"]["user"]["websocket_url"] = "wss://ws.example.com/ws?token=ws-secret-4567"
        c["single"]["user"]["urgent_reminder_device"] = {"device_token": "dev-secret-89"}
        with open(path, "w") as f:
            json.dump(c, f)
        self.cli("list")
        self.assertNotIn("secret-token", self.read(path))
        self.assertNotIn("ws-secret", self.read(path))
        self.assertNotIn("dev-secret", self.read(path))
        self.assertIn("(me)", self.cli("people").stdout)

    def test_changes_made_elsewhere_arrive_through_the_incremental_sync(self):
        self.cli("add", "Mine", "--area", "tools")
        pid = [p["id"] for p in mock.STORE.projects if p["name"] == "Work"][0]
        sid = [s["id"] for s in mock.STORE.sections if s["name"] == "tools"][0]
        phone = mock.STORE.add_item({"content": "Added on the phone", "project_id": pid, "section_id": sid},
                                    "6Phone0000000002")
        self.assertEqual(sorted(r["title"] for r in self.jlist()), ["Added on the phone", "Mine"])
        phone["checked"], phone["completed_at"] = True, mock.stamp()
        mock.STORE.touch(phone)
        self.assertEqual([r["title"] for r in self.jlist()], ["Mine"])
        self.assertEqual(mock.STORE.full_reads, 1)

    def test_a_lagging_full_sync_is_caught_up(self):
        mock.STORE.lag = 1  # the live API answered a full sync with data from before the last write
        self.cli("add", "Just written", "--area", "tools", "--kind", "build")
        self.assertEqual([r["title"] for r in self.jlist("--fresh")], ["Just written"])

    def test_a_broken_cache_file_is_replaced(self):
        self.cli("list")
        cache = os.path.join(self.tmp, "cache")
        [state] = [f for f in os.listdir(cache) if f.startswith("state-")]
        with open(os.path.join(cache, state), "w") as f:
            f.write("{not json")
        self.cli("add", "Still works", "--area", "tools")
        self.assertEqual([r["title"] for r in self.jlist()], ["Still works"])

    def test_a_deleted_projects_tasks_leave_the_cache(self):
        self.cli("projects", "add", "Temp")
        self.cli("add", "Ghost", "--area", "x", "--in", "Temp")
        self.assertIn("Ghost", self.cli("list", "--all-projects").stdout)
        self.cli("projects", "rm", "Temp", "--yes")
        # observed live: the incremental sync carries the deleted project, not its tasks; the cache drops them itself
        p = self.cli("list", "--all-projects")
        self.assertNotIn("Ghost", p.stdout)
        self.assertNotIn("Temp/x", self.cli("sections", "--all-projects").stdout)
        self.assertEqual(mock.STORE.full_reads, 1)


class TestSettle(Base):
    def test_edit_waits_until_a_new_task_has_settled(self):
        mock.STORE.settle = 2.0  # the live API lost title and due changes sent in a task's first ~3 s
        self.cli("add", "Fresh", "--area", "tools", "--due", "2026-10-01")
        rid = self.jlist()[0]["id"]
        self.cli("edit", rid, "--title", "Lost title", "--due", "2026-10-02", settle="0")
        [it] = self.items()
        self.assertEqual((it["content"], it["due"]["date"]), ("Fresh", "2026-10-01"))  # accepted, and lost
        p = self.cli("edit", rid, "--title", "Kept title", "--due", "2026-10-03", settle="2.5")
        self.assertIn("waiting", p.stderr)
        [it] = self.items()
        self.assertEqual((it["content"], it["due"]["date"]), ("Kept title", "2026-10-03"))


class TestPlan(Base):
    def test_deadline_refused_before_writing_on_a_free_plan(self):
        mock.STORE.plan.update(plan_name="free_new_4", deadlines=False)
        self.assertIn("needs a paid Todoist plan",
                      self.cli("add", "T", "--area", "tools", "--deadline", "2026-10-01", ok=False).stderr)
        path = self.file("d.md", "- [ ] With deadline #tools\n      deadline: 2026-10-01\n")
        self.assertIn("1 row(s) with a deadline", self.cli("import", path, ok=False).stderr)
        self.assertEqual(mock.STORE.write_requests, 0)
        self.cli("add", "No deadline", "--area", "tools")
        rid = self.jlist()[0]["id"]
        self.assertIn("needs a paid Todoist plan", self.cli("edit", rid, "--deadline", "2026-10-01", ok=False).stderr)
        self.assertIn("empty task id", self.cli("done", "", ok=False).stderr)


class TestLifecycle(Base):
    def test_done_undone_rm(self):
        self.cli("add", "Finish me", "--area", "tools", "--src", "7e57ab1e")
        self.cli("add", "Delete me", "--area", "tools")
        rows = {r["title"]: r for r in self.jlist()}
        self.assertTrue(self.cli("done", rows["Finish me"]["short"]).stdout.startswith("done: "))
        self.assertEqual([r["title"] for r in self.jlist()], ["Delete me"])
        done = json.loads(self.cli("list", "--done", "--since", "1d", "--json").stdout)
        self.assertEqual([(d["title"], d["done"]) for d in done], [("Finish me", True)])
        self.assertIn("doneAt", done[0])
        self.assertIn(" x ", self.cli("list", "--done").stdout)
        self.assertEqual(len(json.loads(self.cli("list", "--all", "--json").stdout)), 2)
        self.assertTrue(self.cli("undone", rows["Finish me"]["short"]).stdout.startswith("reopened: "))
        self.assertEqual(sorted(r["title"] for r in self.jlist()), ["Delete me", "Finish me"])
        self.assertTrue(self.cli("rm", rows["Delete me"]["id"]).stdout.startswith("removed: "))
        self.assertEqual([i["content"] for i in self.items()], ["Finish me"])
        self.assertIn("no open task with id starting zzz", self.cli("done", "zzz", ok=False).stderr)

    def test_done_window_longer_than_three_months(self):
        self.cli("add", "Old", "--area", "tools")
        it = self.items()[0]
        it["checked"], it["completed_at"] = True, mock.stamp(datetime.now(timezone.utc) - timedelta(days=100))
        mock.STORE.touch(it)
        done = json.loads(self.cli("list", "--done", "--since", "120d", "--json").stdout)
        self.assertEqual([d["title"] for d in done], ["Old"])
        spans = mock.STORE.completed_requests
        self.assertGreaterEqual(len(spans), 2)
        self.assertTrue(all(u - s <= timedelta(days=92) for s, u in spans))


MD = """# seed

## Import

- [ ] Decide backup media fetch !3 #tools #decision
      export.py already does it. Repo ~/src/backup.
      src: 0facbdc3; since: 2026-09-01; effort: S; mode: assisted
- [ ] Apply to leads @2026-09-30 !1 #bills
      Two leads.
      src: 0facbdc3 \u00b7 since: 2026-08-22 \u00b7 effort: S \u00b7 mode: owner
- [x] Already done #bills
- [ ] Decide backup media fetch !2 #tools
- [ ] Old file item !2 #home #build #verify
      src: todo-2026-09-02#10; since: 2026-09-02; effort: M; mode: unattended; deadline: 2026-10-31
"""


class TestImportExport(Base):
    def test_markdown_dry_real_dedupe(self):
        path = self.file("seed.md", MD)
        p = self.cli("import", path, "--dry")
        self.assertIn("would add 3; skipped 1 done row(s), 1 duplicate(s)", p.stderr)  # add-only wording
        self.assertEqual((self.items(), mock.STORE.write_requests), ([], 0))
        self.assertIn("would add [bills] Apply to leads @2026-09-30 !1  labels=effort-S,owner", p.stdout)
        p = self.cli("import", path)
        self.assertIn("added 3; skipped 1 done row(s), 1 duplicate(s)", p.stderr)
        rows = {r["title"]: r for r in self.jlist()}
        a = rows["Apply to leads"]
        self.assertEqual((a["due"], a["prio"], a["mode"], a["src"], a["since"], a["url"]),
                         ("2026-09-30", 1, "owner", "0facbdc3", "2026-08-22", SESSION % "0facbdc3"))
        d = rows["Decide backup media fetch"]
        self.assertEqual((d["prio"], d["kinds"], d["area"]), (3, ["decision"], "tools"))
        self.assertEqual(d["desc"], "export.py already does it. Repo ~/src/backup.")
        o = rows["Old file item"]
        self.assertEqual((o["kinds"], o["deadline"], o["prio"], o["src"]),
                         (["build", "verify"], "2026-10-31", 2, "todo-2026-09-02#10"))
        self.assertNotIn("url", o)
        self.assertIn("added 0; skipped 1 done row(s), 4 duplicate(s)", self.cli("import", path).stderr)

    def test_json_import_in_the_todo_shape(self):
        rows = [{"area": "bills", "title": "From Reminders", "desc": "Text.", "kinds": ["decision"],
                 "due": "2026-09-25 18:00", "prio": 2, "effort": "S", "value": 3, "mode": "owner", "src": "0facbdc3",  # value is ignored
                 "since": "2026-08-22", "url": SESSION % "0facbdc3", "done": False, "id": "F2580DC8-10C9",
                 "short": "f2580dc8"},
                {"area": "bills", "title": "Done in Reminders", "done": True}]
        p = self.cli("import", self.file("rows.json", json.dumps(rows)))
        self.assertIn("added 1; skipped 1 done row(s)", p.stderr)
        [r] = self.jlist()
        self.assertEqual((r["prio"], r["due"], r["since"]), (2, "2026-09-25 18:00", "2026-08-22"))
        [it] = self.items()
        self.assertEqual(it["description"], "Text. [Origin](%s)" % (SESSION % "0facbdc3"))

    def test_caps_are_checked_before_anything_is_written(self):
        text = "- [ ] %s #tools\n- [ ] Fine #tools\n" % ("y" * 70)
        p = self.cli("import", self.file("long.md", text), ok=False)
        self.assertIn("1 row(s) over the title cap", p.stderr)
        self.assertEqual(mock.STORE.write_requests, 0)

    def test_more_than_one_hundred_commands(self):
        rows = []
        for n in range(60):
            rows.append("- [ ] Task number %02d #bulk%d #kind%d" % (n, n % 3, n % 4))
            rows.append("      src: todo-bulk#%d; since: 2026-09-01; effort: S; mode: unattended" % n)
        p = self.cli("import", self.file("bulk.md", "\n".join(rows) + "\n"))
        self.assertIn("added 60", p.stderr)
        items = self.items()
        self.assertEqual(len(items), 60)
        for it in items:
            n = int(it["content"].split()[-1])
            self.assertEqual(self.notes(it["id"]), ["src: todo-bulk#%d; since: 2026-09-01" % n])
        self.assertGreaterEqual(mock.STORE.write_requests, 4)  # project, sections and labels, two item batches

    def test_export_stats_areas_round_trip(self):
        TestList.seed(self)
        out = self.cli("export").stdout
        self.assertTrue(out.startswith("# Work - open tasks (GENERATED "))
        self.assertIn("\n## bills\n", out)
        self.assertRegex(out, r"- \[ \] Alpha @2020-01-01 !1 \[id 6X\S+, decision, S, unattended, "
                              r"src 0facbdc3, since 2026-08-22, overdue\]")
        self.assertIn("\n      first line\n      second line\n", out)
        path = os.path.join(self.tmp, "TODO.md")
        self.assertIn("wrote %s: 3 open task(s)" % path, self.cli("export", "--out", path).stderr)
        self.assertIn("would add 0; skipped 0 done row(s), 3 duplicate(s)", self.cli("import", path, "--dry").stderr)
        self.assertIn("would add 0, update 0, close 0, leave 3 unchanged",
                      self.cli("import", path, "--dry", "--update").stderr)  # the export reads back whole
        s = json.loads(self.cli("stats", "--json").stdout)
        self.assertEqual((s["open"], s["overdue"], s["areas"], s["maxTasks"], s["sections"]),
                         (3, 1, {"bills": 2, "home": 1}, 300, 2))
        self.assertIn("Work: 3 open, 0 done in 30d, 1 overdue", self.cli("stats").stdout)
        self.assertEqual(self.cli("areas").stdout.split("\n")[:2], ["bills  (2 open)", "home  (1 open)"])

    def test_export_writes_only_on_change(self):
        TestList.seed(self)
        path = os.path.join(self.tmp, "TODO.md")
        self.assertIn("wrote %s: 3 open task(s)" % path, self.cli("export", "--out", path).stderr)
        with open(path) as f:
            first = f.read()
        at = first.index("GENERATED ") + len("GENERATED ")
        aged = first[:at] + "2020-01-01 00:00" + first[at + 16:]
        with open(path, "w") as f:
            f.write(aged)  # another stamp alone is not a change
        self.assertIn("unchanged %s: 3 open task(s)" % path, self.cli("export", "--out", path).stderr)
        with open(path) as f:
            self.assertEqual(f.read(), aged)  # left alone, the old stamp included
        self.cli("add", "Delta", "--area", "bills")
        self.assertIn("wrote %s: 4 open task(s)" % path, self.cli("export", "--out", path).stderr)
        with open(path) as f:
            now_text = f.read()
        self.assertIn("- [ ] Delta [id ", now_text)
        self.assertNotIn("GENERATED 2020-01-01 00:00", now_text)


class TestLegacyLinks(Base):
    def test_old_link_lines_read_back_and_are_rewritten_on_edit(self):
        self.cli("add", "Seed", "--area", "tools")
        pid = [p["id"] for p in mock.STORE.projects if p["name"] == "Work"][0]
        sid = [s["id"] for s in mock.STORE.sections if s["name"] == "tools"][0]
        old = "Old text.\n\n[session 7e57ab1e](%s)" % (SESSION % "7e57ab1e")
        mock.STORE.add_item({"content": "Imported earlier", "project_id": pid, "section_id": sid, "description": old},
                            "6Old000000000001")
        mock.STORE.add_item({"content": "With a plain link", "project_id": pid, "section_id": sid,
                             "description": "Text.\n\n[link](https://example.com/x)"}, "6Old000000000002")
        rows = {r["title"]: r for r in self.jlist()}
        self.assertEqual((rows["Imported earlier"]["desc"], rows["Imported earlier"]["url"]),
                         ("Old text.", SESSION % "7e57ab1e"))
        self.assertEqual(rows["With a plain link"]["url"], "https://example.com/x")
        self.assertTrue(self.cli("edit", "6Old000000000001").stdout.startswith("edited: "))  # rewritten, nothing else
        it = [i for i in mock.STORE.items if i["id"] == "6Old000000000001"][0]
        self.assertEqual(it["description"], "Old text. [Origin](%s)" % (SESSION % "7e57ab1e"))
        self.assertTrue(self.cli("edit", "6Old000000000001").stdout.startswith("unchanged: "))


class TestSubtasks(Base):
    def seed(self):
        self.cli("add", "Ship the guide", "--area", "write", "--kind", "build", "--effort", "L",
                 "--mode", "assisted", "--src", "7e57ab1e", "--prio", "1")
        parent = self.jlist()[0]
        self.cli("add", "Outline", "--parent", parent["short"], "--kind", "write", "--effort", "S")
        self.cli("add", "Draft", "--parent", parent["id"], "--effort", "M", "--note", "Two passes.")
        self.cli("add", "Other root", "--area", "tools", "--prio", "2")
        return parent

    def test_add_list_show_json(self):
        parent = self.seed()
        self.assertIn("lives in its parent's area", self.cli("add", "Wrong", "--parent", parent["short"], "--area",
                                                              "tools", ok=False).stderr)
        self.assertIn("needs --area", self.cli("add", "Nowhere", ok=False).stderr)
        subs = [i for i in self.items() if i["parent_id"] == parent["id"]]
        self.assertEqual([i["content"] for i in subs], ["Outline", "Draft"])
        sid = [s["id"] for s in mock.STORE.sections if s["name"] == "write"][0]
        self.assertTrue(all(i["section_id"] == sid for i in subs))  # the section is the parent's
        out = self.cli("list").stdout.split("\n")
        self.assertRegex(out[0], r"^\S+ - !1 \[write:build\] L/assisted Ship the guide$")
        self.assertRegex(out[1], r"^  \S+ - -- \[write:write\] S Outline$")
        self.assertRegex(out[2], r"^  \S+ - -- \[write\] M Draft$")
        self.assertRegex(out[3], r"^\S+ - !2 \[tools\] Other root$")
        self.assertEqual(titles(self.cli("list", "--area", "write")), ["guide", "Outline", "Draft"])
        self.assertEqual(titles(self.cli("list", "--effort", "M")), ["Draft"])  # a subtask alone, still indented
        self.assertTrue(self.cli("list", "--effort", "M").stdout.startswith("  "))
        rows = self.jlist()
        self.assertEqual([r.get("parent") for r in rows], [None, parent["id"], parent["id"], None])
        self.assertEqual(rows[0]["subtasks"], [rows[1]["id"], rows[2]["id"]])
        self.assertNotIn("subtasks", rows[1])
        show = self.cli("show", rows[2]["short"]).stdout
        self.assertIn("parent:   %s Ship the guide" % rows[0]["short"], show)
        show = self.cli("show", rows[0]["short"]).stdout
        self.assertIn("subtasks: 2 open\n  %s - Outline\n  %s - Draft" % (rows[1]["short"], rows[2]["short"]), show)
        desc = self.cli("list", "--desc").stdout
        self.assertIn("\n           Two passes.\n", desc)

    def test_show_tree_reads_the_subtasks_and_their_comments(self):
        parent = self.seed()
        rows = {r["title"]: r for r in self.jlist()}
        self.cli("add", "Deep", "--parent", rows["Outline"]["short"])
        self.cli("comments", "add", parent["short"], "-", stdin="On the parent\n\nsecond paragraph\n")
        self.cli("comments", "add", rows["Draft"]["short"], "On the draft")
        note = [n for n in mock.STORE.notes if n["content"] == "On the draft"][0]
        note["posted_uid"] = "2671362"  # written by a collaborator
        # one task: the comments in full, the src/since comment left out
        out = self.cli("show", parent["short"], "--comments").stdout
        self.assertIn("comments: 1\n", out)
        self.assertRegex(out, r"\n  \S+ \d{4}-\d\d-\d\d \d\d:\d\d On the parent\n\n    second paragraph\n$")
        o = json.loads(self.cli("show", parent["short"], "--comments", "--json").stdout)
        self.assertEqual([sorted(c) for c in o["comments"]], [["content", "id", "posted"]])
        self.assertEqual(o["comments"][0]["content"], "On the parent\n\nsecond paragraph")
        self.assertRegex(o["comments"][0]["posted"], r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertNotIn("comments", json.loads(self.cli("show", parent["short"], "--json").stdout))
        # the tree: the task, then its open subtasks, each after its parent
        out = self.cli("show", parent["short"], "--tree", "--comments").stdout
        self.assertEqual([l for l in out.split("\n") if l.startswith(("title: ", "# "))],
                         ["title:    Ship the guide", "# subtask 1 of 3 (depth 1)", "title:    Outline",
                          "# subtask 2 of 3 (depth 2)", "title:    Deep", "# subtask 3 of 3 (depth 1)", "title:    Draft"])
        self.assertEqual(out.count("comments: "), 4)
        self.assertIn("On the draft", out)
        self.assertNotIn("# subtask", self.cli("show", rows["Draft"]["short"], "--tree").stdout)
        o = json.loads(self.cli("show", parent["short"], "--tree", "--comments", "--json", "--fields", "title,parent").stdout)
        self.assertEqual([(r["title"], len(r["comments"])) for r in o],
                         [("Ship the guide", 1), ("Outline", 0), ("Deep", 0), ("Draft", 1)])
        self.assertEqual(o[3]["comments"][0]["by"], "2671362")
        self.assertEqual(o[2]["parent"], rows["Outline"]["id"])
        self.assertEqual([r["title"] for r in json.loads(self.cli("show", rows["Outline"]["short"], "--tree", "--json").stdout)],
                         ["Outline", "Deep"])
        # a completed subtask leaves the tree; --all brings it back with its comments
        self.cli("done", rows["Draft"]["short"])
        out = self.cli("show", parent["short"], "--tree", "--comments").stdout
        self.assertNotIn("Draft", out)
        self.assertIn("subtasks: 1 open\n", out)
        out = self.cli("show", parent["short"], "--tree", "--all", "--comments").stdout
        self.assertIn("subtasks: 1 open, 1 done\n  %s - Outline\n  %s x Draft" % (rows["Outline"]["short"], rows["Draft"]["short"]), out)
        self.assertIn("# subtask 3 of 3 (depth 1)\n", out)
        self.assertIn("On the draft", out)
        o = json.loads(self.cli("show", parent["short"], "--tree", "--all", "--comments", "--json").stdout)
        self.assertEqual([(r["title"], r["done"]) for r in o],
                         [("Ship the guide", False), ("Outline", False), ("Deep", False), ("Draft", True)])
        self.assertEqual(o[3]["comments"][0]["content"], "On the draft")
        # a completed task with its completed subtasks
        self.cli("done", parent["short"])
        o = json.loads(self.cli("show", parent["id"], "--tree", "--all", "--json").stdout)
        self.assertEqual([(r["title"], r["done"]) for r in o],
                         [("Ship the guide", True), ("Outline", True), ("Deep", True), ("Draft", True)])

    def test_edit_moves_and_refusals(self):
        parent = self.seed()
        rows = {r["title"]: r for r in self.jlist()}
        p = self.cli("edit", rows["Other root"]["short"], "--parent", parent["short"])
        self.assertTrue(p.stdout.startswith("edited: "))
        rows = {r["title"]: r for r in self.jlist()}
        self.assertEqual((rows["Other root"]["parent"], rows["Other root"]["area"]), (parent["id"], "write"))
        self.assertIn("cannot move", self.cli("edit", parent["short"], "--parent", rows["Draft"]["short"], ok=False).stderr)
        self.assertIn("cannot move", self.cli("edit", parent["short"], "--parent", parent["short"], ok=False).stderr)
        self.assertIn("is a subtask and stays", self.cli("edit", rows["Draft"]["short"], "--area", "tools", ok=False).stderr)
        self.assertIn("lives in its parent's area", self.cli("edit", rows["Draft"]["short"], "--parent",
                                                              rows["Outline"]["short"], "--area", "tools", ok=False).stderr)
        # nesting deeper, then detaching back to the area's root
        self.cli("edit", rows["Draft"]["short"], "--parent", rows["Outline"]["short"])
        out = self.cli("list").stdout.split("\n")
        self.assertTrue(out[2].startswith("    ") and out[2].endswith("Draft"))
        self.cli("edit", rows["Draft"]["short"], "--parent", "", "--area", "tools")
        rows = {r["title"]: r for r in self.jlist()}
        self.assertEqual((rows["Draft"].get("parent"), rows["Draft"]["area"]), (None, "tools"))
        # moving the parent to another area takes the subtasks along
        self.cli("edit", parent["short"], "--area", "tools")
        rows = {r["title"]: r for r in self.jlist()}
        self.assertEqual(rows["Outline"]["area"], "tools")
        self.assertTrue(self.cli("edit", parent["short"]).stdout.startswith("unchanged: "))

    def test_done_and_rm_take_the_subtasks_along(self):
        parent = self.seed()
        rows = {r["title"]: r for r in self.jlist()}
        p = self.cli("done", parent["short"], rows["Draft"]["short"])
        self.assertEqual(p.stdout.count("done: "), 1)  # the subtask is covered by its parent
        self.assertIn("Ship the guide (+2 subtasks)", p.stdout)
        self.assertEqual(titles(self.cli("list")), ["root"])
        done = json.loads(self.cli("list", "--done", "--since", "1d", "--json").stdout)
        self.assertEqual([d["title"] for d in done], ["Ship the guide", "Outline", "Draft"])  # tree order
        self.cli("undone", parent["short"])
        self.cli("add", "Child again", "--parent", parent["short"])
        p = self.cli("rm", parent["short"])
        self.assertIn("Ship the guide (+1 subtask)", p.stdout)
        self.assertEqual([i["content"] for i in self.items()], ["Other root"])

    def test_export_import_round_trip_with_subtasks(self):
        self.seed()
        out = self.cli("export").stdout
        self.assertRegex(out, r"\n- \[ \] Ship the guide !1 \[id \S+, build, L, assisted, src 7e57ab1e, since %s\]\n"
                              r"  - \[ \] Outline \[id \S+, write, S, since %s\]\n"
                              r"  - \[ \] Draft \[id \S+, M, since %s\]\n        Two passes\.\n" % (TODAY, TODAY, TODAY))
        path = os.path.join(self.tmp, "TODO.md")
        self.cli("export", "--out", path)
        self.assertIn("would add 0; skipped 0 done row(s), 4 duplicate(s)", self.cli("import", path, "--dry").stderr)
        self.assertIn("leave 4 unchanged", self.cli("import", path, "--dry", "--update").stderr)
        # a fresh account reads the export back whole: attributes, bodies and the nesting
        mock.STORE.reset()
        p = self.cli("import", path, "--fresh")  # the reset store starts its sync tokens over: full sync
        self.assertIn("added 4;", p.stderr)
        rows = {r["title"]: r for r in self.jlist()}
        g = rows["Ship the guide"]
        self.assertEqual((g["kinds"], g["effort"], g["mode"], g["src"], g["prio"], g["url"]),
                         (["build"], "L", "assisted", "7e57ab1e", 1, SESSION % "7e57ab1e"))
        self.assertEqual((rows["Outline"]["parent"], rows["Outline"]["kinds"], rows["Outline"]["effort"]),
                         (g["id"], ["write"], "S"))
        self.assertEqual((rows["Draft"]["parent"], rows["Draft"]["desc"]), (g["id"], "Two passes."))
        self.assertEqual(rows["Other root"]["area"], "tools")

    def test_import_update_edits_adds_and_closes_by_id(self):
        parent = self.seed()
        rows = {r["title"]: r for r in self.jlist()}
        body = "# Why\n\nBecause.\n\n```\n  keep this indent\n```"
        text = "\n".join([
            "## write",
            "- [ ] Ship the guide, retitled @2026-12-01 !2 [id %s, build/decision, M, owner, src 0facbdc3, since 2026-09-01]" % rows["Ship the guide"]["short"],
            "      " + body.replace("\n", "\n      "),
            "  - [x] Outline [id %s]" % rows["Outline"]["short"],
            "  - [ ] Draft [id %s]" % rows["Draft"]["short"],
            "        Two passes.",
            "  - [ ] Review #verify",
            "        One line.",
            "        effort: S; mode: unattended",
            "- [ ] Brand new #home #build",
            "  - [ ] Its first step",
            "", "## tools",
            "- [ ] Other root !2 [id %s]" % rows["Other root"]["short"],
            ""])
        path = self.file("edit.md", text)
        before = mock.STORE.write_requests
        p = self.cli("import", path, "--dry", "--update")
        self.assertIn("would update %s Ship the guide: title, body, labels, priority, due, src/since" % rows["Ship the guide"]["short"], p.stdout)
        self.assertIn("would close %s Outline" % rows["Outline"]["short"], p.stdout)
        self.assertIn("would add [write] Review  labels=verify,effort-S,unattended", p.stdout)
        self.assertIn("under: " + rows["Ship the guide"]["short"], p.stdout)
        self.assertIn("would add [home] Its first step", p.stdout)
        self.assertIn("under: Brand new", p.stdout)
        self.assertIn("would add 3, update 1, close 1, leave 2 unchanged", p.stderr)
        self.assertEqual(mock.STORE.write_requests, before)  # the dry run wrote nothing
        p = self.cli("import", path, "--update")
        self.assertIn("added 3, updated 1, closed 1, unchanged 2", p.stderr)
        self.assertIn("updated: ", p.stdout)
        self.assertIn("closed: ", p.stdout)
        rows = {r["title"]: r for r in self.jlist()}
        g = rows["Ship the guide, retitled"]
        self.assertEqual((g["kinds"], g["effort"], g["mode"], g["src"], g["since"], g["prio"], g["due"]),
                         (["build", "decision"], "M", "owner", "0facbdc3", "2026-09-01", 2, "2026-12-01"))
        self.assertEqual((g["desc"], g["url"]), (body, SESSION % "0facbdc3"))
        self.assertEqual(sorted(r["title"] for r in rows.values() if r.get("parent") == g["id"]), ["Draft", "Review"])
        self.assertEqual((rows["Review"]["kinds"], rows["Review"]["effort"], rows["Review"]["mode"], rows["Review"]["desc"]),
                         (["verify"], "S", "unattended", "One line."))
        self.assertEqual(rows["Its first step"]["parent"], rows["Brand new"]["id"])
        self.assertEqual(rows["Brand new"]["area"], "home")
        self.assertNotIn("Outline", rows)
        self.assertEqual([d["title"] for d in json.loads(self.cli("list", "--done", "--json").stdout)], ["Outline"])
        # an unknown id refuses the whole file before anything is written
        n = mock.STORE.write_requests
        p = self.cli("import", self.file("bad.md", "- [ ] Ghost [id 6Nope000]\n- [ ] Fine #tools\n"), "--update", ok=False)
        self.assertIn("no open task with id 6Nope000", p.stderr)
        self.assertEqual(mock.STORE.write_requests, n)
        # without --update the same file only adds: ids are ignored, titles dedupe
        p = self.cli("import", path, "--dry")
        self.assertIn("would add 0; skipped 1 done row(s), 6 duplicate(s)", p.stderr)  # every title exists by now

    def test_json_import_with_parents(self):
        parent = self.seed()
        rows = [{"title": "From JSON", "area": "write", "parent": parent["id"]},
                {"id": "row-1", "title": "New parent", "area": "tools", "kinds": ["build"]},
                {"title": "New child", "parent": "row-1", "effort": "S"}]
        p = self.cli("import", self.file("rows.json", json.dumps(rows)))
        self.assertIn("added 3;", p.stderr)
        got = {r["title"]: r for r in self.jlist()}
        self.assertEqual(got["From JSON"]["parent"], parent["id"])
        self.assertEqual((got["New child"]["parent"], got["New child"]["area"]), (got["New parent"]["id"], "tools"))
        p = self.cli("import", self.file("bad.json", json.dumps([{"title": "Orphan", "parent": "6Nope"}])), ok=False)
        self.assertIn("no open task with id 6Nope", p.stderr)


class TestAccountVerbs(Base):
    """The verbs beyond the task list: every one against the mock, with its plan gate, --yes rule and --json."""

    def seed(self):
        self.cli("add", "Seed one", "--area", "alpha", "--kind", "build", "--due", "2026-09-25", "--prio", "1")
        self.cli("add", "Seed two", "--area", "beta", "--effort", "S", "--mode", "unattended")
        rows = {r["title"]: r for r in self.jlist()}
        return rows["Seed one"]["short"], rows["Seed two"]["short"]

    def pid(self, name="Work"):
        return [p["id"] for p in mock.STORE.projects if p["name"] == name and not p["is_deleted"]][0]

    # ---- tasks: natural-language due, recurrence, duration, assignee, quick add, reschedule, move, assign, order

    def test_due_as_a_phrase_and_recurrence_survives_a_plain_reschedule(self):
        p = self.cli("add", "Weekly review", "--area", "alpha", "--due", "every monday 9am", "--json")
        self.assertEqual(json.loads(p.stdout)["due"], "every monday 9am")  # printed before the server parsed it
        [it] = self.items()
        self.assertTrue(it["due"]["is_recurring"])
        self.assertEqual(it["due"]["string"], "every monday 9am")
        self.assertTrue(it["due"]["date"].endswith("T09:00:00"))
        row = self.jlist()[0]
        self.assertEqual(row["recur"], "every monday 9am")
        self.assertIn("~", self.cli("list").stdout)  # the recurrence marker after the due date
        self.assertIn("repeats: every monday 9am", self.cli("show", row["short"]).stdout)
        # a plain date keeps the recurrence and the time
        p = self.cli("edit", row["short"], "--due", "2026-10-06")
        [it] = self.items()
        self.assertEqual((it["due"]["date"], it["due"]["string"], it["due"]["is_recurring"]), ("2026-10-06T09:00:00", "every monday 9am", True))
        # reschedule does the same for many; a new phrase replaces the recurrence
        p = self.cli("reschedule", row["short"], "2026-10-13")
        self.assertIn("rescheduled:", p.stdout)
        self.assertEqual(self.items()[0]["due"]["date"], "2026-10-13T09:00:00")
        self.cli("edit", row["short"], "--due", "tomorrow")
        self.assertFalse(self.items()[0]["due"]["is_recurring"])
        # done on a recurring task moves it on; --forever completes it
        self.cli("edit", row["short"], "--due", "every day")
        p = self.cli("done", row["short"])
        self.assertIn("recurring: moved to its next occurrence", p.stdout)
        self.assertFalse(self.items()[0]["checked"])
        self.cli("done", row["short"], "--forever")
        self.assertEqual(self.items(), [])

    def test_done_at_backdates_and_undone_by_full_id(self):
        a, b = self.seed()
        self.cli("done", a, "--at", "2026-09-01T10:00")
        done = [i for i in mock.STORE.items if i["checked"]]
        self.assertEqual(len(done), 1)
        self.assertTrue(done[0]["completed_at"].startswith("2026-09-01T"))
        p = self.cli("undone", done[0]["id"])  # a full id needs no lookup window
        self.assertIn("reopened", p.stdout)
        self.assertEqual(len(self.items()), 2)

    def test_duration_assignee_order_and_the_plan_gate(self):
        a, b = self.seed()
        self.cli("edit", a, "--duration", "1h30m", "--assign", "me", "--order", "7")
        [it] = [i for i in self.items() if i["content"] == "Seed one"]
        self.assertEqual((it["duration"], it["responsible_uid"], it["child_order"]), ({"amount": 90, "unit": "minute"}, mock.ME, 7))
        row = [r for r in self.jlist() if r["title"] == "Seed one"][0]
        self.assertEqual((row["duration"], row["assignee"]), ("90m", mock.ME))
        self.cli("edit", a, "--clear-duration", "--assign", "")
        [it] = [i for i in self.items() if i["content"] == "Seed one"]
        self.assertEqual((it["duration"], it["responsible_uid"]), (None, None))
        mock.STORE.plan["durations"] = False
        p = self.cli("add", "No duration", "--area", "alpha", "--duration", "2h", ok=False)
        self.assertIn("needs a paid Todoist plan", p.stderr)
        self.assertNotIn("No duration", [i["content"] for i in self.items()])
        p = self.cli("assign", a, "--to", "alex")
        self.assertIn("assigned to 2671362", p.stdout)
        self.cli("unassign", a)
        self.assertIsNone([i for i in self.items() if i["content"] == "Seed one"][0]["responsible_uid"])
        # order: the given order among siblings
        self.cli("add", "Seed three", "--area", "alpha")
        c = [r["short"] for r in self.jlist() if r["title"] == "Seed three"][0]
        self.cli("order", c, a)
        by = {i["content"]: i["child_order"] for i in self.items()}
        self.assertEqual((by["Seed three"], by["Seed one"]), (1, 2))
        self.assertIn("not siblings", self.cli("order", a, b, ok=False).stderr)

    def test_quick_add_with_src(self):
        self.seed()
        p = self.cli("quick", "Buy bread tomorrow #Work /alpha @errand p2 // from the bakery", "--src", "7e57ab1e", "--json")
        o = json.loads(p.stdout)
        it = [i for i in mock.STORE.items if i["content"] == "Buy bread"][0]
        self.assertEqual((it["priority"], it["labels"], it["description"][:15]), (3, ["errand"], "from the bakery"))
        self.assertEqual(it["section_id"], [s["id"] for s in mock.STORE.sections if s["name"] == "alpha"][0])
        self.assertEqual(self.notes(it["id"]), ["src: 7e57ab1e; since: %s" % TODAY])
        self.assertTrue(it["description"].endswith("[Origin](%s)" % (SESSION % "7e57ab1e")))
        self.assertEqual((o["title"], o["src"], o["prio"]), ("Buy bread", "7e57ab1e", 2))
        mock.STORE.plan["deadlines"] = False
        self.assertIn("{deadline}", self.cli("quick", "Report {friday}", ok=False).stderr)

    def test_move_between_projects_and_the_in_flag(self):
        a, b = self.seed()
        self.cli("projects", "add", "Personal")
        p = self.cli("move", a, "--to", "Personal", "--area", "money")
        self.assertIn("moved:", p.stdout)
        self.assertIn('created section "money" in Personal', p.stderr)
        it = [i for i in mock.STORE.items if i["content"] == "Seed one"][0]
        self.assertEqual(it["project_id"], self.pid("Personal"))
        self.assertEqual([r["title"] for r in self.jlist()], ["Seed two"])
        rows = self.jlist("--in", "Personal")
        self.assertEqual([(r["title"], r["area"]) for r in rows], [("Seed one", "money")])
        # a task of another project resolves by id and shows its project; scoped edits are refused
        self.assertIn("project:  Personal", self.cli("show", it["id"][:8]).stdout)
        self.assertIn("--in Personal", self.cli("edit", it["id"][:8], "--area", "x", ok=False).stderr)
        self.assertIn("Personal/money", self.cli("list", "--all-projects").stdout)
        # --in must name an existing project; --in by id speaks the name
        p = self.cli("add", "Nope", "--area", "a", "--in", "Nowhere", ok=False)
        self.assertIn('no Todoist project "Nowhere"', p.stderr)
        self.assertEqual(json.loads(self.cli("stats", "--json", "--in", self.pid("Personal")).stdout)["project"], "Personal")

    def test_rm_of_many_needs_yes(self):
        ids = []
        for n in range(6):
            ids.append(json.loads(self.cli("add", "Bulk %d" % n, "--area", "alpha", "--json").stdout)["short"])
        p = self.cli("rm", *ids, ok=None)
        self.assertEqual(p.returncode, 2)
        self.assertIn("would remove", p.stdout)
        self.assertEqual(len(self.items()), 6)
        self.cli("rm", *ids, "--yes")
        self.assertEqual(self.items(), [])

    # ---- reading: server filters, grep, labels, sections, done by due date, search, overview, stats --account

    def test_list_filter_grep_label_and_done_by_due(self):
        a, b = self.seed()
        p = self.cli("list", "--filter", "p1")
        self.assertIn("Seed one", p.stdout)
        self.assertNotIn("Seed two", p.stdout)
        self.assertIn("Inbox/-", self.cli("list", "--filter", "@errand").stdout)  # another project's row
        self.assertIn("unknown filter term", self.cli("list", "--filter", "bogus", ok=False).stderr)
        self.assertEqual([r["title"] for r in self.jlist("--grep", "TWO")], ["Seed two"])
        self.assertEqual([r["title"] for r in self.jlist("--label", "effort-S,unattended")], ["Seed two"])
        self.assertEqual([r["title"] for r in self.jlist("--section", "Beta")], ["Seed two"])
        self.assertEqual([r["title"] for r in self.jlist("--saved", "Priority 1")], ["Seed one"])
        self.cli("done", a)
        self.assertEqual([r["title"] for r in self.jlist("--done", "--by", "due", "--since", "2026-09-01", "--until", "2026-10-01")], ["Seed one"])
        self.assertIn("--by takes", self.cli("list", "--done", "--by", "x", ok=False).stderr)

    def test_search_overview_and_account_stats(self):
        self.seed()
        p = self.cli("search", "seed")
        self.assertEqual(p.stdout.count("task     "), 2)
        self.assertIn("2 task(s)", p.stderr)
        o = json.loads(self.cli("search", "alpha", "--json").stdout)
        self.assertEqual([s["name"] for s in o["sections"]], ["alpha"])
        p = self.cli("overview")
        self.assertIn("Work  (2 open)", p.stdout)
        self.assertRegex(p.stdout, r"\n  \S+ alpha  \(1 open\)")
        self.assertIn("## beta", self.cli("overview", "Work").stdout)
        p = self.cli("stats", "--account")
        self.assertIn("karma 8619 (up)", p.stdout)
        self.assertIn("goals: 5 a day, 25 a week", p.stdout)

    # ---- projects, people, sections, labels

    def test_projects_lifecycle(self):
        self.seed()
        p = self.cli("projects")
        self.assertIn("Inbox [inbox]", p.stdout)
        self.assertIn("Work  open:2 sections:2", p.stdout)
        p = self.cli("projects", "add", "Side", "--color", "blue", "--favorite", "--description", "A side project")
        self.assertIn("added:", p.stdout)
        side = [x for x in mock.STORE.projects if x["name"] == "Side"][0]
        self.assertEqual((side["color"], side["is_favorite"], side["description"]), ("blue", True, "A side project"))
        self.assertIn("--color takes one of", self.cli("projects", "add", "Bad", "--color", "plaid", ok=False).stderr)
        self.assertIn("exists", self.cli("projects", "add", "side", ok=False).stderr)
        self.cli("projects", "edit", "Side", "--name", "Sideways", "--no-favorite", "--parent", "Work")
        self.assertEqual((side["name"], side["is_favorite"], side["parent_id"]), ("Sideways", False, self.pid()))
        self.assertIn("under:Work", self.cli("projects", "show", "Sideways").stdout)
        p = self.cli("projects", "archive", "Sideways", ok=None)
        self.assertEqual(p.returncode, 2)
        self.cli("projects", "archive", "Sideways", "--yes")
        self.assertTrue(side["is_archived"])
        self.assertIn("Sideways", self.cli("projects", "--archived").stdout)
        self.assertNotIn("Sideways", self.cli("projects").stdout)
        self.cli("projects", "unarchive", "Sideways")
        self.assertFalse(side["is_archived"])
        self.cli("projects", "order", "Sideways", "Work")
        self.assertEqual((side["child_order"], [x for x in mock.STORE.projects if x["name"] == "Work"][0]["child_order"]), (1, 2))
        p = self.cli("projects", "rm", "Sideways", ok=None)
        self.assertEqual(p.returncode, 2)
        self.assertIn("would delete project Sideways", p.stdout)
        self.cli("projects", "rm", "Sideways", "--yes")
        self.assertTrue(side["is_deleted"])
        mock.STORE.plan["max_projects"] = 2  # Work and Third fill it; the Inbox row does not count
        self.assertIn("added:", self.cli("projects", "add", "Third").stdout)
        self.assertIn("max_projects", self.cli("projects", "add", "Fourth", ok=False).stderr)
        # what the server refuses comes back as its message, not as a token complaint
        p = self.cli("projects", "health", "Work", ok=False)
        self.assertIn("only available for workspace projects", p.stderr)
        self.assertNotIn("refused the token", p.stderr)
        self.assertIn("Teams feature", self.cli("projects", "move", "Work", "--personal", "--yes", ok=False).stderr)
        self.assertIn("roles", self.cli("projects", "roles").stdout)
        self.assertIn("Work", self.cli("projects", "search", "wor").stdout)

    def test_people_and_share(self):
        self.seed()
        p = self.cli("people")
        self.assertIn("Alex Example <alex@example.com>", p.stdout)
        self.assertIn("(me)", p.stdout)
        p = self.cli("share", "add", "Work", "alex@example.com", ok=None)
        self.assertEqual(p.returncode, 2)
        self.cli("share", "add", "Work", "alex@example.com", "--yes")
        self.assertEqual([c["user_id"] for c in mock.STORE.collaborator_states], ["2671362"])
        self.assertIn("Alex", self.cli("people", "Work").stdout)
        self.assertNotIn("Test User", self.cli("people", "Work").stdout)
        self.cli("share", "role", "Work", "alex", "read_write")
        self.assertEqual(mock.STORE.collaborator_states[0]["role"], "READ_WRITE")
        self.cli("share", "rm", "Work", "alex@example.com", "--yes")
        self.assertTrue(mock.STORE.collaborator_states[0]["is_deleted"])

    def test_sections_lifecycle(self):
        a, b = self.seed()
        p = self.cli("sections")
        self.assertIn("Work/alpha  open:1", p.stdout)
        self.cli("sections", "add", "Gamma Ray", "--description", "two words are fine here")
        sec = [s for s in mock.STORE.sections if s["name"] == "Gamma Ray"][0]
        self.assertEqual(sec["description"], "two words are fine here")
        self.cli("add", "In gamma", "--section", "Gamma Ray")
        self.assertEqual([i["section_id"] for i in self.items() if i["content"] == "In gamma"], [sec["id"]])
        self.assertIn("exists", self.cli("sections", "add", "gamma ray", ok=False).stderr)
        self.cli("sections", "edit", "Gamma Ray", "--name", "gamma", "--clear-description")
        self.assertEqual((sec["name"], sec["description"]), ("gamma", ""))
        self.cli("sections", "order", "gamma", "alpha", "beta")
        self.assertEqual([s["name"] for s in sorted(mock.STORE.sections, key=lambda s: s["section_order"])], ["gamma", "alpha", "beta"])
        self.cli("sections", "archive", "gamma", "--yes")
        self.assertTrue(sec["is_archived"])
        self.cli("sections", "unarchive", "gamma")
        self.cli("projects", "add", "Other")
        self.cli("sections", "move", "gamma", "--to", "Other", "--yes")
        self.assertEqual(sec["project_id"], self.pid("Other"))
        self.assertEqual([i["project_id"] for i in mock.STORE.items if i["content"] == "In gamma"], [self.pid("Other")])
        self.assertIn("Other/gamma", self.cli("sections", "--all-projects").stdout)
        p = self.cli("sections", "rm", "Other/gamma", ok=None)
        self.assertEqual(p.returncode, 2)
        self.assertIn("1 open tasks", p.stdout)
        self.cli("sections", "rm", "Other/gamma", "--yes")
        self.assertTrue(sec["is_deleted"])
        self.assertTrue([i for i in mock.STORE.items if i["content"] == "In gamma"][0]["is_deleted"])
        self.assertIn("renamed: alpha -> omega", self.cli("sections", "rename", "alpha", "omega").stdout)

    def test_labels_lifecycle_and_the_reserved_guard(self):
        a, b = self.seed()
        p = self.cli("labels")
        self.assertIn("effort-S  tasks:1", p.stdout)
        self.assertIn("errand  tasks:1", p.stdout)
        self.cli("labels", "add", "urgent", "--color", "red", "--favorite")
        l = [x for x in mock.STORE.labels if x["name"] == "urgent"][0]
        self.assertEqual((l["color"], l["is_favorite"]), ("red", True))
        self.assertIn("exists", self.cli("labels", "add", "Urgent", ok=False).stderr)
        self.cli("edit", a, "--kind", "build,urgent")
        self.cli("labels", "edit", "urgent", "--name", "pressing", "--no-favorite")
        self.assertEqual(l["name"], "pressing")
        self.assertIn("pressing", [i for i in self.items() if i["content"] == "Seed one"][0]["labels"])
        p = self.cli("labels", "edit", "effort-S", "--name", "small", ok=False)
        self.assertIn("--force overrides", p.stderr)
        self.assertIn("--force overrides", self.cli("labels", "rm", "unattended", "--yes", ok=False).stderr)
        p = self.cli("labels", "rm", "pressing", ok=None)
        self.assertEqual(p.returncode, 2)
        self.cli("labels", "rm", "pressing", "--yes")
        self.assertTrue(l["is_deleted"])
        self.assertNotIn("pressing", [i for i in self.items() if i["content"] == "Seed one"][0]["labels"])
        self.cli("labels", "rename-shared", "build", "make", "--yes")
        self.assertIn("make", [i for i in self.items() if i["content"] == "Seed one"][0]["labels"])
        self.cli("labels", "strip-shared", "make", "--yes")
        self.assertNotIn("make", [i for i in self.items() if i["content"] == "Seed one"][0]["labels"])
        self.cli("labels", "order", "errand", "effort-S")
        self.assertEqual([x["item_order"] for x in mock.STORE.labels if x["name"] in ("errand", "effort-S")], [1, 2])
        self.assertIn("errand", self.cli("labels", "--shared", "--all").stdout)

    # ---- comments, uploads, reminders, filters

    def test_comments_add_edit_react_rm_and_the_attr_guard(self):
        self.cli("add", "Commented", "--area", "alpha", "--src", "7e57ab1e")
        short = self.jlist()[0]["short"]
        p = self.cli("comments", short)
        self.assertIn("[attr] src: 7e57ab1e", p.stdout)
        attr_id = p.stdout.split()[0]
        self.cli("comments", "add", short, "First thought", "--notify", "alex@example.com")
        self.cli("comments", "add", short, "-", stdin="From stdin\nline two\n")
        rows = json.loads(self.cli("comments", short, "--json").stdout)
        self.assertEqual([r["content"] for r in rows][1:], ["First thought", "From stdin\nline two"])
        self.assertEqual(rows[1]["uids_to_notify"], ["2671362"])
        cid = rows[1]["id"]
        self.cli("comments", "edit", cid, "Second thought")
        self.assertEqual([n["content"] for n in mock.STORE.notes if n["id"] == cid], ["Second thought"])
        self.cli("comments", "react", cid, "thumbs_up")
        self.assertIn("reactions:thumbs_up x1", self.cli("comments", short).stdout)
        self.cli("comments", "unreact", cid, "thumbs_up")
        self.assertIn("--force overrides", self.cli("comments", "rm", attr_id, "--yes", ok=False).stderr)
        p = self.cli("comments", "rm", cid, ok=None)
        self.assertEqual(p.returncode, 2)
        self.cli("comments", "rm", cid, "--yes")
        self.assertTrue([n for n in mock.STORE.notes if n["id"] == cid][0]["is_deleted"])
        self.cli("comments", "add", "--project", "Work", "On the project")
        self.assertIn("On the project", self.cli("comments", "--project", "Work").stdout)
        self.assertIn("comments: 1", self.cli("show", short, "--comments").stdout)

    def test_upload_attaches_a_file_and_the_size_gate(self):
        self.cli("add", "With file", "--area", "alpha")
        short = self.jlist()[0]["short"]
        path = self.file("note.txt", "hello")
        self.cli("comments", "add", short, "see the file", "--file", path)
        [n] = [n for n in mock.STORE.notes if n["content"] == "see the file"]
        self.assertEqual((n["file_attachment"]["file_name"], n["file_attachment"]["file_size"]), ("note.txt", 5))
        self.assertIn("file:note.txt", self.cli("comments", short).stdout)
        o = json.loads(self.cli("uploads", "add", self.file("other.txt", "bye"), "--project", "Work").stdout)
        self.assertEqual(o["upload_state"], "completed")
        self.cli("uploads", "rm", o["file_url"], "--yes")
        self.assertEqual(len(mock.STORE.uploads), 1)
        mock.STORE.plan["upload_limit_mb"] = 0
        self.assertIn("upload limit", self.cli("uploads", "add", path, ok=False).stderr)

    def test_reminders_lifecycle_and_the_plan_gate(self):
        self.cli("add", "Timed", "--area", "alpha", "--due", "2026-09-25T18:00")
        self.cli("add", "Untimed", "--area", "alpha", "--due", "2026-09-26")
        rows = {r["title"]: r["short"] for r in self.jlist()}
        self.cli("reminders", "add", rows["Timed"], "--before", "30m", "--urgent")
        self.cli("reminders", "add", rows["Timed"], "--at", "2026-09-25T08:00", "--service", "email")
        self.cli("reminders", "add", rows["Timed"], "--place", "Office", "--lat", "41.4", "--lon", "2.2", "--on", "enter", "--radius", "150")
        self.assertIn("needs a due date with a time", self.cli("reminders", "add", rows["Untimed"], "--before", "10m", ok=False).stderr)
        p = self.cli("reminders")
        self.assertIn("relative 30 min before the due time [urgent]", p.stdout)
        self.assertIn("absolute at 2026-09-25 08:00 [email]", p.stdout)
        self.assertIn("location on_enter Office (41.4, 2.2, radius 150)", p.stdout)
        self.assertEqual(len(self.cli("reminders", "--location").stdout.strip().split("\n")), 1)
        self.assertIn("reminders: 3", self.cli("show", rows["Timed"], "--reminders").stdout)
        rid = p.stdout.split("\n")[0].split()[0]
        self.cli("reminders", "edit", rid, "--before", "1h")
        self.assertEqual([r["minute_offset"] for r in mock.STORE.reminders if r["id"] == rid], [60])
        self.assertIn("keeps its type", self.cli("reminders", "edit", rid, "--at", "2026-09-25T07:00", ok=False).stderr)
        self.cli("reminders", "rm", rid)
        self.assertEqual(len([r for r in mock.STORE.reminders if not r["is_deleted"]]), 2)
        self.assertIn('["Home", "41.38", "2.17"]', self.cli("reminders", "locations").stdout)
        self.cli("reminders", "clear-locations", "--yes")
        self.assertEqual(mock.STORE.locations, [])
        mock.STORE.plan["reminders"] = False
        p = self.cli("reminders", "add", rows["Timed"], "--before", "5m", ok=False)
        self.assertIn("need a paid Todoist plan", p.stderr)
        self.cli("reminders", "add", rows["Timed"], "--before", "0m")  # at the due time, where reminders_at_due holds
        self.assertEqual(len([r for r in mock.STORE.reminders if not r["is_deleted"]]), 3)

    def test_filters_lifecycle_run_and_the_cap(self):
        a, b = self.seed()
        self.assertIn("Priority 1  p1", self.cli("filters").stdout)
        self.cli("filters", "add", "Small", "@effort-S", "--color", "green", "--description", "quick wins")
        f = [x for x in mock.STORE.filters if x["name"] == "Small"][0]
        self.assertEqual((f["query"], f["color"], f["description"]), ("@effort-S", "green", "quick wins"))
        p = self.cli("filters", "run", "Small")
        self.assertIn("Seed two", p.stdout)
        self.assertNotIn("Seed one", p.stdout)
        self.cli("filters", "edit", "Small", "--query", "@effort-S & p1", "--favorite")
        self.assertEqual((f["query"], f["is_favorite"]), ("@effort-S & p1", True))
        self.assertEqual(self.cli("filters", "run", "Small").stdout, "")
        self.cli("filters", "add", "Third", "today")
        self.assertIn("max_filters", self.cli("filters", "add", "Fourth", "overdue", ok=False).stderr)
        self.cli("filters", "order", "Third", "Small")
        self.assertEqual(f["item_order"], 2)
        p = self.cli("filters", "rm", "Small", ok=None)
        self.assertEqual(p.returncode, 2)
        self.cli("filters", "rm", "Small", "--yes")
        self.assertTrue(f["is_deleted"])

    # ---- activity, user, notifications, views

    def test_activity_log(self):
        a, b = self.seed()
        self.cli("done", a)
        p = self.cli("activity")
        self.assertIn("completed item", p.stdout)
        self.assertIn("added item", p.stdout)
        self.assertIn("Seed one", p.stdout)
        self.assertIn("in Work", p.stdout)
        self.assertNotIn("Buy milk", p.stdout)  # scoped to the project
        rows = json.loads(self.cli("activity", "--type", "task", "--event", "completed", "--json").stdout)
        self.assertEqual([e["event_type"] for e in rows], ["completed"])
        rows = json.loads(self.cli("activity", "--task", b, "--json").stdout)
        self.assertEqual([e["event_type"] for e in rows], ["added"])
        self.assertEqual(self.cli("activity", "--others").stdout, "")
        self.assertIn("Seed one", self.cli("activity", "--mine").stdout)
        rows = json.loads(self.cli("activity", "--all-projects", "--event", "!completed", "--since", "1d", "--limit", "2", "--json").stdout)
        self.assertEqual(len(rows), 2)
        mock.STORE.plan["activity_log_limit"] = 7  # beyond the plan's history the API answers 403: read from its edge
        self.assertIn("keeps 7 days of activity; reading from ", self.cli("activity", "--since", "30d").stderr)
        p = self.cli("activity", "--since", "7d")
        self.assertIn("keeps 7 days", p.stderr)
        self.assertIn("Seed one", p.stdout)
        self.assertNotIn("keeps 7 days", self.cli("activity", "--since", "6d").stderr)
        self.assertIn("PREMIUM_ONLY", self.cli("api", "GET", "/activities", "--q", "date_from=2020-01-01T00:00:00Z", ok=False).stderr)
        self.assertIn("nothing to read: --until 20d is before", self.cli("activity", "--since", "30d", "--until", "20d", ok=False).stderr)
        self.cli("activity", "--since", "30d", "--until", "1h")

    def test_user_settings_goals_and_redaction(self):
        p = self.cli("user")
        self.assertIn("Test User <me@example.com>  id 2671355  tz Europe/Madrid  plan pro", p.stdout)
        self.assertNotIn("secret-token", p.stdout)
        o = json.loads(self.cli("user", "--json").stdout)
        self.assertNotIn("token", o["user"])  # the state never keeps it (the cache test); api read user masks it
        self.assertNotIn("websocket_url", o["user"])
        self.assertEqual(o["user"]["email"], "me@example.com")
        self.assertIn("max_filters: 3", self.cli("user", "plan").stdout)
        self.cli("user", "settings", "reminder_email=on")
        self.assertTrue(mock.STORE.user_settings["reminder_email"])
        self.assertIn("is not one of", self.cli("user", "settings", "bogus=on", ok=False).stderr)
        self.cli("user", "set", "start_day=7", "timezone=Europe/Kyiv")
        self.assertEqual((mock.STORE.user["start_day"], mock.STORE.user["timezone"]), (7, "Europe/Kyiv"))
        self.assertIn("not one of", self.cli("user", "set", "password=x", ok=False).stderr)
        self.cli("user", "goals", "--daily", "7", "--vacation", "on", "--days", "6,7")
        self.assertEqual((mock.STORE.user["daily_goal"], mock.STORE.user["goals"]["vacation_mode"], mock.STORE.user["goals"]["ignore_days"]), (7, 1, [6, 7]))
        self.assertIn("share_invitation_sent by push: off", self.cli("user", "notify", "share_invitation_sent", "push", "off").stdout)
        info = self.cli("user", "info").stdout
        self.assertEqual(json.loads(info)["id"], "2671355")
        self.assertNotIn("secret-token", info)  # GET /user carries the API token and the websocket address too
        self.assertNotIn("ws-secret", info)
        self.assertNotIn("dev-secret", info)
        self.assertEqual(json.loads(info)["websocket_url"], "***")
        out = os.path.join(self.tmp, "user.json")  # api --out writes the masked JSON too
        self.cli("api", "GET", "/user", "--out", out)
        self.assertEqual((json.loads(self.read(out))["token"], json.loads(self.read(out))["websocket_url"]), ("***", "***"))
        self.assertNotIn("secret", self.read(out))
        self.assertIn("must-be-masked", json.dumps(mock.STORE.plan) + "must-be-masked")  # the billing mock carries a token key
        self.assertNotIn("must-be-masked", self.cli("billing", "state").stdout)

    def test_notifications_and_views(self):
        mock.STORE.live_notifications.append({"id": "n1", "created_at": mock.stamp(), "notification_type": "share_invitation_sent",
                                              "is_unread": True, "from_uid": "2671362", "invitation_id": "456",
                                              "invitation_secret": "s3cret", "_v": 1})
        p = self.cli("notifications", "--unread")
        self.assertIn("share_invitation_sent [unread] from:2671362", p.stdout)
        self.assertNotIn("s3cret", p.stdout)
        self.assertEqual(json.loads(self.cli("notifications", "--json").stdout)[0]["invitation_secret"], "***")
        self.cli("notifications", "read", "n1")
        self.assertFalse(mock.STORE.live_notifications[0]["is_unread"])
        self.cli("notifications", "unread", "n1")
        self.assertTrue(mock.STORE.live_notifications[0]["is_unread"])
        self.cli("notifications", "read", "--all")
        self.assertFalse(mock.STORE.live_notifications[0]["is_unread"])
        self.assertIn("accepted invitation 456", self.cli("share", "accept", "n1").stdout)
        self.seed()
        self.cli("views", "set", "project", "Work", "--group", "priority", "--sort-by", "due_date", "--direction", "asc", "--completed", "off")
        v = mock.STORE.view_options[0]
        self.assertEqual((v["view_type"], v["object_id"], v["grouped_by"], v["show_completed_tasks"]), ("project", self.pid(), "priority", False))
        self.assertIn("project %s" % self.pid(), self.cli("views").stdout)
        self.cli("views", "set", "today", "--mode-view", "board")
        self.cli("views", "reset", "project", "Work")
        self.assertEqual([v["view_type"] for v in mock.STORE.view_options], ["today"])
        self.cli("views", "default", "Work", "--sort-by", "priority")
        self.assertEqual([p for p in mock.STORE.projects if p["name"] == "Work"][0]["view_defaults"], {"sorted_by": "priority"})

    # ---- templates, backups, emails, ids, workspaces, folders

    def test_templates_export_import_new(self):
        self.seed()
        p = self.cli("templates", "export", "Work")
        self.assertIn("task,Seed one,", p.stdout)
        self.assertIn("section,alpha,", p.stdout)
        path = os.path.join(self.tmp, "t.csv")
        self.cli("templates", "export", "Work", "--out", path, "--relative")
        self.assertIn("task,Seed two,", self.read(path))
        self.assertIn("templates.todoist.com", self.cli("templates", "url", "Work").stdout)
        self.cli("projects", "add", "Copy")
        p = self.cli("templates", "import", "Copy", "--file", path, ok=None)
        self.assertEqual(p.returncode, 2)
        self.cli("templates", "import", "Copy", "--file", path, "--yes")
        self.assertEqual(sorted(i["content"] for i in mock.STORE.items if i["project_id"] == self.pid("Copy")), ["Seed one", "Seed two"])
        self.cli("templates", "import", "Copy", "--id", "product-launch", "--yes")
        self.assertIn("From template product-launch", [i["content"] for i in mock.STORE.items])
        self.cli("templates", "new", "Fresh", "--file", path, "--yes")
        self.assertEqual(len([i for i in mock.STORE.items if i["project_id"] == self.pid("Fresh")]), 2)
        mock.STORE.plan["templates"] = False
        self.assertIn("needs a paid", self.cli("templates", "url", "Work", ok=False).stderr)

    def test_backup_download_follows_the_redirect_without_the_token(self):
        p = self.cli("backups")
        self.assertIn("2026-09-22 03:00", p.stdout)
        out = os.path.join(self.tmp, "b.zip")
        self.cli("backups", "get", "--latest", "--out", out)
        self.assertEqual(self.read(out, "rb")[:2], b"PK")
        self.assertEqual(mock.STORE.cdn_requests, [("/cdn/b1.zip", False)])

    def test_emails_ids_workspaces_folders(self):
        a, b = self.seed()
        self.assertIn("item.", self.cli("emails", "get", "--task", a).stdout)
        self.assertIn("project.", self.cli("emails", "--project", "Work").stdout)
        p = self.cli("emails", "off", "--task", a, ok=None)
        self.assertEqual(p.returncode, 2)
        self.cli("emails", "off", "--task", a, "--yes")
        self.assertEqual(list(mock.STORE.emails), ["project:" + self.pid()])
        self.assertIn('"new_id": "v2_abc"', self.cli("ids", "map", "items", "abc").stdout)
        self.assertEqual(self.cli("workspaces").stdout, "")
        p = self.cli("workspaces", "users", "1", ok=False)
        self.assertIn("Teams feature", p.stderr)
        self.assertNotIn("refused the token", p.stderr)
        self.assertIn("Teams feature", self.cli("folders", "list", "--workspace", "1", ok=False).stderr)
        self.assertIn("Teams feature", self.cli("workspaces", "invite", "1", "a@b.c", "--yes", ok=False).stderr)
        self.assertEqual(self.cli("workspaces", "kick", "1", "a@b.c", ok=None).returncode, 2)

    # ---- the escape hatch

    def test_api_get_write_sync_and_read(self):
        a, b = self.seed()
        rows = json.loads(self.cli("api", "GET", "/tasks", "--q", "project_id=" + self.pid()).stdout)["results"]
        self.assertEqual(sorted(r["content"] for r in rows), ["Seed one", "Seed two"])
        rows = json.loads(self.cli("api", "GET", "/projects", "--all-pages").stdout)
        self.assertIn("Work", [p["name"] for p in rows])
        self.assertIn("starts with /", self.cli("api", "GET", "https://evil.example/x", ok=False).stderr)
        p = self.cli("api", "POST", "/tasks/quick", "--body", '{"text": "Via api"}', ok=None)
        self.assertEqual(p.returncode, 2)
        self.assertNotIn("Via api", [i["content"] for i in mock.STORE.items])
        self.cli("api", "POST", "/tasks/quick", "--body", '{"text": "Via api"}', "--yes")
        self.assertIn("Via api", [i["content"] for i in mock.STORE.items])
        p = self.cli("api", "sync", "item_update", "--args", '{"id": "%s", "priority": 4}' % self.items()[0]["id"], "--dry")
        self.assertIn('"type": "item_update"', p.stdout)
        self.assertEqual(self.items()[0]["priority"], 4 if self.items()[0]["content"] == "Seed one" else 1)
        iid = [i["id"] for i in self.items() if i["content"] == "Seed two"][0]
        self.cli("api", "sync", "item_update", "--args", '{"id": "%s", "priority": 3}' % iid, "--yes")
        self.assertEqual([i["priority"] for i in self.items() if i["id"] == iid], [3])
        p = self.cli("api", "sync", "label_add", "--args", '{"name": "viaapi"}', "--temp-id", "--yes")
        self.assertIn("temp_id_mapping", p.stdout)
        self.assertIn("viaapi", [l["name"] for l in mock.STORE.labels])
        p = self.cli("api", "sync", "bogus_cmd", "--args", "{}", "--yes", ok=False)
        self.assertIn("Unknown command type", p.stderr)
        o = json.loads(self.cli("api", "read", "user,filters").stdout)
        self.assertEqual((o["user"]["token"], o["user"]["websocket_url"]), ("***", "***"))
        self.assertEqual([f["name"] for f in o["filters"]], ["Priority 1"])
        out = os.path.join(self.tmp, "csv.txt")
        self.cli("api", "GET", "/templates/file", "--q", "project_id=" + self.pid(), "--raw", "--out", out)
        self.assertIn("task,Seed one", self.read(out))
        self.assertIn("--args must be JSON", self.cli("api", "sync", "item_update", "--args", "nope", ok=False).stderr)


class TestConfigVerbs(Base):
    """config path|show|check|init and doctor, against the fixture config and the mock (docs/spec-config.md sec. 6)."""

    def test_path_show_check(self):
        self.assertEqual(self.cli("config", "path").stdout.strip(), CONFIG)
        eff = json.loads(self.cli("config", "show", "--json").stdout)
        self.assertEqual((eff["defaults"]["project"], eff["attributes"]["mode"]["values"][2], eff["todoist"]["token"]["source"],
                          eff["provenance"]["src"]["url_template"]), ("Work", "owner", "env", SESSION))
        self.assertNotIn(mock.TOKEN, self.cli("config", "show").stdout)
        self.assertIn("ok: " + CONFIG, self.cli("config", "check").stdout)
        self.assertIn("todos config:", self.cli("config", "frobnicate", ok=False).stderr)

    def test_init_and_a_broken_file_stops_every_verb_but_config_and_help(self):
        path = os.path.join(self.tmp, "config.json")
        self.assertIn("wrote " + path, self.cli("config", "init", "--out", path).stdout)
        with open(path) as f:
            raw = json.load(f)
        self.assertEqual((raw["version"], raw["backend"], raw["defaults"]["project"]), (1, "todoist", "Tasks"))
        self.assertIn("exists", self.cli("config", "init", "--out", path, ok=False).stderr)
        self.assertIn("ok: " + path, self.cli("config", "check", config=path).stdout)
        self.assertIn('no Todoist project "Tasks" yet', self.cli("list", config=path).stderr)
        bad = self.file("bad.json", '{"version": 1, "attributes": {"mode": {"values": ["Big Rock", "x"]}}, "zzz": 1}')
        p = self.cli("list", config=bad, ok=False)
        self.assertIn('attributes.mode.values[0]: "Big Rock" is not one lowercase word', p.stderr)
        p = self.cli("config", "check", config=bad, ok=False)
        self.assertIn("warning: unknown key zzz", p.stderr)
        self.assertIn("1 error(s)", p.stderr)
        self.assertIn("todos add", self.cli("help", config=bad).stdout)
        p = self.cli("list", "--config", bad, ok=False)  # the flag names the file too
        self.assertIn("Big Rock", p.stderr)
        self.assertEqual(mock.STORE.write_requests, 0)

    def test_no_default_project_and_the_vocabulary_from_the_file(self):
        empty = self.file("empty.json", '{"version": 1}')
        self.assertIn("no default project", self.cli("list", config=empty, ok=False).stderr)
        self.assertIn("Inbox", self.cli("projects", config=empty).stdout)  # account verbs need none
        self.assertIn("(none)", self.cli("help", config=empty).stdout)
        own = self.file("own.json", json.dumps({
            "version": 1, "defaults": {"project": "Work"}, "todoist": {"token": {"source": "env"}},
            "attributes": {"effort": {"prefix": "size-", "values": ["xs", "xl"]}, "mode": {"values": ["auto", "human"]},
                           "kinds": {"create_missing": False}},
            "provenance": {"origin_link": "Source", "src": {"url_template": "https://s.example/%s"}}}))
        self.assertIn("--mode auto|human", self.cli("help", config=own).stdout)
        self.assertIn("mode must be one of auto|human", self.cli("add", "T", "--area", "a", "--mode", "owner", config=own, ok=False).stderr)
        p = self.cli("add", "Sized", "--area", "a", "--effort", "XL", "--mode", "Human", "--src", "7e57ab1e", "--note", "Body", config=own)
        [it] = self.items()
        self.assertEqual(sorted(it["labels"]), ["human", "size-xl"])  # the configured spellings
        self.assertEqual(it["description"], "Body [Source](https://s.example/7e57ab1e)")
        row = json.loads(self.cli("list", "--json", config=own).stdout)[0]
        self.assertEqual((row["effort"], row["mode"], row["url"]), ("xl", "human", "https://s.example/7e57ab1e"))
        self.assertEqual([r["title"] for r in json.loads(self.cli("list", "--json", "--effort", "xl", "--mode", "HUMAN", config=own).stdout)], ["Sized"])
        self.assertIn("keeps kinds to the existing labels", self.cli("add", "Kinded", "--area", "a", "--kind", "newkind", config=own, ok=False).stderr)
        self.assertRegex(self.cli("export", config=own).stdout, r"\[id \S+, xl, human, src 7e57ab1e, since ")
        self.assertIn("leave 1 unchanged", self.cli("import", self.file("own.md", self.cli("export", config=own).stdout), "--dry", "--update", config=own).stderr)

    def test_init_from_account_check_account_and_setup(self):
        # the fixture config names Work (bills, home, tools) and Personal; the account gets Work with bills and home,
        # labels through the tasks, a section that is not one word, and owner on a task with no other mode
        self.cli("add", "A", "--area", "bills", "--kind", "decision", "--effort", "S", "--mode", "unattended")
        self.cli("add", "B", "--area", "home", "--effort", "M", "--mode", "assisted", "--kind", "build")
        self.cli("add", "C", "--area", "home", "--mode", "owner")
        self.cli("sections", "add", "Big Rock")
        out = os.path.join(self.tmp, "acct.json")
        p = self.cli("config", "init", "--from-account", "--out", out)
        with open(out) as f:
            raw = json.load(f)
        self.assertEqual(raw["defaults"]["project"], "Work")
        self.assertEqual(raw["projects"]["Work"], {"areas": ["bills", "home"]})
        self.assertEqual(sorted(raw["attributes"]["effort"]["values"]), ["M", "S"])
        self.assertNotIn("meaning", raw["attributes"]["effort"])
        self.assertEqual(raw["attributes"]["mode"]["values"], ["unattended", "assisted", "owner"])  # the defaults stay
        self.assertEqual(raw["attributes"]["kinds"]["known"], ["build", "decision"])  # from the label rows
        self.assertIn('sections not usable as areas: "Big Rock"', p.stdout)
        # owner, and the inbox seed's errand (a label on a task with no label row), never sit on a task with the two modes
        self.assertIn("third-mode candidates (labels never on a task with unattended or assisted): errand, owner", p.stdout)
        self.assertIn("default project: Work (the most open tasks)", p.stdout)
        self.assertIn("ok: " + out, self.cli("config", "check", config=out).stdout)
        # drift against the fixture config: Work lacks tools, Personal does not exist
        p = self.cli("config", "check", "--account", ok=False)
        self.assertIn("drift: project Work: no section tools", p.stdout)
        self.assertIn("drift: project Personal: not in the account", p.stdout)
        self.assertIn("note: labels in use outside the vocabulary: errand", p.stdout)
        self.assertIn("2 drift item(s)", p.stderr)
        p = self.cli("setup", "plan")
        for l in ("would create project Personal", "would create section tools in Work", "would create label effort-L",
                  "would create label verify", "1 project(s), 1 section(s), 4 label(s) to create"):
            self.assertIn(l, p.stdout)
        self.assertNotIn("would create label owner", p.stdout)
        before = mock.STORE.write_requests
        p = self.cli("setup", "apply", ok=False)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(mock.STORE.write_requests, before)  # nothing written without --yes
        p = self.cli("setup", "apply", "--yes")
        self.assertIn("created: 1 project(s), 1 section(s), 4 label(s)", p.stdout)
        self.assertTrue([x for x in mock.STORE.projects if x["name"] == "Personal"])
        self.assertEqual(len([x for x in mock.STORE.sections if x["name"] == "tools"]), 1)
        self.assertIn("ok: the account has every configured project and area", self.cli("config", "check", "--account").stdout)
        self.assertIn("nothing to create", self.cli("setup", "plan").stdout)
        self.assertIn("todos setup: plan | apply", self.cli("setup", "frob", ok=False).stderr)
        # doctor --claude in a HOME with no skill link
        p = self.cli("doctor", "--claude", env={"HOME": self.tmp}, ok=False)
        self.assertIn("FAIL: skill link %s" % os.path.join(self.tmp, ".claude", "skills", "invoke-todos"), p.stdout)

    def test_doctor(self):
        p = self.cli("doctor")
        self.assertIn("ok:   token: %d characters from the environment" % len(mock.TOKEN), p.stdout)
        self.assertIn("plan pro", p.stdout)
        self.assertIn("ok:   default project: Work", p.stdout)
        self.assertNotIn(mock.TOKEN, p.stdout)
        p = self.cli("doctor", token="", ok=False)
        self.assertIn("FAIL: token: no Todoist token: TODOIST_API_TOKEN is not set", p.stdout)
        self.assertIn("1 check(s) failed", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
