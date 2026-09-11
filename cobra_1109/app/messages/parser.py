"""
Extraction of form values from the intercept data file.

The recorder system decides the format: some systems write a JSON file named
after the Event ID, others always write PRI.XML. Both end up producing the same
dict of column -> value, so the rest of the application doesn't care which was
used.

=============================================================================
FILLING IN THE MAPPINGS
=============================================================================
Only the two MAP dicts below need editing. Everything else is generic.

For JSON, the right-hand side is a dotted path into the parsed document:

    "Start_Time": "call.startTime"      -> doc["call"]["startTime"]
    "Clg_No":     "parties.0.number"    -> doc["parties"][0]["number"]
    "Duration":   "duration"            -> doc["duration"]

For XML, the right-hand side is an ElementTree path, optionally with @attribute:

    "Start_Time": "Call/StartTime"          -> text of <StartTime>
    "Event_Id":   "Call@id"                 -> the id attribute of <Call>
    "Source_Ip":  "Network/Source@address"  -> address attribute of <Source>

Leave an entry as None if that field isn't present in that format; it will be
skipped rather than raising. Unmapped fields simply come back empty, so the
form still loads and the operator can fill them in by hand.
=============================================================================
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from app.messages.field_spec import JSON as SRC_JSON, fields_for


# --- mappings to be completed -------------------------------------------
# Every JSON-sourced column for each table. Fill in the right-hand values.

VOIP_JSON_MAP = {
    "Event_Id": None,
    "Filter_Type": None,
    "Filter_Value": None,
    "Attach_No": None,
    "Start_Time": None,
    "End_Time": None,
    "Duration": None,
    "Clg_No": None,
    "Cld_No": None,
    "Source_Ip": None,
    "Dest_Ip": None,
    "Protocol": None,
    "Org_Country": None,
    "Dest_Country": None,
    "Msg_Comments": None,
    "Time_Interception": None,
    "Clg_Svc_Provider": None,
    "Cld_Svc_Provider": None,
    "Link": None,
    "MAC_Add": None,
    "VLAN_ID": None,
}

VOIP_XML_MAP = dict.fromkeys(VOIP_JSON_MAP)

IP_JSON_MAP = {
    "Event_Id": None,
    "Filter_Type": None,
    "Filter_Value": None,
    "Attach_No": None,
    "Start_Time": None,
    "End_Time": None,
    "Duration": None,
    "Clg_Pty": None,
    "Cld_Pty": None,
    "Source_Ip": None,
    "Dest_Ip": None,
    "Protocol": None,
    "Org_Country": None,
    "Dest_Country": None,
    "Msg_Comments": None,
    "Time_Interception": None,
    "Link": None,
    "MAC_Add": None,
    "VLAN_ID": None,
    "BEPS_ID": None,
}

IP_XML_MAP = dict.fromkeys(IP_JSON_MAP)

MAPS = {
    ("voip", "json"): VOIP_JSON_MAP,
    ("voip", "xml"): VOIP_XML_MAP,
    ("ip", "json"): IP_JSON_MAP,
    ("ip", "xml"): IP_XML_MAP,
}


class ParseError(Exception):
    pass


# --- generic extraction ---------------------------------------------------

def _dig(doc, dotted):
    """Walk a dotted path through dicts and lists. Returns None if absent."""
    cur = doc
    for part in dotted.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _flatten(value):
    """Reference data is sometimes a list; join it rather than storing repr()."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v is not None)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _xml_get(root, path):
    """Read an ElementTree path, optionally 'Some/Path@attribute'."""
    attr = None
    if "@" in path:
        path, attr = path.split("@", 1)
    path = path.strip("/")
    node = root if not path else root.find(path)
    if node is None:
        return None
    if attr:
        return node.get(attr)
    return (node.text or "").strip()


def parse_file(file_path, msg_type, file_kind):
    """
    Read the data file and return {column: value} for the mapped fields.

    Unmapped entries are skipped, so this works before the mappings are filled
    in — it just returns fewer fields.
    """
    mapping = MAPS.get((msg_type, file_kind))
    if mapping is None:
        raise ParseError(f"No mapping for {msg_type}/{file_kind}")

    p = Path(file_path)
    if not p.exists():
        raise ParseError(f"Data file not found: {file_path}")

    try:
        if file_kind == "json":
            doc = json.loads(p.read_text(encoding="utf-8-sig"))
            getter = lambda path: _dig(doc, path)
        else:
            root = ET.parse(str(p)).getroot()
            getter = lambda path: _xml_get(root, path)
    except json.JSONDecodeError as e:
        raise ParseError(f"{p.name} is not valid JSON: {e}") from e
    except ET.ParseError as e:
        raise ParseError(f"{p.name} is not valid XML: {e}") from e
    except OSError as e:
        raise ParseError(f"Could not read {p.name}: {e}") from e

    out = {}
    for column, path in mapping.items():
        if not path:
            continue
        out[column] = _flatten(getter(path))
    return out


def unmapped_fields(msg_type, file_kind):
    """Which JSON-sourced columns still have no mapping — used by a self-check."""
    mapping = MAPS.get((msg_type, file_kind), {})
    return sorted(k for k, v in mapping.items() if not v)


def mapping_coverage(msg_type, file_kind):
    expected = {f.name for f in fields_for(msg_type) if f.source == SRC_JSON}
    mapping = MAPS.get((msg_type, file_kind), {})
    return {
        "mapped": sorted(k for k, v in mapping.items() if v),
        "unmapped": sorted(k for k, v in mapping.items() if not v),
        "missing_from_map": sorted(expected - set(mapping)),
        "not_a_json_field": sorted(set(mapping) - expected),
    }
