"""HTML tables -> DataFrames of *strings* with flattened multi-row headers.

pandas.read_html type-infers cells, turning Indonesian '1.200' into 1.2. We keep
every cell as text and let parse_count decide. rowspan/colspan are expanded.
"""
from __future__ import annotations

import html as _html
from typing import List

import lxml.etree
import lxml.html
import pandas as pd


def unescape_if_needed(html: str) -> str:
    """BPS serves table HTML entity-escaped inside JSON ('&lt;table&gt;'); undo that."""
    if html and "<table" not in html.lower() and "&lt;table" in html.lower():
        return _html.unescape(html)
    return html or ""


def grid_tables(html: str) -> List[List[List[str]]]:
    """Every <table> as a rectangular grid of cell strings (rowspan/colspan expanded),
    with no header inference. For messy Excel-exported tables."""
    html = unescape_if_needed(html)
    if not html or "<table" not in html.lower():
        return []
    try:
        doc = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return []
    out = []
    for table in doc.iter("table"):
        rows = [tr for tr in table.iter("tr")]
        if rows:
            out.append(_grid(rows))
    return out


def _grid(rows) -> List[List[str]]:
    """Expand rowspan/colspan into a rectangular grid of cell texts."""
    grid: List[List[str]] = []
    pending = {}  # (row, col) -> text, for rowspans
    for ri, tr in enumerate(rows):
        out: List[str] = []
        ci = 0
        cells = [c for c in tr if c.tag in ("td", "th")]
        k = 0
        while k < len(cells) or (ri, ci) in pending:
            if (ri, ci) in pending:
                out.append(pending.pop((ri, ci)))
                ci += 1
                continue
            c = cells[k]
            k += 1
            text = " ".join(c.text_content().split())
            rs, cs = int(c.get("rowspan", 1) or 1), int(c.get("colspan", 1) or 1)
            for dc in range(cs):
                out.append(text)
                for dr in range(1, rs):
                    pending[(ri + dr, ci)] = text
                ci += 1
        grid.append(out)
    width = max((len(r) for r in grid), default=0)
    return [r + [""] * (width - len(r)) for r in grid]


def read_html_tables(html: str) -> List[pd.DataFrame]:
    html = unescape_if_needed(html)
    if not html or "<table" not in html.lower():
        return []
    try:
        doc = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return []
    out = []
    for table in doc.iter("table"):
        rows = [tr for tr in table.iter("tr")]
        if not rows:
            continue
        is_header = []
        for tr in rows:
            cells = [c for c in tr if c.tag in ("td", "th")]
            in_thead = any(a.tag == "thead" for a in tr.iterancestors())
            is_header.append(in_thead or (bool(cells) and all(c.tag == "th" for c in cells)))
        n_head = 0
        while n_head < len(rows) and is_header[n_head]:
            n_head += 1
        grid = _grid(rows)
        head, body = grid[:n_head], grid[n_head:]
        if not head:
            head, body = grid[:1], grid[1:]
        width = len(grid[0]) if grid else 0
        cols = []
        for j in range(width):
            parts = []
            for h in head:
                v = h[j] if j < len(h) else ""
                if v and v not in parts:
                    parts.append(v)
            cols.append(" | ".join(parts) if parts else f"col{j}")
        # de-duplicate column names
        seen, uniq = {}, []
        for c in cols:
            seen[c] = seen.get(c, 0) + 1
            uniq.append(c if seen[c] == 1 else f"{c}.{seen[c]-1}")
        out.append(pd.DataFrame(body, columns=uniq, dtype=str))
    return out
