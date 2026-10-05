"""Religion tables out of Dukcapil 'Data Agregat Kependudukan' PDFs.

Formats differ by kabupaten, so this is deliberately heuristic: find tables with a
header row containing religion names and a first column with place names, and
pull the numbers. Always eyeball a sample of the output against the PDF.
Requires `pip install pdfplumber`.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

import pandas as pd

from .religion import (LONG_COLUMNS, canonical_religion, norm_label, norm_unit_name, parse_count,
                       semester_from_text, unit_level, year_from_text)

Table = Sequence[Sequence[Optional[str]]]


def _header_map(row: Sequence[Optional[str]]):
    rel = [(i, canonical_religion(c)) for i, c in enumerate(row) if c]
    rel = [(i, r) for i, r in rel if r is not None]
    return rel


def tables_to_long(tables: List[Table], ref: str, year: Optional[int], semester: Optional[int],
                   province_code: Optional[str] = None, source: str = "pdf") -> pd.DataFrame:
    """Pure function over extracted tables (lists of rows) so it can be unit-tested."""
    rows = []
    for t in tables:
        if not t or len(t) < 2:
            continue
        header_idx, rel = None, []
        for i in range(min(4, len(t))):  # header can span a few rows
            cand = _header_map([(c or "") for c in t[i]])
            if len(cand) >= 2:
                header_idx, rel = i, cand
                break
        if header_idx is None:
            continue
        for r in t[header_idx + 1:]:
            if not r or not r[0]:
                continue
            name = str(r[0]).strip()
            nm = norm_label(name)
            if not nm or nm in {"no", "no.", "kecamatan", "kabupaten/kota", "desa/kelurahan"}:
                continue
            for i, religion in rel:
                if i >= len(r):
                    continue
                rows.append({"source": source, "province_code": province_code, "unit_code": None,
                             "unit_name": name, "year": year, "semester": semester, "religion": religion,
                             "count": parse_count(r[i]), "ref": ref})
    df = pd.DataFrame(rows, columns=LONG_COLUMNS)
    df["level"] = df["unit_name"].map(unit_level)
    df["unit_name_norm"] = df["unit_name"].map(norm_unit_name)
    return df


def extract_pdf(path: str | Path, province_code: Optional[str] = None, year: Optional[int] = None,
                semester: Optional[int] = None) -> pd.DataFrame:
    try:
        import pdfplumber  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install pdfplumber") from e
    path = Path(path)
    tables: List[Table] = []
    text_head = ""
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i < 3:
                text_head += (page.extract_text() or "") + "\n"
            for t in page.extract_tables() or []:
                tables.append(t)
    year = year or year_from_text(text_head) or year_from_text(path.name)
    semester = semester or semester_from_text(text_head) or semester_from_text(path.name)
    return tables_to_long(tables, ref=f"pdf:{path.name}", year=year, semester=semester,
                          province_code=province_code)
