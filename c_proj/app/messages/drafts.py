"""
Draft persistence and per-user table column preferences.

Drafts
------
The operator leaves the New Message form to pick references or write OSINT
notes and comes back expecting their half-filled message intact. The draft is
kept in the Flask session keyed by message type, so VOIP and IP drafts do not
overwrite each other and the draft survives a refresh or a stray back button.

It is deliberately NOT stored in the database: a draft is scratch state, and a
crashed browser should not leave rows behind for someone else to clean up.
Reset clears it.

Column preferences
------------------
Stored per user per page, so the operator's chosen columns follow them to any
machine. Kept in its own table rather than a JSON column on name_details —
that table is the login record and is read on every request.
"""

import json

from flask import session
from sqlalchemy import select

from app.extensions import db

DRAFT_KEY = "cobra_draft"


# --- drafts ---------------------------------------------------------------

def load_draft(msg_type):
    return (session.get(DRAFT_KEY) or {}).get(msg_type) or {}


def save_draft(msg_type, payload):
    drafts = dict(session.get(DRAFT_KEY) or {})
    drafts[msg_type] = payload
    session[DRAFT_KEY] = drafts
    session.modified = True
    return payload


def merge_draft(msg_type, changes):
    """Update part of the draft without discarding the rest."""
    current = dict(load_draft(msg_type))
    current.update(changes or {})
    return save_draft(msg_type, current)


def clear_draft(msg_type=None):
    if msg_type is None:
        session.pop(DRAFT_KEY, None)
    else:
        drafts = dict(session.get(DRAFT_KEY) or {})
        drafts.pop(msg_type, None)
        session[DRAFT_KEY] = drafts
    session.modified = True


# --- column preferences ---------------------------------------------------

class TablePreference(db.Model):
    __tablename__ = "user_table_prefs"

    NameID = db.Column(db.String(50), primary_key=True)
    Page = db.Column(db.String(50), primary_key=True)
    Columns = db.Column(db.Text)          # JSON list of column keys, in order
    Updated_At = db.Column(db.String(45))


# Column key -> heading, matching the existing Flet tables.
REFERENCE_COLUMNS = {
    "voip": [
        ("TC_No", "TC No."),
        ("Wan_Out_No", "WAN Out No"),
        ("Wan_Date", "Date"),
        ("Clg_No", "Clg_no"),
        ("Clg_Pty", "Clg_party"),
        ("Cld_No", "Cld_no"),
        ("Cld_Pty", "Cld_party"),
        ("Category", "Category"),
        ("Msg_Subject", "Subject"),
    ],
    "ip": [
        ("TC_No", "TC No."),
        ("Wan_Out_No", "WAN Out No"),
        ("Wan_Date", "Date"),
        ("Clg_Pty", "Clg Party"),
        ("Cld_Pty", "Cld Party"),
        ("Category", "Category"),
        ("Event_Id", "Msg ID"),
        ("Protocol", "Protocol"),
        ("Classification", "Classification"),
        ("Msg_Subject", "Message Subject"),
    ],
}

# Anything else the operator may choose to add.
EXTRA_COLUMNS = {
    "voip": [
        ("Event_Id", "Event ID"), ("Language", "Language"),
        ("Classification", "Classification"), ("Protocol", "Protocol"),
        ("Start_Time", "Start time"), ("Duration", "Duration"),
        ("Clg_Country", "Clg country"), ("Cld_Country", "Cld country"),
        ("Filter_Value", "Filter"), ("Link", "Link"),
        ("Lgd_By", "Logged by"), ("Prep_By", "Prepared by"),
    ],
    "ip": [
        ("Language", "Language"), ("Start_Time", "Start time"),
        ("Duration", "Duration"), ("BEPS_ID", "BEPS ID"),
        ("Filter_Value", "Filter"), ("Link", "Link"),
        ("Lgd_By", "Logged by"), ("Prep_By", "Prepared by"),
    ],
}


def available_columns(msg_type):
    """Default columns first, then the rest — labels resolved for display."""
    seen, out = set(), []
    for key, label in REFERENCE_COLUMNS[msg_type] + EXTRA_COLUMNS[msg_type]:
        if key not in seen:
            seen.add(key)
            out.append({"key": key, "label": label})
    return out


def default_columns(msg_type):
    return [k for k, _ in REFERENCE_COLUMNS[msg_type]]


def get_columns(name_id, page, msg_type):
    """The user's saved column order, or the default when they have none."""
    row = db.session.execute(
        select(TablePreference).where(
            TablePreference.NameID == name_id, TablePreference.Page == page
        )
    ).scalars().first()
    if row and row.Columns:
        try:
            saved = json.loads(row.Columns)
        except (TypeError, ValueError):
            saved = None
        if isinstance(saved, list) and saved:
            # Drop anything no longer offered, so a renamed column cannot
            # break the page for whoever had it selected.
            valid = {c["key"] for c in available_columns(msg_type)}
            kept = [c for c in saved if c in valid]
            if kept:
                return kept
    return default_columns(msg_type)


def set_columns(name_id, page, msg_type, columns):
    from datetime import datetime

    valid = {c["key"] for c in available_columns(msg_type)}
    kept = [c for c in (columns or []) if c in valid]
    if not kept:
        kept = default_columns(msg_type)

    row = db.session.execute(
        select(TablePreference).where(
            TablePreference.NameID == name_id, TablePreference.Page == page
        )
    ).scalars().first()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if row is None:
        row = TablePreference(NameID=name_id, Page=page)
        db.session.add(row)
    row.Columns = json.dumps(kept)
    row.Updated_At = now
    db.session.commit()
    return kept
