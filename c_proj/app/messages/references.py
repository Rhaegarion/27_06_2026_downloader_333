"""
Reference lookup for the New Message form.

The operator picks earlier messages that involved the same numbers (VOIP) or
email addresses (IP); each selection becomes a sentence appended to the
Reference field.

The matching rule is deliberately loose in both directions — a stored number
contains the current one, or the current one contains it — because numbers are
recorded with and without country codes and neither form is canonical.
"""

from sqlalchemy import or_, select

from app.extensions import db
from app.models.message import model_for

# Kept identical to the wording used by the existing application; the phrasing
# ends up in outgoing messages, so it is not ours to tidy.
REF_SENTENCE = (
    "Pls ref our earlier Msg no. {tc_no} dated. {wan_date} in respect of the "
    "{side} ({value}) on {category}({subject}). "
)
NO_REF_BOTH = "No Reference on the Calling No. and Called No."


def _parts(value):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def search(msg_type, filters, page_no=0, offset=25):
    """Mirrors the old /search_ref query: all criteria are ANDed, blanks skipped."""
    model = model_for(msg_type)
    q = select(model)

    def has(key):
        v = filters.get(key)
        return v not in (None, "", "None")

    if has("start_date"):
        q = q.where(model.Wan_Date >= filters["start_date"])
    if has("end_date"):
        q = q.where(model.Wan_Date <= filters["end_date"])
    if has("number") and msg_type == "voip":
        n = filters["number"]
        q = q.where(or_(model.Clg_No.contains(n), model.Cld_No.contains(n)))
    if has("calling_party"):
        q = q.where(model.Clg_Pty.contains(filters["calling_party"]))
    if has("called_party"):
        q = q.where(model.Cld_Pty.contains(filters["called_party"]))
    if has("category"):
        q = q.where(model.Category == filters["category"])
    if has("filter_value"):
        q = q.where(model.Filter_Value.contains(filters["filter_value"]))
    if has("language"):
        q = q.where(model.Language == filters["language"])
    if has("key_word"):
        clauses = []
        for word in _parts(filters["key_word"]):
            clauses.append(
                or_(model.Msg_Subject.contains(word), model.Msg_Gist.contains(word))
            )
        if clauses:
            q = q.where(or_(*clauses))

    q = q.order_by(model.Wan_Date.desc()).offset(page_no * offset).limit(offset)
    return list(db.session.execute(q).scalars())


def search_for_current(msg_type, numbers, parties, page_no=0, offset=25):
    """
    Candidate references for the message being written: any earlier message
    that touched one of its numbers (VOIP) or addresses (IP), on either side.
    """
    model = model_for(msg_type)
    clauses = []
    if msg_type == "voip":
        for n in numbers:
            clauses.append(model.Clg_No.contains(n))
            clauses.append(model.Cld_No.contains(n))
    for p in parties:
        clauses.append(model.Clg_Pty.contains(p))
        clauses.append(model.Cld_Pty.contains(p))
    if not clauses:
        return []
    q = (
        select(model)
        .where(or_(*clauses))
        .order_by(model.Wan_Date.desc())
        .offset(page_no * offset)
        .limit(offset)
    )
    return list(db.session.execute(q).scalars())


def build_reference_text(rows, current_numbers, current_parties, msg_type):
    """
    Turn the selected messages into reference sentences.

    A row is described as Calling or Called depending on which side of the
    CURRENT message the shared value sits on, not which side it occupied in
    the older message.
    """
    out = []
    for row in rows:
        stored = []
        if msg_type == "voip":
            stored += _parts(getattr(row, "Clg_No", "")) + _parts(getattr(row, "Cld_No", ""))
        stored += _parts(getattr(row, "Clg_Pty", "")) + _parts(getattr(row, "Cld_Pty", ""))

        matched = None
        side = None
        for value in current_numbers:
            if any(s and (s in value or value in s) for s in stored):
                matched, side = value, "Calling No."
                break
        if matched is None:
            for value in current_parties:
                if any(s and (s in value or value in s) for s in stored):
                    matched, side = value, "Called No."
                    break
        if matched is None:
            # Selected by hand from a free search rather than matched.
            matched = (getattr(row, "Clg_No", "") or
                       getattr(row, "Clg_Pty", "") or "")
            side = "Calling No."

        out.append(REF_SENTENCE.format(
            tc_no=getattr(row, "TC_No", "") or "",
            wan_date=getattr(row, "Wan_Date", "") or "",
            side=side,
            value=matched,
            category=getattr(row, "Category", "") or "",
            subject=getattr(row, "Msg_Subject", "") or "",
        ))
    return "".join(out)


def append_reference(existing, addition):
    """Append without repeating a sentence that is already present."""
    existing = str(existing or "")
    if not addition:
        return existing
    if addition.strip() and addition.strip() in existing:
        return existing
    if existing.strip() in ("", NO_REF_BOTH):
        return addition
    return existing + addition
