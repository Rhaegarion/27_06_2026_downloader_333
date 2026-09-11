"""
Word document generation — placeholder.

The real implementation lives in your existing word.py. To plug it in:

  1. Drop word.py into this folder (app/messages/).
  2. Rewrite generate_document() below to call into it, keeping the same
     signature and return value.

Keep the signature as it is: values in, path out. No Flask imports, no UI
calls, nothing reading global state. The route already commits the database row
before calling this, so a document failure cannot roll back a saved message —
it is reported to the operator as a warning and can be regenerated.

    def generate_document(values, destination_folder, msg_type, extra=None):
        from app.messages import word
        return word.build(...)          # must return the written file path
"""

from pathlib import Path


class DocumentError(Exception):
    pass


DOCUMENTS_ENABLED = False   # flip to True once word.py is wired in


def document_filename(values, msg_type):
    """Name the file after the message number, falling back to the Event ID."""
    tc = (values.get("TC_No") or "").strip()
    if tc:
        return f"{msg_type.upper()}_{tc}.docx"
    event = (values.get("Event_Id") or "message").split(",")[0].strip()
    return f"{msg_type.upper()}_{event}.docx"


def generate_document(values, destination_folder, msg_type, extra=None):
    """
    Build the Word report for a saved message.

    values            - {column: value} for the row that was just written
    destination_folder- the ...\\<msg no> folder, already created
    msg_type          - "voip" or "ip"
    extra             - display-only values that aren't columns (Extra_Add)

    Returns the path of the written document.
    """
    if not DOCUMENTS_ENABLED:
        raise DocumentError(
            "Word document generation is not wired in yet "
            "(app/messages/docx_generator.py)."
        )

    target = Path(destination_folder) / document_filename(values, msg_type)
    raise DocumentError(f"generate_document() is not implemented; wanted {target}")
