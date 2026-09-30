"""Output and exit: messages on stderr, JSON on stdout with secret-named values masked, the --yes gate."""
import json
import sys


SECRET_KEYS = ("token", "access_token", "refresh_token", "client_secret", "invitation_secret", "password",
               "current_password", "device_token", "feature_identifier",
               "websocket_url")  # the user object's websocket address carries a token of its own in its query


def err(msg):
    sys.stderr.write(msg + "\n")


def die(msg, code=1):
    sys.stdout.flush()
    err(msg)
    sys.exit(code)


def print_json(obj, pretty=False):
    if pretty:
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


def redact(obj):
    """A copy with every secret-named value masked (the user object carries the API token, and a second token
    in its websocket_url)."""
    if isinstance(obj, dict):
        return {k: ("***" if k in SECRET_KEYS and v else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def emit(rows, a, fn):
    """Rows as one line each (fn), or as JSON with --json; secrets masked either way."""
    if a.has("json"):
        print_json(redact(rows), a.has("pretty"))
    else:
        for r in rows:
            print(fn(r))


def need_yes(a, lines, what):
    """A destructive or bulk write: without --yes print what would happen and exit 2."""
    if a.has("yes"):
        return
    for l in lines:
        print("would " + l)
    die("%s needs --yes" % what, 2)
