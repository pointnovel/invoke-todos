#!/usr/bin/env python3
"""Public-safety audit: no private marker in any file the public archive would carry.

Scans every file git would commit (tracked or untracked and not ignored; without git, every file
under the tree outside build and cache folders) except the paths .gitattributes marks
export-ignore and this file, and fails naming every hit as path:line: marker, so the failure
output is the checklist of what still ties the tree to its author. Red on purpose until the
refactor's de-personalisation phases landed; green is a release condition
(docs/spec-onboarding.md sec. 1). Files that are not UTF-8 text are skipped.

    python3 tests/test_public.py
"""
import fnmatch
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = os.path.relpath(os.path.abspath(__file__), ROOT)
ALWAYS_SKIP = {SELF}
# The author's account name is public by construction (the repository's owner, the license holder); the
# markers catch the home path (/Users/) and the email address instead.
SKIP_DIRS = {".git", "dist", "__pycache__", ".venv", "node_modules"}

# (pattern, what it is); every pattern is matched without regard to case.
MARKERS = (
    (r"vlad", "the author's first name"),
    (r"pointnovel@", "the author's email address"),
    (r"\bnmac\b", "the author's machine"),
    (r"tail14aeab", "the author's tailnet"),
    (r"lifeos", "the author's repo and project"),
    (r"csessions", "the author's session viewer"),
    (r"\bsecret (set|get|run)\b", "a private helper"),
    (r"\basya\b", "a real person in a fixture"),
    (r"~/Tools\b", "the author's tool folder"),
    (r"~/\.claude/tools\b", "the author's private hooks folder"),
    (r"/Users/", "an absolute home path"),
)
PATTERNS = [(re.compile(p, re.IGNORECASE), what) for p, what in MARKERS]


def export_ignored():
    """The paths and patterns .gitattributes marks export-ignore."""
    out = set()
    try:
        with open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and not parts[0].startswith("#") and "export-ignore" in parts[1:]:
                    out.add(parts[0].strip("/"))
    except OSError:
        pass
    return out


def is_ignored(path, patterns):
    for p in patterns:
        if path == p or path.startswith(p + "/") or fnmatch.fnmatch(path, p) or fnmatch.fnmatch(os.path.basename(path), p):
            return True
    return False


def candidates():
    """What git would commit: tracked files plus untracked ones that are not ignored."""
    try:
        r = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, check=True)
        return sorted(p for p in r.stdout.decode("utf-8").split("\0") if p)
    except (OSError, subprocess.CalledProcessError):
        out = []
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for f in sorted(files):
                out.append(os.path.relpath(os.path.join(d, f), ROOT))
        return out


def scan():
    ignored = export_ignored()
    hits = []
    for path in candidates():
        if path in ALWAYS_SKIP or is_ignored(path, ignored) or path.split("/")[0] in SKIP_DIRS:
            continue
        try:
            with open(os.path.join(ROOT, path), encoding="utf-8") as f:
                lines = f.read().split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(lines, 1):
            for rx, what in PATTERNS:
                if rx.search(line):
                    hits.append((path, n, rx.pattern, what))
    return hits


class TestPublic(unittest.TestCase):
    def test_no_private_markers(self):
        hits = scan()
        if not hits:
            return
        per_file = {}
        for path, _, _, _ in hits:
            per_file[path] = per_file.get(path, 0) + 1
        summary = ", ".join("%s %d" % kv for kv in sorted(per_file.items()))
        detail = "\n".join("%s:%d: %s (%s)" % h for h in hits)
        self.fail("%d private marker(s) in %d file(s): %s\n%s" % (len(hits), len(per_file), summary, detail))


if __name__ == "__main__":
    unittest.main()
