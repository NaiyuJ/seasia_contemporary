"""Find the population-by-religion table inside BPS 'Dalam Angka' PDFs and show how
pdfplumber sees it, so the extractor can be written against the real layout.

    python scripts/pdf_find_religion.py data/raw/pubs/6101_5bbbe5408991b1cf07f8966e.pdf [...]
"""
import logging
import re
import sys

import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)  # 'Cannot set gray stroke color' noise

RELS = ["islam", "kristen", "protestan", "katolik", "hindu", "budha", "buddha", "konghucu", "khonghucu", "khong hu cu"]
STRONG = re.compile(r"(?i)agama yang dianut|menurut (kecamatan dan )?agama|by religion|pemeluk agama|penganut agama")


def score(text: str) -> int:
    t = text.lower()
    return sum(r in t for r in RELS) + (3 if STRONG.search(t) else 0)


from konghucu import dalam_angka as da

force = "--force" in sys.argv
for path in [a for a in sys.argv[1:] if not a.startswith("--")]:
    with pdfplumber.open(path) as pdf:
        texts = [(i, p.extract_text() or "") for i, p in enumerate(pdf.pages)]
        ranked = sorted(((score(t), i) for i, t in texts), reverse=True)
        print(f"==== {path}: {len(pdf.pages)} pages; best pages (score, index): {ranked[:6]}")
        for sc, i in ranked[:2]:
            if sc < 4 and not force:
                break
            page = pdf.pages[i]
            print(f"---- page {i} text (first 2500 chars)")
            print(texts[i][:2500])
            for k, tb in enumerate(page.extract_tables() or []):
                print(f"---- page {i} table {k}: {len(tb)} rows x {max(len(r) for r in tb)} cols")
                for row in tb[:25]:
                    print("   | ".join("" if c is None else str(c).replace("\n", " ")[:18] for c in row))
            wrows = da.rows_from_words(page)
            print(f"---- page {i} rows from word positions: {len(wrows)}")
            for row in wrows[:25]:
                print("   | ".join(str(c)[:18] for c in row))
