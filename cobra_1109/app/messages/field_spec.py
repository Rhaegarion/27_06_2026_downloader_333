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


# --- groups, in the order they appear on the form -------------------------
G_IDENT = "Message identity"
G_CALL = "Call details"
G_PARTIES = "Parties"
G_NETWORK = "Network"
G_ADDRESS = "Addressing"
G_CONTENT = "Message content"
G_PEOPLE = "People & timings"
G_STATUS = "Status & utilisation"
G_SYSTEM = "System (not shown)"

GROUP_ORDER = [
    G_IDENT, G_CALL, G_PARTIES, G_NETWORK, G_ADDRESS,
    G_CONTENT, G_PEOPLE, G_STATUS, G_SYSTEM,
]


# --- fields common to both tables ----------------------------------------
# Declared once; each table's spec below adds only what differs.
def _common(msg_type):
    return [
        # identity
        F("Event_Id", JSON, "Event ID", "readonly", G_IDENT,
          note="main identifier of the call"),
        F("TC_No", AUTO, "Message No", "readonly", G_IDENT,
          note="allocated atomically at save"),
        F("Wan_No", AUTO, "WAN No", "readonly", G_IDENT,
          note="assigned later by WAN allocation"),
        F("Wan_Out_No", AUTO, "WAN Out No", "readonly", G_IDENT, default="TBD",
          note="assigned later by WAN allocation"),
        F("Wan_Date", AUTO, "WAN Date", "readonly", G_IDENT),
        F("Priority", AUTO, "Priority", "readonly", G_IDENT, default="M/IMMDT"),
        F("Attach_No", JSON, "Attachments", "readonly", G_IDENT),
        F("Classification", USER, "Classification", "select", G_IDENT),

        # call details
        F("Start_Time", JSON, "Start time", "readonly", G_CALL),
        F("End_Time", JSON, "End time", "readonly", G_CALL),
        F("Duration", JSON, "Duration", "readonly", G_CALL),
        F("Time_Interception", JSON, "Time intercepted", "readonly", G_CALL),
        F("Category", USER, "Category", "select", G_CALL),
        F("Language", USER, "Language", "select", G_CALL),
        F("Filter_Type", JSON, "Filter type", "readonly", G_CALL),
        F("Filter_Value", JSON, "Filter value", "readonly", G_CALL),

        # network
        F("Source_Ip", JSON, "Source IP", "readonly", G_NETWORK),
        F("Dest_Ip", JSON, "Destination IP", "readonly", G_NETWORK),
        F("Protocol", JSON, "Protocol", "readonly", G_NETWORK),
        F("Link", JSON, "Link", "readonly", G_NETWORK),
        F("VLAN_ID", JSON, "VLAN ID", "readonly", G_NETWORK),
        F("System", USER, "Recorder system", "select", G_NETWORK),

        # addressing
        F("Add_To", USER, "Addressee (To)", "text", G_ADDRESS),
        F("Add_Info", USER, "Addressee (Info)", "text", G_ADDRESS),

        # content
        F("Msg_Subject", USER, "Subject", "text", G_CONTENT),
        F("Msg_Gist", USER, "Gist", "textarea", G_CONTENT),
        F("Msg_Ref", USER, "References", "textarea", G_CONTENT),
        F("Msg_Comments", JSON, "Comments", "textarea", G_CONTENT),

        # people & timings
        F("Lgd_By", AUTO, "Logged by", "readonly", G_PEOPLE,
          note="parsed from the source filename"),
        F("Loggers_Name", AUTO, "Logger's full name", "readonly", G_PEOPLE,
          note="resolved from Lgd_By via name_details"),
        F("Txbd_By", USER, "Transcribed by", "select", G_PEOPLE),
        F("Prep_By", AUTO, "Prepared by", "readonly", G_PEOPLE,
          note="logged-in user"),
        F("Time_Txbd", AUTO, "Time transcribed", "readonly", G_PEOPLE,
          note="clock at save"),

        # status & utilisation
        F("Imp_Msg", USER, "Important message", "checkbox", G_STATUS,
          note="stored as Yes/No"),
        F("Utililization", AUTO, "Utilised", "hidden", G_STATUS, default="NIL",
          note="column name is misspelt in the database; set by the Utilization page"),
        F("Uti_Branch", AUTO, "Utilising branch", "hidden", G_STATUS, default="NIL",
          note="set by the Utilization page"),
        F("Uti_Type", AUTO, "Utilisation type", "hidden", G_STATUS, default="NIL",
          note="set by the Utilization page"),
        F("Sup_Ckd", AUTO, "Supervisor checked", "hidden", G_STATUS, default="No"),
        F("Msg_Prepared", AUTO, "Message prepared", "hidden", G_STATUS, default="No"),
        F("CIN", AUTO, "CIN", "hidden", G_STATUS, default="NIL"),

        # system
        F("Msg_Type", AUTO, "Message type", "hidden", G_SYSTEM, default=msg_type),
        F("MAC_Add", JSON, "MAC address", "hidden", G_SYSTEM),
        F("Msg_Country", AUTO, "Message country", "hidden", G_SYSTEM,
          note="mirrors whatever the operator selects for Clg_Country"),
        F("Org_Country", JSON, "Origin country (raw)", "readonly", G_SYSTEM,
          note="from file, not reliable"),
        F("Dest_Country", JSON, "Destination country (raw)", "readonly", G_SYSTEM,
          note="from file, not reliable"),

        # analyst-corrected countries — present on both tables
        F("Clg_Country", USER, "Calling country", "select", G_PARTIES,
          note="corrected version of Org_Country; also copied into Msg_Country"),
        F("Cld_Country", USER, "Called country", "select", G_PARTIES,
          note="corrected version of Dest_Country"),
    ]


# --- VOIP: phone numbers from the file, party names typed in, plus the ----
#     analyst-corrected country and service-provider fields.
VOIP_FIELDS = _common("voip") + [
    F("Clg_No", JSON, "Calling number", "readonly", G_PARTIES),
    F("Cld_No", JSON, "Called number", "readonly", G_PARTIES),
    F("Clg_Pty", USER, "Calling party", "text", G_PARTIES),
    F("Cld_Pty", USER, "Called party", "text", G_PARTIES),
    F("Clg_Svc_Provider", JSON, "Calling service provider", "readonly", G_PARTIES),
    F("Cld_Svc_Provider", JSON, "Called service provider", "readonly", G_PARTIES),
]

# --- IP: parties are email addresses from the file; phone number columns --
#     are constant "NIL"; BEPS_ID is IP-only.
IP_FIELDS = _common("ip") + [
    F("Clg_No", AUTO, "Calling number", "hidden", G_PARTIES, default="NIL"),
    F("Cld_No", AUTO, "Called number", "hidden", G_PARTIES, default="NIL"),
    F("Clg_Pty", JSON, "Sender email", "readonly", G_PARTIES),
    F("Cld_Pty", JSON, "Recipient email", "readonly", G_PARTIES),
    F("BEPS_ID", JSON, "BEPS ID", "readonly", G_PARTIES),
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
