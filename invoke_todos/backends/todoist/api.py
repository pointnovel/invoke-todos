"""HTTP against the Todoist API v1: one request (call, rest), cursor pagination, multipart bodies, Sync commands
and their batched write, downloads that carry the token only to todoist.com hosts over https."""
import json
import mimetypes
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from invoke_todos.backends.todoist.auth import token, token_store_hint
from invoke_todos.config import cfg
from invoke_todos.output import die, err, redact


BATCH = 100


def retry_after(body):
    try:
        return (json.loads(body).get("error_extra") or {}).get("retry_after")
    except (ValueError, AttributeError):
        return None


def call(method, path, query=None, form=None, body=None, data=None, content_type=None, raw=False,
         timeout=None, retry=True, headers=None):
    """One HTTP request. `form` is urlencoded, `body` is sent as JSON, `data` as bytes of `content_type`.
    `raw` returns the response bytes; otherwise JSON is decoded (text comes back as str). A 5xx or a network
    error is retried twice when `retry` (Sync commands carry uuids and GETs are idempotent; a REST write
    is not retried, the docs do not promise deduplication). The token rides as an unredirected header, so a
    redirect to another host (a backup download goes to a CDN) does not carry it along."""
    url = cfg.api_base + path + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
    hdrs = dict(headers or {})
    payload = None
    if form is not None:
        payload = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        payload = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    elif data is not None:
        payload = data
        hdrs["Content-Type"] = content_type or "application/octet-stream"
    if os.environ.get("TODOIST_DEBUG") == "1":  # the request, never the token nor a secret-named value
        shown = form if form is not None else body
        if isinstance(shown, dict) and isinstance(shown.get("commands"), str):
            try:
                shown = dict(shown, commands=json.loads(shown["commands"]))
            except ValueError:
                pass
        shown = json.dumps(redact(shown)) if shown is not None else ("<%d bytes>" % len(payload) if payload else "")
        err("debug: %s %s %s" % (method, url, shown))
    attempts = 3 if retry else 1
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=payload, method=method, headers=hdrs)
        req.add_unredirected_header("Authorization", "Bearer " + token())
        try:
            with urllib.request.urlopen(req, timeout=timeout or cfg.timeout) as r:
                out = r.read()
            if raw:
                return out
            if not out:
                return {}
            try:
                return json.loads(out.decode("utf-8"))
            except ValueError:
                return out.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if e.code == 401:
                die("Todoist refused the token (HTTP 401). Replace it where it is stored (the %s source): %s"
                    % (cfg.token_source, token_store_hint()))
            if e.code == 429:
                wait = e.headers.get("Retry-After") or retry_after(text)
                try:
                    wait = int(float(wait))
                except (TypeError, ValueError):
                    wait = None
                if wait is not None and wait <= cfg.max_wait and attempt < 3:
                    err("rate limited by Todoist; waiting %d s" % wait)
                    time.sleep(wait + 0.5)
                    continue
                die("Todoist rate limit reached (HTTP 429)" + (", retry in %s s" % wait if wait else ""), 75)
            if e.code >= 500 and attempt < attempts:
                time.sleep(1.5)
                continue
            die("Todoist %s %s: HTTP %d %s" % (method, path, e.code, text[:300].strip()))
        except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
            if attempt < attempts:
                time.sleep(1.5)
                continue
            die("cannot reach Todoist at %s: %s" % (cfg.api_base, getattr(e, "reason", e)))


def rest(method, path, query=None, body=None, **kw):
    """A REST call: GETs are retried, writes are not."""
    kw.setdefault("retry", method == "GET")
    return call(method, path, query=query, body=body, **kw)


def rows_of(r):
    """The list a paginated response carries (`results`, `items`, ...), whatever its key."""
    if isinstance(r, list):
        return r
    if isinstance(r, dict):
        for k in ("results", "items", "events", "backups", "collaborators"):
            if isinstance(r.get(k), list):
                return r[k]
        for v in r.values():
            if isinstance(v, list):
                return v
    return []


def pages(path, query=None, limit=None, max_pages=None):
    """Every object of a cursor-paginated GET, page after page (limit 200, the API's ceiling)."""
    q = dict(query or {})
    q["limit"] = limit or 200
    n = 0
    while True:
        r = call("GET", path, query=q)
        n += 1
        for x in rows_of(r):
            yield x
        cursor = r.get("next_cursor") if isinstance(r, dict) else None
        if not cursor or (max_pages and n >= max_pages):
            return
        q["cursor"] = cursor


def multipart(fields, files):
    """(body, content type) for multipart/form-data; files = [(field, file name, bytes, mime type)]."""
    boundary = "----todoist-cli-" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode())
    for field, name, blob, mime in files:
        out.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
                    % (boundary, field, name, mime)).encode() + blob + b"\r\n")
    out.append(("--%s--\r\n" % boundary).encode())
    return b"".join(out), "multipart/form-data; boundary=" + boundary


def read_file(path):
    path = os.path.expanduser(path)
    try:
        with open(path, "rb") as f:
            return f.read(), os.path.basename(path), mimetypes.guess_type(path)[0] or "application/octet-stream"
    except OSError as e:
        die("cannot read %s: %s" % (path, e))


def new_cmd(kind, args):
    """A Sync command. Every *_add carries a temp_id: the live API refuses label_add without one."""
    c = {"type": kind, "uuid": str(uuid.uuid4()), "args": args}
    if kind.endswith("_add"):
        c["temp_id"] = str(uuid.uuid4())
    return c


def describe(c):
    a = c["args"]
    return a.get("content") or a.get("name") or a.get("id") or a.get("item_id") or ""


def write(groups):
    """Send command groups (a group travels in one request: a task and its comment) in batches of at most
    100 commands. Returns the temp id mapping; any failed command ends the run after its batch."""
    mapping = {}
    batch = []

    def flush():
        if not batch:
            return
        for c in batch:  # a temp id created by an earlier request has a real id by now
            for k in ("id", "item_id", "project_id", "section_id", "parent_id"):
                v = c["args"].get(k)
                if isinstance(v, str) and v in mapping:
                    c["args"][k] = mapping[v]
        r = call("POST", "/sync", form={"commands": json.dumps(batch)})
        status = r.get("sync_status") or {}
        mapping.update(r.get("temp_id_mapping") or {})
        failed = [(c, status.get(c["uuid"])) for c in batch if status.get(c["uuid"]) != "ok"]
        for c, s in failed:
            msg = s.get("error") if isinstance(s, dict) else (s or "no status returned")
            extra = s.get("error_extra") if isinstance(s, dict) else None
            err("failed: %s %s: %s%s" % (c["type"], describe(c), msg, " " + json.dumps(extra) if extra else ""))
        if failed:
            die("%d of %d command(s) in the last request failed; the others were applied" % (len(failed), len(batch)))
        del batch[:]

    for g in groups:
        if batch and len(batch) + len(g) > BATCH:
            flush()
        batch.extend(g)
    flush()
    return mapping


def download(url, out=None):
    """Fetch a file the API points at (an attachment, a backup); the token goes only to todoist.com hosts,
    and only over https."""
    req = urllib.request.Request(url)
    u = urllib.parse.urlparse(url)
    host = u.hostname or ""
    if u.scheme == "https" and (host == "todoist.com" or host.endswith(".todoist.com")):
        req.add_unredirected_header("Authorization", "Bearer " + token())
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            blob, ctype = r.read(), r.headers.get("Content-Type") or ""
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        die("cannot fetch %s: %s" % (url, getattr(e, "reason", e)))
    if out == "-":
        sys.stdout.buffer.write(blob)
        return None
    out = os.path.expanduser(out or os.path.basename(urllib.parse.urlparse(url).path) or "download")
    try:
        with open(out, "wb") as f:
            f.write(blob)
    except OSError as e:
        die("cannot write %s: %s" % (out, e))
    print("wrote %s: %d bytes%s" % (out, len(blob), " " + ctype if ctype else ""))
    return out
