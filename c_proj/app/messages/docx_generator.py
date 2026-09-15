"""
Word document generation.

Adapted from word.py (VOIP) and word_ip.py (IP). The two shared almost all of
their body, so the layout is expressed once and the handful of genuine
differences are branched on msg_type:

  VOIP  Calling/Called No. lines with country in brackets; OSINT block is
        conditional; Ref is inline.
  IP    no number lines; BEPS ID drives the WAN heading, adds a BEPS ID line
        and a "Filtered By: BEPS" line; OSINT block is unconditional; Ref is
        on its own paragraph below the label.

Changes from the originals, all deliberate:

  * The destination folder is passed in rather than recomputed here. COBRA
    already works it out to copy the intercept material, and two copies of
    that logic would eventually disagree.
  * Returns the saved path on success instead of None, so the caller can tell
    "written" from "silently did nothing".
  * Month folder names come from a fixed table rather than strftime("%b"),
    which is locale-dependent.
  * WD_ALIGN_PARAGRAPH.RIGHT.CENTER replaced with CENTER. Chained enum access
    resolved to CENTER on 3.11 and raises on 3.12; the signature block keeps
    its right-hand indent from the Right_Aligned_Narrow style, with the text
    centred inside it.
  * paragraph.styles / run.font_name / run.font_size assignments corrected to
    paragraph.style / run.font.name / run.font.size — the originals set
    attributes that did not exist, so they silently did nothing.
"""

import os
from datetime import datetime

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

RULE = "=" * 76


class DocumentError(Exception):
    pass


def set_paragraph_spacing(paragraph, line_spacing, space_after):
    fmt = paragraph.paragraph_format
    fmt.line_spacing = line_spacing
    fmt.space_after = Pt(space_after)


def set_page_margin(document, left, right, top, bottom):
    for section in document.sections:
        section.left_margin = Inches(left)
        section.right_margin = Inches(right)
        section.top_margin = Inches(top)
        section.bottom_margin = Inches(bottom)


def set_font_for_file_document(document, font_name, font_size):
    style = document.styles["Normal"]
    style.font.name = font_name
    style.font.size = Pt(font_size)

    char_style = None
    for s in document.styles:
        if s.type == WD_STYLE_TYPE.CHARACTER and s.name == "Default Character":
            char_style = s
            break
    if char_style is None:
        char_style = document.styles.add_style(
            "Default Character", WD_STYLE_TYPE.CHARACTER
        )
    char_style.font.name = font_name
    char_style.font.size = Pt(font_size)

    for paragraph in document.paragraphs:
        paragraph.style = document.styles["Normal"]
        for run in paragraph.runs:
            run.font.name = font_name
            run.font.size = Pt(font_size)


def _blank(value):
    return value is None or str(value).strip() in ("", "NIL")


def _t(value):
    """Documents should never print the word None."""
    return "" if value is None else str(value)


def _rule(doc, spacing=1):
    p = doc.add_paragraph(RULE)
    set_paragraph_spacing(p, spacing, 0)
    return p


def _line(doc, text, spacing=1):
    p = doc.add_paragraph(text)
    set_paragraph_spacing(p, spacing, 0)
    return p


def build_document(data, msg_type):
    """Build the document in memory and return it. Does not write to disk."""
    is_ip = msg_type == "ip"

    date_month = _t(data.get("Date_month"))
    date = _t(data.get("Date"))
    msgno = _t(data.get("MsgNo"))
    beps_id = data.get("Beps_ID") or data.get("BEPS_ID")
    transcribed_by = data.get("TxbdBy")

    doc = Document()
    set_font_for_file_document(doc, "Arial", 12)
    set_page_margin(doc, 0.6, 0.5, 0.3, 0.5)

    styles = doc.styles
    narrow = styles.add_style("Right_Aligned_Narrow", WD_STYLE_TYPE.PARAGRAPH)
    narrow.base_style = styles["Normal"]
    narrow.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    narrow.paragraph_format.left_indent = Inches(5)

    p = doc.add_paragraph("SECRET")
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    if is_ip and not _blank(beps_id):
        doc.add_paragraph(
            "WAN No.CEC-KOL-BEPS-    /" + date_month
            + "\t\t\t     Dt. " + date + "    \t\t\t   M/IMMDT"
        )
    elif is_ip:
        doc.add_paragraph(
            "WAN No.CEC-KOL \t/" + date_month
            + "\t\t\t     Dt. " + date + "    \t\t\t   M/IMMDT"
        )
    else:
        doc.add_paragraph(
            "WAN No.CEC-KOL \t\t/" + date_month
            + "\t\t\t     Dt. " + date + "    \t\t\t   M/IMMDT"
        )

    _line(doc, "From\t::\t" + _t(data.get("Fromstn")) + "  " + _t(data.get("Fromadd")))
    _line(doc, "To\t::\t" + _t(data.get("Tostn")) + "  " + _t(data.get("Toadd")))
    _line(doc, "Info\t::\t" + _t(data.get("Infostn")) + "  " + _t(data.get("Infoadd")))

    # The by-hand line is unconditional on IP but depends on a transcriber
    # on VOIP — matching the two originals.
    if is_ip or not _blank(transcribed_by):
        _line(doc, "\t::\tKolkata\t\tCommissioner(EZ) - By Hand")

    _rule(doc)
    _line(
        doc,
        "No.2/2/CEC(KOL)/2015-" + msgno
        + "\t\t\t\t\t\t              Date : " + date,
    )
    _rule(doc)

    _line(doc, "Link: " + _t(data.get("Link")))
    _line(
        doc,
        "Message Type: " + _t(data.get("Msgtype"))
        + "\t\t\t\t\t\t\t Language: " + _t(data.get("Lang")),
    )
    _line(doc, "Event ID\t:  " + _t(data.get("EventID")))

    if is_ip and not _blank(beps_id):
        _line(doc, "BEPS ID      :  " + _t(beps_id))

    _line(doc, "Classification:  " + _t(data.get("Classfcn")))
    _line(doc, "Start Time\t:  " + _t(data.get("St_Tm")))
    _line(doc, "End Time\t:  " + _t(data.get("Ed_Tm")))

    if not is_ip:
        _line(
            doc,
            "Calling No.\t:  " + _t(data.get("ClgNo"))
            + "   (" + _t(data.get("ClgCty")) + ")",
        )
    _line(doc, "Calling Party\t:  " + _t(data.get("ClgPty")))
    if not is_ip:
        _line(
            doc,
            "Called No.\t:  " + _t(data.get("CldNo"))
            + "   (" + _t(data.get("CldCty")) + ")",
        )
    _line(doc, "Called Party\t:  " + _t(data.get("CldPty")))

    _line(doc, "Logged By\t\t: " + _t(data.get("LgdBy")))
    if not _blank(transcribed_by):
        _line(doc, "Transcribed By \t: " + _t(transcribed_by))
    if is_ip and not _blank(beps_id):
        _line(doc, "Filtered By       : BEPS")
    _line(doc, "Prepared By\t\t: " + _t(data.get("PrepBy")))

    _rule(doc)
    _line(doc, "Category: " + _t(data.get("Catgy")))
    _rule(doc)
    _line(doc, "Subject: " + _t(data.get("Sub")))
    _rule(doc)

    gist = doc.add_paragraph(_t(data.get("Gist")))
    if is_ip:
        gist.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY_HI
    set_paragraph_spacing(gist, 1, 0)
    _rule(doc)

    # Ref layout genuinely differs between the two originals.
    if is_ip:
        _line(doc, "Ref: ", spacing=2)
        ref_p = doc.add_paragraph(_t(data.get("Ref")))
        ref_p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY_HI
    else:
        _line(doc, "Ref: " + _t(data.get("Ref")), spacing=2)

    _rule(doc)
    _line(doc, "Comments: " + _t(data.get("Cmnt")))

    osint = data.get("Osint")
    if is_ip:
        _rule(doc)
        _line(doc, "OSINT Info: ", spacing=2)
        _line(doc, _t(osint))
        _rule(doc, spacing=4)
    else:
        _rule(doc, spacing=3)
        if not _blank(osint):
            _line(doc, "OSINT Info: ", spacing=2)
            _line(doc, _t(osint))
            _rule(doc, spacing=4)

    sign = doc.add_paragraph(
        "Additional Commissioner (Tech)\nCEC Kolkata", style="Right_Aligned_Narrow"
    )
    # Block sits on the right (via the style's 5" indent); text centred in it.
    sign.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_paragraph_spacing(sign, 1, 0)

    return doc


def document_filename(data):
    """<YYYY_MM_DD>_Kolkata_<msgno>_Main.docx, as before."""
    date = _t(data.get("Date"))
    try:
        date_name = datetime.strptime(date, "%d.%m.%Y").strftime("%Y_%m_%d")
    except ValueError:
        date_name = datetime.now().strftime("%Y_%m_%d")
    return f"{date_name}_Kolkata_{_t(data.get('MsgNo'))}_Main.docx"


def generate_document(data, destination_folder, msg_type, extra=None):
    """
    Build and save the report. Returns the path written.

    destination_folder is supplied by the caller and already exists — the
    intercept material was copied into it first.
    """
    if extra:
        data = dict(data)
        data.update(extra)

    try:
        doc = build_document(data, msg_type)
    except Exception as e:
        raise DocumentError(f"Could not build the document: {e}") from e

    try:
        os.makedirs(destination_folder, exist_ok=True)
        path = os.path.join(destination_folder, document_filename(data))
        doc.save(path)
    except OSError as e:
        raise DocumentError(f"Could not save the document: {e}") from e

    return path
