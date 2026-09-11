"""
Message number allocation.

Numbers restart at 1 each calendar month. Allocation has to be safe when
several operators press Save at the same moment, so the database enforces
uniqueness and a losing insert is retried rather than the application trying
to check-then-write (which races).

Requires this one-off migration:

    ALTER TABLE msg_no_generator
      ADD COLUMN period CHAR(7) NOT NULL AFTER dated,
      ADD UNIQUE KEY uq_period_msgno (period, msgno);
    UPDATE msg_no_generator SET period = LEFT(dated, 7);
"""

import time
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db


class MsgNoTaken(Exception):
    """A manually chosen number is already used this period."""


class MsgNoUnavailable(Exception):
    """Allocation kept losing races; almost certainly a deadlock or outage."""


class MsgNoGenerator(db.Model):
    __tablename__ = "msg_no_generator"
    ID_Main = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dated = db.Column(db.String(45))
    period = db.Column(db.String(7), nullable=False)
    msgno = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("period", "msgno", name="uq_period_msgno"),
    )


def period_for(on_date=None):
    return (on_date or date.today()).strftime("%Y-%m")


def peek_next(on_date=None):
    """
    The number that would probably be allocated next. For display only — it is
    not reserved, and may differ from what Save actually assigns if someone
    else saves first. Never write this value to a message row.
    """
    p = period_for(on_date)
    current = db.session.execute(
        select(func.max(MsgNoGenerator.msgno)).where(MsgNoGenerator.period == p)
    ).scalar()
    return (current or 0) + 1


def allocate(on_date=None, manual=None, retries=12):
    """
    Reserve and return a message number.

    Two statements and a UNIQUE key rather than INSERT..SELECT: the latter takes
    a bulk-insert auto-increment lock and behaves differently across MySQL 5.7,
    8.x and MariaDB depending on innodb_autoinc_lock_mode. This form is portable
    and each office runs its own server, so portability matters.

    Caller must commit. The number is only truly reserved once that happens.
    """
    on_date = on_date or date.today()
    p = period_for(on_date)
    dated = on_date.strftime("%Y-%m-%d")

    for attempt in range(retries):
        try:
            with db.session.begin_nested():
                if manual is not None:
                    candidate = int(manual)
                else:
                    current = db.session.execute(
                        select(func.max(MsgNoGenerator.msgno))
                        .where(MsgNoGenerator.period == p)
                    ).scalar()
                    candidate = (current or 0) + 1

                db.session.add(
                    MsgNoGenerator(dated=dated, period=p, msgno=candidate)
                )
            return candidate
        except IntegrityError:
            if manual is not None:
                raise MsgNoTaken(
                    f"Message number {manual} is already used this month."
                )
            time.sleep(0.004 * (attempt + 1))

    raise MsgNoUnavailable(
        "Could not reserve a message number. Try again in a moment."
    )
