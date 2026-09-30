#!/usr/bin/env python3
"""install.sh and the setup verbs in a scratch HOME against the mock: the refactor's phase 4 exit
check (install, config init, setup apply, add, brief, doctor --claude, uninstall).
python3 tests/test_install.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import mock_todoist as mock  # noqa: E402


class TestInstall(unittest.TestCase):
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
        self.home = tempfile.mkdtemp(prefix="todos-home.")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.bin = os.path.join(self.home, ".local", "bin")
        self.link = os.path.join(self.bin, "todos")
        self.skill = os.path.join(self.home, ".claude", "skills", "invoke-todos")
        self.config = os.path.join(self.home, ".config", "invoke-todos", "config.json")

    def env(self):
        # a scratch HOME, and a PATH that starts with its bin folder and holds only the system's python3
        return {"HOME": self.home, "PATH": self.bin + ":/usr/bin:/bin:/usr/local/bin", "LANG": "C.UTF-8",
                "TODOIST_API_BASE": self.base, "TODOIST_API_TOKEN": mock.TOKEN, "TODOIST_TIMEOUT": "10", "TODOIST_SETTLE": "0"}

    def run_(self, argv, ok=True, stdin=None):
        p = subprocess.run(argv, input=stdin, capture_output=True, text=True, env=self.env(), timeout=60)
        if ok is True and p.returncode != 0:
            self.fail("%s -> %d\nstdout: %s\nstderr: %s" % (" ".join(argv), p.returncode, p.stdout, p.stderr))
        if ok is False and p.returncode == 0:
            self.fail("expected a failure: %s\nstdout: %s" % (" ".join(argv), p.stdout))
        return p

    def sh(self, *args, **kw):
        return self.run_(["sh", os.path.join(REPO, "install.sh")] + list(args), **kw)

    def todos(self, *args, **kw):
        cli = kw.pop("cli", self.link)
        return self.run_([sys.executable, cli] + list(args), **kw)

    def test_install_config_setup_add_brief_doctor_uninstall(self):
        p = self.sh("--dry-run", "--config")
        self.assertIn("would run: ln -s", p.stdout)
        self.assertFalse(os.path.lexists(self.link))
        p = self.sh("--config")
        self.assertIn("linked: %s -> %s" % (self.link, os.path.join(REPO, "todos")), p.stdout)
        self.assertIn("linked: %s -> %s" % (self.skill, os.path.join(REPO, "skills", "invoke-todos")), p.stdout)
        self.assertEqual(os.path.realpath(self.link), os.path.join(REPO, "todos"))
        self.assertTrue(os.path.isfile(os.path.join(self.skill, "SKILL.md")))
        self.assertIn("wrote " + self.config, p.stdout)
        with open(self.config) as f:
            raw = json.load(f)
        self.assertEqual((raw["defaults"]["project"], sorted(raw["projects"]["Tasks"]["areas"])), ("Tasks", ["inbox", "tools", "writing"]))
        p = self.sh("--config")
        self.assertIn("ok, already linked", p.stdout)
        self.assertIn("ok, config exists", p.stdout)
        # the scratch account lacks everything the config names
        p = self.todos("config", "check", "--account", ok=False)
        self.assertIn("drift: project Tasks: not in the account", p.stdout)
        self.assertIn("1 drift item(s)", p.stderr)
        p = self.todos("setup", "plan")
        for l in ("would create project Tasks", "would create section inbox in Tasks", "would create label effort-S",
                  "would create label owner", "would create label parked", "1 project(s), 3 section(s), 11 label(s) to create"):
            self.assertIn(l, p.stdout)
        p = self.todos("setup", "apply", ok=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("setup apply needs --yes", p.stderr)
        p = self.todos("setup", "apply", "--yes")
        self.assertIn("created: 1 project(s), 3 section(s), 11 label(s)", p.stdout)
        [proj] = [x for x in mock.STORE.projects if x["name"] == "Tasks"]
        self.assertEqual(sorted(s["name"] for s in mock.STORE.sections if s["project_id"] == proj["id"]), ["inbox", "tools", "writing"])
        self.assertTrue({"effort-S", "effort-M", "effort-L", "unattended", "assisted", "owner", "decision", "verify", "build",
                         "write", "parked"} <= {l["name"] for l in mock.STORE.labels})
        self.assertIn("nothing to create", self.todos("setup", "plan").stdout)
        self.assertIn("ok: the account has every configured project and area", self.todos("config", "check", "--account").stdout)
        # first use
        self.todos("add", "First task", "--area", "inbox", "--kind", "build", "--effort", "S", "--mode", "unattended")
        p = self.todos("brief")
        self.assertTrue(p.stdout.startswith("Tasks: 1 open, 0 overdue, 0 due today; areas: inbox 1"), p.stdout)
        self.assertIn("First task", p.stdout)  # under # unattended
        p = self.todos("doctor", "--claude")
        self.assertIn("ok:   skill link %s -> %s" % (self.skill, os.path.join(REPO, "skills", "invoke-todos")), p.stdout)
        self.assertIn("ok:   todos on PATH: " + self.link, p.stdout)
        self.assertIn("ok:   cache dir " + os.path.join(self.home, ".cache", "invoke-todos"), p.stdout)
        # undo
        p = self.sh("--uninstall")
        self.assertIn("removed: " + self.link, p.stdout)
        self.assertIn("removed: " + self.skill, p.stdout)
        self.assertFalse(os.path.lexists(self.link) or os.path.lexists(self.skill))
        self.assertTrue(os.path.exists(self.config))
        p = self.todos("doctor", "--claude", cli=os.path.join(REPO, "todos"), ok=False)
        self.assertIn("FAIL: skill link", p.stdout)
        self.assertIn("FAIL: todos on PATH: not found", p.stdout)

    def test_refusals_and_options(self):
        os.makedirs(self.bin)
        with open(self.link, "w") as f:
            f.write("#!/bin/sh\n")
        p = self.sh("--no-skill", ok=False)
        self.assertIn("exists and is not a link; left alone", p.stderr)
        self.assertIn("skipped the skill link (--no-skill)", p.stdout)
        p = self.sh("--no-skill", "--force")
        self.assertEqual(os.path.realpath(self.link), os.path.join(REPO, "todos"))
        self.assertFalse(os.path.lexists(self.skill))
        p = self.sh("--name", "td", "--skills", os.path.join(self.home, "elsewhere"))
        self.assertEqual(os.path.realpath(os.path.join(self.bin, "td")), os.path.join(REPO, "todos"))
        self.assertTrue(os.path.islink(os.path.join(self.home, "elsewhere", "invoke-todos")))
        self.assertIn("unknown option", self.sh("--frob", ok=False).stderr)
        self.assertIn("--name needs a plain file name", self.sh("--name", "a/b", ok=False).stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
