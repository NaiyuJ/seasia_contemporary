"""BPS provincial tables on foreign nationals, via the BPS Web API."""
from __future__ import annotations

import time
from typing import List, Optional

import pandas as pd

from konghucu.bps_api import list_static_tables, view_static_table
from konghucu.htmltable import read_html_tables
from konghucu.religion import PROVINCES, norm_label, parse_count, year_from_text

from .nationality import LONG_COLUMNS, header_role, norm_kanim

KEYWORDS = ("orang asing", "izin tinggal", "kebangsaan", "tenaga kerja asing", "warga negara asing")


def search_all_provinces(session, key: str, keywords=KEYWORDS, sleep_s: float = 0.2) -> pd.DataFrame:
    rows, seen = [], set()
    for code in PROVINCES:
        for kw in keywords:
            try:
                found = list_static_tables(session, f"{code}00", kw, key)
            except RuntimeError as e:
                print(f"  {code} '{kw}': {e}")
                continue
            for r in found:
                k = (r["domain"], r.get("table_id"))
                if k in seen:
                    continue
                seen.add(k)
                rows.append({"domain": r["domain"], "province_code": code, "table_id": r.get("table_id"),
                             "title": r.get("title"), "subj": r.get("subj"), "updt_date": r.get("updt_date"),
                             "keyword": kw})
            time.sleep(sleep_s)
    df = pd.DataFrame(rows, columns=["domain", "province_code", "table_id", "title", "subj", "updt_date", "keyword"])
    t = df["title"].fillna("").map(norm_label)
    df["by_nationality"] = t.str.contains(r"kebangsaan|kewarganegaraan|negara asal|nationality", regex=True)
    return df


def parse_foreign_html(html: str, province_code: str, year: Optional[int], ref: str,
                       source: str = "bps") -> pd.DataFrame:
    """Nationality x (permit | year | kanim) tables, either orientation, to long form."""
    frames = []
    for t in read_html_tables(html):
        if t.shape[1] < 2:
            continue
        row_labels = t.iloc[:, 0].astype(str).tolist()
        col_labels = [str(c) for c in t.columns[1:]]
        row_roles = [header_role(x) for x in row_labels]
        col_roles = [header_role(x) for x in col_labels]
        n_row_nat = sum(r == "nationality" for r, _ in row_roles)
        n_col_nat = sum(r == "nationality" for r, _ in col_roles)
        if max(n_row_nat, n_col_nat) < 2:
            continue
        nat_on_rows = n_row_nat >= n_col_nat

        def resolve(role, val, on_nat_axis):
            # 'Jumlah' means nationality TOTAL on the nationality axis, permit TOTAL on the other
            if role == "total":
                return ("nationality", "TOTAL") if on_nat_axis else ("permit", "TOTAL")
            return role, val

        for i, rl in enumerate(row_labels):
            rrole, rval = resolve(*row_roles[i], nat_on_rows)
            for j, cl in enumerate(col_labels):
                crole, cval = resolve(*col_roles[j], not nat_on_rows)
                nat = rval if (nat_on_rows and rrole == "nationality") else (cval if (not nat_on_rows and crole == "nationality") else None)
                if nat is None:
                    continue
                # the non-nationality axis supplies permit / year / kanim; else fall back to table defaults
                other_role, other_val = (crole, cval) if nat_on_rows else (rrole, rval)
                permit = other_val if other_role == "permit" else None
                yr = int(other_val) if other_role == "year" else year
                region_name, level = (norm_kanim(other_val), "kanim") if other_role == "kanim" \
                    else (PROVINCES.get(province_code, province_code), "province")
                if other_role == "other" and other_val is None and not nat_on_rows:
                    # rows are plain place names under nationality columns: treat as kabupaten rows
                    region_name, level = rl.strip(), "kabupaten"
                val = parse_count(t.iat[i, j + 1])
                frames.append({"source": source, "province_code": province_code, "region_name": region_name,
                               "region_level": level, "nationality": nat, "permit_type": permit,
                               "year": yr, "count": val, "ref": ref})
    return pd.DataFrame(frames, columns=LONG_COLUMNS)


def fetch_tables(session, catalogue: pd.DataFrame, key: str, sleep_s: float = 0.3,
                 raw_dir: Optional[str] = None) -> pd.DataFrame:
    from pathlib import Path
    parts = []
    for rec in catalogue.itertuples(index=False):
        data = view_static_table(session, rec.domain, rec.table_id, key)
        html = data.get("table") or ""
        if raw_dir:
            Path(raw_dir).mkdir(parents=True, exist_ok=True)
            (Path(raw_dir) / f"bps_foreign_{rec.domain}_{rec.table_id}.html").write_text(html, encoding="utf-8")
        if not html:
            continue
        year = year_from_text(data.get("title") or rec.title)
        try:
            parts.append(parse_foreign_html(html, str(rec.province_code), year, f"bps:{rec.domain}:{rec.table_id}"))
        except ValueError:
            continue
        time.sleep(sleep_s)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=LONG_COLUMNS)
