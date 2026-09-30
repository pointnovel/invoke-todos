"""The backends, one package per task app; load(name) imports the one the config names."""
import importlib

from invoke_todos.config import BACKENDS
from invoke_todos.output import die


def load(name):
    """The package invoke_todos.backends.<name>; an unknown name stops with the known list."""
    if name not in BACKENDS:
        die("unknown backend %s; known: %s" % (name, ", ".join(BACKENDS)))
    return importlib.import_module("invoke_todos.backends." + name)
