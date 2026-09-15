"""
New Message page.

Two tabs (VOIP and IP) over separate tables. Flow:

  1. Operator picks the recorder system and pastes the intercept folder path.
  2. "Extract" reads the JSON or XML file and fills the auto-populated fields.
  3. Operator completes the rest; dropdowns append addressees as they go.
  4. "Save" allocates a message number, writes the row, then copies the
     material and generates the document.

Ordering in save_message() is deliberate: the database row is committed before
any filesystem work. A failed copy leaves a recoverable message; a failed
insert after copying would leave orphaned folders nobody can identify.
"""

from datetime import date, datetime

from flask import (Blueprint, abort, render_template, request, jsonify,
                   url_for, redirect)
from flask_login import login_required, current_user
from sqlalchemy import select, or_

from app.extensions import db
from app.models.message import model_for
from app.models.user import User
from app.messages import msgno as msgno_svc
from app.messages import lookups, parser, paths
from app.messages.docx_generator import generate_document, DocumentError
from app.messages.link_resolver import resolve_link
from app.messages import drafts as draft_store
from app.messages import references as refs
from app.messages.word_dict import build_word_dict, ROW_MSG_TYPE
from app.messages.field_spec import (fields_for, defaults, grouped,
                                     G_SOURCE, USER, AUTO)
from app.messages.file_ops import copy_intercept_folder, FileOpsError

messages_bp = Blueprint("messages", __name__, url_prefix="/message")

MSG_TYPES = ("voip", "ip")


def _check_type(msg_type):
    """Unknown tab names are a 404, not a server error."""
    if msg_type not in MSG_TYPES:
        abort(404)
    return msg_type


def _dropdowns(msg_type):
    model = model_for(msg_type)
    users = list(db.session.execute(select(User).order_by(User.NameID)).scalars())
    # Lgd_By, Txbd_By and Prep_By all store the 3-letter NameID.
    # Loggers_Name is the only place a full name is written, resolved
    # server-side from Lgd_By.
    by_id = [{"value": u.NameID, "label": f"{u.NameID} — {u.Name}"} for u in users]
    return {
        "Txbd_By": by_id,
        "Lgd_By": by_id,
        "Prep_By": by_id,
        "Category": lookups.category_options(),
        "Language": lookups.language_options(),
        "Clg_Country": lookups.country_options(),
        "Cld_Country": lookups.country_options(),
        "System": lookups.system_options(),
        "Classification": lookups.distinct_values(model, "Classification"),
    }


@messages_bp.route("/new")
@login_required
def new_redirect():
    return redirect(url_for("messages.new", msg_type="voip"))


@messages_bp.route("/new/<msg_type>")
@login_required
def new(msg_type):
    _check_type(msg_type)
    all_groups = grouped(msg_type, sources=("json", "user", "auto"))
    source_fields = next(
        (items for g, items in all_groups if g == G_SOURCE), []
    )
    return render_template(
        "messages/new.html",
        msg_type=msg_type,
        draft=draft_store.load_draft(msg_type),
        groups=all_groups,
        source_fields=source_fields,
        dropdowns=_dropdowns(msg_type),
        field_defaults=defaults(msg_type),
        next_msgno=msgno_svc.peek_next(),
        user=current_user,
    )


# Fields that must be present before a message can be saved. Checked server
# side as well as in the browser, since the browser check is only a courtesy.
REQUIRED_FIELDS = {
    "voip": [("System", "System"), ("Classification", "Classification"),
             ("Prep_By", "Prepared By"), ("Msg_Subject", "Subject")],
    "ip": [("System", "System"), ("Classification", "Classification"),
           ("Prep_By", "Prepared By"), ("Msg_Subject", "Subject"),
           ("Txbd_By", "Transcribed By"), ("BEPS_ID", "BEPS ID")],
}


def missing_required(msg_type, values, checkbox_ok=True):
    missing = [label for key, label in REQUIRED_FIELDS[msg_type]
               if not str(values.get(key) or "").strip()]
    if msg_type == "ip" and not checkbox_ok:
        missing.append("BEPS confirmation")
    return missing


@messages_bp.route("/api/validate", methods=["POST"])
@login_required
def validate():
    """Checked before the message-number dialog, so the operator is not asked
    to confirm a number for a message that cannot be saved."""
    d = request.get_json(silent=True) or {}
    msg_type = d.get("msg_type", "voip")
    if msg_type not in MSG_TYPES:
        return jsonify({"ok": False, "error": "Unknown message type."}), 400
    missing = missing_required(msg_type, d.get("values") or {},
                               checkbox_ok=bool(d.get("beps_checked", True)))
    return jsonify({"ok": not missing, "missing": missing})


@messages_bp.route("/api/extract", methods=["POST"])
@login_required
def extract():
    """Read the data file and return the values it supplies."""
    data = request.get_json(silent=True) or {}
    msg_type = data.get("msg_type", "voip")
    folder = data.get("folder_path", "")
    system = data.get("system", "")

    if msg_type not in MSG_TYPES:
        return jsonify({"ok": False, "error": "Unknown message type."}), 400
    try:
        kind = paths.file_kind_for_system(system)
        info = paths.parse_source_path(folder, kind)
    except paths.PathError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # Refuse early if this call has already been processed. Event IDs may be
    # comma-separated when several calls were handled together, so each one is
    # checked individually rather than comparing the combined string.
    dupe = _find_existing(msg_type, info["event_id"])
    if dupe:
        return jsonify({
            "ok": False,
            "error": f"Event ID {info['event_id']} has already been processed "
                     f"as message {dupe or 'unknown'}.",
        }), 409

    try:
        parsed = parser.parse_file(info["data_file"], msg_type, kind)
    except parser.ParseError as e:
        return jsonify({"ok": False, "error": str(e),
                        "detail": info["data_file"]}), 400

    if not str(parsed.get("Event_Id") or "").strip():
        parsed["Event_Id"] = info["event_id"]

    # Resolve the link from every MAC in the capture, by priority.
    macs = parsed.pop("_macs", [])
    link_name, matched_mac = resolve_link(macs)
    parsed["Link"] = link_name
    parsed["MAC_Add"] = matched_mac

    # Several captures can be combined into one message, so merge into what
    # the form already holds instead of replacing it.
    current = data.get("current") or {}
    merged = parser.accumulate(current, parsed)

    # Loggers accumulate too: each folder contributes one, joined with "/".
    existing_ids = [p for p in str(current.get("Lgd_By") or "").split("/") if p.strip()]
    if info["lgd_by"] not in existing_ids:
        existing_ids.append(info["lgd_by"])
    forms = [lookups.logger_forms(nid) for nid in existing_ids]
    logger_found = all(f is not None for f in forms)
    joined = lookups.join_logger_forms(forms)
    merged["Lgd_By"] = joined["Lgd_By"]
    merged["Loggers_Name"] = joined["Loggers_Name"]

    auto = dict(defaults(msg_type))
    auto["Prep_By"] = current_user.NameID
    auto["Wan_Date"] = date.today().strftime("%Y-%m-%d")
    auto["Msg_Type"] = ROW_MSG_TYPE.get(msg_type, msg_type.upper())

    return jsonify({
        "ok": True,
        "extracted": merged,
        "auto": auto,
        "logger_final": joined["logger_final"],
        "info": {
            "file_kind": kind,
            "data_file": info["data_file"],
            "source_folder": info["source_folder"],
            "logger_found": logger_found,
            "logger_id": info["lgd_by"],
            "link": link_name,
            "event_count": len([e for e in str(merged.get("Event_Id") or "").split(",") if e.strip()]),
        },
    })


def _find_existing(msg_type, event_id):
    """
    Has any part of this Event ID been processed before?

    Stored Event_Id may be a comma-separated group, so a plain equality check
    would miss a call that was previously saved as part of a batch.
    """
    model = model_for(msg_type)
    parts = [p.strip() for p in str(event_id).split(",") if p.strip()]
    if not parts:
        return None
    clauses = []
    for part in parts:
        clauses.append(model.Event_Id == part)
        clauses.append(model.Event_Id.like(f"{part},%"))
        clauses.append(model.Event_Id.like(f"%,{part}"))
        clauses.append(model.Event_Id.like(f"%,{part},%"))
    row = db.session.execute(
        select(model).where(or_(*clauses)).limit(1)
    ).scalars().first()
    return row.TC_No if row else None


@messages_bp.route("/api/addressees", methods=["POST"])
@login_required
def addressees():
    """Recompute the addressing fields after a dropdown change."""
    d = request.get_json(silent=True) or {}
    return jsonify(lookups.resolve_addressees(
        category_value=d.get("Category"),
        language_value=d.get("Language"),
        country_value=d.get("Clg_Country"),
        current_to=d.get("Add_To", ""),
        current_info=d.get("Add_Info", ""),
        current_extra=d.get("Extra_Add", ""),
    ))


@messages_bp.route("/api/next-msgno")
@login_required
def next_msgno():
    return jsonify({"next": msgno_svc.peek_next()})


@messages_bp.route("/new/<msg_type>", methods=["POST"])
@login_required
def save_message(msg_type):
    if msg_type not in MSG_TYPES:
        return jsonify({"ok": False, "error": "Unknown message type."}), 400

    data = request.get_json(silent=True) or {}
    values = dict(data.get("values") or {})
    manual_no = (data.get("manual_msgno") or "").strip() or None
    source_folder = data.get("source_folder", "")
    extra_add = data.get("Extra_Add", "")

    model = model_for(msg_type)
    spec = fields_for(msg_type)
    names = {f.name for f in spec}

    event_id = (values.get("Event_Id") or "").strip()
    if not event_id:
        return jsonify({"ok": False, "error": "Event ID is missing. "
                                              "Extract the folder first."}), 400

    missing = missing_required(msg_type, values,
                               checkbox_ok=bool(data.get("beps_checked", True)))
    if missing:
        return jsonify({"ok": False,
                        "error": "Required fields are missing: " + ", ".join(missing),
                        "missing": missing}), 400

    existing = _find_existing(msg_type, event_id)
    if existing is not None:
        return jsonify({"ok": False,
                        "error": f"Already processed as message {existing}."}), 409

    # Server-side defaults and derived values. Never trusted from the client.
    values = {k: v for k, v in values.items() if k in names}
    for key, val in defaults(msg_type).items():
        if not str(values.get(key) or "").strip():
            values[key] = val

    values["Msg_Country"] = values.get("Clg_Country") or ""
    values["Msg_Type"] = ROW_MSG_TYPE.get(msg_type, msg_type.upper())
    if not str(values.get("Prep_By") or "").strip():
        values["Prep_By"] = current_user.NameID
    values["Time_Txbd"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values["Imp_Msg"] = "Yes" if data.get("Imp_Msg") else "No"
    if not str(values.get("Wan_Date") or "").strip():
        values["Wan_Date"] = date.today().strftime("%Y-%m-%d")

    today = date.today()

    # --- database first -------------------------------------------------
    try:
        number = msgno_svc.allocate(today, manual=manual_no)
        values["TC_No"] = str(number)
        db.session.add(model().apply(values))
        db.session.commit()
    except msgno_svc.MsgNoTaken as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 409
    except msgno_svc.MsgNoUnavailable as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 503
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False,
                        "error": "Could not save the message.",
                        "detail": str(e)}), 500

    # --- filesystem afterwards ------------------------------------------
    # The message is saved at this point. Anything below is reported as a
    # warning so the operator knows what still needs doing, but the row stands.
    warnings = []
    destination = paths.build_destination(number, today)
    try:
        result = copy_intercept_folder(source_folder, destination)
        if result["skipped"]:
            warnings.append(
                f"{len(result['skipped'])} item(s) already existed and were "
                "left untouched."
            )
    except FileOpsError as e:
        warnings.append(f"Material was not copied: {e}")

    doc_path = None
    try:
        word_data = build_word_dict(
            values, msg_type, today,
            extra={
                "Extra_Add": extra_add,
                "Osint": data.get("Osint", ""),
                "logger_final": data.get("logger_final", ""),
                "txbd_final": _person_final(values.get("Txbd_By")),
                "prep_final": _person_final(values.get("Prep_By")),
            },
        )
        doc_path = generate_document(word_data, destination, msg_type)
    except DocumentError as e:
        warnings.append(str(e))
    except Exception as e:
        warnings.append(f"The document could not be generated: {e}")

    # The message exists and the files are written, so the draft is spent.
    draft_store.clear_draft(msg_type)

    return jsonify({
        "ok": True,
        "msgno": number,
        "destination": destination,
        "document": doc_path,
        "warnings": warnings,
    })


def _person_final(name_id):
    """"Sh. Name,Rank" for the document; falls back to the raw value."""
    forms = lookups.logger_forms(name_id) if name_id else None
    return forms["logger_final"] if forms else (name_id or "")


# --- draft state ----------------------------------------------------------
# The operator leaves this form to pick references or write OSINT notes; the
# draft is held in the session so nothing they typed is lost on the way back.

@messages_bp.route("/api/draft/<msg_type>", methods=["GET", "POST"])
@login_required
def draft(msg_type):
    if msg_type not in MSG_TYPES:
        return jsonify({"ok": False, "error": "Unknown message type."}), 400
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        draft_store.save_draft(msg_type, payload)
        return jsonify({"ok": True})
    return jsonify({"ok": True, "draft": draft_store.load_draft(msg_type)})


@messages_bp.route("/api/draft/<msg_type>/clear", methods=["POST"])
@login_required
def draft_clear(msg_type):
    if msg_type not in MSG_TYPES:
        return jsonify({"ok": False, "error": "Unknown message type."}), 400
    draft_store.clear_draft(msg_type)
    return jsonify({"ok": True})


# --- references -----------------------------------------------------------

@messages_bp.route("/references/<msg_type>")
@login_required
def references_page(msg_type):
    _check_type(msg_type)
    draft = draft_store.load_draft(msg_type)
    values = draft.get("values") or {}
    return render_template(
        "messages/references.html",
        msg_type=msg_type,
        draft=draft,
        current_numbers=_current_numbers(values, msg_type),
        current_parties=_current_parties(values),
        columns=draft_store.get_columns(current_user.NameID, "references", msg_type),
        available=draft_store.available_columns(msg_type),
        dropdowns={
            "Category": lookups.category_options(),
            "Language": lookups.language_options(),
        },
    )


def _current_numbers(values, msg_type):
    if msg_type != "voip":
        return []
    out = refs._parts(values.get("Clg_No")) + refs._parts(values.get("Cld_No"))
    return [v for v in out if v and v.upper() != "NIL"]


def _current_parties(values):
    out = refs._parts(values.get("Clg_Pty")) + refs._parts(values.get("Cld_Pty"))
    return [v for v in out if v and v.upper() not in ("NIL", "NOT KNOWN")]


@messages_bp.route("/api/references/<msg_type>", methods=["POST"])
@login_required
def references_search(msg_type):
    if msg_type not in MSG_TYPES:
        return jsonify({"ok": False, "error": "Unknown message type."}), 400
    d = request.get_json(silent=True) or {}
    page_no = int(d.get("page_no") or 0)
    offset = int(d.get("offset") or 25)

    if d.get("prefill"):
        rows = refs.search_for_current(
            msg_type, d.get("numbers") or [], d.get("parties") or [],
            page_no, offset,
        )
    else:
        rows = refs.search(msg_type, d.get("filters") or {}, page_no, offset)

    columns = draft_store.get_columns(current_user.NameID, "references", msg_type)
    label_for = {c["key"]: c["label"] for c in draft_store.available_columns(msg_type)}
    return jsonify({
        "ok": True,
        "columns": [{"key": k, "label": label_for.get(k, k)} for k in columns],
        "rows": [
            dict({k: (getattr(r, k, "") or "") for k in columns},
                 _id=getattr(r, "Event_Id", "") or "")
            for r in rows
        ],
        "page_no": page_no,
        "count": len(rows),
    })


@messages_bp.route("/api/references/<msg_type>/apply", methods=["POST"])
@login_required
def references_apply(msg_type):
    """Turn the ticked rows into reference sentences and fold them into the draft."""
    if msg_type not in MSG_TYPES:
        return jsonify({"ok": False, "error": "Unknown message type."}), 400
    d = request.get_json(silent=True) or {}
    ids = [i for i in (d.get("event_ids") or []) if i]
    if not ids:
        return jsonify({"ok": False, "error": "No messages were selected."}), 400

    model = model_for(msg_type)
    rows = list(db.session.execute(
        select(model).where(model.Event_Id.in_(ids))
    ).scalars())

    draft = draft_store.load_draft(msg_type)
    values = dict(draft.get("values") or {})
    text = refs.build_reference_text(
        rows,
        _current_numbers(values, msg_type),
        _current_parties(values),
        msg_type,
    )
    values["Msg_Ref"] = refs.append_reference(values.get("Msg_Ref"), text)
    draft["values"] = values
    draft_store.save_draft(msg_type, draft)
    return jsonify({"ok": True, "Msg_Ref": values["Msg_Ref"], "added": len(rows)})


@messages_bp.route("/api/references/<msg_type>/columns", methods=["POST"])
@login_required
def references_columns(msg_type):
    if msg_type not in MSG_TYPES:
        return jsonify({"ok": False, "error": "Unknown message type."}), 400
    d = request.get_json(silent=True) or {}
    kept = draft_store.set_columns(
        current_user.NameID, "references", msg_type, d.get("columns") or []
    )
    return jsonify({"ok": True, "columns": kept})


# --- OSINT ----------------------------------------------------------------

@messages_bp.route("/osint/<msg_type>")
@login_required
def osint_page(msg_type):
    _check_type(msg_type)
    return render_template(
        "messages/osint.html",
        msg_type=msg_type,
        draft=draft_store.load_draft(msg_type),
    )


@messages_bp.route("/api/osint/<msg_type>/apply", methods=["POST"])
@login_required
def osint_apply(msg_type):
    """Append the OSINT note to the draft's OSINT box."""
    if msg_type not in MSG_TYPES:
        return jsonify({"ok": False, "error": "Unknown message type."}), 400
    d = request.get_json(silent=True) or {}
    note = (d.get("note") or "").strip()
    if not note:
        return jsonify({"ok": False, "error": "Nothing to add."}), 400

    draft = draft_store.load_draft(msg_type)
    current = str(draft.get("Osint") or "")
    # Appended, as the original did. A separator is added only between
    # entries so the existing text is never run together with the new one.
    draft["Osint"] = (current + ("\n" if current.strip() else "") + note)
    draft_store.save_draft(msg_type, draft)
    return jsonify({"ok": True, "Osint": draft["Osint"]})
