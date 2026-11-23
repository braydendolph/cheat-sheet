"""The cheat sheet text format."""
from __future__ import annotations


def parse_sheet(text: str) -> list:
    """Turn a sheet into pages -> sections -> rows.

    Returns ``[{"title": str, "sections": [{"title": str, "rows": [row, ...]}]}]``
    where each row is ``(kind, key, [cells...])`` and kind is
    ``"row"``, ``"head"`` (a ``> | col | col`` line) or ``"note"``.
    """
    pages = []
    page = None
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("## "):
            if page is None:
                page = {"title": "", "sections": []}
                pages.append(page)
            section = {"title": line[3:].strip(), "rows": []}
            page["sections"].append(section)
            continue
        if line.startswith("# "):
            page = {"title": line[2:].strip(), "sections": []}
            pages.append(page)
            section = None
            continue
        if page is None:
            page = {"title": "", "sections": []}
            pages.append(page)
        if section is None:
            section = {"title": "", "rows": []}
            page["sections"].append(section)
        if line.startswith(">"):
            cells = [c.strip() for c in line[1:].split("|")]
            section["rows"].append(("head", cells[0], cells[1:]))
        elif "|" in line:
            cells = [c.strip() for c in line.split("|")]
            section["rows"].append(("row", cells[0], cells[1:]))
        else:
            section["rows"].append(("note", None, [line]))
    for p in pages:
        p["sections"] = [s for s in p["sections"] if s["rows"] or s["title"]]
    return [p for p in pages if p["sections"]]


def distribute(sections: list, ncols: int) -> list:
    """Split sections into columns, keeping reading order and balancing height."""
    if not sections:
        return []
    n = max(1, min(ncols, len(sections)))
    weights = [len(s["rows"]) + (1.6 if s["title"] else 0) + 0.9 for s in sections]
    target = sum(weights) / n
    cols = [[]]
    acc = 0.0
    for s, w in zip(sections, weights):
        if cols[-1] and len(cols) < n and acc + w / 2 > target * len(cols):
            cols.append([])
        cols[-1].append(s)
        acc += w
    return cols
