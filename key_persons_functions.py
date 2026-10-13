# =============================================================================
# KEY PERSONS FILE  ->  <query>_key_persons.json  (input for network_diagram.py)
# =============================================================================
_PHONE_RE = re.compile(r"\+?\d[\d\s\-]{6,}\d")


def key_persons_path(query: str, output_dir: str = OUTPUT_DIR) -> str:
    docx, _ = output_paths(query, "key_persons", output_dir)
    return os.path.splitext(docx)[0] + ".json"


def _key_persons_table(body: str) -> list[list[str]]:
    m = re.search(r"^##\s*\d+\.\s*KEY PERSONS\b.*?$(.*?)(?=^##\s*\d+\.|\Z)", body,
                  flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    return [[c.strip() for c in ln.strip().strip("|").split("|")]
            for ln in m.group(1).splitlines()
            if ln.strip().startswith("|") and not re.fullmatch(r"\|?[\s:\-|]+\|?", ln.strip())]


def save_key_persons(body: str, records: list[dict], facts: dict, query: str, output_dir: str) -> str | None:
    """Read the KEY PERSONS table the model wrote and save every person who has a phone number.
    Numbers are kept only if they really occur in the records (header numbers or call text),
    so a number the model mistyped never reaches the database search."""
    rows = _key_persons_table(body)
    if len(rows) < 2:
        log.warning("KEY PERSONS table not found; key persons file not written")
        return None
    header = [h.lower() for h in rows[0]]
    col = lambda word, default: next((i for i, h in enumerate(header) if word in h), default)
    ni, nu, ro = col("name", 1), col("number", 2), col("role", 3)

    known = {}                                  # number key -> exact number as written in the records
    for r in records:
        for n in (r["calling_number"], r["called_number"]):
            if _number_key(n):
                known.setdefault(_number_key(n), n.strip())
        for n in _PHONE_RE.findall(r["message"]):
            known.setdefault(_number_key(n), re.sub(r"[\s\-]", "", n))

    persons, seen = [], {}
    for row in rows[1:]:
        get = lambda i: row[i] if i < len(row) else ""
        name = re.sub(r"\*+", "", re.split(r"<br\s*/?>", get(ni), flags=re.IGNORECASE)[0]).strip()
        numbers = []
        for n in _PHONE_RE.findall(get(nu)):
            k = _number_key(n)
            if k in known and known[k] not in numbers:
                numbers.append(known[k])
            elif k not in known:
                log.warning("Key person %s: number %s not found in the records - skipped", name, n)
        if not numbers:
            continue                            # mentioned-only persons: nothing to search
        hit = next((seen[_number_key(n)] for n in numbers if _number_key(n) in seen), None)
        if hit is not None:                     # same person listed twice: merge
            for n in numbers:
                if n not in hit["numbers"]:
                    hit["numbers"].append(n)
            continue
        if name.lower().startswith("name not given"):          # keep an alias like ('Bhai') if given
            alias = re.search(r"[\'\"‘“](.+?)[\'\"’”]", name)
            name = alias.group(1) if alias else ""
        p = {"name": name,
             "numbers": numbers, "role": re.sub(r"<br\s*/?>", " ", get(ro)).strip()}
        persons.append(p)
        for n in numbers:
            seen[_number_key(n)] = p

    data = {"query": query, "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "categories": sorted(facts["category_counts"]), "key_persons": persons}
    path = key_persons_path(query, output_dir)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    log.info("Key persons file: %s (%d persons)", path, len(persons))
    return path


