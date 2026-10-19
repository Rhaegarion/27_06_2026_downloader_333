"""
network_diagram.py
------------------
1st-level call network diagrams for every key person in a report.

Input : <query>_key_persons.json, written by report_generator.py when a report is generated
        { "query": ..., "categories": [...], "key_persons": [{"name", "numbers": [...], "role"}, ...] }
Data  : cobra MySQL database, table final_table_voip. ONLY calls whose category is one of the
        categories in the key persons file are used.
Output: <LINK_DIAGRAMS_PARENT>/link_diagrams/<phone number>.png  (one image per key person)
        + index.json in the same folder describing every image.

Each diagram: the key person in the centre, every person they called / were called by around them,
lines labelled with the number of calls (total, plus outgoing / incoming), and - if those contacts
also called EACH OTHER - grey dashed lines between them with their call count.
A key person whose whole network is already fully shown in another key person's diagram
(e.g. two people linked by a single call) does not get a duplicate image.

Streamlit (button in the frontend):
    from network_diagram import show_network_diagrams, render_results
    if st.button("Network Diagrams"):
        show_network_diagrams(kp_path)                      # query cobra, draw, display
    elif "network_diagram_results" in st.session_state:     # keep showing them after reruns
        render_results(st.session_state["network_diagram_results"])

Command line test:
    python network_diagram.py "C:\\path\\to\\<query>_key_persons.json"
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")                     # no screen needed; safe inside Streamlit threads
import matplotlib.pyplot as plt           # noqa: E402
from matplotlib.lines import Line2D       # noqa: E402

log = logging.getLogger("network_diagram")

# =============================================================================
# CONFIG - replace the placeholders
# =============================================================================
COBRA_DB = {                              # PLACEHOLDERS - real connection details
    "host": "localhost",
    "port": 3306,
    "user": "DB_USER",
    "password": "DB_PASSWORD",
    "database": "cobra",
}
TABLE = "final_table_voip"
COLUMNS = {                               # PLACEHOLDERS - real column names in final_table_voip
    "calling_number": "calling_number",
    "called_number": "called_number",
    "calling_party": "calling_party",     # set to None if the table has no name columns
    "called_party": "called_party",
    "category": "category",
}
KEY_PERSONS_FILE = r"C:\PATH\TO\REPORTS\query_key_persons.json"   # PLACEHOLDER (default input)
LINK_DIAGRAMS_PARENT = r"C:\PATH\TO\OUTPUT"                         # PLACEHOLDER - 'link_diagrams' is created here

TOP_N_CONTACTS = 30            # contacts drawn per diagram (by number of calls); the rest are counted in a note.
                               # Contacts who are themselves key persons are always drawn.
SHOW_CONTACT_LINKS = True      # also draw calls between the contacts themselves (option b)
IMAGE_DPI = 130

# colours
C_KEY, C_CONTACT, C_ALSO_KEY = "#C62828", "#90CAF9", "#FFB300"
C_OUT, C_IN, C_BOTH, C_BETWEEN = "#2E7D32", "#1565C0", "#8E24AA", "#9E9E9E"

_JUNK_NAMES = {"", "unknown", "unk", "na", "n/a", "none", "nil", "-", "--", "null", "not known",
               "name not given", "0"}


# =============================================================================
# DATABASE
# =============================================================================
def _connect():
    import mysql.connector
    return mysql.connector.connect(**COBRA_DB)


def _run_query(conn, sql: str, params: list) -> list[tuple]:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def _q(col_key: str) -> str:
    return f"`{COLUMNS[col_key]}`"


def _name_cols() -> str:
    c, d = COLUMNS.get("calling_party"), COLUMNS.get("called_party")
    return f"MAX(`{c}`), MAX(`{d}`)" if c and d else "NULL, NULL"


def _category_filter(categories: list[str]) -> tuple[str, list]:
    if not categories:
        log.warning("No categories in key persons file - searching ALL categories")
        return "1=1", []
    return f"{_q('category')} IN ({', '.join(['%s'] * len(categories))})", list(categories)


def fetch_person_calls(conn, number: str, categories: list[str]) -> tuple[list[tuple], str]:
    """All calls to/from `number` in the given categories, grouped per (calling, called) pair.
    Exact number first; if nothing matches, falls back to the last 10 digits."""
    cat_sql, cat_params = _category_filter(categories)
    base = (f"SELECT {_q('calling_number')}, {_q('called_number')}, COUNT(*), {_name_cols()} "
            f"FROM `{TABLE}` WHERE {cat_sql} AND ({{cond}}) "
            f"GROUP BY {_q('calling_number')}, {_q('called_number')}")
    rows = _run_query(conn, base.format(cond=f"{_q('calling_number')} = %s OR {_q('called_number')} = %s"),
                      cat_params + [number, number])
    if rows:
        return rows, "exact"
    last10 = re.sub(r"\D", "", number)[-10:]
    if len(last10) < 10:
        return [], "none"
    rows = _run_query(conn, base.format(cond=f"{_q('calling_number')} LIKE %s OR {_q('called_number')} LIKE %s"),
                      cat_params + ["%" + last10, "%" + last10])
    return rows, ("last10" if rows else "none")


def fetch_links_between(conn, raw_numbers: list[str], categories: list[str]) -> list[tuple]:
    """Calls where BOTH sides are among `raw_numbers` (used for contact-to-contact lines)."""
    if len(raw_numbers) < 2:
        return []
    cat_sql, cat_params = _category_filter(categories)
    ph = ", ".join(["%s"] * len(raw_numbers))
    sql = (f"SELECT {_q('calling_number')}, {_q('called_number')}, COUNT(*) FROM `{TABLE}` "
           f"WHERE {cat_sql} AND {_q('calling_number')} IN ({ph}) AND {_q('called_number')} IN ({ph}) "
           f"GROUP BY {_q('calling_number')}, {_q('called_number')}")
    return _run_query(conn, sql, cat_params + list(raw_numbers) + list(raw_numbers))


# =============================================================================
# BUILD ONE PERSON'S NETWORK
# =============================================================================
def _key(num) -> str:
    """Comparison key for a phone number: digits only, '00' prefix dropped, last 10 digits."""
    d = re.sub(r"\D", "", str(num or ""))
    if d.startswith("00"):
        d = d[2:]
    return d[-10:] if len(d) >= 10 else d


def _clean_name(n) -> str:
    n = str(n or "").strip()
    return "" if n.lower() in _JUNK_NAMES else n


def build_network(conn, person: dict, categories: list[str], top_n: int, key_numbers: set = frozenset()) -> dict:
    own_keys = {_key(n) for n in person["numbers"]}
    contacts = defaultdict(lambda: {"raw": Counter(), "names": Counter(), "out": 0, "in": 0})
    own_raw, own_names, match_modes = Counter(), Counter(), []
    star_edges = set()                                   # frozenset({own number key, contact key})

    for number in person["numbers"]:
        rows, mode = fetch_person_calls(conn, number, categories)
        match_modes.append(mode)
        for calling, called, cnt, calling_name, called_name in rows:
            kc, kd = _key(calling), _key(called)
            if kc in own_keys and kd in own_keys:
                continue                                 # between the person's own numbers
            if kc in own_keys:
                c, direction, me, me_raw, me_name, c_raw, c_name = kd, "out", kc, calling, calling_name, called, called_name
            elif kd in own_keys:
                c, direction, me, me_raw, me_name, c_raw, c_name = kc, "in", kd, called, called_name, calling, calling_name
            else:
                continue
            if not c:
                continue
            contacts[c][direction] += cnt
            contacts[c]["raw"][str(c_raw).strip()] += cnt
            if _clean_name(c_name):
                contacts[c]["names"][_clean_name(c_name)] += cnt
            own_raw[str(me_raw).strip()] += cnt
            if _clean_name(me_name):
                own_names[_clean_name(me_name)] += cnt
            star_edges.add(frozenset((me, c)))

    ranked = sorted(contacts, key=lambda k: -(contacts[k]["out"] + contacts[k]["in"]))
    # contacts who are themselves key persons are always drawn; the rest fill up to top_n by call count
    must = [k for k in ranked if k in key_numbers]
    shown = must + [k for k in ranked if k not in key_numbers][:max(top_n - len(must), 0)]
    shown.sort(key=lambda k: -(contacts[k]["out"] + contacts[k]["in"]))

    between = Counter()                                  # frozenset({contact key, contact key}) -> calls
    if SHOW_CONTACT_LINKS and len(shown) > 1:
        raw_list = sorted({r for k in shown for r in contacts[k]["raw"]})
        shown_set = set(shown)
        for calling, called, cnt in fetch_links_between(conn, raw_list, categories):
            a, b = _key(calling), _key(called)
            if a != b and a in shown_set and b in shown_set:
                between[frozenset((a, b))] += cnt

    return {
        "person": person,
        "own_keys": own_keys,
        "own_name_db": own_names.most_common(1)[0][0] if own_names else "",
        "contacts": {k: contacts[k] for k in ranked},
        "shown": shown,
        "between": between,
        "star_edges": star_edges,
        "match": "last10" if "last10" in match_modes and "exact" not in match_modes
                 else ("exact" if "exact" in match_modes else "none"),
    }


def drawn_edges(net: dict) -> set:
    """Edges actually visible in this person's image (for duplicate detection)."""
    shown = set(net["shown"])
    edges = {e for e in net["star_edges"] if (e - net["own_keys"]) & shown}
    return edges | set(net["between"])


# =============================================================================
# DRAWING
# =============================================================================
def _label(raw: Counter, names: Counter) -> str:
    number = raw.most_common(1)[0][0] if raw else ""
    name = names.most_common(1)[0][0] if names else ""
    return f"{number}\n{name}" if name else number


def draw_network(net: dict, path: str, categories: list[str], key_numbers_elsewhere: set,
                 key_names: dict | None = None) -> None:
    """key_numbers_elsewhere: number keys of the OTHER key persons (highlighted);
    key_names: number key -> name from the report, used when cobra has no name for that number."""
    key_names = key_names or {}
    person, contacts, shown = net["person"], net["contacts"], net["shown"]
    n = len(shown)
    fig, ax = plt.subplots(figsize=(14, 14))
    lim = 1.95 if n <= 14 else 2.3
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.axis("off")

    # positions: key person in the centre, contacts on a circle (two staggered rings when crowded)
    pos = {"__KEY__": (0.0, 0.0)}
    for i, k in enumerate(shown):
        ang = math.pi / 2 - 2 * math.pi * i / max(n, 1)
        r = 1.25 if n <= 14 else (1.15 if i % 2 == 0 else 1.75)
        pos[k] = (r * math.cos(ang), r * math.sin(ang))

    totals = {k: contacts[k]["out"] + contacts[k]["in"] for k in shown}
    max_total = max(totals.values(), default=1)

    # contact <-> contact lines (behind everything)
    for pair, cnt in net["between"].items():
        a, b = tuple(pair)
        (x1, y1), (x2, y2) = pos[a], pos[b]
        ax.plot([x1, x2], [y1, y2], color=C_BETWEEN, lw=1.0 + 2.5 * cnt / max(max_total, cnt),
                ls="--", alpha=0.7, zorder=1)
        ax.text((x1 + x2) / 2, (y1 + y2) / 2, str(cnt), fontsize=7.5, color="#424242", ha="center",
                va="center", zorder=4, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=C_BETWEEN, lw=0.6))

    # key person <-> contact lines with call counts
    for k in shown:
        out_, in_ = contacts[k]["out"], contacts[k]["in"]
        tot = out_ + in_
        share = out_ / tot if tot else 0.5
        colour = C_OUT if share >= 2 / 3 else (C_IN if share <= 1 / 3 else C_BOTH)
        x, y = pos[k]
        ax.plot([0, x], [0, y], color=colour, lw=1.2 + 5.0 * tot / max_total, alpha=0.85, zorder=2)
        f = 0.6 if n <= 14 else 0.72                      # label nearer the contact -> labels spread out
        lx, ly = f * x, f * y
        ax.text(lx, ly, f"{tot} call{'s' if tot != 1 else ''}\nout {out_} | in {in_}", fontsize=7.5,
                ha="center", va="center", zorder=5, color="#212121",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=colour, lw=0.9))

    # contact nodes + labels
    for k in shown:
        x, y = pos[k]
        is_key = k in key_numbers_elsewhere
        ax.scatter([x], [y], s=300 + 700 * totals[k] / max_total, c=C_ALSO_KEY if is_key else C_CONTACT,
                   edgecolors="#37474F", linewidths=1.0, zorder=6)
        d = math.hypot(x, y) or 1
        tx, ty = x + 0.17 * x / d, y + 0.17 * y / d
        ha = "left" if x > 0.15 else ("right" if x < -0.15 else "center")
        va = "bottom" if y > 0.15 else ("top" if y < -0.15 else "center")
        names = contacts[k]["names"] or (Counter({key_names[k]: 1}) if key_names.get(k) else Counter())
        ax.text(tx, ty, _label(contacts[k]["raw"], names), fontsize=8.5, ha=ha, va=va,
                zorder=7, fontweight="bold" if is_key else "normal")

    # key person node
    name = person.get("name") or net["own_name_db"]
    ax.scatter([0], [0], s=3200, c=C_KEY, edgecolors="black", linewidths=1.5, zorder=8)
    key_label = "\n".join(([name] if name else []) + person["numbers"])
    ax.text(0, -0.2, key_label, fontsize=10, fontweight="bold", ha="center", va="top", zorder=9,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=C_KEY, lw=1.2))

    # titles, notes, legend
    total_calls = sum(c["out"] + c["in"] for c in contacts.values())
    title = f"1st-level network: {name + ' - ' if name else ''}{person['numbers'][0]}"
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.975)
    sub = (f"Categories: {', '.join(categories) or 'all'}   |   {total_calls} calls with "
           f"{len(contacts)} contact{'s' if len(contacts) != 1 else ''}")
    if len(contacts) > n:
        sub += f"   |   showing top {n} by calls (+{len(contacts) - n} more not drawn)"
    if net["match"] == "last10":
        sub += "   |   matched on last 10 digits"
    fig.text(0.5, 0.948, sub, ha="center", fontsize=10, color="#424242")

    legend = [
        Line2D([0], [0], color=C_OUT, lw=3, label="Mostly outgoing from key person"),
        Line2D([0], [0], color=C_IN, lw=3, label="Mostly incoming to key person"),
        Line2D([0], [0], color=C_BOTH, lw=3, label="Both directions"),
        Line2D([0], [0], color=C_BETWEEN, lw=2, ls="--", label="Calls between contacts"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_KEY, markersize=12, label="Key person"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_ALSO_KEY, markersize=11,
               label="Contact who is also a key person"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_CONTACT, markersize=11, label="Contact"),
    ]
    ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.06), ncol=4, fontsize=8.5,
              frameon=False)
    fig.text(0.5, 0.012, "Line labels: total calls, then 'out' = calls made BY the key person, "
             "'in' = calls received BY the key person. Line thickness and node size grow with call count.",
             ha="center", fontsize=8, color="#616161")
    fig.savefig(path, dpi=IMAGE_DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# =============================================================================
# MAIN FUNCTION
# =============================================================================
def _safe_name(query) -> str:
    """Query cleaned for use in a Windows folder name (same rules as the report file names)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(query or "").strip())
    return re.sub(r"\s+", " ", name).strip(" .")[:80].rstrip(" .") or "untitled"


def _safe_file(number: str) -> str:
    return (re.sub(r"[^\d+]", "", number) or "unknown") + ".png"


def generate_network_diagrams(key_persons_file: str = KEY_PERSONS_FILE,
                              output_parent: str = LINK_DIAGRAMS_PARENT,
                              top_n: int = TOP_N_CONTACTS) -> list[dict]:
    """
    Returns one dict per key person:
      {name, numbers, role, status, image, contacts, calls, shown, covered_by, match}
      status: 'drawn' | 'covered' (network already fully shown in another image) | 'no_calls' | 'error'
    """
    with open(key_persons_file, "r", encoding="utf-8") as fh:
        kp = json.load(fh)
    categories, persons = kp.get("categories", []), kp.get("key_persons", [])
    out_dir = os.path.join(output_parent, f"{_safe_name(kp.get('query'))}_link_diagrams")
    os.makedirs(out_dir, exist_ok=True)
    all_key_numbers = {_key(n) for p in persons for n in p.get("numbers", [])}
    key_names = {_key(n): p.get("name", "") for p in persons for n in p.get("numbers", [])}

    conn = _connect()
    try:
        nets, results = [], []
        for p in persons:
            if not p.get("numbers"):
                continue
            try:
                nets.append(build_network(conn, p, categories, top_n, all_key_numbers))
            except Exception as e:                           # noqa: BLE001
                log.exception("Network query failed for %s", p["numbers"])
                results.append({**p, "status": "error", "error": str(e), "image": None})
    finally:
        conn.close()

    # biggest networks first, so smaller ones fully contained in them are recognised as duplicates
    nets.sort(key=lambda nt: -len(nt["contacts"]))
    drawn = []                                               # (result dict, edges visible in its image)
    for net in nets:
        p = net["person"]
        base = {"name": p.get("name") or net["own_name_db"], "numbers": p["numbers"], "role": p.get("role", ""),
                "contacts": len(net["contacts"]), "shown": len(net["shown"]), "match": net["match"],
                "calls": sum(c["out"] + c["in"] for c in net["contacts"].values()), "covered_by": None,
                "image": None}
        if not net["contacts"]:
            results.append({**base, "status": "no_calls"})
            continue
        cover = next((r for r, edges in drawn if net["star_edges"] <= edges), None)
        if cover:
            results.append({**base, "status": "covered", "covered_by": cover["numbers"][0],
                            "covered_by_image": cover["image"]})
            continue
        path = os.path.join(out_dir, _safe_file(p["numbers"][0]))
        draw_network(net, path, categories, all_key_numbers - net["own_keys"], key_names)
        res = {**base, "status": "drawn", "image": path}
        results.append(res)
        drawn.append((res, drawn_edges(net)))

    order = {tuple(p.get("numbers", [])): i for i, p in enumerate(persons)}  # back to report order
    results.sort(key=lambda r: order.get(tuple(r.get("numbers", [])), 999))
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"query": kp.get("query"), "categories": categories, "diagrams": results}, fh,
                  ensure_ascii=False, indent=2)
    return results


# =============================================================================
# WORD / PDF OUTPUT
#   add_network_to_report() - run right after generate_report(): draws the diagrams, adds a
#   "Network" section (top 5 diagrams) to the report .docx/.pdf, and writes
#   <query>_network_diagrams.docx/.pdf with every diagram.
# =============================================================================
REPORT_TOP_N_DIAGRAMS = 5      # diagrams added to the report itself (most calls first)
DOC_IMAGE_WIDTH_IN = 5.8       # width of a diagram on an A4 page


def _ranked(results: list[dict]) -> list[dict]:
    """Drawn diagrams, most active first (total calls, then number of contacts)."""
    return sorted((r for r in results if r["status"] == "drawn"), key=lambda r: (-r["calls"], -r["contacts"]))


def _who(r: dict) -> str:
    return f"{r['name']} - {', '.join(r['numbers'])}" if r["name"] else ", ".join(r["numbers"])


def _caption(r: dict) -> str:
    return (f"{r['calls']} calls with {r['contacts']} contacts"
            + (f" (top {r['shown']} shown)" if r["shown"] < r["contacts"] else ""))


def _add_diagram(doc, r: dict, heading_level: int, number: int | None = None, new_page: bool = True,
                 width_in: float = DOC_IMAGE_WIDTH_IN) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches
    h = doc.add_heading((f"{number}. " if number else "") + _who(r), level=heading_level)
    h.paragraph_format.page_break_before = new_page        # never leaves an empty page, unlike a page break
    h.paragraph_format.keep_with_next = True               # heading, image and caption stay together
    if r.get("role"):
        role = doc.add_paragraph()
        role.add_run(f"Role: {r['role']}").italic = True
        role.paragraph_format.keep_with_next = True
    doc.add_picture(r["image"], width=Inches(width_in))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.paragraphs[-1].paragraph_format.keep_with_next = True
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.add_run(_caption(r)).italic = True


def _count_pages(docx_path: str) -> int | None:
    """Total pages of a .docx, laid out by MS Word (pywin32) or, failing that, LibreOffice."""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        word = doc = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(os.path.abspath(docx_path), False, True)
            doc.Repaginate()
            return int(doc.ComputeStatistics(2))                    # wdStatisticPages
        finally:
            if doc is not None:
                doc.Close(False)
            if word is not None:
                word.Quit()
            pythoncom.CoUninitialize()
    except ImportError:
        pass
    except Exception as e:                                          # noqa: BLE001
        log.warning("Word page count failed: %s", e)
    import report_generator as rg
    pages = rg._pages_via_libreoffice(docx_path)                   # returns total - 1 (cover)
    return pages + 1 if pages is not None else None


def _set_page_numbers(docx_path: str, total_pages: int | None, encl_pages: int | None = None) -> None:
    """Store the real page count as the cached value of the 'of Y' footer field (Word recalculates it
    anyway; LibreOffice shows the cached value) and, for the report, in the cover's 'Encl: ... (X pages)'."""
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document(docx_path)
    if encl_pages:
        for p in doc.paragraphs:
            if p.text.strip().startswith("Encl:"):
                for r in p.runs:
                    r.text = re.sub(r"\((\d+|__) pages?\)",
                                    f"({encl_pages} page{'s' if encl_pages != 1 else ''})", r.text)
    if total_pages:
        for sec in doc.sections:
            for par in sec.footer.paragraphs:
                waiting = False
                for el in par._p.iter():
                    if el.tag == qn("w:instrText") and re.search(r"SECTIONPAGES|NUMPAGES", el.text or ""):
                        waiting = True
                    elif waiting and el.tag == qn("w:t"):
                        el.text = str(total_pages)
                        waiting = False
    doc.save(docx_path)


def append_network_to_report(report_docx: str, results: list[dict], categories: list[str],
                             top_n: int = REPORT_TOP_N_DIAGRAMS, all_diagrams_name: str = "") -> str | None:
    """Add a new page 'Network' with the top_n most active diagrams to the report .docx,
    update its page counts and re-create its PDF. Returns the PDF path."""
    import report_generator as rg
    from docx import Document
    top = _ranked(results)[:top_n]
    if not top:
        log.info("No diagrams drawn - report left unchanged")
        return None
    doc = Document(report_docx)
    doc.add_heading("Network", level=1).paragraph_format.page_break_before = True
    intro = (f"The {len(top)} most active key-person call networks in the database (ranked by number of calls; "
             f"categories: {', '.join(categories) or 'all'}). Each diagram shows the key person in the centre, "
             "everyone they called or were called by, and the number of calls on each link.")
    if all_diagrams_name:
        intro += f" All network diagrams for this report are in {all_diagrams_name}."
    doc.add_paragraph(intro)
    for i, r in enumerate(top):
        # the first diagram shares its page with the introduction, so it is drawn a little smaller
        _add_diagram(doc, r, heading_level=2, new_page=i > 0, width_in=5.0 if i == 0 else DOC_IMAGE_WIDTH_IN)
    doc.save(report_docx)

    total = _count_pages(report_docx)                               # cover page is page 1
    _set_page_numbers(report_docx, total - 1 if total else None, encl_pages=total - 1 if total else None)
    return rg.export_pdf(report_docx)


def save_network_document(results: list[dict], query: str, categories: list[str],
                          output_dir: str) -> tuple[str | None, str | None]:
    """<query>_network_diagrams.docx/.pdf: overview table + every diagram (most active first)."""
    import report_generator as rg
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Pt
    from datetime import datetime

    drawn = _ranked(results)
    docx_path, _ = rg.output_paths(query, "network_diagrams", output_dir)
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = rg.DOC_FONT
    style.element.rPr.rFonts.set(qn("w:eastAsia"), rg.DOC_FONT)
    style.font.size = Pt(11)
    sec = doc.sections[0]
    rg._setup_page(sec)
    rg._header_classification(sec)
    rg._build_footer(sec)

    doc.add_heading(f"Network Diagrams: {query}", level=0)
    for label, value in (("Date", datetime.now().strftime("%d %B %Y")),
                         ("Categories", ", ".join(categories) or "all"),
                         ("Key persons searched", str(len(results))),
                         ("Diagrams", str(len(drawn)))):
        p = doc.add_paragraph()
        p.add_run(f"{label}: ").bold = True
        p.add_run(value)

    page_of = {id(r): i + 2 for i, r in enumerate(drawn)}           # page 1 = this overview
    rows = ["| # | Name | Number(s) | Role | Calls | Contacts | Diagram |"]
    for i, r in enumerate(sorted(results, key=lambda r: -r.get("calls", 0)), 1):
        if r["status"] == "drawn":
            where = f"Page {page_of[id(r)]}"
        elif r["status"] == "covered":
            where = f"Shown in diagram of {r['covered_by']}"
        elif r["status"] == "no_calls":
            where = "No calls in these categories"
        else:
            where = "Database error"
        rows.append(f"| {i} | {r.get('name') or '-'} | {', '.join(r['numbers'])} | {r.get('role') or '-'} | "
                    f"{r.get('calls', 0)} | {r.get('contacts', 0)} | {where} |")
    doc.add_paragraph()
    rg._flush_table(doc, rows)

    for i, r in enumerate(drawn, 1):
        _add_diagram(doc, r, heading_level=1, number=i)

    os.makedirs(output_dir, exist_ok=True)
    doc.save(docx_path)
    _set_page_numbers(docx_path, _count_pages(docx_path))
    return docx_path, rg.export_pdf(docx_path)


def add_network_to_report(query: str, report_docx: str, output_parent: str = LINK_DIAGRAMS_PARENT,
                          top_n: int = REPORT_TOP_N_DIAGRAMS) -> dict:
    """
    One call after generate_report():
      1. draws every key person's diagram into <output_parent>/<query>_link_diagrams/
      2. adds a 'Network' page with the top_n most active diagrams to the report .docx and re-makes its PDF
      3. writes <query>_network_diagrams.docx/.pdf (all diagrams) next to the report
    Returns {"results", "report_pdf", "network_docx", "network_pdf", "markdown"}  ('markdown' is ready
    for db.add_message). If the key persons file is missing, returns empty values and does nothing.
    """
    import report_generator as rg
    report_dir = os.path.dirname(os.path.abspath(report_docx))
    kp_path = rg.key_persons_path(query, report_dir)
    empty = {"results": [], "report_pdf": None, "network_docx": None, "network_pdf": None, "markdown": ""}
    if not os.path.isfile(kp_path):
        log.warning("Key persons file not found (%s) - no network diagrams", kp_path)
        return empty
    with open(kp_path, "r", encoding="utf-8") as fh:
        categories = json.load(fh).get("categories", [])

    results = generate_network_diagrams(kp_path, output_parent)
    network_docx, network_pdf = save_network_document(results, query, categories, report_dir)
    all_name = os.path.basename(network_pdf or network_docx or "")
    report_pdf = append_network_to_report(report_docx, results, categories, top_n, all_name)
    return {"results": results, "report_pdf": report_pdf, "network_docx": network_docx,
            "network_pdf": network_pdf, "markdown": results_markdown(results)}


# =============================================================================
# STREAMLIT DISPLAY
# =============================================================================
def render_results(results: list[dict]) -> None:
    import streamlit as st
    drawn = [r for r in results if r["status"] == "drawn"]
    st.subheader(f"Network diagrams ({len(drawn)})")
    for r in drawn:
        who = f"{r['name']} - " if r["name"] else ""
        st.markdown(f"**{who}{', '.join(r['numbers'])}**" + (f"  ·  {r['role']}" if r["role"] else ""))
        caption = (f"{r['calls']} calls with {r['contacts']} contacts"
                   + (f" (top {r['shown']} shown)" if r["shown"] < r["contacts"] else ""))
        try:
            st.image(r["image"], use_container_width=True, caption=caption)
        except TypeError:                                   # older Streamlit versions
            st.image(r["image"], use_column_width=True, caption=caption)
    notes = []
    for r in results:
        who = f"{r['name']} ({', '.join(r['numbers'])})" if r["name"] else ", ".join(r["numbers"])
        if r["status"] == "covered":
            notes.append(f"- {who}: all calls already shown in the diagram of {r['covered_by']}")
        elif r["status"] == "no_calls":
            notes.append(f"- {who}: no calls of these categories found in cobra")
        elif r["status"] == "error":
            notes.append(f"- {who}: database error - {r.get('error', '')}")
    if notes:
        st.markdown("**Not drawn separately:**\n" + "\n".join(notes))


def results_markdown(results: list[dict], max_width: int = 1200) -> str:
    """The diagrams as ONE markdown message (images embedded), so they can be saved and shown
    like the report: db.add_message(chat_id, "assistant", results_markdown(results)).
    The PNG files themselves stay in the link_diagrams folder."""
    import base64
    import io
    from PIL import Image

    def embed(path):
        img = Image.open(path).convert("RGB")
        if img.width > max_width:                               # keep the chat message small
            img = img.resize((max_width, int(img.height * max_width / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    parts = []
    for r in results:
        if r["status"] != "drawn":
            continue
        who = f"{r['name']} - " if r["name"] else ""
        caption = (f"{r['calls']} calls with {r['contacts']} contacts"
                   + (f" (top {r['shown']} shown)" if r["shown"] < r["contacts"] else ""))
        parts.append(f"**{who}{', '.join(r['numbers'])}**" + (f"  ·  {r['role']}" if r["role"] else "")
                     + f"\n\n![{caption}]({embed(r['image'])})\n\n*{caption}*")
    notes = []
    for r in results:
        who = f"{r['name']} ({', '.join(r['numbers'])})" if r["name"] else ", ".join(r["numbers"])
        if r["status"] == "covered":
            notes.append(f"- {who}: all calls already shown in the diagram of {r['covered_by']}")
        elif r["status"] == "no_calls":
            notes.append(f"- {who}: no calls of these categories found in cobra")
        elif r["status"] == "error":
            notes.append(f"- {who}: database error - {r.get('error', '')}")
    if notes:
        parts.append("**Not drawn separately:**\n" + "\n".join(notes))
    return "\n\n---\n\n".join(parts) if parts else "No key person had calls of these categories in cobra."


def show_network_diagrams(key_persons_file: str = KEY_PERSONS_FILE,
                          output_parent: str = LINK_DIAGRAMS_PARENT) -> list[dict]:
    """Call from the Streamlit button: queries cobra, draws, displays, and keeps the results in
    st.session_state['network_diagram_results'] so they survive Streamlit reruns."""
    import streamlit as st
    if not os.path.isfile(key_persons_file):
        st.warning("Key persons file not found - generate the report first.")
        return []
    with st.spinner("Searching cobra and drawing network diagrams..."):
        results = generate_network_diagrams(key_persons_file, output_parent)
    st.session_state["network_diagram_results"] = results
    render_results(results)
    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    for r in generate_network_diagrams(sys.argv[1] if len(sys.argv) > 1 else KEY_PERSONS_FILE):
        print(r["status"].ljust(9), r["numbers"], r["name"], "->", r["image"] or r.get("covered_by") or "")
