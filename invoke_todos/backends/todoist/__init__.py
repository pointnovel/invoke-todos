"""The Todoist backend: the API, the account state, the verbs and their flag sets, the usage text.

What cli.main reads: NAME, VALUE_FLAGS and BOOL_FLAGS (one flag namespace for every verb), usage() and
register_verbs(), which imports the verb modules so each registers its handlers in invoke_todos.verbs.HANDLERS."""
from invoke_todos.backends.todoist.usage import USAGE_TEXT, usage  # noqa: F401

NAME = "todoist"


VALUE_FLAGS = {"area", "due", "deadline", "prio", "kind", "tag", "effort", "mode", "src", "since", "url",
               "note", "title", "due-before", "sort", "out", "fields", "parent", "project", "in", "section",
               "duration", "assign", "assignee", "tz", "order", "at", "filter", "saved", "grep", "label", "by",
               "until", "to", "name", "color", "text", "view", "workspace", "folder", "visibility", "collapsed",
               "weeks", "file", "notify", "before", "place", "lat", "lon", "on", "radius", "query", "task",
               "type", "event", "events", "limit", "max", "daily", "weekly", "vacation", "karma", "role",
               "group", "sort-by", "direction", "mode-view", "completed", "calendar", "id", "new", "locale",
               "mfa", "projects", "add", "remove", "code", "q", "body", "form", "args", "commands", "service",
               "lang", "email", "user", "days", "link-sharing", "guests", "reminder", "description", "config"}
BOOL_FLAGS = {"json", "pretty", "open", "all", "done", "dry", "force", "help", "overdue", "clear-due", "fresh",
              "clear-deadline", "desc", "no-desc", "yes", "update", "clear-duration", "forever", "all-projects",
              "comments", "reminders", "account", "archived", "root", "favorite", "no-favorite", "tasks",
              "context", "analyze", "personal", "shared", "counts", "keep-on-tasks", "clear-description", "email-service",
              "push", "urgent", "location", "mine", "others", "children", "parents", "notes", "unread",
              "relative", "latest", "delete", "all-pages", "raw", "temp-id", "full", "day", "meta", "from-account", "claude", "tree", "links"}


def register_verbs():
    """Import the verb modules, in the usage text's order; each registers its handlers on import."""
    from invoke_todos.backends.todoist import verbs  # noqa: F401
    return verbs
