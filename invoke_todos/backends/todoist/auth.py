"""The API token: the environment first, then the configured source (the macOS Keychain, a 0600 file, or a
command that prints it). The token is never printed."""
import getpass
import os
import subprocess

from invoke_todos.config import cfg
from invoke_todos.output import die


_token = None
WHERE_TOKEN = "the value is in Todoist > Settings > Integrations > Developer"


def token_store_hint():
    """The one line that stores the token for the configured source, typed in the user's own terminal."""
    src = cfg.token_source
    if src == "keychain":
        return 'security add-generic-password -a "$USER" -s %s -w' % cfg.token_item
    if src == "file":
        return "umask 077; printf '%%s' '<token>' > %s" % cfg.token_path
    if src == "command":
        return "make `%s` print it" % " ".join(cfg.token_command or ["<the configured command>"])
    return "export %s=<token> in your shell profile" % cfg.token_env


def find_token():
    """(token, None) from the environment or the configured source (todoist.token in the config), else (None, why).
    The token is never printed."""
    t = os.environ.get(cfg.token_env, "").strip()
    if t:
        return t, None
    src = cfg.token_source
    tail = " (%s), or export %s for one command." % (WHERE_TOKEN, cfg.token_env)
    if src == "env":
        return None, "no Todoist token: %s is not set. Store it once: %s%s" % (cfg.token_env, token_store_hint(), tail)
    if src == "keychain":
        if os.environ.get("TODOIST_NO_KEYCHAIN") == "1":
            return None, "no Todoist token: %s is not set and the Keychain is off (TODOIST_NO_KEYCHAIN=1)." % cfg.token_env
        try:
            r = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", getpass.getuser(),
                                "-s", cfg.token_item, "-w"], capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip(), None
        except (OSError, subprocess.SubprocessError):
            pass
        return None, "no Todoist token in the Keychain item %s. Store it once, in your own terminal: %s%s" % (
            cfg.token_item, token_store_hint(), tail)
    if src == "file":
        p = cfg.token_path
        try:
            mode = os.stat(p).st_mode & 0o777
        except OSError:
            return None, "no Todoist token file %s. Store it once: %s%s" % (p, token_store_hint(), tail)
        if mode & 0o077:
            return None, "%s is readable by others (mode %o); chmod 600 %s" % (p, mode, p)
        try:
            with open(p, encoding="utf-8") as f:
                t = f.read().strip()
        except OSError as e:
            return None, "cannot read %s: %s" % (p, e)
        return (t, None) if t else (None, "%s is empty. Store the token: %s%s" % (p, token_store_hint(), tail))
    if src == "command":
        try:
            r = subprocess.run(cfg.token_command, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as e:
            return None, "the token command `%s` failed: %s" % (" ".join(cfg.token_command), e)
        t = (r.stdout.split("\n") or [""])[0].strip()
        if r.returncode != 0 or not t:
            return None, "the token command `%s` exited %d without a token" % (" ".join(cfg.token_command), r.returncode)
        return t, None
    return None, "unknown token source %s (todos config check)" % src


def token():
    global _token
    if _token:
        return _token
    t, why = find_token()
    if not t:
        die(why)
    _token = t
    return t
