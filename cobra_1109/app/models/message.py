"""
voip_table and ip_table models.

The columns are declared from field_spec rather than typed out again, so the
spec stays the single source of truth and the two can't drift apart. Every
column is VARCHAR(255) except the four LONGTEXT ones.

Column names deliberately mirror the database exactly, including the
misspelling of `Utililization`. If that column is ever renamed in MySQL,
change it in field_spec and here together.
"""

from app.extensions import db
from app.messages.field_spec import VOIP_FIELDS, IP_FIELDS

LONGTEXT_COLUMNS = {"Msg_Subject", "Msg_Gist", "Msg_Ref", "Msg_Comments"}


def _columns(fields):
    """Build a dict of SQLAlchemy columns from a field spec list."""
    cols = {}
    for f in fields:
        if f.name in LONGTEXT_COLUMNS:
            col_type = db.Text(length=4294967295)   # LONGTEXT
        else:
            col_type = db.String(255)
        # Event_Id is the natural key for a call and is what the DB treats as
        # the primary identifier.
        cols[f.name] = db.Column(
            f.name, col_type, primary_key=(f.name == "Event_Id")
        )
    return cols


class MessageMixin:
    """Shared helpers for both message tables."""

    def apply(self, values):
        """Set only columns that actually exist on this table."""
        for key, val in values.items():
            if hasattr(self, key):
                setattr(self, key, val)
        return self

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


VoipMessage = type(
    "VoipMessage",
    (MessageMixin, db.Model),
    {"__tablename__": "voip_table", **_columns(VOIP_FIELDS)},
)

IpMessage = type(
    "IpMessage",
    (MessageMixin, db.Model),
    {"__tablename__": "ip_table", **_columns(IP_FIELDS)},
)


MODEL_FOR = {"voip": VoipMessage, "ip": IpMessage}


def model_for(msg_type):
    try:
        return MODEL_FOR[msg_type]
    except KeyError:
        raise ValueError(f"unknown message type: {msg_type!r}")
