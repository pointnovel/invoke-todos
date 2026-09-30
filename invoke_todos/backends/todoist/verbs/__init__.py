"""The Todoist verbs, one module per family, imported in the usage text's order so registration is deterministic."""
from invoke_todos.backends.todoist.verbs import (  # noqa: F401
    tasks, projects, sections, labels, comments, reminders, filters, activity, user, views, workspace, api, setup,
)
