"""
Dropdown sources for the New Message form.

Four reference tables drive the selects, and three of them also carry
"addressee" text that gets folded into the addressing fields when the operator
picks a value:

    category.Addressee        -> Add_Info
    msg_language.Addressee    -> Extra_Add (display only)
    msg_country.Addressee_To  -> Add_To
    msg_country.Addressee_Info-> Add_Info

Several sources feed the same target, so addressees are appended and deduped
rather than overwritten. The fields stay editable, so anything the operator has
typed survives; re-selecting the same dropdown value will not duplicate an
addressee that is already present.

Classification / Uti_* have no reference table; their options come from the
values already present in voip_table.
"""

from sqlalchemy import select, distinct
from app.extensions import db


class Category(db.Model):
    __tablename__ = "category"
    Category = db.Column(db.String(255), primary_key=True)
    Cat_Desc = db.Column(db.String(255))      # shown in the dropdown
    Addressee = db.Column(db.String(255))     # appended to Add_Info


class MsgLanguage(db.Model):
    __tablename__ = "msg_language"
    Lan_Id = db.Column(db.String(3), primary_key=True)
    Language = db.Column(db.String(255))      # shown in the dropdown
    Addressee = db.Column(db.String(255))     # appended to the extra addressee field


class MsgCountry(db.Model):
    __tablename__ = "msg_country"
    Country_Code = db.Column(db.String(255), primary_key=True)
    Country = db.Column(db.String(255))       # shown in the dropdown
    Addressee_To = db.Column(db.String(255))  # appended to Add_To
    Addressee_Info = db.Column(db.String(255))  # appended to Add_Info


class MsgSystem(db.Model):
    __tablename__ = "msg_system"
    S_NO = db.Column(db.String(255), primary_key=True)
    Name = db.Column(db.String(255))          # shown in the dropdown
    # `Desc` is a reserved word in MySQL; SQLAlchemy quotes it, but the
    # attribute is renamed here so Python code isn't shadowing anything odd.
    Description = db.Column("Desc", db.String(255))


# --- dropdown option loaders ---------------------------------------------

def category_options():
    rows = db.session.execute(
        select(Category.Cat_Desc, Category.Category)
        .where(Category.Cat_Desc.isnot(None))
        .order_by(Category.Cat_Desc)
    ).all()
    return [{"value": r.Category, "label": r.Cat_Desc} for r in rows]


def language_options():
    rows = db.session.execute(
        select(MsgLanguage.Language, MsgLanguage.Lan_Id)
        .where(MsgLanguage.Language.isnot(None))
        .order_by(MsgLanguage.Language)
    ).all()
    return [{"value": r.Language, "label": r.Language} for r in rows]


def country_options():
    rows = db.session.execute(
        select(MsgCountry.Country)
        .where(MsgCountry.Country.isnot(None))
        .order_by(MsgCountry.Country)
    ).all()
    return [{"value": r.Country, "label": r.Country} for r in rows]


def system_options():
    rows = db.session.execute(
        select(MsgSystem.Name, MsgSystem.Description)
        .where(MsgSystem.Name.isnot(None))
        .order_by(MsgSystem.Name)
    ).all()
    return [{"value": r.Name, "label": r.Name, "desc": r.Description} for r in rows]


def distinct_values(model, column_name):
    """
    Options for fields with no reference table (Classification, Uti_*), taken
    from what already exists in the message table.
    """
    col = getattr(model, column_name)
    rows = db.session.execute(
        select(distinct(col)).where(col.isnot(None), col != "").order_by(col)
    ).scalars().all()
    return [{"value": v, "label": v} for v in rows if v.strip()]


# --- addressee cascade ----------------------------------------------------

def _split(text):
    if not text:
        return []
    return [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]


def merge_addressees(*sources):
    """
    Combine addressee strings, preserving order and dropping duplicates
    (case-insensitively, since the reference tables aren't consistent).
    """
    out, seen = [], set()
    for src in sources:
        for part in _split(src):
            key = part.upper()
            if key not in seen:
                seen.add(key)
                out.append(part)
    return ", ".join(out)


def append_addressees(current, *additions):
    """
    Append addressee values to whatever is already in the field.

    The addressing fields are operator-editable, so existing content — typed by
    hand or contributed by an earlier dropdown choice — is always kept. Dedup is
    still applied, otherwise re-selecting the same dropdown value would add the
    same addressee a second time.
    """
    return merge_addressees(current, *additions)


def addressees_for_category(category_value):
    cat = db.session.get(Category, category_value) if category_value else None
    return cat.Addressee if cat else ""


def addressees_for_country(country_value):
    if not country_value:
        return "", ""
    row = db.session.execute(
        select(MsgCountry).where(MsgCountry.Country == country_value)
    ).scalars().first()
    if not row:
        return "", ""
    return row.Addressee_To or "", row.Addressee_Info or ""


def addressees_for_language(language_value):
    if not language_value:
        return ""
    row = db.session.execute(
        select(MsgLanguage).where(MsgLanguage.Language == language_value)
    ).scalars().first()
    return (row.Addressee if row else "") or ""


def resolve_addressees(category_value=None, language_value=None,
                       country_value=None, current_to="", current_info="",
                       current_extra=""):
    """
    Fold the selected dropdown's addressees into the current field contents.

    Appends rather than replaces: the operator can edit these fields freely and
    nothing they have typed is discarded. Note this means switching a dropdown
    leaves the previous selection's addressee in place — that is intentional,
    and the operator removes it by hand if it no longer applies.
    """
    cat_info = addressees_for_category(category_value)
    ctry_to, ctry_info = addressees_for_country(country_value)
    lang_extra = addressees_for_language(language_value)

    return {
        "Add_To": append_addressees(current_to, ctry_to),
        "Add_Info": append_addressees(current_info, cat_info, ctry_info),
        # Display-only: shown on the form and carried into the Word document,
        # but not a column on either message table.
        "Extra_Add": append_addressees(current_extra, lang_extra),
    }


# --- logger identity ------------------------------------------------------
# Lgd_By exists in three forms and they are not interchangeable:
#   Lgd_By        the NameID            -> the database column
#   Loggers_Name  "Name,Rank"           -> the database column
#   logger_final  "Sh. Name,Rank"       -> the Word document only
# Several loggers are joined with "/" in all three.

HONORIFIC = {"Male": "Sh.", "Female": "Ms."}


def logger_forms(name_id):
    """
    The three renderings of one logger. Returns None when the acronym is not
    in name_details, so the caller can warn rather than silently writing a
    half-filled name.
    """
    from app.models.user import User

    if not name_id:
        return None
    user = db.session.get(User, str(name_id).strip().upper())
    if user is None:
        return None

    name_rank = user.Name or ""
    if user.Rank:
        name_rank = f"{name_rank},{user.Rank}"

    honorific = HONORIFIC.get((user.Gender or "").strip())
    final = f"{honorific} {name_rank}" if honorific else name_rank

    return {
        "NameID": user.NameID,
        "Name": user.Name or "",
        "loggers_name": name_rank,
        "logger_final": final,
    }


def join_logger_forms(entries, separator="/"):
    """Combine several loggers into the three joined strings."""
    entries = [e for e in entries if e]
    if not entries:
        return {"Lgd_By": "NIL", "Loggers_Name": "NIL", "logger_final": "NIL"}
    return {
        "Lgd_By": separator.join(e["NameID"] for e in entries),
        "Loggers_Name": separator.join(e["loggers_name"] for e in entries),
        "logger_final": separator.join(e["logger_final"] for e in entries),
    }
