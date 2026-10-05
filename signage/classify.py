"""Stage 4b: split CJK text boxes into 'local' (Chinese-Indonesian) vs 'mainland'
(PRC nationals / PRC firms) vs 'ambiguous'.

Public Chinese script in Indonesia mixes two populations. Treating all of it as
Chinese-Indonesian identity display would fold the treatment (Chinese presence)
into the outcome. This stage scores each CJK box on:

  script       traditional characters lean local (older community convention);
               simplified lean mainland (weak signal: young locals also use it)
  keywords     mainland markers (regional cuisines, PRC firms, worker services)
               vs local markers (clan halls, temples, Indonesian-Chinese terms)
  co-text      Latin text in the same image: Indonesian words lean local,
               Hokkien/Hakka-derived loanwords lean local, pinyin-only leans mainland

The lexicons are a starting point. Hand-code a sample (validate-export adds a
human_sign_type column) and edit them; treat the split as a measured variable
with its own error rate, not as ground truth.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

import pandas as pd

MAINLAND_CJK = [
    "川菜", "湘菜", "东北", "東北菜", "兰州", "拉面", "沙县", "重庆", "火锅", "麻辣", "烧烤", "中国", "华为",
    "微信", "支付宝", "快递", "宿舍", "劳务", "项目部", "工程", "建设", "集团", "中建", "中铁", "中交",
    "青山", "德龙", "镍", "园区", "物流", "国际贸易", "进出口", "招聘", "中国人", "中餐", "家常菜",
]
LOCAL_CJK = [
    "公会", "宗亲", "会馆", "會館", "庙", "廟", "宫", "宮", "堂", "坛", "壇", "寺", "祠", "社", "基金会",
    "基金會", "校友会", "校友會", "印尼", "印度尼西亚", "印度尼西亞", "中华", "中華", "华社", "華社",
    "孔教", "华文", "華文", "补习", "補習", "三语", "三語", "慈善", "联谊", "聯誼", "总会", "總會",
    "同乡", "同鄉", "大伯公", "妈祖", "媽祖", "观音", "觀音", "佛堂", "道堂",
]
# Latin co-text: Indonesian everyday words and Indonesian-Chinese loanwords
INDONESIAN_WORDS = {
    "toko", "warung", "jalan", "jl", "rumah", "makan", "kopi", "apotek", "bank", "hotel", "dan", "jaya",
    "abadi", "makmur", "sejahtera", "bengkel", "salon", "klinik", "sekolah", "yayasan", "vihara", "kelenteng",
    "klenteng", "pt", "cv", "ud", "tb", "grosir", "eceran", "murah", "baru", "lama", "pusat", "cabang",
    "jam", "buka", "tutup", "dijual", "disewakan", "sewa", "ruko", "indah", "mulia", "sentosa", "bakti",
}
LOANWORDS = {"bakmi", "bakmie", "kwetiau", "kwetiaw", "bakpao", "bakso", "capcay", "cap", "go", "meh",
             "lontong", "kue", "tahu", "tauge", "mie", "mi", "kecap", "teh", "angpao", "hio", "pecinan"}
PINYIN_RE = re.compile(r"^(?:[bpmfdtnlgkhjqxzcsryw]?h?[aeiouü]{1,3}(?:ng?|r)?)+$", re.I)


def _tokens(text: str) -> List[str]:
    return [t for t in re.split(r"[^A-Za-zÀ-ÿ]+", text or "") if t]


def cotext_signal(latin_texts: Iterable[str]) -> Tuple[float, float, List[str]]:
    """(local_points, mainland_points, reasons) from Latin boxes in the same image."""
    toks = [t.lower() for s in latin_texts for t in _tokens(s)]
    if not toks:
        return 0.0, 0.0, []
    reasons, local, mainland = [], 0.0, 0.0
    indo = [t for t in toks if t in INDONESIAN_WORDS]
    loan = [t for t in toks if t in LOANWORDS]
    if indo:
        local += 1.0
        reasons.append("indonesian:" + ",".join(sorted(set(indo))[:3]))
    if loan:
        local += 1.0
        reasons.append("loanword:" + ",".join(sorted(set(loan))[:3]))
    long_toks = [t for t in toks if len(t) >= 4]
    if long_toks and not indo and all(PINYIN_RE.match(t) for t in long_toks):
        mainland += 0.5
        reasons.append("pinyin_only")
    return local, mainland, reasons


def classify_box(text: str, script: str, latin_texts: Iterable[str]) -> Tuple[str, float, str]:
    """Return (sign_type, score, reasons). score > 0 leans local, < 0 leans mainland."""
    local, mainland, reasons = cotext_signal(latin_texts)
    if script == "traditional":
        local += 1.0
        reasons.append("traditional")
    elif script == "simplified":
        mainland += 0.5
        reasons.append("simplified")
    hits_m = [k for k in MAINLAND_CJK if k in (text or "")]
    hits_l = [k for k in LOCAL_CJK if k in (text or "")]
    if hits_m:
        mainland += 2.0
        reasons.append("kw_mainland:" + ",".join(hits_m[:3]))
    if hits_l:
        local += 2.0
        reasons.append("kw_local:" + ",".join(hits_l[:3]))
    score = local - mainland
    if score >= 1.0:
        t = "local"
    elif score <= -1.0:
        t = "mainland"
    else:
        t = "ambiguous"
    return t, score, ";".join(reasons)


def classify_boxes(boxes: pd.DataFrame) -> pd.DataFrame:
    """Add sign_type / sign_score / sign_reasons to the CJK rows of ocr_boxes."""
    out = boxes.copy()
    out["sign_type"], out["sign_score"], out["sign_reasons"] = None, None, None
    latin_by_image: Dict[str, List[str]] = (
        out[~out["is_cjk"].astype(bool)].groupby("path")["text"].agg(list).to_dict())
    for idx in out.index[out["is_cjk"].astype(bool)]:
        r = out.loc[idx]
        t, s, why = classify_box(str(r["text"]), str(r.get("script", "unknown")), latin_by_image.get(r["path"], []))
        out.at[idx, "sign_type"], out.at[idx, "sign_score"], out.at[idx, "sign_reasons"] = t, s, why
    return out


def image_type_counts(classified: pd.DataFrame, ocr_images: pd.DataFrame) -> pd.DataFrame:
    """Merge per-image counts of local / mainland / ambiguous CJK boxes into ocr_images."""
    cjk = classified[classified["sign_type"].notna()]
    counts = pd.crosstab(cjk["path"], cjk["sign_type"]).reindex(columns=["local", "mainland", "ambiguous"], fill_value=0)
    counts.columns = [f"n_{c}_boxes" for c in counts.columns]
    merged = ocr_images.merge(counts, left_on="path", right_index=True, how="left")
    for c in ("n_local_boxes", "n_mainland_boxes", "n_ambiguous_boxes"):
        merged[c] = merged[c].fillna(0).astype(int)
    return merged
