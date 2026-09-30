#!/usr/bin/env python3
# A stand-in for the part of the Todoist API v1 that ../todoist uses, for offline tests: the Sync
# endpoint (full and incremental reads of every resource type the CLI asks for, write commands for
# tasks, projects, sections, labels, comments, reminders, filters, view options, sharing, the user and
# live notifications) and the REST endpoints behind the other verbs (completed tasks by completion or
# due date, the filter query, quick add, comments and reactions, uploads, templates, activity, stats,
# the user, emails, backups with their redirect, id mappings, folders and workspaces). Shapes follow
# developer.todoist.com/api/v1 as read on 2026-09-22, corrected by what the live API did on 2026-09-23:
# an *_add without a temp_id is refused, a deadline on a free plan is refused, the server stores labels
# sorted, and title and due changes to a task in its first seconds are lost (`settle`). Subtasks as the
# docs describe them: an item_add with parent_id lands in the parent's section, a subtask follows its
# parent through item_move, and item_close, item_complete and item_delete take the subtasks along.
# `lag` plays the docs' warning that a full sync can lag behind the latest writes (not seen live). The
# state lives in memory; every object carries a change version for incremental syncs. Possibly
# stricter than the real service, on purpose: a duplicate personal label and a temp id from another
# request are errors. The filter query and Quick Add parsers cover a small subset of the language.
# `python3 mock_todoist.py [port]` serves it alone.

import copy
import json
import random
import re
import string
import sys
import threading
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "test-token"
ALNUM = string.ascii_letters + string.digits
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
LISTS = ("projects", "sections", "labels", "items", "notes", "project_notes", "filters", "reminders",
         "collaborators", "collaborator_states", "live_notifications")
ME = "2671355"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def stamp(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def public(o):
    return {k: v for k, v in o.items() if k != "_v"}


class CommandError(Exception):
    def __init__(self, code, tag, msg):
        Exception.__init__(self, msg)
        self.code, self.tag, self.msg = code, tag, msg


class Store(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        for k in LISTS:
            setattr(self, k, [])
        self.plan = {"plan_name": "pro", "deadlines": True, "durations": True, "reminders": True, "reminders_at_due": True,
                     "comments": True, "labels": True, "filters": True, "uploads": True, "templates": True,
                     "activity_log": True, "activity_log_limit": 7, "email_forwarding": True, "automatic_backups": False,
                     "completed_tasks": True, "max_tasks": 300, "max_sections": 20, "max_projects": 300, "max_labels": 500,
                     "max_filters": 3, "max_reminders_time": 700, "max_reminders_location": 300, "max_collaborators": 25,
                     "upload_limit_mb": 5, "max_free_workspaces_created": 1, "max_folders_per_workspace": 5}
        self.user = {"id": ME, "full_name": "Test User", "email": "me@example.com", "token": "secret-token-0123",
                     "websocket_url": "wss://ws.example.com/ws?token=ws-secret-4567",  # observed live, 2026-09-30
                     "urgent_reminder_device": {"device_platform": "ios", "device_id": "12345678",
                                                "device_token": "dev-secret-89", "device_name": "Phone"},
                     "tz_info": {"timezone": "Europe/Madrid", "gmt_string": "+02:00", "hours": 2}, "daily_goal": 5,
                     "weekly_goal": 25, "karma": 8619, "karma_trend": "up", "start_day": 1, "days_off": [6, 7],
                     "inbox_project_id": "6Inbox000000000A", "is_premium": False, "lang": "en", "features": {}}
        self.user_settings = {"reminder_push": True, "reminder_desktop": True, "reminder_email": False,
                              "completed_sound_desktop": True, "completed_sound_mobile": True}
        self.locations = [["Home", "41.38", "2.17"]]
        self.view_options = []
        self.events = []
        self.uploads = []
        self.emails = {}
        self.folders = []
        self.cdn_requests = []  # (path, had an Authorization header): the backup download's redirect
        self.version = 0
        self.lag = 0          # > 0: a full sync answers with the state from before the last `lag` writes
        self.settle = 0       # > 0: title and due changes to a task younger than this many seconds are lost
        self.history = []     # (version, state) before each write, kept while lag > 0
        self.write_requests = 0
        self.full_reads = 0
        self.incremental_reads = 0
        self.completed_requests = []
        self.rest_requests = []
        self.silent = set()   # ids changed by the current write that the incremental sync must not carry
        # somebody's other data, which the CLI must leave alone
        inbox = {"id": "6Inbox000000000A", "name": "Inbox", "inbox_project": True, "is_deleted": False,
                 "is_archived": False, "color": "charcoal", "child_order": 0, "shared": False}
        self.projects.append(inbox)
        self.labels.append({"id": "2156154810", "name": "errand", "is_deleted": False, "color": "charcoal", "item_order": 1,
                            "is_favorite": False})
        self.add_item({"content": "Buy milk", "project_id": inbox["id"], "labels": ["errand"]}, "6Inbox00000000T1")
        self.filters.append({"id": "2200000001", "name": "Priority 1", "query": "p1", "color": "teal", "item_order": 1,
                             "is_favorite": False, "is_deleted": False})
        self.collaborators.append({"id": ME, "full_name": "Test User", "email": "me@example.com", "is_deleted": False})
        self.collaborators.append({"id": "2671362", "full_name": "Alex Example", "email": "alex@example.com", "is_deleted": False})

    # ------------------------------------------------ helpers for tests that change the account directly

    def touch(self, obj):
        self.version += 1
        obj["_v"] = self.version

    def add_item(self, args, rid):
        it = self.item(args, rid)
        self.items.append(it)
        self.touch(it)
        return it

    def event(self, obj_type, obj, event_type):
        self.events.append({"id": str(len(self.events) + 1), "object_type": obj_type, "object_id": obj.get("id"),
                            "event_type": event_type, "event_date": stamp(), "initiator_id": ME,
                            "parent_project_id": obj.get("project_id"), "parent_item_id": obj.get("item_id") or obj.get("parent_id"),
                            "extra_data": {"content": obj.get("content"), "name": obj.get("name")}})

    # ------------------------------------------------ commands

    def new_id(self, prefix):
        return prefix + "".join(random.choice(ALNUM) for _ in range(16 - len(prefix)))

    def find(self, rows, rid, what):
        for r in rows:
            if str(r["id"]) == str(rid) and not r.get("is_deleted"):
                return r
        raise CommandError(20 if what != "item" else 22, what.upper() + "_NOT_FOUND", what.capitalize() + " not found")

    @staticmethod
    def due(d, old=None):
        """A due object as the server would store it: from a date, or from a string of the small subset this
        mock parses (today, tomorrow, YYYY-MM-DD, every day, every <weekday>); a date plus the old string
        keeps a recurrence (the reschedule shape)."""
        if d is None:
            return None
        s, text = d.get("date"), d.get("string")
        if s and not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?Z?)?", s):
            raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Invalid argument value")
        if s:
            recurring = bool(d.get("is_recurring")) and bool(text)
            return {"date": s, "timezone": d.get("timezone"), "string": text or s.replace("T", " ")[:16], "lang": "en",
                    "is_recurring": recurring}
        if not text:
            raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Invalid argument value")
        low = text.strip().lower()
        today = date.today()
        if low == "today":
            day, rec = today, False
        elif low == "tomorrow":
            day, rec = today + timedelta(days=1), False
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", low):
            day, rec = date.fromisoformat(low), False
        elif low == "every day":
            day, rec = today, True
        elif low.startswith("every ") and low[6:].split()[0] in WEEKDAYS:
            want = WEEKDAYS.index(low[6:].split()[0])
            day = today + timedelta(days=(want - today.weekday()) % 7)
            rec = True
        else:
            raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Unable to parse the due string")
        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", low)
        when = day.isoformat()
        if m and (m.group(2) or m.group(3)):
            h = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
            when += "T%02d:%02d:00" % (h, int(m.group(2) or 0))
        return {"date": when, "timezone": d.get("timezone"), "string": text.strip(), "lang": "en", "is_recurring": rec}

    def deadline(self, d):
        if not d:
            return None
        if not self.plan["deadlines"]:
            raise CommandError(32, "PREMIUM_ONLY", "Premium only feature")
        return {"date": d["date"], "lang": "en"}

    def duration(self, d):
        if not d:
            return None
        if not self.plan["durations"]:
            raise CommandError(32, "PREMIUM_ONLY", "Premium only feature")
        if d.get("unit") not in ("minute", "day") or not isinstance(d.get("amount"), int) or d["amount"] <= 0:
            raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Invalid argument value")
        return {"amount": d["amount"], "unit": d["unit"]}

    def item(self, a, rid):
        prio = a.get("priority", 1)
        if prio not in (1, 2, 3, 4):
            raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Invalid argument value")
        project_id, section_id, parent_id = a.get("project_id"), a.get("section_id"), a.get("parent_id")
        if parent_id:
            parent = self.find(self.items, parent_id, "item")
            if section_id and section_id != parent["section_id"]:
                raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Section differs from the parent's")
            project_id, section_id = parent["project_id"], parent["section_id"]
        siblings = [i for i in self.items if i["parent_id"] == parent_id and i["project_id"] == project_id
                    and i["section_id"] == section_id and not i["is_deleted"]]
        return {"id": rid, "user_id": ME, "project_id": project_id, "section_id": section_id,
                "content": a["content"], "description": a.get("description", ""), "priority": prio,
                "due": self.due(a.get("due")), "deadline": self.deadline(a.get("deadline")),
                "parent_id": parent_id, "child_order": a.get("child_order") or len(siblings) + 1,
                "labels": sorted(a.get("labels") or []), "checked": False, "is_deleted": False, "added_at": stamp(),
                "updated_at": stamp(), "completed_at": None, "duration": self.duration(a.get("duration")),
                "responsible_uid": a.get("responsible_uid"), "day_order": -1, "is_collapsed": False, "note_count": 0}

    def subtree(self, it):
        out = []
        for c in self.items:
            if c["parent_id"] == it["id"] and not c["is_deleted"]:
                out.append(c)
                out += self.subtree(c)
        return out

    def resolve(self, args, mapping):
        for k in ("id", "item_id", "project_id", "section_id", "parent_id"):
            v = args.get(k)
            if isinstance(v, str) and UUID_RE.match(v):
                if v not in mapping:
                    raise CommandError(15, "INVALID_TEMPID", "Invalid temporary id")
                args[k] = mapping[v]
        return args

    def run(self, kind, a, prefix):
        # ---- projects
        if kind == "project_add":
            # the Inbox does not count against max_projects (observed live)
            if len([p for p in self.projects if not p["is_deleted"] and not p["is_archived"] and not p.get("inbox_project")]) >= self.plan["max_projects"]:
                raise CommandError(46, "MAX_PROJECTS_LIMIT_REACHED", "Maximum number of projects reached")
            rid = self.new_id(prefix)
            row = {"id": rid, "name": a["name"], "is_deleted": False, "is_archived": False, "color": a.get("color", "charcoal"),
                   "child_order": len(self.projects), "is_favorite": bool(a.get("is_favorite")), "view_style": a.get("view_style", "list"),
                   "description": a.get("description", ""), "parent_id": a.get("parent_id"), "shared": False, "inbox_project": False}
            self.projects.append(row)
            self.event("project", row, "added")
            return rid
        if kind == "project_update":
            p = self.find(self.projects, a.get("id"), "project")
            for k in ("name", "color", "is_favorite", "view_style", "description", "is_collapsed"):
                if k in a:
                    p[k] = a[k]
            self.event("project", p, "updated")
            return None
        if kind == "project_move":
            p = self.find(self.projects, a.get("id"), "project")
            p["parent_id"] = a.get("parent_id")
            return None
        if kind in ("project_archive", "project_unarchive"):
            p = self.find(self.projects, a.get("id"), "project")
            p["is_archived"] = kind == "project_archive"
            self.event("project", p, kind[8:] + "d")
            return None
        if kind == "project_delete":
            p = self.find(self.projects, a.get("id"), "project")
            p["is_deleted"] = True
            for it in self.items:
                if it["project_id"] == p["id"]:
                    it["is_deleted"] = True
                    self.silent.add(it["id"])  # observed live 2026-09-29: the deleted project's tasks do not travel in the incremental sync
            self.event("project", p, "deleted")
            return None
        if kind == "project_reorder":
            for row in a["projects"]:
                self.find(self.projects, row["id"], "project")["child_order"] = row["child_order"]
            return None
        if kind in ("project_move_to_workspace", "project_move_to_personal"):
            raise CommandError(403, "FORBIDDEN", "Workspaces are a Teams feature")
        if kind == "project_leave":
            p = self.find(self.projects, a.get("project_id"), "project")
            if not p.get("shared"):
                raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Project is not shared")
            p["is_deleted"] = True
            return None
        if kind == "project_change_role":
            self.find(self.projects, a.get("id"), "project")
            for c in self.collaborator_states:
                if c["project_id"] == a["id"] and c["user_id"] == str(a["user_id"]):
                    c["role"] = a["role"]
            return None
        # ---- sections
        if kind == "section_add":
            self.find(self.projects, a.get("project_id"), "project")
            if len([s for s in self.sections if s["project_id"] == a["project_id"] and not s["is_deleted"]]) >= 20:
                raise CommandError(46, "MAX_SECTIONS_LIMIT_REACHED", "Maximum number of sections reached")
            rid = self.new_id(prefix)
            row = {"id": rid, "name": a["name"], "project_id": a["project_id"], "is_deleted": False,
                   "is_archived": False, "section_order": len(self.sections) + 1, "description": a.get("description", "")}
            self.sections.append(row)
            self.event("section", row, "added")
            return rid
        if kind == "section_update":
            sec = self.find(self.sections, a.get("id"), "section")
            for k in ("name", "description", "is_collapsed"):
                if k in a:
                    sec[k] = a[k]
            self.event("section", sec, "updated")
            return None
        if kind == "section_move":
            sec = self.find(self.sections, a.get("id"), "section")
            self.find(self.projects, a.get("project_id"), "project")
            sec["project_id"] = a["project_id"]
            for it in self.items:
                if it["section_id"] == sec["id"]:
                    it["project_id"] = a["project_id"]
            return None
        if kind == "section_reorder":
            for row in a["sections"]:
                self.find(self.sections, row["id"], "section")["section_order"] = row["section_order"]
            return None
        if kind in ("section_archive", "section_unarchive"):
            sec = self.find(self.sections, a.get("id"), "section")
            sec["is_archived"] = kind == "section_archive"
            return None
        if kind == "section_delete":
            sec = self.find(self.sections, a.get("id"), "section")
            sec["is_deleted"] = True
            for it in self.items:
                if it["section_id"] == sec["id"]:
                    it["is_deleted"] = True
            self.event("section", sec, "deleted")
            return None
        # ---- labels
        if kind == "label_add":
            if any(l["name"].lower() == a["name"].lower() and not l["is_deleted"] for l in self.labels):
                raise CommandError(20, "LABEL_ALREADY_EXISTS", "Label already exists")
            rid = str(random.randint(10 ** 9, 10 ** 10))
            self.labels.append({"id": rid, "name": a["name"], "is_deleted": False, "color": a.get("color", "charcoal"),
                                "item_order": len(self.labels) + 1, "is_favorite": bool(a.get("is_favorite"))})
            return rid
        if kind == "label_update":
            l = self.find(self.labels, a.get("id"), "label")
            old = l["name"]
            for k in ("name", "color", "item_order", "is_favorite"):
                if k in a:
                    l[k] = a[k]
            if l["name"] != old:  # a renamed label follows on every task
                for it in self.items:
                    if old in it["labels"]:
                        it["labels"] = sorted([l["name"] if x == old else x for x in it["labels"]])
            return None
        if kind == "label_delete":
            l = self.find(self.labels, a.get("id"), "label")
            l["is_deleted"] = True
            if a.get("cascade", "all") == "all":
                for it in self.items:
                    if l["name"] in it["labels"]:
                        it["labels"] = [x for x in it["labels"] if x != l["name"]]
            return None
        if kind == "label_rename":
            for it in self.items:
                if a["name_old"] in it["labels"]:
                    it["labels"] = sorted([a["name_new"] if x == a["name_old"] else x for x in it["labels"]])
            return None
        if kind == "label_delete_occurrences":
            for it in self.items:
                it["labels"] = [x for x in it["labels"] if x != a["name"]]
            return None
        if kind == "label_update_orders":
            for lid, order in a["id_order_mapping"].items():
                self.find(self.labels, lid, "label")["item_order"] = order
            return None
        # ---- items
        if kind == "item_add":
            if not a.get("content"):
                raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Invalid argument value")
            if a.get("project_id"):
                self.find(self.projects, a["project_id"], "project")
            if a.get("section_id"):
                sec = self.find(self.sections, a["section_id"], "section")
                if a.get("project_id") and sec["project_id"] != a["project_id"]:
                    raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Section is not in that project")
            rid = self.new_id(prefix)
            it = self.item(a, rid)
            self.items.append(it)
            self.event("item", it, "added")
            return rid
        if kind == "item_update":
            it = self.find(self.items, a.get("id"), "item")
            # observed live: title and due changes sent in a task's first seconds are accepted and lost
            young = self.settle and datetime.now(timezone.utc) - parse(it["added_at"]) < timedelta(seconds=self.settle)
            for k in ("content", "description", "priority", "responsible_uid", "child_order", "day_order", "is_collapsed"):
                if k in a and not (young and k == "content"):
                    it[k] = a[k]
            if "labels" in a:
                it["labels"] = sorted(a["labels"])
            if "due" in a and not young:
                it["due"] = self.due(a["due"], it.get("due"))
            if "deadline" in a:
                it["deadline"] = self.deadline(a["deadline"])
            if "duration" in a:
                it["duration"] = self.duration(a["duration"])
            it["updated_at"] = stamp()
            self.event("item", it, "updated")
            return None
        if kind == "item_move":
            it = self.find(self.items, a.get("id"), "item")
            keys = [k for k in ("parent_id", "section_id", "project_id") if a.get(k)]
            if len(keys) != 1:
                raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Exactly one destination")
            if keys[0] == "parent_id":
                parent = self.find(self.items, a["parent_id"], "item")
                if parent["id"] == it["id"] or parent["id"] in [c["id"] for c in self.subtree(it)]:
                    raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Cannot move a task under itself")
                it["parent_id"], it["section_id"], it["project_id"] = parent["id"], parent["section_id"], parent["project_id"]
                it["child_order"] = len([c for c in self.items if c["parent_id"] == parent["id"] and not c["is_deleted"]])
            elif keys[0] == "section_id":
                sec = self.find(self.sections, a["section_id"], "section")
                it["section_id"], it["project_id"], it["parent_id"] = sec["id"], sec["project_id"], None
            else:
                self.find(self.projects, a["project_id"], "project")
                it["project_id"], it["section_id"], it["parent_id"] = a["project_id"], None, None
            for c in self.subtree(it):  # subtasks follow their parent
                c["section_id"], c["project_id"], c["updated_at"] = it["section_id"], it["project_id"], stamp()
            it["updated_at"] = stamp()
            self.event("item", it, "moved")
            return None
        if kind == "item_reorder":
            for row in a["items"]:
                self.find(self.items, row["id"], "item")["child_order"] = row["child_order"]
            return None
        if kind == "item_update_day_orders":
            for iid, order in a["ids_to_orders"].items():
                self.find(self.items, iid, "item")["day_order"] = order
            return None
        if kind == "item_close":
            it = self.find(self.items, a.get("id"), "item")
            if (it.get("due") or {}).get("is_recurring"):  # a recurring task moves on instead of closing
                d = it["due"]
                nxt = date.fromisoformat(d["date"][:10]) + timedelta(days=7 if d["string"].lower() != "every day" else 1)
                it["due"] = dict(d, date=nxt.isoformat() + d["date"][10:])
                it["updated_at"] = stamp()
                self.event("item", it, "completed")
                return None
            for c in [it] + self.subtree(it):
                c["checked"], c["completed_at"] = True, stamp()
            self.event("item", it, "completed")
            return None
        if kind == "item_complete":
            it = self.find(self.items, a.get("id"), "item")
            for c in [it] + self.subtree(it):
                c["checked"], c["completed_at"] = True, a.get("date_completed") or stamp()
            self.event("item", it, "completed")
            return None
        if kind == "item_update_date_complete":
            it = self.find(self.items, a.get("id"), "item")
            it["due"] = self.due(a.get("due"), it.get("due"))
            return None
        if kind == "item_uncomplete":
            it = self.find(self.items, a.get("id"), "item")
            it["checked"], it["completed_at"] = False, None
            self.event("item", it, "uncompleted")
            return None
        if kind == "item_delete":
            it = self.find(self.items, a.get("id"), "item")
            for c in [it] + self.subtree(it):
                c["is_deleted"] = True
            self.event("item", it, "deleted")
            return None
        # ---- comments
        if kind == "note_add":
            rid = self.new_id(prefix)
            row = {"id": rid, "content": a["content"], "is_deleted": False, "posted_at": stamp(), "posted_uid": ME,
                   "file_attachment": a.get("file_attachment"), "uids_to_notify": a.get("uids_to_notify"), "reactions": None}
            if a.get("project_id"):
                p = self.find(self.projects, a["project_id"], "project")
                row["project_id"] = p["id"]
                self.project_notes.append(row)
            else:
                it = self.find(self.items, a.get("item_id"), "item")
                row["item_id"] = it["id"]
                self.notes.append(row)
                it["note_count"] += 1
            self.event("note", row, "added")
            return rid
        if kind == "note_update":
            n = self.find(self.notes + self.project_notes, a.get("id"), "note")
            n["content"] = a["content"]
            self.event("note", n, "updated")
            return None
        if kind == "note_delete":
            n = self.find(self.notes + self.project_notes, a.get("id"), "note")
            n["is_deleted"] = True
            self.event("note", n, "deleted")
            return None
        # ---- reminders
        if kind == "reminder_add":
            it = self.find(self.items, a.get("item_id"), "item")
            if not self.plan["reminders"] and not (a.get("type") == "relative" and a.get("minute_offset") == 0
                                                   and self.plan["reminders_at_due"]):
                raise CommandError(32, "PREMIUM_ONLY", "Reminders are a premium only feature")
            if a.get("type") not in ("relative", "absolute", "location"):
                raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Invalid reminder type")
            rid = str(random.randint(10 ** 9, 10 ** 10))
            row = {"id": rid, "item_id": it["id"], "type": a["type"], "notify_uid": a.get("notify_uid") or ME,
                   "is_deleted": False, "is_urgent": bool(a.get("is_urgent")), "service": a.get("service", "push")}
            if a["type"] == "relative":
                row["minute_offset"] = a.get("minute_offset")
            elif a["type"] == "absolute":
                row["due"] = self.due(a.get("due"))
            else:
                for k in ("name", "loc_lat", "loc_long", "loc_trigger", "radius"):
                    row[k] = a.get(k)
            self.reminders.append(row)
            return rid
        if kind == "reminder_update":
            r = self.find(self.reminders, a.get("id"), "reminder")
            for k, v in a.items():
                if k != "id":
                    r[k] = self.due(v) if k == "due" else v
            return None
        if kind == "reminder_delete":
            self.find(self.reminders, a.get("id"), "reminder")["is_deleted"] = True
            return None
        if kind == "clear_locations":
            self.locations = []
            return None
        # ---- filters
        if kind == "filter_add":
            if len([f for f in self.filters if not f["is_deleted"]]) >= self.plan["max_filters"]:
                raise CommandError(46, "MAX_FILTERS_LIMIT_REACHED", "Maximum number of filters reached")
            rid = str(random.randint(10 ** 8, 10 ** 9))
            self.filters.append({"id": rid, "name": a["name"], "query": a["query"], "color": a.get("color", "charcoal"),
                                 "item_order": len(self.filters) + 1, "is_favorite": bool(a.get("is_favorite")),
                                 "description": a.get("description", ""), "is_deleted": False})
            return rid
        if kind == "filter_update":
            f = self.find(self.filters, a.get("id"), "filter")
            for k in ("name", "query", "color", "item_order", "is_favorite", "description"):
                if k in a:
                    f[k] = a[k]
            return None
        if kind == "filter_delete":
            self.find(self.filters, a.get("id"), "filter")["is_deleted"] = True
            return None
        if kind == "filter_update_orders":
            for fid, order in a["id_order_mapping"].items():
                self.find(self.filters, fid, "filter")["item_order"] = order
            return None
        # ---- sharing
        if kind == "share_project":
            p = self.find(self.projects, a.get("project_id"), "project")
            p["shared"] = True
            uid = next((c["id"] for c in self.collaborators if c["email"] == a["email"]), None)
            if not uid:
                uid = str(random.randint(10 ** 6, 10 ** 7))
                self.collaborators.append({"id": uid, "full_name": a["email"].split("@")[0], "email": a["email"], "is_deleted": False})
            self.collaborator_states.append({"project_id": p["id"], "user_id": uid, "state": "invited", "is_deleted": False,
                                             "role": a.get("role")})
            self.event("project", p, "shared")
            return None
        if kind == "delete_collaborator":
            p = self.find(self.projects, a.get("project_id"), "project")
            uid = next((c["id"] for c in self.collaborators if c["email"] == a["email"]), None)
            for c in self.collaborator_states:
                if c["project_id"] == p["id"] and c["user_id"] == uid:
                    c["is_deleted"] = True
            return None
        if kind in ("accept_invitation", "reject_invitation", "delete_invitation"):
            return None
        # ---- the user, notifications, view options, folders, workspaces
        if kind == "user_update":
            if "email" in a or "password" in a:
                raise CommandError(20, "INVALID_ARGUMENT_VALUE", "current_password required")
            self.user.update(a)
            return None
        if kind == "update_goals":
            for k in ("daily_goal", "weekly_goal"):
                if k in a:
                    self.user[k] = a[k]
            self.user["goals"] = dict(self.user.get("goals") or {}, **a)
            return None
        if kind == "user_settings_update":
            self.user_settings.update(a)
            return None
        if kind.startswith("live_notifications_"):
            for n in self.live_notifications:
                if kind.endswith("mark_read_all") or str(n["id"]) in [str(x) for x in a.get("ids") or []]:
                    n["is_unread"] = kind.endswith("mark_unread")
            return None
        if kind == "view_options_set":
            self.view_options = [v for v in self.view_options if (v["view_type"], v.get("object_id")) != (a["view_type"], a.get("object_id"))]
            self.view_options.append(dict(a))
            return None
        if kind == "view_options_delete":
            self.view_options = [v for v in self.view_options if (v["view_type"], v.get("object_id")) != (a["view_type"], a.get("object_id"))]
            return None
        if kind == "project_view_options_defaults_set":
            self.find(self.projects, a.get("project_id"), "project")["view_defaults"] = {k: v for k, v in a.items() if k != "project_id"}
            return None
        if kind in ("folder_add", "folder_update") or kind.startswith("workspace_"):
            raise CommandError(403, "FORBIDDEN", "Workspaces are a Teams feature")
        raise CommandError(20, "INVALID_COMMAND", "Unknown command type " + kind)

    def write(self, commands):
        with self.lock:
            self.write_requests += 1
            if self.lag:
                self.history.append((self.version, {k: copy.deepcopy(getattr(self, k)) for k in LISTS}))
            before = {k: {o["id"]: json.dumps(o, sort_keys=True) for o in getattr(self, k)} for k in LISTS if k != "collaborator_states"}
            prefix = "6X" + "".join(random.choice(ALNUM) for _ in range(3))  # ids made together share a prefix
            status, mapping = {}, {}
            for c in commands:
                try:
                    if c["type"].endswith("_add") and not c.get("temp_id"):  # observed live on label_add
                        raise CommandError(20, "INVALID_ARGUMENT_VALUE", "Invalid argument value")
                    new = self.run(c["type"], self.resolve(dict(c.get("args") or {}), mapping), prefix)
                    if c.get("temp_id") and new:
                        mapping[c["temp_id"]] = new
                    status[c["uuid"]] = "ok"
                except CommandError as e:
                    status[c["uuid"]] = {"error_code": e.code, "error_tag": e.tag, "error": e.msg, "http_code": 400}
            self.version += 1
            for k in LISTS:
                for o in getattr(self, k):
                    if o.get("id") in self.silent:  # collaborator states have no id
                        continue  # changed, but the live API does not send it in the incremental sync
                    if k == "collaborator_states" or before[k].get(o["id"]) != json.dumps(o, sort_keys=True):
                        o["_v"] = self.version
            self.silent = set()
            return {"sync_status": status, "temp_id_mapping": mapping, "sync_token": "v%d" % self.version,
                    "full_sync": False}

    def read(self, types, token):
        with self.lock:
            everything = "all" in types
            if token == "*":
                self.full_reads += 1
                if self.lag and len(self.history) >= self.lag:
                    version, state = self.history[-self.lag]
                else:
                    version, state = self.version, {k: getattr(self, k) for k in LISTS}
                active = {i["id"] for i in state["items"] if not i["is_deleted"] and not i["checked"]}
                out = {"sync_token": "v%d" % version, "full_sync": True}
                for k in LISTS:
                    rows = [o for o in state[k] if not o.get("is_deleted")]
                    if k == "items":
                        rows = [o for o in rows if o["id"] in active]
                    if k == "notes":
                        rows = [o for o in rows if o["item_id"] in active]
                    if k in types or everything:
                        out[k] = [public(o) for o in rows]
            else:
                self.incremental_reads += 1
                since = int(token[1:])
                out = {"sync_token": "v%d" % self.version, "full_sync": False}
                for k in LISTS:
                    if k in types or everything:
                        out[k] = [public(o) for o in getattr(self, k) if o.get("_v", 0) > since]
            if "user_plan_limits" in types or everything:
                out["user_plan_limits"] = {"current": dict(self.plan), "next": None}
            if "user" in types or everything:
                out["user"] = dict(self.user)
            if "user_settings" in types or everything:
                out["user_settings"] = dict(self.user_settings)
            if "locations" in types or everything:
                out["locations"] = list(self.locations)
            if "view_options" in types or everything:
                out["view_options"] = list(self.view_options)
            if "stats" in types or everything:
                out["stats"] = self.stats()
            return out

    # ------------------------------------------------ REST

    def completed(self, q, by="completion"):
        with self.lock:
            since, until = parse(q["since"]), parse(q["until"])
            self.completed_requests.append((since, until))
            if until - since > timedelta(days=92 if by == "completion" else 42):
                return 400, {"error": "The date range cannot exceed the limit", "error_tag": "INVALID_DATE_RANGE"}

            def when(i):
                if by == "completion":
                    return parse(i["completed_at"]) if i["completed_at"] else None
                d = (i.get("due") or {}).get("date")
                return datetime.combine(date.fromisoformat(d[:10]), datetime.min.time(), timezone.utc) if d else None
            rows = [public(i) for i in self.items if i["checked"] and not i["is_deleted"] and when(i)
                    and since <= when(i) < until
                    and (not q.get("project_id") or i["project_id"] == q["project_id"])]
            start = int(q.get("cursor") or 0)
            limit = int(q.get("limit") or 50)
            page = rows[start:start + limit]
            nxt = str(start + limit) if start + limit < len(rows) else None
            return 200, {"items": page, "next_cursor": nxt}

    def matches(self, it, term):
        """One term of the filter language (the subset this mock knows)."""
        term = term.strip()
        neg = term.startswith("!")
        if neg:
            term = term[1:].strip()
        low = term.lower()
        d = (it.get("due") or {}).get("date")
        today = date.today().isoformat()
        if low == "all":
            ok = True
        elif low == "today":
            ok = bool(d) and d[:10] == today
        elif low == "overdue":
            ok = bool(d) and d[:10] < today
        elif low == "no date":
            ok = not d
        elif re.fullmatch(r"p[1-4]", low):
            ok = it["priority"] == 5 - int(low[1])
        elif low.startswith("@"):
            ok = term[1:].lower() in [x.lower() for x in it["labels"]]
        elif low.startswith("#"):
            name = term.lstrip("#").lower()
            ok = any(p["id"] == it["project_id"] and p["name"].lower() == name for p in self.projects)
        elif low.startswith("search:"):
            ok = term[7:].strip().lower() in it["content"].lower()
        elif low.startswith("assigned to:"):
            who = term[12:].strip().lower()
            ok = it.get("responsible_uid") == (ME if who == "me" else who)
        else:
            raise ValueError("unknown filter term " + term)
        return ok != neg

    def filter_tasks(self, query):
        out = []
        for it in self.items:
            if it["checked"] or it["is_deleted"]:
                continue
            if any(all(self.matches(it, t) for t in alt.split("&")) for alt in query.split("|")):
                out.append(public(it))
        return out

    def quick_add(self, body):
        text = body.get("text") or ""
        if not text.strip():
            return 400, {"error": "text is required"}
        desc = ""
        if " // " in text:
            text, desc = text.split(" // ", 1)
        words, project, section, labels, prio, due, deadline = [], None, None, [], 1, None, None
        for w in text.split():
            low = w.lower()
            if w.startswith("#"):
                hit = [p for p in self.projects if p["name"].lower() == w[1:].lower() and not p["is_deleted"]]
                if hit:
                    project = hit[0]
                    continue
            if w.startswith("/") and project:
                hit = [s for s in self.sections if s["project_id"] == project["id"] and s["name"].lower() == w[1:].lower()]
                if hit:
                    section = hit[0]
                    continue
            if w.startswith("@") and len(w) > 1:
                labels.append(w[1:])
                continue
            if re.fullmatch(r"p[1-4]", low):
                prio = 5 - int(low[1])
                continue
            if low in ("today", "tomorrow") or re.fullmatch(r"\d{4}-\d{2}-\d{2}", low):
                due = {"string": low}
                continue
            if w.startswith("{") and w.endswith("}"):
                if not self.plan["deadlines"]:
                    return 403, {"error": "Deadlines are a premium only feature", "error_tag": "PREMIUM_ONLY"}
                deadline = {"date": w[1:-1]}
                continue
            words.append(w)
        args = {"content": " ".join(words), "description": desc, "project_id": (project or self.projects[0])["id"],
                "section_id": section["id"] if section else None, "labels": labels, "priority": prio, "due": due,
                "deadline": deadline}
        with self.lock:
            it = self.item(args, self.new_id("6Q"))
            self.items.append(it)
            self.touch(it)
            self.event("item", it, "added")
            if body.get("note"):
                self.notes.append({"id": self.new_id("6N"), "item_id": it["id"], "content": body["note"], "is_deleted": False,
                                   "posted_at": stamp(), "posted_uid": ME, "file_attachment": None, "_v": self.version})
        out = public(it)
        if body.get("meta"):
            out["meta"] = {"project": project and project["name"], "labels": labels, "due": due}
        return 200, out

    def stats(self):
        done = [i for i in self.items if i["checked"] and not i["is_deleted"]]
        return {"karma": self.user["karma"], "karma_trend": self.user["karma_trend"], "completed_count": len(done),
                "goals": {"daily_goal": self.user["daily_goal"], "weekly_goal": self.user["weekly_goal"],
                          "current_daily_streak": {"count": 1}, "max_daily_streak": {"count": 3}},
                "days_items": [{"date": date.today().isoformat(), "total_completed": len(done)}],
                "week_items": [{"from": (date.today() - timedelta(days=6)).isoformat(), "total_completed": len(done)}]}

    def activities(self, q):
        days = self.plan.get("activity_log_limit")
        if q.get("date_from") and days and parse(q["date_from"]) < datetime.now(timezone.utc) - timedelta(days=days):
            return 403, {"error": "Activity older than the plan's history limit is a premium only feature",
                         "error_code": 32, "error_tag": "PREMIUM_ONLY", "http_code": 403}  # observed live, 2026-09-30
        rows = list(self.events)
        types = {"item", "note", "project", "section"}
        if q.get("object_type"):
            if q["object_type"] not in types:
                return 400, {"error": "invalid object_type"}
            rows = [e for e in rows if e["object_type"] == q["object_type"]]
        if q.get("object_id"):
            rows = [e for e in rows if e["object_id"] == q["object_id"] or
                    (q.get("include_child_objects") == "true" and e["parent_item_id"] == q["object_id"])]
        if q.get("parent_project_id"):
            rows = [e for e in rows if e["parent_project_id"] == q["parent_project_id"] or
                    (e["object_type"] == "project" and e["object_id"] == q["parent_project_id"])]
        if q.get("parent_item_id"):
            rows = [e for e in rows if e["parent_item_id"] == q["parent_item_id"] or
                    (e["object_type"] == "item" and e["object_id"] == q["parent_item_id"])]
        if q.get("event_type"):
            et = q["event_type"]
            rows = [e for e in rows if (e["event_type"] != et[1:] if et.startswith("!") else e["event_type"] == et)]
        if q.get("object_event_types"):
            wanted = q["object_event_types"] if isinstance(q["object_event_types"], list) else [q["object_event_types"]]
            rows = [e for e in rows if any((not t.split(":")[0] or t.split(":")[0] == e["object_type"]) and
                                           (not t.split(":")[1] or t.split(":")[1] == e["event_type"]) for t in wanted)]
        if q.get("date_from"):
            rows = [e for e in rows if parse(e["event_date"]) >= parse(q["date_from"])]
        if q.get("date_to"):
            rows = [e for e in rows if parse(e["event_date"]) < parse(q["date_to"])]
        if q.get("initiator_id_null") == "true":
            rows = [e for e in rows if not e["initiator_id"]]
        if q.get("initiator_id"):
            rows = [e for e in rows if str(e["initiator_id"]) == str(q["initiator_id"])]
        rows = list(reversed(rows))
        if q.get("annotate_parents") == "true":
            names = {p["id"]: p["name"] for p in self.projects}
            rows = [dict(e, extra_data=dict(e["extra_data"], parent_project_name=names.get(e["parent_project_id"])))
                    if e["object_type"] != "project" else e for e in rows]
        start, limit = int(q.get("cursor") or 0), int(q.get("limit") or 50)
        page = rows[start:start + limit]
        return 200, {"results": page, "next_cursor": str(start + limit) if start + limit < len(rows) else None}

    def template_csv(self, project_id):
        rows = ["TYPE,CONTENT,DESCRIPTION,PRIORITY,INDENT,AUTHOR,RESPONSIBLE,DATE,DATE_LANG,TIMEZONE,DURATION,DURATION_UNIT,DEADLINE,DEADLINE_LANG"]
        for s in self.sections:
            if s["project_id"] == project_id and not s["is_deleted"]:
                rows.append("section,%s,,,1,,,,,,,,," % s["name"])
        for i in self.items:
            if i["project_id"] == project_id and not i["is_deleted"] and not i["checked"]:
                rows.append("task,%s,%s,%d,1,,,,,,,,," % (i["content"], i.get("description", ""), 5 - i["priority"]))
        return "\n".join(rows) + "\n"

    def import_csv(self, project_id, text):
        n = 0
        with self.lock:
            for row in text.split("\n")[1:]:
                cells = row.split(",")
                if len(cells) > 1 and cells[0] == "task":
                    it = self.item({"content": cells[1], "description": cells[2] if len(cells) > 2 else "", "project_id": project_id}, self.new_id("6T"))
                    self.items.append(it)
                    self.touch(it)
                    n += 1
        return n


STORE = Store()


def parse_multipart(body, ctype):
    """The fields and files of a multipart/form-data body -> (fields, {field: (filename, bytes)})."""
    boundary = ctype.split("boundary=", 1)[1].encode()
    fields, files = {}, {}
    for part in body.split(b"--" + boundary)[1:]:
        if part.strip() in (b"", b"--"):
            continue
        head, _, content = part.partition(b"\r\n\r\n")
        content = content[:-2] if content.endswith(b"\r\n") else content
        m = re.search(rb'name="([^"]+)"', head)
        fn = re.search(rb'filename="([^"]+)"', head)
        if not m:
            continue
        if fn:
            files[m.group(1).decode()] = (fn.group(1).decode(), content)
        else:
            fields[m.group(1).decode()] = content.decode("utf-8")
    return fields, files


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else (obj.encode() if isinstance(obj, str) else json.dumps(obj).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.headers.get("Authorization") == "Bearer rate-limited":
            self.send_response(429)
            self.send_header("Retry-After", "30")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.reply(401, {"error": "Unauthorized", "error_tag": "AUTH_INVALID_TOKEN"})
            return False
        return True

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json_body(self):
        raw = self.body()
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return None

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith("/cdn/"):  # the backup download's redirect target: no token must arrive here
            STORE.cdn_requests.append((u.path, "Authorization" in self.headers))
            return self.reply(200, b"PK\x03\x04mock-backup", "application/zip")
        if not self.authorized():
            return
        STORE.rest_requests.append(("POST", u.path))
        if u.path == "/api/v1/sync":
            if self.headers.get("Content-Type") != "application/x-www-form-urlencoded":
                return self.reply(400, {"error": "Expected a form body"})
            form = urllib.parse.parse_qs(self.body().decode("utf-8"))
            if "commands" in form:
                commands = json.loads(form["commands"][0])
                if len(commands) > 100:
                    return self.reply(400, {"error": "Too many commands", "error_tag": "MAX_COMMANDS_LIMIT_REACHED"})
                return self.reply(200, STORE.write(commands))
            if "resource_types" in form and form.get("sync_token"):
                return self.reply(200, STORE.read(json.loads(form["resource_types"][0]), form["sync_token"][0]))
            return self.reply(400, {"error": "Missing parameters"})
        path = u.path[len("/api/v1"):]
        ctype = self.headers.get("Content-Type") or ""
        if path == "/tasks/quick":
            body = self.json_body()
            if body is None or not ctype.startswith("application/json"):
                return self.reply(400, {"error": "Expected a JSON body"})
            return self.reply(*STORE.quick_add(body))
        if path == "/uploads":
            blob = self.body()
            name = self.headers.get("X-File-Name") or "upload.bin"
            if len(blob) > STORE.plan["upload_limit_mb"] * 1024 * 1024:
                return self.reply(413, {"error": "File too large"})
            fa = {"file_name": name, "file_size": len(blob), "file_type": ctype, "resource_type": "file",
                  "file_url": "https://files.todoist.com/mock/%s" % name, "upload_state": "completed"}
            STORE.uploads.append(fa)
            return self.reply(200, fa)
        m = re.fullmatch(r"/comments/([^/]+)/reactions(/remove)?", path)
        if m:
            body = self.json_body() or {}
            with STORE.lock:
                n = next((x for x in STORE.notes + STORE.project_notes if x["id"] == m.group(1) and not x["is_deleted"]), None)
                if not n:
                    return self.reply(404, {"error": "Comment not found"})
                reactions = dict(n.get("reactions") or {})
                if m.group(2):
                    reactions.pop(body.get("reaction"), None)
                else:
                    reactions[body.get("reaction")] = [ME]
                n["reactions"] = reactions or None
                STORE.touch(n)
            return self.reply(200, public(n))
        if path == "/templates/import_into_project_from_template_id":
            body = self.json_body() or {}
            with STORE.lock:
                it = STORE.item({"content": "From template " + str(body.get("template_id")), "project_id": body.get("project_id")}, STORE.new_id("6T"))
                STORE.items.append(it)
                STORE.touch(it)
            return self.reply(200, {"status": "ok"})
        if path in ("/templates/import_into_project_from_file", "/templates/create_project_from_file"):
            if not ctype.startswith("multipart/form-data"):
                return self.reply(400, {"error": "Expected multipart/form-data"})
            fields, files = parse_multipart(self.body(), ctype)
            if "file" not in files:
                return self.reply(400, {"error": "file is required"})
            if path.endswith("create_project_from_file"):
                with STORE.lock:
                    pid = STORE.run("project_add", {"name": fields.get("name")}, "6P")
                    STORE.touch(STORE.projects[-1])
            else:
                pid = fields.get("project_id")
            n = STORE.import_csv(pid, files["file"][1].decode("utf-8"))
            return self.reply(200, {"status": "ok", "project_id": pid, "imported": n})
        if path == "/payments/get_subscription_info":
            return self.reply(200, {"plan": STORE.plan["plan_name"], "status": "active"})
        m = re.fullmatch(r"/projects/([^/]+)/join", path)
        if m:
            return self.reply(403, {"error": "Only usable by a workspace user", "error_tag": "FORBIDDEN"})
        m = re.fullmatch(r"/projects/([^/]+)/insights/health/analyze", path)
        if m:
            return self.reply(403, {"error": "Project Health is only available for workspace projects", "error_tag": "FORBIDDEN"})
        if path.startswith("/workspaces"):
            return self.reply(403, {"error": "Workspaces are a Teams feature", "error_tag": "FORBIDDEN"})
        self.reply(404, {"error": "Not found"})

    def do_PUT(self):
        if not self.authorized():
            return
        u = urllib.parse.urlparse(self.path)
        path = u.path[len("/api/v1"):]
        STORE.rest_requests.append(("PUT", u.path))
        if path == "/emails":
            body = self.json_body() or {}
            key = "%s:%s" % (body.get("obj_type"), body.get("obj_id"))
            STORE.emails[key] = "%s.%s@todoist.net" % (body.get("obj_type"), body.get("obj_id"))
            return self.reply(200, {"email": STORE.emails[key]})
        if path == "/notification_setting":
            body = self.json_body() or {}
            return self.reply(200, {body.get("notification_type"): {body.get("service"): not body.get("dont_notify")}})
        if path.startswith("/workspaces"):
            return self.reply(403, {"error": "Workspaces are a Teams feature", "error_tag": "FORBIDDEN"})
        self.reply(404, {"error": "Not found"})

    def do_DELETE(self):
        if not self.authorized():
            return
        u = urllib.parse.urlparse(self.path)
        path = u.path[len("/api/v1"):]
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        STORE.rest_requests.append(("DELETE", u.path))
        if path == "/uploads":
            STORE.uploads = [f for f in STORE.uploads if f["file_url"] != q.get("file_url")]
            return self.reply(200, "ok")
        if path == "/emails":
            STORE.emails.pop("%s:%s" % (q.get("obj_type"), q.get("obj_id")), None)
            return self.reply(200, "ok")
        if path.startswith(("/folders/", "/workspaces")):
            return self.reply(403, {"error": "Workspaces are a Teams feature", "error_tag": "FORBIDDEN"})
        self.reply(404, {"error": "Not found"})

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith("/cdn/"):  # the backup download's redirect target: no token must arrive here
            STORE.cdn_requests.append((u.path, "Authorization" in self.headers))
            return self.reply(200, b"PK\x03\x04mock-backup", "application/zip")
        if not self.authorized():
            return
        q = {k: (v[0] if len(v) == 1 else v) for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path[len("/api/v1"):]
        STORE.rest_requests.append(("GET", u.path))

        def page(rows, key="results"):
            start, limit = int(q.get("cursor") or 0), int(q.get("limit") or 50)
            nxt = str(start + limit) if start + limit < len(rows) else None
            return self.reply(200, {key: rows[start:start + limit], "next_cursor": nxt})

        if path in ("/tasks/completed/by_completion_date", "/tasks/completed/by_due_date"):
            if "since" not in q or "until" not in q:
                return self.reply(400, {"error": "since and until are required"})
            code, obj = STORE.completed(q, "completion" if path.endswith("completion_date") else "due")
            return self.reply(code, obj)
        if path == "/tasks/filter":
            try:
                return page(STORE.filter_tasks(q.get("query") or ""))
            except ValueError as e:
                return self.reply(400, {"error": str(e), "error_tag": "INVALID_QUERY"})
        if path == "/tasks/completed/stats":
            return self.reply(200, STORE.stats())
        if path == "/tasks":
            rows = [public(i) for i in STORE.items if not i["checked"] and not i["is_deleted"]
                    and (not q.get("project_id") or i["project_id"] == q["project_id"])]
            return page(rows)
        m = re.fullmatch(r"/tasks/([^/]+)", path)
        if m:
            it = next((i for i in STORE.items if i["id"] == m.group(1) and not i["is_deleted"]), None)
            return self.reply(200, public(it)) if it else self.reply(404, {"error": "Task not found"})
        if path == "/projects":
            return page([public(p) for p in STORE.projects if not p["is_deleted"] and not p["is_archived"]])
        if path == "/projects/archived":
            return page([public(p) for p in STORE.projects if not p["is_deleted"] and p["is_archived"]])
        if path == "/projects/search":
            return page([public(p) for p in STORE.projects if not p["is_deleted"] and (q.get("query") or "").lower() in p["name"].lower()])
        if path == "/projects/permissions":
            return self.reply(200, {"roles": {"ADMIN": ["everything"], "READ_WRITE": ["tasks"]}})
        m = re.fullmatch(r"/projects/([^/]+)/collaborators", path)
        if m:
            allowed = {c["user_id"] for c in STORE.collaborator_states if c["project_id"] == m.group(1) and not c["is_deleted"]}
            return page([public(c) for c in STORE.collaborators if c["id"] in allowed])
        m = re.fullmatch(r"/projects/([^/]+)/insights/(health|health/context)", path)
        if m:
            return self.reply(403, {"error": "Project Health is only available for workspace projects", "error_tag": "FORBIDDEN"})
        m = re.fullmatch(r"/projects/([^/]+)/insights/activity_stats", path)
        if m:
            return self.reply(403, {"error": "Project insights are not available on your current plan", "error_tag": "FORBIDDEN"})
        m = re.fullmatch(r"/projects/([^/]+)", path)
        if m:
            p = next((x for x in STORE.projects if x["id"] == m.group(1) and not x["is_deleted"]), None)
            return self.reply(200, public(p)) if p else self.reply(404, {"error": "Project not found"})
        if path == "/sections":
            return page([public(s) for s in STORE.sections if not s["is_deleted"] and (not q.get("project_id") or s["project_id"] == q["project_id"])])
        if path == "/labels":
            return page([public(l) for l in STORE.labels if not l["is_deleted"]])
        if path == "/labels/shared":
            personal = {l["name"].lower() for l in STORE.labels if not l["is_deleted"]}
            names = sorted({x for i in STORE.items if not i["is_deleted"] for x in i["labels"]
                            if not (q.get("omit_personal") == "true" and x.lower() in personal)})
            return page(names)
        if path == "/comments":
            if q.get("task_id"):
                rows = [public(n) for n in STORE.notes if n["item_id"] == q["task_id"] and not n["is_deleted"]]
            else:
                rows = [public(n) for n in STORE.project_notes if n.get("project_id") == q.get("project_id") and not n["is_deleted"]]
            return page(rows)
        m = re.fullmatch(r"/comments/([^/]+)", path)
        if m:
            n = next((x for x in STORE.notes + STORE.project_notes if x["id"] == m.group(1) and not x["is_deleted"]), None)
            return self.reply(200, public(n)) if n else self.reply(404, {"error": "Comment not found"})
        if path == "/reminders":
            return page([public(r) for r in STORE.reminders if not r["is_deleted"] and r["type"] != "location"])
        if path == "/location_reminders":
            return page([public(r) for r in STORE.reminders if not r["is_deleted"] and r["type"] == "location"])
        if path == "/activities":
            return self.reply(*STORE.activities(q))
        if path == "/user":
            return self.reply(200, dict(STORE.user))  # observed live: the whole user object, tokens included
        if path == "/templates/file":
            return self.reply(200, STORE.template_csv(q.get("project_id")), "text/csv")
        if path == "/templates/url":
            return self.reply(200, {"file_url": "https://templates.todoist.com/mock/%s.csv" % q.get("project_id")})
        if path == "/backups":
            host = "http://%s:%d" % self.server.server_address
            return self.reply(200, [{"version": "2026-09-22 03:00", "url": host + "/api/v1/backups/download?file=b1.zip"}])
        if path == "/backups/download":
            self.send_response(302)
            self.send_header("Location", "http://%s:%d/cdn/%s" % (self.server.server_address + (q.get("file") or "x.zip",)))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        m = re.fullmatch(r"/id_mappings/([^/]+)/([^/]+)", path)
        if m:
            return self.reply(200, [{"old_id": x, "new_id": "v2_" + x} for x in m.group(2).split(",")])
        if path == "/workspaces":
            return self.reply(200, {"results": [], "next_cursor": None})
        if path.startswith(("/workspaces", "/folders")):
            return self.reply(403, {"error": "Workspaces are a Teams feature", "error_tag": "FORBIDDEN"})
        if path.startswith("/usage_billing/"):
            return self.reply(200, {"product": "automations", "credits": 0, "token": "must-be-masked"})
        self.reply(404, {"error": "Not found"})


def serve(port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    s = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
    print("mock Todoist API on http://127.0.0.1:%d/api/v1 (token %s)" % (s.server_address[1], TOKEN))
    threading.Event().wait()
