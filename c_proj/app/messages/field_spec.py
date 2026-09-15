"""
Single source of truth for the VOIP and IP message field layouts.

103 columns across two tables is far too many to hand-maintain in three
separate places (model, form template, Word template). Everything is declared
once here; the model, the form renderer and the docx generator all read from
this. Adding a column later means editing one line, not three files.

SOURCE values
  JSON   - extracted from the JSON/XML file found in the selected folder
  AUTO   - set by the application (constant, logged-in user, clock, allocator)
  USER   - typed or selected by the operator on the form

WIDGET values are hints for the form renderer only; they have no effect on
storage (every column is VARCHAR(255) or LONGTEXT in MySQL).
"""

JSON = "json"
AUTO = "auto"
USER = "user"


class F:
    """One column's specification."""

    __slots__ = ("name", "source", "label", "widget", "group", "default", "note")

    def __init__(self, name, source, label, widget="text", group="",
                 default=None, note=""):
        self.name = name
        self.source = source
        self.label = label
        self.widget = widget      # text | textarea | select | readonly | hidden
        self.group = group
        self.default = default    # for AUTO fields with a constant value
        self.note = note

    def __repr__(self):
        return f"<F {self.name} {self.source}>"


# --- form blocks, in the order they appear on the page --------------------
# Block 1 takes the operator's input needed to find the file; block 2 is what
# the file gives back; block 3 is classification and addressing; block 4 is the
# long-form content. Block 5 (hidden) never renders.
G_SOURCE = "Source"
G_EXTRACTED = "Extracted details"
G_CLASSIFY = "Classification & addressing"
G_CONTENT = "Message content"
G_HIDDEN = "Hidden"

GROUP_ORDER = [G_SOURCE, G_EXTRACTED, G_CLASSIFY, G_CONTENT, G_HIDDEN]

# Kept as aliases so nothing importing the old names breaks.
G_IDENT = G_SOURCE
G_CALL = G_EXTRACTED
G_PARTIES = G_EXTRACTED
G_NETWORK = G_EXTRACTED
G_ADDRESS = G_CLASSIFY
G_PEOPLE = G_CLASSIFY
G_STATUS = G_HIDDEN
G_SYSTEM = G_HIDDEN


# --- fields common to both tables ----------------------------------------
# Declared once; each table's spec below adds only what differs.
def _common(msg_type):
    return [
        # ---- Block 1: Source -------------------------------------------
        # What the operator supplies before extracting, plus the few details
        # that belong with it rather than buried further down the form.
        F("System", USER, "Recorder system", "select", G_SOURCE,
          note="systems containing VS read PRI.XML"),
        F("Link", JSON, "Link", "text", G_SOURCE,
          note="auto-filled on extract, editable"),
        F("Filter_Value", JSON, "Filter name", "text", G_SOURCE,
          note="auto-filled on extract, editable"),
        F("Imp_Msg", USER, "Important message", "checkbox", G_SOURCE,
          note="stored as Yes/No"),

        # ---- Block 2: Extracted details --------------------------------
        F("Event_Id", JSON, "Event ID", "readonly", G_EXTRACTED),
        F("VLAN_ID", JSON, "VLAN ID", "readonly", G_EXTRACTED),
        F("Start_Time", JSON, "Start time", "readonly", G_EXTRACTED),
        F("End_Time", JSON, "End time", "readonly", G_EXTRACTED),
        F("Duration", JSON, "Duration", "readonly", G_EXTRACTED),
        F("Time_Interception", JSON, "Export time", "readonly", G_EXTRACTED),
        F("Org_Country", JSON, "Origin country", "readonly", G_EXTRACTED,
          note="from file, not reliable"),
        F("Dest_Country", JSON, "Destination country", "readonly", G_EXTRACTED,
          note="from file, not reliable"),

        # ---- Block 3: Classification & addressing ----------------------
        F("Clg_Country", USER, "Calling country", "select", G_CLASSIFY,
          note="corrected version of origin country; copied into Msg_Country"),
        F("Cld_Country", USER, "Called country", "select", G_CLASSIFY,
          note="corrected version of destination country"),
        F("Category", USER, "Category", "select", G_CLASSIFY),
        F("Language", USER, "Language", "select", G_CLASSIFY),
        F("Classification", USER, "Classification", "select", G_CLASSIFY),
        F("Txbd_By", USER, "Transcribed by", "select", G_CLASSIFY),
        F("Lgd_By", AUTO, "Logged by", "select", G_CLASSIFY,
          note="set from the folder name on extract, editable"),
        F("Prep_By", AUTO, "Prepared by", "select", G_CLASSIFY,
          note="the signed-in user"),
        F("Add_To", USER, "Being addressed to", "textarea", G_CLASSIFY),
        F("Add_Info", USER, "Info to", "textarea", G_CLASSIFY),

        # ---- Block 4: Message content ----------------------------------
        F("Msg_Subject", USER, "Subject", "textarea", G_CONTENT),
        F("Msg_Gist", USER, "Gist", "textarea", G_CONTENT),
        F("Msg_Ref", USER, "Reference", "textarea", G_CONTENT),
        F("Msg_Comments", JSON, "Comments", "textarea", G_CONTENT),

        # ---- Hidden: never rendered ------------------------------------
        F("TC_No", AUTO, "Message No", "hidden", G_HIDDEN),
        F("Wan_No", AUTO, "WAN No", "hidden", G_HIDDEN,
          note="assigned later by WAN allocation"),
        F("Wan_Out_No", AUTO, "WAN Out No", "hidden", G_HIDDEN, default="TBD",
          note="assigned later by WAN allocation"),
        F("Wan_Date", AUTO, "WAN Date", "hidden", G_HIDDEN),
        F("Priority", AUTO, "Priority", "hidden", G_HIDDEN, default="M/IMMDT"),
        F("Attach_No", JSON, "Attachments", "hidden", G_HIDDEN),
        F("Filter_Type", JSON, "Filter type", "hidden", G_HIDDEN),
        F("Source_Ip", JSON, "Source IP", "hidden", G_HIDDEN),
        F("Dest_Ip", JSON, "Destination IP", "hidden", G_HIDDEN),
        F("Protocol", JSON, "Protocol", "hidden", G_HIDDEN),
        F("Loggers_Name", AUTO, "Logger's full name", "hidden", G_HIDDEN,
          note="resolved from Lgd_By"),
        F("Time_Txbd", AUTO, "Time transcribed", "hidden", G_HIDDEN,
          note="clock at save"),
        F("Utililization", AUTO, "Utilised", "hidden", G_HIDDEN, default="NIL",
          note="column name is misspelt in the database; set by the Utilization page"),
        F("Uti_Branch", AUTO, "Utilising branch", "hidden", G_HIDDEN, default="NIL"),
        F("Uti_Type", AUTO, "Utilisation type", "hidden", G_HIDDEN, default="NIL"),
        F("Sup_Ckd", AUTO, "Supervisor checked", "hidden", G_HIDDEN, default="No"),
        F("Msg_Prepared", AUTO, "Message prepared", "hidden", G_HIDDEN, default="No"),
        F("CIN", AUTO, "CIN", "hidden", G_HIDDEN, default="NIL"),
        F("Msg_Type", AUTO, "Message type", "hidden", G_HIDDEN, default=msg_type),
        F("MAC_Add", JSON, "MAC address", "hidden", G_HIDDEN),
        F("Msg_Country", AUTO, "Message country", "hidden", G_HIDDEN,
          note="mirrors Clg_Country"),
    ]


# VOIP: phone numbers and party names sit in the extracted block; parties
# default to NOT KNOWN because the file often omits them.
VOIP_FIELDS = _common("voip") + [
    F("Clg_No", JSON, "Calling number", "readonly", G_EXTRACTED),
    F("Cld_No", JSON, "Called number", "readonly", G_EXTRACTED),
    F("Clg_Pty", JSON, "Calling party", "text", G_EXTRACTED, default="NOT KNOWN",
      note="editable"),
    F("Cld_Pty", JSON, "Called party", "text", G_EXTRACTED, default="NOT KNOWN",
      note="editable"),
    F("Clg_Svc_Provider", JSON, "Calling service provider", "hidden", G_HIDDEN),
    F("Cld_Svc_Provider", JSON, "Called service provider", "hidden", G_HIDDEN),
]

# IP: parties are email addresses from the file; the phone columns are "NIL".
IP_FIELDS = _common("ip") + [
    F("Clg_No", AUTO, "Calling number", "hidden", G_HIDDEN, default="NIL"),
    F("Cld_No", AUTO, "Called number", "hidden", G_HIDDEN, default="NIL"),
    F("Clg_Pty", JSON, "Calling party", "text", G_EXTRACTED,
      note="filled from the sender email on extract; editable"),
    F("Cld_Pty", JSON, "Called party", "text", G_EXTRACTED,
      note="filled from the recipient email on extract; editable"),
    F("BEPS_ID", JSON, "BEPS ID", "readonly", G_EXTRACTED),
]


SPECS = {"voip": VOIP_FIELDS, "ip": IP_FIELDS}


# --- helpers used by routes, form renderer and docx builder ---------------
def fields_for(msg_type):
    return SPECS[msg_type]


def by_source(msg_type, source):
    return [f for f in fields_for(msg_type) if f.source == source]


def field_map(msg_type):
    return {f.name: f for f in fields_for(msg_type)}


def grouped(msg_type, sources=(JSON, AUTO, USER)):
    """Fields bucketed by group, in GROUP_ORDER, for template rendering."""
    out = []
    fmap = fields_for(msg_type)
    for g in GROUP_ORDER:
        items = [f for f in fmap if f.group == g and f.source in sources]
        if items:
            out.append((g, items))
    return out


def defaults(msg_type):
    return {f.name: f.default for f in fields_for(msg_type) if f.default is not None}
