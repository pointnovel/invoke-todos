#!/usr/bin/env python3
"""The layering rules of docs/spec-modules.md sec. 1: the core never imports a backend (rule 5; cli.py is the
one exception, through backends.load), no module imports one below it in the sec. 3 order (rule 4), the verb
modules form no cycle among themselves, and every module of the package imports on its own.
python3 tests/test_layering.py"""
import ast
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "invoke_todos")
CORE = ["output", "dates", "config", "model", "args", "query", "render", "importer", "exporter", "verbs", "cli"]
BACKEND = ["auth", "api", "items", "state", "flags", "query", "mutations", "render", "usage"]
BACKEND_DIR = os.path.join(PKG, "backends", "todoist")


def py_files(folder, skip=()):
    out = []
    for d, dirs, files in os.walk(folder):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__" and x not in skip)
        out += [os.path.join(d, f) for f in sorted(files) if f.endswith(".py")]
    return out


def imports_of(path):
    """The package modules a file imports, as dotted names without the invoke_todos prefix."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "invoke_todos":
            base = node.module[len("invoke_todos"):].lstrip(".")
            out += [base] if base else [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            out += [a.name[len("invoke_todos."):] for a in node.names if a.name.startswith("invoke_todos.")]
    return out


def module_name(path):
    rel = os.path.relpath(path, ROOT)[:-3].replace(os.sep, ".")
    return rel[:-len(".__init__")] if rel.endswith(".__init__") else rel


class TestLayering(unittest.TestCase):
    def test_the_core_never_names_a_backend(self):
        for path in py_files(PKG, skip=("backends",)):
            if os.path.basename(path) == "cli.py":
                continue
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("backends", f.read(), os.path.relpath(path, ROOT))

    def test_a_core_module_imports_only_modules_above_it(self):
        for name in CORE:
            for imp in imports_of(os.path.join(PKG, name + ".py")):
                if imp == "backends":
                    self.assertEqual(name, "cli", "%s imports the backends" % name)
                    continue
                self.assertIn(imp, CORE, "%s imports %s, which is not a core module" % (name, imp))
                self.assertLess(CORE.index(imp), CORE.index(name), "%s imports %s, which sits below it" % (name, imp))

    def test_a_backend_module_imports_the_core_or_modules_above_it(self):
        for name in BACKEND:
            for imp in imports_of(os.path.join(BACKEND_DIR, name + ".py")):
                if imp.startswith("backends.todoist."):
                    below = imp[len("backends.todoist."):]
                    self.assertIn(below, BACKEND, "%s imports %s" % (name, imp))
                    self.assertLess(BACKEND.index(below), BACKEND.index(name), "%s imports %s, which sits below it" % (name, imp))
                else:
                    self.assertIn(imp, CORE, "%s imports %s, which is neither core nor above it" % (name, imp))

    def test_the_verb_modules_form_no_cycle(self):
        prefix = "backends.todoist.verbs."
        graph = {}
        for path in py_files(os.path.join(BACKEND_DIR, "verbs")):
            name = os.path.basename(path)[:-3]
            graph[name] = [imp[len(prefix):] for imp in imports_of(path) if imp.startswith(prefix)]

        def reaches(start, target, seen):
            for nxt in graph.get(start, []):
                if nxt == target or (nxt not in seen and reaches(nxt, target, seen | {nxt})):
                    return True
            return False

        for name in graph:
            self.assertFalse(reaches(name, name, {name}), "%s imports itself through %s" % (name, graph[name]))

    def test_every_module_imports_on_its_own(self):
        env = dict(os.environ, TODOS_CONFIG=os.path.join(HERE, "fixtures", "config.json"), PYTHONPATH=ROOT)
        for path in py_files(PKG):
            mod = module_name(path)
            p = subprocess.run([sys.executable, "-c", "import " + mod], capture_output=True, text=True, env=env,
                               cwd=ROOT, timeout=60)
            self.assertEqual(p.returncode, 0, "import %s failed:\n%s" % (mod, p.stderr))


if __name__ == "__main__":
    unittest.main(verbosity=1)
