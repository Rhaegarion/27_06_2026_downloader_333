"""
Path handling for the New Message page.

Two jobs:

  parse_source_path()  - pull Event_Id and Lgd_By out of the network path the
                         operator pastes in, and work out which data file to
                         look for (JSON or XML, decided by the recorder system).

  build_destination()  - work out the MMM YYYY / dd.mm.yyyy Msg / <msgno>
                         folder tree the intercept material gets copied into.

PureWindowsPath is used rather than Path so that UNC paths parse identically
whether this runs on Windows (production) or Linux (dev/CI).
"""

from datetime import date
from pathlib import PurePosixPath, PureWindowsPath


def _pure(raw):
    """
    Pick the right path flavour.

    Production runs on Windows against UNC shares, so backslash paths must parse
    as Windows paths regardless of what the server OS is. A path with no
    backslash is treated as POSIX so the app still works when developed or
    tested on Linux.
    """
    return PureWindowsPath(raw) if "\\" in str(raw) else PurePosixPath(raw)

# Root of the intercept archive. Kept here rather than in code that uses it so
# an office with a different share only edits one line (or overrides via .env).
INTERCEPT_ROOT = r"\\192.168.2.205\New Intercepts"

# The XML variant always uses this fixed filename; the JSON variant is named
# after the final folder (which is also the Event ID).
XML_FILENAME = "PRI.XML"

# Month folder names. Defined explicitly instead of using strftime("%b") because
# that is locale-dependent and would silently produce "Sep" on one machine and
# something else on another — which would create duplicate month folders.
MONTH_ABBR = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}


class PathError(ValueError):
    """Raised when a supplied source path doesn't match the expected layout."""


# Recorder systems whose name contains this marker write PRI.XML; every other
# system writes a JSON file named after the Event ID.
XML_SYSTEM_MARKER = "VS"


def file_kind_for_system(system_name):
    """
    Decide whether to look for the XML or the JSON file, based on the recorder
    system the operator selected.

    Matching is case-insensitive and looks anywhere in the name, so "VS-100",
    "NEWVS" and "vs2" all resolve to XML.
    """
    if not system_name or not str(system_name).strip():
        raise PathError("Select a recorder system before extracting.")
    return "xml" if XML_SYSTEM_MARKER in str(system_name).upper() else "json"


def parse_source_path(raw_path, file_kind="json"):
    """
    Pull the identifiers out of an intercept folder path.

    Expected shape (the last two components are what matter):
        ...\\MSG01_ASK_NOI_DS CCS_BENG_SUSPS\\kg83638bejdh638
            |                                |
            |                                +-- Event ID, and the JSON filename
            +-- message folder; Lgd_By is between the 1st and 2nd underscore

    file_kind is "json" or "xml" and is decided by the recorder system the
    operator selected, not by inspecting the folder.

    Returns a dict with event_id, lgd_by, data_file and folder paths.
    """
    if not raw_path or not raw_path.strip():
        raise PathError("No folder path was supplied.")

    p = _pure(raw_path.strip().rstrip("\\/"))
    parts = p.parts
    if len(parts) < 2:
        raise PathError(f"Path is too short to identify a message folder: {raw_path!r}")

    event_folder = p.name                 # kg83638bejdh638
    msg_folder = p.parent.name            # MSG01_ASK_NOI_DS CCS_BENG_SUSPS

    if not event_folder:
        raise PathError("Could not read the Event ID folder from the path.")

    # Lgd_By sits between the first and second underscore of the message folder.
    segments = msg_folder.split("_")
    if len(segments) < 2 or not segments[1].strip():
        raise PathError(
            f"Could not read the logger's ID from folder {msg_folder!r}. "
            "Expected a name like MSG01_ASK_NOI_..."
        )
    lgd_by = segments[1].strip().upper()

    kind = (file_kind or "json").lower()
    if kind == "xml":
        data_filename = XML_FILENAME
    elif kind == "json":
        data_filename = f"{event_folder}.json"
    else:
        raise PathError(f"Unknown data file type: {file_kind!r}")

    return {
        "event_id": event_folder,
        "lgd_by": lgd_by,
        "msg_folder_name": msg_folder,
        "source_folder": str(p),
        "data_file": str(p / data_filename),
        "data_file_kind": kind,
    }


def month_folder(on_date):
    return f"{MONTH_ABBR[on_date.month]} {on_date.year}"


def day_folder(on_date):
    return f"{on_date:%d.%m.%Y} Msg"


def msg_folder(msg_no):
    """
    Folder named for the message number. Leading zeros are stripped so that
    TC_No "0001" and "1" can't produce two different folders for one message.
    """
    s = str(msg_no).strip()
    if not s:
        raise PathError("A message number is required to build the destination path.")
    digits = s.lstrip("0")
    return digits if digits else "0"


def build_destination(msg_no, on_date=None, root=INTERCEPT_ROOT):
    """
    Build the archive folder for a message:
        <root>\\MMM YYYY\\dd.mm.yyyy Msg\\<msg no>

    Returns the path only — it does not touch the filesystem. Creating the
    tree is the caller's job, after the database row is safely committed.
    """
    on_date = on_date or date.today()
    return str(
        _pure(root)
        / month_folder(on_date)
        / day_folder(on_date)
        / msg_folder(msg_no)
    )
