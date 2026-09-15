"""
Translation between COBRA's column names and the keys create_doc expects.

The Word layout was written against its own short key names (Fromstn, St_Tm,
ClgPty...). Rather than rename those throughout the document code, the mapping
lives here so both sides keep their own vocabulary and only this file has to
change if either moves.
"""

from datetime import date as date_cls

# Station headings are fixed for this office.
FROM_STATION = "CEC Kolkata"
TO_STATION = "New Delhi"
INFO_STATION = "New Delhi"
FROM_ADDRESS = "\tAdditional Commissioner (Tech)"

# What the document prints for Message Type, which is not the same as the
# Msg_Type stored on the row ("VOIP" / "EMAIL").
DOC_MSG_TYPE = {"voip": "IP Traffic (VOIP)", "ip": "IP Traffic"}
ROW_MSG_TYPE = {"voip": "VOIP", "ip": "EMAIL"}


def compose_number(number, provider):
    """
    "<number> (<service provider>)" as the document prints it.

    The columns store number and provider separately; the original code joined
    them before saving, which made the provider impossible to query on.
    """
    num = (number or "").strip()
    prov = (provider or "").strip()
    if prov and prov.upper() != "NIL":
        return f"{num}({prov})"
    return num


def build_word_dict(values, msg_type, on_date=None, extra=None):
    """
    values   the row as stored, by column name
    extra    display-only values (Extra_Add, Osint, logger_final)
    """
    extra = extra or {}
    on_date = on_date or date_cls.today()

    def v(key, default=""):
        got = values.get(key)
        return default if got is None else str(got)

    to_add = v("Add_To")
    info_add = v("Add_Info")
    # The extra addressee is display-only; it rides along on the Info line so
    # it reaches the document without needing a column.
    extra_add = (extra.get("Extra_Add") or "").strip()
    if extra_add:
        info_add = f"{info_add}, {extra_add}" if info_add.strip() else extra_add

    data = {
        "Date_month": on_date.strftime("%m"),
        "Date": on_date.strftime("%d.%m.%Y"),
        "Fromstn": FROM_STATION,
        "Tostn": TO_STATION,
        "Infostn": INFO_STATION,
        "Fromadd": FROM_ADDRESS,
        "Toadd": "\t\t" + to_add,
        "Infoadd": "\t\t" + info_add,
        "MsgNo": v("TC_No"),
        "Link": v("Link"),
        "Msgtype": DOC_MSG_TYPE.get(msg_type, ""),
        "Lang": v("Language"),
        "EventID": v("Event_Id"),
        "Classfcn": v("Classification"),
        "St_Tm": v("Start_Time"),
        "Ed_Tm": v("End_Time"),
        "ClgPty": v("Clg_Pty"),
        "CldPty": v("Cld_Pty"),
        # logger_final is the "Sh. Name,Rank" form, not the stored acronym.
        "LgdBy": extra.get("logger_final") or v("Lgd_By"),
        "TxbdBy": extra.get("txbd_final") or v("Txbd_By"),
        "PrepBy": extra.get("prep_final") or v("Prep_By"),
        "Catgy": v("Category"),
        "Sub": v("Msg_Subject"),
        "Gist": v("Msg_Gist"),
        "Ref": v("Msg_Ref"),
        "Cmnt": v("Msg_Comments"),
        "Osint": extra.get("Osint", ""),
    }

    if msg_type == "ip":
        data["Beps_ID"] = v("BEPS_ID")
    else:
        data["ClgNo"] = compose_number(v("Clg_No"), v("Clg_Svc_Provider"))
        data["CldNo"] = compose_number(v("Cld_No"), v("Cld_Svc_Provider"))
        data["ClgCty"] = v("Clg_Country", "NIL") or "NIL"
        data["CldCty"] = v("Cld_Country", "NIL") or "NIL"

    return data
