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
from app.messages.field_spec import fields_for, defaults, grouped, USER, AUTO
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
    return {
        "Category": lookups.category_options(),
        "Language": lookups.language_options(),
        "Clg_Country": lookups.country_options(),
        "Cld_Country": lookups.country_options(),
        "System": lookups.system_options(),
        "Classification": lookups.distinct_values(model, "Classification"),
        "Txbd_By": [
            {"value": u.NameID, "label": f"{u.NameID} — {u.Name}"}
            for u in db.session.execute(
                select(User).order_by(User.NameID)
            ).scalars()
        ],
    }


@messages_bp.route("/new")
@login_required
def new_redirect():
    return redirect(url_for("messages.new", msg_type="voip"))


@messages_bp.route("/new/<msg_type>")
@login_required
def new(msg_type):
    _check_type(msg_type)
    return render_template(
        "messages/new.html",
        msg_type=msg_type,
        groups=grouped(msg_type, sources=("json", "user")),
        dropdowns=_dropdowns(msg_type),
        field_defaults=defaults(msg_type),
        next_msgno=msgno_svc.peek_next(),
        user=current_user,
    )


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
        extracted = parser.parse_file(info["data_file"], msg_type, kind)
    except parser.ParseError as e:
        return jsonify({"ok": False, "error": str(e),
                        "detail": info["data_file"]}), 400

    extracted.setdefault("Event_Id", info["event_id"])

    logger = db.session.get(User, info["lgd_by"])
    auto = {
        "Lgd_By": info["lgd_by"],
        "Loggers_Name": logger.Name if logger else "",
        "Prep_By": current_user.Name or current_user.NameID,
        "Wan_Date": date.today().strftime("%Y-%m-%d"),
    }
    auto.update(defaults(msg_type))

    unmapped = parser.unmapped_fields(msg_type, kind)
    return jsonify({
        "ok": True,
        "extracted": extracted,
        "auto": auto,
        "info": {
            "file_kind": kind,
            "data_file": info["data_file"],
            "source_folder": info["source_folder"],
            "logger_found": logger is not None,
            "unmapped_count": len(unmapped),
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
    values["Prep_By"] = current_user.Name or current_user.NameID
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

    try:
        generate_document(values, destination, msg_type,
                          extra={"Extra_Add": extra_add})
    except DocumentError as e:
        warnings.append(str(e))

    return jsonify({
        "ok": True,
        "msgno": number,
        "destination": destination,
        "warnings": warnings,
    })
