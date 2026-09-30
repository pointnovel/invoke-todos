#!/usr/bin/env python3
"""Unit tests of invoke_todos.config: the defaults, the file, the environment, validation, the example.
python3 tests/test_config.py"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from invoke_todos import config as C  # noqa: E402


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="todos-config.")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name, obj):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))
        return path

    def env(self, **kw):
        e = {"HOME": self.tmp}
        e.update(kw)
        return e

    def test_defaults_without_a_file(self):
        cfg = C.load(None, self.env())
        self.assertEqual(cfg.path, os.path.join(self.tmp, ".config", "invoke-todos", "config.json"))
        self.assertFalse(cfg.exists)
        self.assertIsNone(cfg.project)
        self.assertEqual((cfg.modes, cfg.efforts, cfg.effort_prefix), (list(C.DEFAULT_MODES), list(C.DEFAULT_EFFORTS), "effort-"))
        self.assertEqual(cfg.token_source, "keychain" if sys.platform == "darwin" else "file")
        self.assertEqual(cfg.cache_dir, os.path.join(self.tmp, ".cache", "invoke-todos"))
        self.assertIsNone(cfg.src_url_template)
        self.assertEqual(cfg.projects, {})
        cfg = C.load(None, self.env(XDG_CONFIG_HOME=os.path.join(self.tmp, "xdg")))
        self.assertEqual(cfg.path, os.path.join(self.tmp, "xdg", "invoke-todos", "config.json"))

    def test_file_then_environment_then_flag(self):
        p = self.write("c.json", {"version": 1, "defaults": {"project": "A", "timeout": 5},
                                  "paths": {"cache_dir": "off"}, "projects": {"A": {"areas": ["x"]}}})
        cfg = C.load(None, self.env(TODOS_CONFIG=p))
        self.assertEqual((cfg.project, cfg.timeout, cfg.cache_dir, cfg.exists), ("A", 5.0, None, True))
        self.assertEqual(cfg.projects, {"A": {"areas": ["x"], "role": None}})
        cfg = C.load(None, self.env(TODOS_CONFIG=p, TODOIST_PROJECT="B", TODOIST_TIMEOUT="7", TODOIST_CACHE="~/c",
                                    TODOIST_SESSION_URL="https://x/%s", TODOIST_API_BASE="http://127.0.0.1:1/api/v1/"))
        self.assertEqual((cfg.project, cfg.timeout, cfg.cache_dir, cfg.src_url_template, cfg.api_base),
                         ("B", 7.0, os.path.join(self.tmp, "c"), "https://x/%s", "http://127.0.0.1:1/api/v1"))
        cfg = C.load(None, self.env(TODOS_CONFIG=p, TODOIST_PROJECT=""))  # an empty variable is not an override
        self.assertEqual(cfg.project, "A")
        q = self.write("d.json", {"version": 1, "defaults": {"project": "D"}})
        cfg = C.load(q, self.env(TODOS_CONFIG=p))
        self.assertEqual((cfg.project, cfg.path), ("D", q))

    def test_comments_and_unknown_keys(self):
        p = self.write("c.json", {"version": 1, "_": "note", "defaults": {"_x": 1, "project": "A"}, "extra": {},
                                  "paths": {"nope": 1}, "projects": {"A": {"colour": "red"}}})
        cfg = C.load(None, self.env(TODOS_CONFIG=p))
        self.assertEqual(cfg.project, "A")
        self.assertEqual(cfg.warnings, ["unknown key extra (ignored)", "unknown key paths.nope (ignored)",
                                        "unknown key projects.A.colour (ignored)"])
        self.assertEqual(cfg.raw, {"version": 1, "defaults": {"project": "A"}, "extra": {}, "paths": {"nope": 1},
                                   "projects": {"A": {"colour": "red"}}})

    def test_validation_names_the_key(self):
        cases = [
            ({"version": 2}, "version: must be 1"),
            ({"version": 1, "backend": "x"}, "backend: must be one of todoist"),
            ({"version": 1, "attributes": {"mode": {"values": ["Big Rock"]}}},
             'attributes.mode.values[0]: "Big Rock" is not one lowercase word'),
            ({"version": 1, "attributes": {"mode": {"values": ["effort-x"]}}},
             "attributes.mode.values[0]: starts with the effort prefix"),
            ({"version": 1, "attributes": {"mode": {"values": ["a", "a"]}}}, "attributes.mode.values: duplicate a"),
            ({"version": 1, "attributes": {"effort": {"values": ["S", "s"]}}}, "attributes.effort.values: duplicate s"),
            ({"version": 1, "projects": {"A": {"areas": ["Two words"]}}},
             'projects.A.areas[0]: "Two words" is not one lowercase word'),
            ({"version": 1, "todoist": {"token": {"value": "x"}}},
             "todoist.token.value: the token does not belong in the config file"),
            ({"version": 1, "todoist": {"token": {"source": "sms"}}},
             "todoist.token.source: must be one of env|keychain|file|command"),
            ({"version": 1, "todoist": {"token": {"source": "command"}}},
             "todoist.token.command: must be a non-empty list of strings"),
            ({"version": 1, "defaults": {"title_max": 10}}, "defaults.title_max: must be an integer of at least 20"),
            ({"version": 1, "defaults": {"timeout": "soon"}}, "defaults.timeout: must be a positive number"),
            ({"version": 1, "provenance": {"src": {"url_template": "https://x/"}}},
             "provenance.src.url_template: must contain %s"),
            ({"version": 1, "todoist": {"task_url": "todoist://task"}}, "todoist.task_url: must contain %s"),
            ({"version": 1, "paths": {"cache_dir": ""}}, "paths.cache_dir: must be a path or off"),
            ({"version": 1, "projects": []}, "projects: must be an object"),
        ]
        for raw, msg in cases:
            p = self.write("v.json", raw)
            with self.assertRaises(C.ConfigError) as cm:
                C.load(None, self.env(TODOS_CONFIG=p))
            self.assertIn(msg, str(cm.exception), raw)
            self.assertTrue(str(cm.exception).startswith(p + ": "), str(cm.exception))
        p = self.write("v.json", "{not json")
        with self.assertRaises(C.ConfigError) as cm:
            C.load(None, self.env(TODOS_CONFIG=p))
        self.assertIn("not JSON", str(cm.exception))
        p = self.write("v.json", "[1]")
        with self.assertRaises(C.ConfigError) as cm:
            C.load(None, self.env(TODOS_CONFIG=p))
        self.assertIn("top level must be an object", str(cm.exception))
        with self.assertRaises(C.ConfigError) as cm:
            C.load(None, self.env(TODOIST_TIMEOUT="soon"))
        self.assertIn("TODOIST_TIMEOUT", str(cm.exception))

    def test_safe_load_keeps_the_defaults_and_the_environment(self):
        p = self.write("v.json", "{not json")
        cfg = C.safe_load(None, self.env(TODOS_CONFIG=p, TODOIST_PROJECT="E"))
        self.assertIn("not JSON", cfg.error)
        self.assertEqual((cfg.path, cfg.exists, cfg.project, cfg.modes), (p, True, "E", list(C.DEFAULT_MODES)))
        cfg = C.safe_load(None, self.env())
        self.assertIsNone(cfg.error)

    def test_check_lists_every_error(self):
        p = self.write("v.json", {"version": 1, "attributes": {"mode": {"values": ["Big Rock", "b b"]}}, "zzz": 1})
        errors, warnings = C.check(p, self.env())
        self.assertEqual(len(errors), 2)
        self.assertEqual(warnings, ["unknown key zzz (ignored)"])
        self.assertEqual(C.check(os.path.join(self.tmp, "none.json"), self.env()), ([], []))
        broken = self.write("broken.json", "{")
        self.assertEqual(C.check(broken, self.env())[0][0][:len(broken)], broken)
        self.assertEqual(C.check(p, self.env(TODOIST_MAX_WAIT="x"))[0][-1], "TODOIST_MAX_WAIT: 'x' is not a number")
        self.assertEqual(C.check(p, self.env(TODOIST_TASK_URL="todoist://task"))[0][-1], "TODOIST_TASK_URL: must contain %s (the task id)")
        self.assertEqual(C.check(p, self.env(TODOIST_SESSION_URL="https://s/none"))[0][-1], "TODOIST_SESSION_URL: must contain %s (the session id)")
        self.assertEqual(len(C.check(p, self.env(TODOIST_TASK_URL="todoist://task?id=%s"))[0]), 2)

    def test_example_loads_clean_and_round_trips(self):
        p = self.write("e.json", C.example())
        cfg = C.load(None, self.env(TODOS_CONFIG=p))
        self.assertEqual((cfg.project, cfg.warnings, cfg.modes[2], cfg.kinds[0]), ("Tasks", [], "owner", "decision"))
        self.assertEqual(cfg.projects["Tasks"], {"role": "work", "areas": ["inbox", "tools", "writing"]})
        eff = cfg.effective()
        self.assertNotIn("value", eff["todoist"]["token"])
        self.assertEqual(json.loads(json.dumps(eff))["defaults"]["project"], "Tasks")
        self.assertEqual(C.validate(C.strip_comments(C.example("Mine"))), ([], []))

    def test_the_shipped_example_is_the_one_config_init_writes(self):
        path = os.path.join(os.path.dirname(HERE), "examples", "config.example.json")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), json.dumps(C.example(), indent=2, ensure_ascii=False) + "\n")

    def test_file_values_reach_the_attributes(self):
        p = self.write("f.json", {
            "version": 1, "backend": "todoist", "account": {"name": "me"},
            "todoist": {"api_base": "https://api.example/v1/", "task_url": "todoist://task?id=%s",
                        "token": {"source": "command", "command": ["pass", "show", "t"]}},
            "defaults": {"project": "P", "export": "~/out.md", "timeout": 3, "settle": 1.5, "max_wait": 4, "title_max": 40},
            "paths": {"cache_dir": "~/cache"},
            "projects": {"P": {"areas": ["a", "b"], "role": "work"}, "Q": {}},
            "attributes": {"effort": {"prefix": "size-", "values": ["xs", "xl"], "meaning": {"xs": "tiny"}},
                           "mode": {"values": ["auto", "human"]},
                           "kinds": {"known": ["k1"], "create_missing": False, "meaning": {"k1": "one"}},
                           "priority": {"meaning": "urgency"}},
            "provenance": {"comment": False, "origin_link": "Source", "src": {"url_template": "https://s/%s"}},
        })
        cfg = C.load(None, self.env(TODOS_CONFIG=p))
        self.assertEqual((cfg.account_name, cfg.api_base, cfg.token_source, cfg.token_command), ("me", "https://api.example/v1", "command", ["pass", "show", "t"]))
        self.assertEqual((cfg.task_url, C.load(None, self.env()).task_url), ("todoist://task?id=%s", None))
        self.assertEqual((cfg.project, cfg.export_path, cfg.timeout, cfg.settle, cfg.max_wait, cfg.title_max), ("P", "~/out.md", 3.0, 1.5, 4, 40))
        self.assertEqual(cfg.cache_dir, os.path.join(self.tmp, "cache"))
        self.assertEqual(cfg.projects, {"P": {"areas": ["a", "b"], "role": "work"}, "Q": {"areas": [], "role": None}})
        self.assertEqual((cfg.effort_prefix, cfg.efforts, cfg.effort_meaning, cfg.modes, cfg.mode_meaning), ("size-", ["xs", "xl"], {"xs": "tiny"}, ["auto", "human"], {}))
        self.assertEqual((cfg.kinds, cfg.kinds_create_missing, cfg.kinds_meaning, cfg.priority_meaning), (["k1"], False, {"k1": "one"}, "urgency"))
        self.assertEqual((cfg.provenance_comment, cfg.origin_link, cfg.src_url_template), (False, "Source", "https://s/%s"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
