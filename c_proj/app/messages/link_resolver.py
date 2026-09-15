"""
Link resolution from MAC addresses.

A capture yields several MAC addresses (source and destination, sometimes more
than one of each). Each is looked up against link_table_mac_address; only a
handful of ports carry a real Link_Name, and everything else is NULL.

Priority is fixed and does not depend on which MAC happened to be listed
first: J-25 beats BAL, BAL beats the TCL fallback. TCL is only correct when no
MAC resolved to anything at all, so it is applied once at the end rather than
per-address — checking addresses in order and returning the first hit would
give a different answer depending on capture order.
"""

from sqlalchemy import select

from app.extensions import db

DEFAULT_LINK = "TCL"

# Highest priority first.
LINK_PRIORITY = ["J-25", "BAL"]


class LinkMacAddress(db.Model):
    __tablename__ = "link_table_mac_address"

    Sl_No = db.Column(db.Integer, primary_key=True)
    Source_Port_Number = db.Column(db.String(255))
    Destination_Port_Number = db.Column(db.String(255))
    Port_MAC_Address = db.Column(db.String(255))
    Link_Name = db.Column(db.String(255))
    Link_Alloted_To = db.Column(db.String(255))
    Link_Status = db.Column(db.String(255))
    Fiber_Identification_Details = db.Column(db.String(255))


def normalise_mac(mac):
    """
    XML gives MACs with dashes, JSON with colons. Stored values are compared
    case-insensitively with colons, matching what the old code did before
    calling the lookup.
    """
    if not mac:
        return ""
    return str(mac).strip().replace("-", ":").upper()


def lookup_link(mac):
    """Link name for one MAC, or None if unknown or NULL in the table."""
    m = normalise_mac(mac)
    if not m:
        return None
    row = db.session.execute(
        select(LinkMacAddress).where(
            db.func.upper(
                db.func.replace(LinkMacAddress.Port_MAC_Address, "-", ":")
            ) == m
        ).limit(1)
    ).scalars().first()
    if row is None:
        return None
    name = (row.Link_Name or "").strip()
    return name or None


def resolve_link(macs):
    """
    Work out the link for a capture from all of its MAC addresses.

    Returns (link_name, matched_mac). matched_mac is the address that produced
    the winning link, or the first usable address when falling back to TCL —
    it is what gets stored in MAC_Add.
    """
    seen = []
    for mac in macs or []:
        m = normalise_mac(mac)
        if m and m not in seen:
            seen.append(m)

    if not seen:
        return DEFAULT_LINK, ""

    found = {}
    for m in seen:
        name = lookup_link(m)
        if name and name not in found:
            found[name] = m

    for preferred in LINK_PRIORITY:
        if preferred in found:
            return preferred, found[preferred]

    # Any other non-null name still beats the fallback.
    for name, m in found.items():
        return name, m

    return DEFAULT_LINK, seen[0]
