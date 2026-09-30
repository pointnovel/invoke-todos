"""The server-side filter: tasks matching a Todoist filter query, read into the house view."""
from invoke_todos.backends.todoist.api import pages
from invoke_todos.backends.todoist.items import Item
from invoke_todos.model import assign_short_ids, link_tree


def server_filter(st, query, lang=None):
    """Tasks matching a Todoist filter query, from GET /tasks/filter (account-wide, one request per page)."""
    names = {sid: sec.get("name") or "" for sid, sec in st.all_sections.items()}
    q = {"query": query}
    if lang:
        q["lang"] = lang
    out = []
    for raw in pages("/tasks/filter", q):
        it = Item(raw, names, st.notes.get(raw.get("id"), []))
        it.project = st.project_names.get(raw.get("project_id"))
        out.append(it)
    assign_short_ids(st.all_items + out)
    link_tree(out)
    return out
