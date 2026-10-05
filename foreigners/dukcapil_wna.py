"""WNI / WNA split out of Dukcapil aggregate PDF tables (reuses konghucu.pdf_tables)."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

import pandas as pd

from konghucu.religion import norm_label, parse_count, semester_from_text, year_from_text

from .nationality import LONG_COLUMNS, WNA_RE, WNI_RE

Table = Sequence[Sequence[Optional[str]]]


def tables_to_wna_long(tables: List[Table], ref: str, year: Optional[int], semester: Optional[int],
                       province_code: Optional[str], region_level: str = "kecamatan") -> pd.DataFrame:
    rows = []
    for t in tables:
        if not t or len(t) < 2:
            continue
        header_idx, wna_cols, wni_cols = None, [], []
        for i in range(min(4, len(t))):
            cells = [(j, c or "") for j, c in enumerate(t[i])]
            wna = [j for j, c in cells if WNA_RE.search(c) and not WNI_RE.search(c)]
            wni = [j for j, c in cells if WNI_RE.search(c)]
            if wna:
                header_idx, wna_cols, wni_cols = i, wna, wni
                break
        if header_idx is None:
            continue
        for r in t[header_idx + 1:]:
            if not r or not r[0]:
                continue
            name = str(r[0]).strip()
            if not norm_label(name) or norm_label(name) in {"no", "no.", "kecamatan", "kabupaten/kota"}:
                continue
            for j in wna_cols:
                if j < len(r):
                    rows.append({"source": "dukcapil", "province_code": province_code, "region_name": name,
                                 "region_level": region_level, "nationality": "WNA", "permit_type": "RESIDENT",
                                 "year": year, "count": parse_count(r[j]), "ref": ref})
            for j in wni_cols[:1]:
                if j < len(r):
                    rows.append({"source": "dukcapil", "province_code": province_code, "region_name": name,
                                 "region_level": region_level, "nationality": "WNI", "permit_type": "RESIDENT",
                                 "year": year, "count": parse_count(r[j]), "ref": ref})
    df = pd.DataFrame(rows, columns=LONG_COLUMNS)
    df["semester"] = semester
    return df


def extract_pdf(path: str | Path, province_code: Optional[str], year: Optional[int] = None,
                semester: Optional[int] = None, region_level: str = "kecamatan") -> pd.DataFrame:
    try:
        import pdfplumber  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install pdfplumber") from e
    path = Path(path)
    tables, head = [], ""
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i < 3:
                head += (page.extract_text() or "") + "\n"
            tables.extend(page.extract_tables() or [])
    year = year or year_from_text(head) or year_from_text(path.name)
    semester = semester or semester_from_text(head) or semester_from_text(path.name)
    return tables_to_wna_long(tables, f"pdf:{path.name}", year, semester, province_code, region_level)
