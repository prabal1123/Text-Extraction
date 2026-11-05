"""Phase 0 spike: measure extraction quality per layout family on the sample PDFs.

Usage (from project root):
    python scripts/spike_report.py

Writes docs/phase0_spike.json (raw per-page data) and prints a summary.
The spike only observes. Nothing here is the real classifier or parser.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pdfplumber  # noqa: E402

from pipeline.pages import read_pdf  # noqa: E402

FIXTURES = {
    "2025_77th_rudrapur": ROOT / "tests/fixtures/2025_77th_rudrapur.pdf",
    "2023_75th_ranchi": ROOT / "tests/fixtures/2023_75th_ranchi.pdf",
}

RANK_TOKEN = re.compile(
    r"^(?:\d{1,3}|Gold|Silver|Bronze|DNF|DNS|ABD|DSQ|Rel\.?|Relegate)$", re.I
)
COMM_NO = re.compile(r"Communique\s*(?:No)?[.:…\s]*([0-9]+)", re.I)
DATE = re.compile(
    r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+"
    r"(?:\w{3,4}\.?\s+\d{1,2},?\s*\d{4}|\d{1,2}\s+\w{3},?\s*\d{4})",
    re.I,
)
CATEGORY = re.compile(
    r"(Men Elite|Women Elite|Men Junior|Women Junior|Sub[ -]Junior Boys|"
    r"Sub[ -]Junior Girls|Youth Boys|Youth Girls)",
    re.I,
)
DISTANCE = re.compile(r"(?:Race\s+)?Distance\s*[-:]\s*([\d.]+\s*(?:Km|KMS?|Mtrs?|mts|Laps?)\.?)", re.I)

RACE_KEYWORDS = [
    ("team_pursuit", r"team\s+pursuit"),
    ("team_sprint", r"team\s+sprint"),
    ("individual_pursuit", r"(?:individual|ind\.)\s+pursuit"),
    ("individual_time_trial", r"individual\s+time\s+trial|time\s+trial"),
    ("omnium", r"omnium"),
    ("madison", r"madison"),
    ("points_race", r"point(?:s)?\s+race"),
    ("scratch", r"scratch"),
    ("elimination", r"elimination"),
    ("keirin", r"keirin"),
    ("sprint", r"\bsprint\b"),
]
FAMILY = {
    "team_pursuit": "team",
    "team_sprint": "team",
    "individual_pursuit": "timed",
    "individual_time_trial": "timed",
    "sprint": "timed",
    "scratch": "placing",
    "elimination": "placing",
    "keirin": "placing",
    "omnium": "points",
    "madison": "points",
    "points_race": "points",
}


def sniff_race(text: str) -> str | None:
    low = text.lower()
    for name, pat in RACE_KEYWORDS:
        if re.search(pat, low):
            return name
    return None


def line_text(line) -> str:
    return " ".join(w.text for w in line)


def count_rank_rows(page) -> int:
    """Visual lines whose first token looks like a rank / status code and which
    also contain a DOB-like token (so header and footer lines do not count)."""
    dob = re.compile(r"\d{1,2}[./-](?:\d{1,2}|[A-Za-z]{3})[./-]\d{2,4}|\d{2}/\d{3}\d{4}")
    n = 0
    for ln in page.lines:
        first = ln[0].text
        if RANK_TOKEN.match(first) and dob.search(line_text(ln)):
            n += 1
    return n


def table_probe(pl_page) -> dict:
    out = {}
    for label, settings in (
        ("lines", {}),
        ("text", {"vertical_strategy": "text", "horizontal_strategy": "text"}),
    ):
        try:
            tables = pl_page.extract_tables(settings) if settings else pl_page.extract_tables()
        except Exception as exc:  # noqa: BLE001
            out[label] = {"error": str(exc)}
            continue
        rows = sum(len(t) for t in tables)
        cols = max((len(r) for t in tables for r in t), default=0)
        none_cells = sum(1 for t in tables for r in t for c in r if c is None)
        out[label] = {"tables": len(tables), "rows": rows, "max_cols": cols, "none_cells": none_cells}
    return out


def header_sniff(page) -> dict:
    t = page.text
    m = COMM_NO.search(t)
    cat = CATEGORY.search(t)
    date = DATE.search(t)
    dist = DISTANCE.search(t)
    race = sniff_race(t)
    first_line = page.text.split("\n", 1)[0] if page.text else ""
    return {
        "communique": m.group(1) if m else None,
        "category": cat.group(1) if cat else None,
        "date": date.group(0) if date else None,
        "distance": dist.group(1) if dist else None,
        "race": race,
        "revision": bool(re.search(r"\bRev(?:ised)?\b", t, re.I)),
        # scrambled = text extraction does not begin with the communique line
        # on pages that have one (points sheets put 'Last' / 'Communique' first)
        "text_starts_with_header": bool(re.match(r"\s*(?:Communique|\d{2,3}\w*\s+Senior|Last)", first_line, re.I)),
        "first_line": first_line[:80],
    }


def classify_page(page, sniff) -> str:
    if page.is_blank:
        return "blank"
    if page.is_footer_only:
        return "footer_only"
    if page.n_words < 15 and sniff["race"] is None:
        return "fragment"
    if sniff["race"] is None and sniff["communique"] is None:
        return "headerless"
    return "headed"


def run() -> dict:
    result = {}
    for name, path in FIXTURES.items():
        pages_out = []
        with pdfplumber.open(str(path)) as pl:
            pl_pages = {i: p for i, p in enumerate(pl.pages, start=1)}
            for page in read_pdf(path):
                sn = header_sniff(page)
                kind = classify_page(page, sn)
                rec = {
                    "page": page.index,
                    "kind": kind,
                    "words": page.n_words,
                    "chars": page.chars,
                    "images": page.image_count,
                    "image_cover": round(page.image_coverage, 3),
                    "scanned_suspect": page.looks_scanned,
                    "size": [round(page.width), round(page.height)],
                    "sniff": sn,
                    "family": FAMILY.get(sn["race"]),
                    "rank_rows_by_words": count_rank_rows(page),
                }
                if kind in ("headed", "headerless"):
                    rec["tables"] = table_probe(pl_pages[page.index])
                pages_out.append(rec)
        result[name] = pages_out
    return result


def summarise(result: dict) -> str:
    lines: list[str] = []
    for name, pages in result.items():
        lines.append(f"\n=== {name}: {len(pages)} pages")
        kinds = Counter(p["kind"] for p in pages)
        lines.append("page kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
        lines.append("scanned-image pages: " + str(sum(p["scanned_suspect"] for p in pages)))
        lines.append("pages with a text layer: " + str(sum(p["words"] > 0 for p in pages)))
        for k in ("blank", "footer_only", "fragment", "headerless"):
            ids = [p["page"] for p in pages if p["kind"] == k]
            if ids:
                lines.append(f"  {k}: pages {ids}")

        headed = [p for p in pages if p["kind"] == "headed"]
        no_num = [p["page"] for p in headed if p["sniff"]["communique"] is None]
        lines.append(f"headed pages: {len(headed)}; no communique number found on pages {no_num}")

        fam = defaultdict(list)
        for p in headed:
            fam[p["family"] or "unknown"].append(p)
        lines.append("\nper layout family (naive header sniff + extraction probes):")
        for f, ps in sorted(fam.items()):
            n = len(ps)
            def hit(key):
                return sum(1 for p in ps if p["sniff"][key])
            tl = [p["tables"]["lines"] for p in ps if "lines" in p.get("tables", {})]
            tt = [p["tables"]["text"] for p in ps if "text" in p.get("tables", {})]
            # row-count agreement between table extraction and the word-line count
            agree_lines = sum(
                1 for p in ps
                if p["tables"]["lines"].get("rows", 0) >= p["rank_rows_by_words"] > 0
            )
            lines.append(
                f"  {f:8s} pages={n:2d} | comm#={hit('communique')}/{n} race={hit('race')}/{n} "
                f"cat={hit('category')}/{n} date={hit('date')}/{n} dist={hit('distance')}/{n} "
                f"hdr_first={sum(p['sniff']['text_starts_with_header'] for p in ps)}/{n} | "
                f"tables(lines): found={sum(1 for t in tl if t.get('tables'))}/{n} "
                f"rows>=word_rows={agree_lines}/{n} | "
                f"tables(text): found={sum(1 for t in tt if t.get('tables'))}/{n}"
            )
        races = Counter(p["sniff"]["race"] for p in headed)
        lines.append("race types sniffed: " + ", ".join(f"{k}={v}" for k, v in sorted(races.items(), key=lambda x: str(x[0]))))
        cats = Counter((p["sniff"]["category"] or "?").lower() for p in headed)
        lines.append("categories sniffed: " + ", ".join(f"{k}={v}" for k, v in sorted(cats.items())))
    return "\n".join(lines)


if __name__ == "__main__":
    res = run()
    out = ROOT / "docs" / "phase0_spike.json"
    out.write_text(json.dumps(res, indent=1))
    print(summarise(res))
    print(f"\nraw data: {out}")
