"""
Extraction of form values from the intercept data file.

Ported from the working New_Entry parsing. Two formats:

  JSON  - named after the Event ID folder. Top-level keys: session, datalink,
          network, payload, filter_names, capture_filters, exported_at_str.
  XML   - always PRI.XML. Identifiers live on the root's attributes; parties
          are Participants/Participant[@Type=From|To].

Each parse returns a flat {column: value} dict for a single file. Merging
several captures into one message is handled by accumulate(), not here, so
this stays a pure function of one file.
"""

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path


class ParseError(Exception):
    pass


# --- small helpers --------------------------------------------------------

def _get(d, *keys):
    """Nested lookup that tolerates missing keys and non-dict intermediates."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _s(value):
    return "" if value is None else str(value)


def _epoch_to_str(value, divisor=1):
    try:
        return datetime.fromtimestamp(int(value) / divisor).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError):
        return ""


# --- JSON -----------------------------------------------------------------

def parse_json(path, msg_type):
    p = Path(path)
    try:
        with p.open("r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as e:
        raise ParseError(f"{p.name} is not valid JSON: {e}") from e
    except OSError as e:
        raise ParseError(f"Could not read {p.name}: {e}") from e

    session = data.get("session") or {}
    datalink = data.get("datalink") or {}
    network = data.get("network") or {}
    payload = data.get("payload") or {}

    out = {"Event_Id": _s(session.get("id"))}

    # --- times. The exporter is inconsistent: some systems write the
    # pre-formatted *_str fields, others only epoch milliseconds. Prefer the
    # string form, fall back to computing it.
    if session.get("start_time_str"):
        out["Start_Time"] = _s(session["start_time_str"])
    elif session.get("start_time") is not None:
        out["Start_Time"] = _epoch_to_str(session["start_time"], 1000)
    else:
        out["Start_Time"] = ""

    if session.get("duration_str"):
        out["Duration"] = _s(session["duration_str"])
    elif session.get("duration") is not None:
        try:
            out["Duration"] = str(timedelta(seconds=session["duration"]))
        except (TypeError, ValueError):
            out["Duration"] = ""
    else:
        out["Duration"] = ""

    if session.get("end_time_str"):
        out["End_Time"] = _s(session["end_time_str"])
    elif session.get("start_time") is not None and session.get("duration") is not None:
        try:
            start = datetime.fromtimestamp(int(session["start_time"]) / 1000)
            out["End_Time"] = (
                start + timedelta(seconds=session["duration"])
            ).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            out["End_Time"] = ""
    else:
        out["End_Time"] = ""

    out["Protocol"] = _s(session.get("protocol")).upper()
    out["Source_Ip"] = _s(network.get("src_ip"))
    out["Dest_Ip"] = _s(network.get("dst_ip"))
    out["Time_Interception"] = _s(data.get("exported_at_str"))

    # VLAN comes from the first link name, when present.
    link_names = datalink.get("link_names") or []
    out["VLAN_ID"] = _s(link_names[0]) if link_names else ""

    # --- filters. filter_names and capture_filters are parallel lists;
    # comments pair a name with its filter's comment.
    filter_names = data.get("filter_names") or []
    capture_filters = data.get("capture_filters") or []
    out["Filter_Type"] = ", ".join(_s(n) for n in filter_names)
    out["Filter_Value"] = ", ".join(
        _s(f.get("name")) for f in capture_filters if isinstance(f, dict)
    )
    comments = []
    for idx, cf in enumerate(capture_filters):
        if not isinstance(cf, dict):
            continue
        name = _s(filter_names[idx]) if idx < len(filter_names) else ""
        comment = _s(cf.get("comment"))
        comments.append(f"{name}: {comment}" if name else comment)
    out["Msg_Comments"] = ", ".join(c for c in comments if c.strip(": "))

    # --- parties differ by message type.
    if msg_type == "ip":
        email_from = payload.get("email_from") or []
        email_to = payload.get("email_to") or []
        out["Clg_Pty"] = _s(email_from[0]) if email_from else ""
        out["Cld_Pty"] = _s(email_to[0]) if email_to else ""
    else:
        out["Clg_No"] = _s(payload.get("sip_from_id"))
        out["Cld_No"] = _s(payload.get("sip_to_id"))
        out["Org_Country"] = _s(payload.get("sip_from_cn"))
        out["Dest_Country"] = _s(payload.get("sip_to_cn"))

    # --- MAC addresses, for the link lookup. Not a column on its own; the
    # caller resolves these into Link and MAC_Add.
    if datalink.get("mac_addresses"):
        macs = [_s(m) for m in datalink["mac_addresses"]]
    else:
        macs = [_s(datalink.get("src_eth")), _s(datalink.get("dst_eth"))]
    out["_macs"] = [m for m in macs if m]

    return out


# --- XML ------------------------------------------------------------------

def parse_xml(path, msg_type):
    p = Path(path)
    try:
        root = ET.parse(str(p)).getroot()
    except ET.ParseError as e:
        raise ParseError(f"{p.name} is not valid XML: {e}") from e
    except OSError as e:
        raise ParseError(f"Could not read {p.name}: {e}") from e

    out = {"Event_Id": _s(root.attrib.get("Id"))}
    out["Protocol"] = _s(root.attrib.get("Protocol"))

    # Times are Unix seconds on the root; duration is derived.
    start_raw = root.attrib.get("Time")
    end_raw = root.attrib.get("EndTime")
    if start_raw and end_raw:
        try:
            start = datetime.fromtimestamp(int(start_raw))
            end = datetime.fromtimestamp(int(end_raw))
            out["Start_Time"] = str(start)
            out["End_Time"] = str(end)
            out["Duration"] = str(end - start)
        except (TypeError, ValueError, OSError):
            out["Start_Time"] = out["End_Time"] = out["Duration"] = ""
    else:
        out["Start_Time"] = out["End_Time"] = out["Duration"] = ""

    # ParentId decides whether this capture is flagged NOI.
    parent_id = _s(root.attrib.get("ParentId"))
    noi = "NOI" if parent_id and parent_id != "0" else "NOT NOI"
    out["Filter_Type"] = noi
    out["Filter_Value"] = noi
    out["Msg_Comments"] = noi

    for participant in root.findall("./Participants/Participant"):
        kind = participant.attrib.get("Type")
        phone = participant.find("PhoneNumber")
        ip = participant.find("IP")
        phone_val = _s(phone.attrib.get("Value")) if phone is not None else ""
        ip_val = _s(ip.attrib.get("Value")) if ip is not None else ""
        if kind == "From":
            if msg_type == "ip":
                out["Clg_Pty"] = phone_val
            else:
                out["Clg_No"] = phone_val
            out["Source_Ip"] = ip_val
        elif kind == "To":
            if msg_type == "ip":
                out["Cld_Pty"] = phone_val
            else:
                out["Cld_No"] = phone_val
            out["Dest_Ip"] = ip_val

    macs = []
    for eth in root.findall("./Network/Ethernet"):
        for attr in ("ClientMac", "ServerMac"):
            val = eth.attrib.get(attr)
            if val:
                macs.append(val)
    out["_macs"] = macs

    # The XML export carries none of these, so they are fixed rather than blank.
    out["Org_Country"] = "NIL"
    out["Dest_Country"] = "NIL"
    out["VLAN_ID"] = "NIL"
    out["Time_Interception"] = "NIL"

    return out


def parse_file(file_path, msg_type, file_kind):
    p = Path(file_path)
    if not p.exists():
        raise ParseError(f"Data file not found: {file_path}")
    if file_kind == "xml":
        return parse_xml(p, msg_type)
    return parse_json(p, msg_type)


# --- accumulation ---------------------------------------------------------

# Values that are a property of the message rather than of one capture, so
# repeating them across files would be noise.
NON_ACCUMULATING = {"Link", "MAC_Add"}


def accumulate(existing, addition, separator=","):
    """
    Merge a freshly parsed capture into what the form already holds.

    Several captures can be combined into one message, so values append with
    commas rather than replacing — this is what produces the comma-separated
    Event IDs. Empty additions are skipped so a blank field in one file cannot
    blank out a value another file supplied.
    """
    merged = dict(existing or {})
    for key, value in (addition or {}).items():
        if key.startswith("_"):
            continue
        new = _s(value).strip()
        if not new:
            continue
        current = _s(merged.get(key)).strip()
        if not current:
            merged[key] = new
        elif key in NON_ACCUMULATING:
            merged[key] = current
        elif new in [part.strip() for part in current.split(separator)]:
            merged[key] = current          # already present, don't repeat
        else:
            merged[key] = current + separator + new
    return merged
