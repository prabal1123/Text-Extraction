"""apply_fix5.py - quality layer for the track_results pipeline.

Adds: row validation (footer junk), DOB normalisation, Madison grouping,
text-line fallback, a rewritten team parser, revised/duplicate communique
handling, a per-championship transactional import_pdf, header aliases,
and a golden-file regression harness.
"""
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path.cwd()
BACKUP = ROOT / ".backup_fixes" / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_fix5")

# ---------------------------------------------------------------------------
QUALITY_PY = r'''"""Row validation, DOB normalisation, Madison grouping, text-line fallback,
team-block parsing and golden helpers. Pure Python: no Django imports."""
import re
from datetime import date

import pdfplumber

from pipeline.parsers import extract_status, parse_pdf_tables

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_DOB_RE = re.compile(r"(?<![\d:.])(\d{1,2}[./-](?:[A-Za-z]{3}|\d{1,2})[./-]?\d{2,4})(?![\d:])")
_TIME_RE = re.compile(r"(?<![\d:.])((?:\d{1,2}:)?\d{1,2}:\d{2}\.\d{3}|\d{2,3}\.\d{3})(?![\d:])")
_SPEED_RE = re.compile(r"(?<![\d:.])(\d{1,3}\.\d{2,3}|#DIV/0!)(?!\d)")
_RANK_RE = re.compile(r"^(\d{1,2}|Gold|Silver|Bronze)$", re.I)
_BIB_RE = re.compile(r"^\*?\d{1,4}$")
_STATUS_WORDS = re.compile(r"\b(DNS|DNF|DSQ|ABD|REL|RELEGATED|RELEGATE)\b", re.I)
_FOOTER_RE = re.compile(r"communiq|approved|commissair|commissar|organi[sz]ed by", re.I)


# ------------------------------------------------------------------ time
def parse_time_to_ms(value):
    """Accepts ss.mmm, m:ss.mmm and h:mm:ss.mmm."""
    if not value:
        return None
    m = re.search(r"(?:(\d{1,2}):)?(?:(\d{1,2}):)?(\d{1,2})\.(\d{1,3})", str(value))
    if not m:
        return None
    pre = [int(x) for x in (m.group(1), m.group(2)) if x is not None]
    if len(pre) == 2:
        hours, minutes = pre
    elif len(pre) == 1:
        hours, minutes = 0, pre[0]
    else:
        hours, minutes = 0, 0
    secs = int(m.group(3))
    ms = int(m.group(4).ljust(3, "0")[:3])
    return ((hours * 60 + minutes) * 60 + secs) * 1000 + ms


def split_time_speed(text):
    """Return (time_str, speed_str, remainder). Handles h:mm:ss.mmm."""
    tm = _TIME_RE.search(text)
    time_str = tm.group(1) if tm else ""
    rest = text.replace(time_str, " ", 1) if time_str else text
    sm = _SPEED_RE.search(rest)
    speed_str = sm.group(1) if sm else ""
    if speed_str:
        rest = rest.replace(speed_str, " ", 1)
    return time_str, speed_str, rest


# ------------------------------------------------------------------- DOB
def _year(y):
    y = int(y)
    if y < 100:
        y += 2000 if y <= 26 else 1900
    return y


def normalize_dob(raw):
    """Return (value, ok). value is ISO yyyy-mm-dd when readable, otherwise the
    cleaned raw text with ok=False (3-digit years, impossible dates, ...)."""
    s = (raw or "").strip()
    if not s:
        return "", True
    t = s.replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})[./-](\d{2})(\d{4})", t)      # 19/072007 typo
    if m:
        d, mo, y = m.groups()
    else:
        m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2}|[A-Za-z]{3})[./-](\d{2,4})", t)
        if not m:
            return s, False
        d, mo, y = m.groups()
    if mo.isalpha():
        mo = _MONTHS.get(mo.lower())
        if not mo:
            return s, False
    else:
        mo = int(mo)
    d = int(d)
    if len(y) == 3:                                            # 28.10.209
        return s, False
    y = _year(y)
    if mo > 12 >= d:                                           # US order, e.g. 10/18/2006
        d, mo = mo, d
    try:
        return date(y, mo, d).isoformat(), True
    except ValueError:
        return s, False


# ------------------------------------------------------ row validation
def looks_like_footer(row):
    for k, v in row.items():
        if k.startswith("_") or not isinstance(v, str):
            continue
        if _FOOTER_RE.search(v) or v.strip().lower() == "panel":
            return True
    return False


def is_valid_row(row):
    if looks_like_footer(row):
        return False
    name = (row.get("name") or "").strip()
    if name and len(re.findall(r"[A-Za-z]", name)) < 2:
        return False
    bib = (row.get("bib") or "").strip()
    if not name and not re.fullmatch(r"\*?\d{1,4}", bib):
        return False
    return True


def group_madison(rows):
    """Madison sheets list the second rider of a team on a row with blank
    rank/bib/team. Fold those into the previous row as '_partners'."""
    out = []
    for r in rows:
        own = ((r.get("rank") or "").strip() or (r.get("bib") or "").strip()
               or (r.get("team") or "").strip())
        if out and not own and (r.get("name") or "").strip():
            out[-1].setdefault("_partners", []).append(r)
        else:
            out.append(r)
    return out


def total_points(row):
    """Highest-numbered numeric 'points' column (Omnium: last = overall total)."""
    best, best_n = None, -1
    for k, v in row.items():
        m = re.fullmatch(r"points(?:_(\d+))?", k)
        if m and isinstance(v, str) and v.strip().lstrip("-").isdigit():
            n = int(m.group(1) or 1)
            if n > best_n:
                best, best_n = int(v.strip()), n
    return best


# ------------------------------------------------ text line parsing
def _lines(page, y_tol=3.0):
    words = page.extract_words(x_tolerance=2, y_tolerance=3)
    lines = []
    for w in sorted(words, key=lambda w: (w["top"] + w["bottom"]) / 2):
        yc = (w["top"] + w["bottom"]) / 2
        if lines and abs(lines[-1]["yc"] - yc) <= y_tol:
            lines[-1]["words"].append(w)
        else:
            lines.append({"yc": yc, "words": [w]})
    return [" ".join(w["text"] for w in sorted(l["words"], key=lambda w: w["x0"])) for l in lines]


def _clean_team(text):
    t = _STATUS_WORDS.sub(" ", text)
    t = re.sub(r"\s+", " ", t).strip(" :-")
    return t if re.search(r"[A-Za-z]{2}", t) else ""


def split_row_line(line):
    """Split 'rank bib name dob team time speed'. Returns a dict, or None when
    the line has no DOB (so it is not a rider line)."""
    m = _DOB_RE.search(line)
    if not m:
        return None
    left = line[:m.start()].split()
    right = line[m.end():].strip()
    rank = bib = ""
    if len(left) >= 2 and _RANK_RE.match(left[0]) and _BIB_RE.match(left[1]):
        rank, bib, name = left[0], left[1], " ".join(left[2:])
    elif left and _BIB_RE.match(left[0]):
        bib, name = left[0], " ".join(left[1:])
    elif len(left) >= 2 and re.fullmatch(r"Gold|Silver|Bronze", left[0], re.I):
        rank, name = left[0], " ".join(left[1:])
    else:
        name = " ".join(left)
    time_str, speed_str, rest = split_time_speed(right)
    return {
        "rank": rank, "bib": bib, "name": name.strip(), "dob": m.group(1),
        "team": _clean_team(rest), "time": time_str, "speed": speed_str,
        "status": extract_status([right]), "raw": line,
    }


def parse_dob_lines(pdf_path, pages):
    """Fallback for timed/placing pages where no table header was recognised."""
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            for line in _lines(pdf.pages[p_num - 1]):
                r = split_row_line(line)
                if r and r["name"]:
                    rows.append({
                        "rank": r["rank"], "bib": r["bib"].lstrip("*"), "name": r["name"],
                        "dob": r["dob"], "team": r["team"], "time": r["time"],
                        "speed": r["speed"],
                        "remarks": r["status"] if r["status"] != "OK" else "",
                        "_sprints": [], "_fallback": True,
                    })
    return rows


def parse_team_blocks(pdf_path, pages):
    """Team Sprint / Team Pursuit pages -> blocks of members.

    A new team starts when a rank appears that differs from the current team's
    rank, when the team name changes, or when a different time appears. Team
    name / time / speed seen on later member lines fill gaps in the current
    team. Stray rank-only lines (Gold, 3, ...) apply to the next team."""
    def norm(s):
        return re.sub(r"\W+", "", (s or "").lower())

    blocks = []
    current = None
    pending_rank = ""
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            for line in _lines(pdf.pages[p_num - 1]):
                row = split_row_line(line)
                if row is None:
                    token = line.strip()
                    if re.fullmatch(r"Gold|Silver|Bronze|[1-9]|[12]\d|30", token, re.I):
                        pending_rank = token
                    continue
                if not row["name"]:
                    continue
                rank = row["rank"]
                if not rank and pending_rank:
                    rank, pending_rank = pending_rank, ""
                team, tm, sp, status = row["team"], row["time"], row["speed"], row["status"]
                new = False
                if current is None:
                    new = True
                elif rank and rank != current["rank"]:
                    new = True
                elif team and current["team"] and norm(team) != norm(current["team"]):
                    new = True
                elif tm and current["time"] and tm != current["time"]:
                    new = True
                if new:
                    current = {"rank": rank, "team": team, "time": tm, "speed": sp,
                               "status": status, "members": []}
                    blocks.append(current)
                else:
                    if team and not current["team"]:
                        current["team"] = team
                    if tm and not current["time"]:
                        current["time"] = tm
                    if sp and not current["speed"]:
                        current["speed"] = sp
                    if status != "OK" and current["status"] == "OK":
                        current["status"] = status
                bib = row["bib"]
                current["members"].append({
                    "bib": bib.lstrip("*"), "name": row["name"], "dob": row["dob"],
                    "is_reserve": bib.startswith("*"), "raw": line,
                })
    return blocks


# ------------------------------------------------------------ top level
def parse_rows(pdf_path, pages, layout_family, race_type=""):
    """Table parse -> footer/validity filter -> text fallback -> Madison grouping."""
    rows = parse_pdf_tables(pdf_path, pages, layout_family)
    total = len(rows)
    rows = [r for r in rows if is_valid_row(r)]
    dropped = total - len(rows)
    fallback = False
    if not rows and layout_family in ("timed", "placing"):
        rows = [r for r in parse_dob_lines(pdf_path, pages) if is_valid_row(r)]
        fallback = bool(rows)
    if "madison" in (race_type or "").lower():
        rows = group_madison(rows)
    return rows, {"dropped": dropped, "fallback": fallback}


def golden_rows(pdf_path, pages, layout, race_type=""):
    """Normalised output used by the golden-file tests."""
    if layout == "team":
        return [{"rank": b["rank"], "team": b["team"], "time": b["time"],
                 "speed": b["speed"], "status": b["status"],
                 "members": [m["name"] for m in b["members"]]}
                for b in parse_team_blocks(pdf_path, pages)]
    rows, _ = parse_rows(pdf_path, pages, layout, race_type)
    out = []
    for r in rows:
        d = {k: (r.get(k) or "") for k in ("rank", "bib", "name", "dob", "team", "time", "speed")}
        d["points"] = total_points(r)
        if r.get("_partners"):
            d["partners"] = [p.get("name", "") for p in r["_partners"]]
        out.append(d)
    return out
'''

# ---------------------------------------------------------------------------
IMPORT_PDF_PY = r'''import os
import re
from django.core.management.base import BaseCommand
from django.db import transaction

from pipeline.parsers import extract_status
from pipeline.quality import (normalize_dob, parse_rows, parse_team_blocks,
                              parse_time_to_ms, total_points)
from results.models import (Championship, PointsDetail, Race, Result, Rider,
                            Team, TeamMember)

FAMILIES = ["timed", "placing", "team", "points"]


def base_number(num):
    m = re.match(r"\s*(\d+)", str(num or ""))
    return m.group(1) if m else None


def is_revised(num):
    return bool(re.search(r"rev", str(num or ""), re.I))


def rank_to_numeric(display_rank):
    d = (display_rank or "").strip()
    if d.isdigit():
        return int(d)
    return {"gold": 1, "silver": 2, "bronze": 3}.get(d.lower())


def first_val(row, base):
    """First non-empty of base, base_2, base_3 (clipped headers can duplicate)."""
    for key in (base, base + "_2", base + "_3"):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def status_cells(row):
    cells = [first_val(row, "rank"), first_val(row, "time"), first_val(row, "speed")]
    cells += [v for k, v in row.items()
              if k.startswith(("x_rem", "remark")) and isinstance(v, str)]
    return cells


class Command(BaseCommand):
    help = "Parse cached PDFs into Result rows (per championship, in a transaction)."

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, nargs="*", help="Only these editions")

    def handle(self, *args, **opts):
        champs = Championship.objects.all().order_by("edition")
        if opts.get("edition"):
            champs = champs.filter(edition__in=opts["edition"])
        totals = {"results": 0, "members": 0, "points": 0, "skipped": 0}
        for champ in champs:
            self.import_championship(champ, totals)
        self.stdout.write(self.style.SUCCESS(
            f"\nPhase 5 Complete! Inserted {totals['results']} Result rows, "
            f"{totals['members']} TeamMember rows, and {totals['points']} PointsDetail rows. "
            f"Skipped {totals['skipped']} races (superseded or duplicate)."))

    # ------------------------------------------------------------------
    @staticmethod
    def find_superseded(races):
        groups = {}
        for race in races:
            b = base_number(race.communique.number)
            if b:
                groups.setdefault((b, race.race_type, race.category, race.stage or ""), []).append(race)
        superseded = set()
        for rs in groups.values():
            revised = [r for r in rs if is_revised(r.communique.number)]
            if len(rs) > 1 and revised:
                keep = revised[-1]
                superseded.update(r.id for r in rs if r.id != keep.id)
        return superseded

    def import_championship(self, champ, totals):
        races = list(Race.objects.filter(communique__championship=champ, layout_family__in=FAMILIES)
                     .select_related("communique").order_by("id"))
        if not races:
            return
        pdf_path = f".cache/pdfs/{champ.pdf_hash}.pdf"
        if not os.path.exists(pdf_path):
            self.stdout.write(self.style.WARNING(
                f"\n{champ.edition}th: cached PDF missing, skipped (existing results kept)."))
            return
        self.stdout.write(self.style.SUCCESS(
            f"\nParsing {len(races)} supported races for {champ.edition}th Edition..."))
        superseded = self.find_superseded(races)
        seen_sigs, seen_numbers = {}, {}
        with transaction.atomic():
            Result.objects.filter(race__communique__championship=champ).delete()
            for race in races:
                self.import_race(race, pdf_path, superseded, seen_sigs, seen_numbers, totals)

    # ------------------------------------------------------------------
    def import_race(self, race, pdf_path, superseded, seen_sigs, seen_numbers, totals):
        comm = race.communique
        label = f"Comm {comm.number or 'None'} (pg {comm.page_range})"
        if race.id in superseded:
            totals["skipped"] += 1
            self.stdout.write(f"  -> {label}: SKIPPED, superseded by a revised communique")
            return
        pages = [int(p) for p in comm.page_range.split("-")]
        if len(pages) == 2:
            pages = list(range(pages[0], pages[1] + 1))
        is_team = race.layout_family == "team"
        info = {}
        if is_team:
            items = parse_team_blocks(pdf_path, pages)
            sig = ("T",) + tuple(sorted((b["rank"], b["team"], len(b["members"])) for b in items))
        else:
            items, info = parse_rows(pdf_path, pages, race.layout_family, race.race_type)
            sig = ("R",) + tuple(sorted(
                (first_val(r, "rank"), first_val(r, "bib"), r.get("name") or "") for r in items))
        if not items:
            self.stdout.write(f"  -> {label}: 0 results ({race.layout_family})")
            return
        sig_key = (race.race_type, race.category, race.stage or "", sig)
        if sig_key in seen_sigs:
            totals["skipped"] += 1
            self.stdout.write(f"  -> {label}: SKIPPED, identical content to {seen_sigs[sig_key]}")
            return
        seen_sigs[sig_key] = label
        extra_flag = ""
        base = base_number(comm.number)
        if base:
            nk = (base, race.race_type, race.category)
            if nk in seen_numbers:
                extra_flag = f"Communique number {base} reused with different content (see {seen_numbers[nk]})"
            else:
                seen_numbers[nk] = label
        if is_team:
            r, m, p = self.save_team_blocks(race, items, extra_flag)
            self.stdout.write(f"  -> {label}: {r} teams, {m} riders (Team)")
        else:
            r, m, p = self.save_rows(race, items, extra_flag, info.get("fallback", False))
            tags = ""
            if info.get("fallback"):
                tags += " [text fallback]"
            if info.get("dropped"):
                tags += f" [dropped {info['dropped']} junk rows]"
            if extra_flag:
                tags += " [number reused]"
            self.stdout.write(f"  -> {label}: {r} results ({race.layout_family}){tags}")
        totals["results"] += r
        totals["members"] += m
        totals["points"] += p

    # ------------------------------------------------------------------
    def get_rider(self, race, name, raw_dob, flags):
        dob, ok = normalize_dob(raw_dob)
        if not ok:
            flags.append(f"DOB not readable: {dob}")
        rider, _ = Rider.objects.get_or_create(name=name, dob=dob, defaults={"gender": race.gender})
        return rider

    def save_rows(self, race, rows, extra_flag, fallback):
        n_results = 0
        members, details = [], []
        for row in rows:
            flags = []
            if extra_flag:
                flags.append(extra_flag)
            if fallback:
                flags.append("parsed from text lines (no table header recognised)")
            status = extract_status(status_cells(row))
            display_rank = first_val(row, "rank")
            numeric_rank = rank_to_numeric(display_rank)
            team_name = (row.get("team") or "").strip()
            team_obj = Team.objects.get_or_create(name=team_name)[0] if team_name else None
            name = (row.get("name") or "").strip()
            rider_obj = self.get_rider(race, name, row.get("dob"), flags) if name else None

            raw = dict(row)
            raw["_source_pages"] = race.communique.page_range
            if flags:
                raw["_import_flag"] = "; ".join(flags)
            result = Result.objects.create(
                race=race, rider=rider_obj, team=team_obj, display_rank=display_rank,
                numeric_rank=numeric_rank, status=status, bib=first_val(row, "bib"),
                time_ms=parse_time_to_ms(first_val(row, "time")), speed=first_val(row, "speed"),
                points=total_points(row), raw_row=raw,
                needs_review=bool(flags) or (status != "OK" and not numeric_rank),
            )
            n_results += 1

            for idx, s_val in enumerate(row.get("_sprints", [])):
                s_val = (s_val or "").strip()
                if s_val:
                    details.append(PointsDetail(
                        result=result, sprint_number=idx + 1,
                        points_awarded=int(s_val) if s_val.lstrip("-").isdigit() else 0,
                        sub_scores_json={"raw_value": s_val}))

            partners = row.get("_partners", [])
            if partners:
                if rider_obj:
                    members.append(TeamMember(result=result, rider=rider_obj, is_reserve=False))
                for p in partners:
                    p_name = (p.get("name") or "").strip()
                    if p_name:
                        partner = self.get_rider(race, p_name, p.get("dob"), [])
                        members.append(TeamMember(result=result, rider=partner, is_reserve=False))
        TeamMember.objects.bulk_create(members)
        PointsDetail.objects.bulk_create(details)
        return n_results, len(members), len(details)

    def save_team_blocks(self, race, blocks, extra_flag):
        n_results = 0
        members = []
        for block in blocks:
            flags = []
            if extra_flag:
                flags.append(extra_flag)
            if not block["team"]:
                flags.append("team name not found")
            display_rank = block["rank"]
            numeric_rank = rank_to_numeric(display_rank)
            team_obj = Team.objects.get_or_create(name=block["team"])[0] if block["team"] else None
            raw = dict(block)
            raw["_source_pages"] = race.communique.page_range
            member_objs = []
            for m in block["members"]:
                if m["name"].strip():
                    member_objs.append((self.get_rider(race, m["name"].strip(), m["dob"], flags), m))
            if flags:
                raw["_import_flag"] = "; ".join(flags)
            result = Result.objects.create(
                race=race, rider=None, team=team_obj, display_rank=display_rank,
                numeric_rank=numeric_rank, status=block["status"], bib=None,
                time_ms=parse_time_to_ms(block["time"]), speed=block["speed"],
                raw_row=raw,
                needs_review=bool(flags) or (block["status"] != "OK" and not numeric_rank),
            )
            n_results += 1
            for rider, m in member_objs:
                members.append(TeamMember(result=result, rider=rider, is_reserve=m["is_reserve"]))
        TeamMember.objects.bulk_create(members)
        return n_results, len(members), 0
'''

# ---------------------------------------------------------------------------
MAKE_GOLDEN_PY = r'''import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from pipeline.quality import golden_rows
from results.models import Race

FIXTURES = {
    77: "tests/fixtures/2025_77th_rudrapur.pdf",
    75: "tests/fixtures/2023_75th_ranchi.pdf",
}


class Command(BaseCommand):
    help = "Write unverified golden files for the given communiques. Check them against the PDF, then set verified to true."

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, required=True)
        parser.add_argument("--comm", nargs="+", required=True)

    def handle(self, *args, **o):
        out_dir = Path("tests/golden")
        out_dir.mkdir(parents=True, exist_ok=True)
        for comm in o["comm"]:
            races = Race.objects.filter(
                communique__championship__edition=o["edition"], communique__number=comm,
                layout_family__in=["timed", "placing", "team", "points"],
            ).select_related("communique__championship")
            if not races:
                self.stdout.write(f"No race found for edition {o['edition']} comm {comm}")
            for race in races:
                c = race.communique
                pages = [int(p) for p in c.page_range.split("-")]
                if len(pages) == 2:
                    pages = list(range(pages[0], pages[1] + 1))
                pdf = FIXTURES.get(o["edition"])
                if not pdf or not Path(pdf).exists():
                    pdf = f".cache/pdfs/{c.championship.pdf_hash}.pdf"
                expected = golden_rows(pdf, pages, race.layout_family, race.race_type)
                name = re.sub(r"\W+", "_", f"{o['edition']}_{comm}_p{c.page_range}")
                path = out_dir / f"{name}.json"
                path.write_text(json.dumps({
                    "verified": False, "pdf": pdf, "pages": pages,
                    "layout": race.layout_family, "race_type": race.race_type,
                    "category": race.category, "expected": expected,
                }, indent=2))
                self.stdout.write(f"\nWrote {path}  ({race.race_type} / {race.category}, "
                                  f"pages {pages}, {len(expected)} rows)")
                for row in expected[:6]:
                    self.stdout.write(f"   {row}")
        self.stdout.write("\nNext: compare each file to the PDF page, fix any wrong values, "
                          'then set "verified": true.')
'''

# ---------------------------------------------------------------------------
DIAG_TABLE_PY = r'''import pdfplumber
from django.core.management.base import BaseCommand

from pipeline.parsers import load_config, normalize_header
from results.models import Race


class Command(BaseCommand):
    help = "Show raw table rows and header mapping for one communique."

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, required=True)
        parser.add_argument("--comm", required=True)
        parser.add_argument("--rows", type=int, default=4)

    def handle(self, *args, **o):
        races = Race.objects.filter(communique__championship__edition=o["edition"],
                                    communique__number=o["comm"]
                                    ).select_related("communique__championship")
        for race in races:
            c = race.communique
            self.stdout.write(f"\n===== Comm {c.number} pages {c.page_range} | {race.race_type} / "
                              f"{race.category} | layout={race.layout_family}")
            config = load_config(race.layout_family)
            pages = [int(p) for p in c.page_range.split("-")]
            if len(pages) == 2:
                pages = list(range(pages[0], pages[1] + 1))
            with pdfplumber.open(f".cache/pdfs/{c.championship.pdf_hash}.pdf") as pdf:
                for p in pages:
                    page = pdf.pages[p - 1]
                    tables = page.extract_tables()
                    self.stdout.write(f"-- page {p}: {len(tables)} table(s)")
                    for t in tables[:3]:
                        self.stdout.write(f"   table with {len(t)} rows")
                        for row in t[:o["rows"]]:
                            cleaned = [str(x).strip().replace("\n", " ") if x else "" for x in row]
                            self.stdout.write(f"     raw   : {cleaned}")
                            if config:
                                self.stdout.write(
                                    f"     mapped: {[normalize_header(x, config['columns']) for x in cleaned]}")
                    self.stdout.write("   text (first 6 lines):")
                    for line in (page.extract_text() or "").splitlines()[:6]:
                        self.stdout.write(f"     {line}")
'''

# ---------------------------------------------------------------------------
TEST_GOLDEN_PY = r'''import json
from pathlib import Path

import pytest

from pipeline.quality import golden_rows

GOLDEN = Path(__file__).parent / "golden"
FILES = sorted(GOLDEN.glob("*.json")) if GOLDEN.exists() else []


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_golden(path):
    spec = json.loads(path.read_text())
    if not spec.get("verified"):
        pytest.skip("not hand-verified yet")
    pdf = Path(spec["pdf"])
    if not pdf.exists():
        pytest.skip(f"{pdf} is missing")
    got = golden_rows(str(pdf), spec["pages"], spec["layout"], spec.get("race_type", ""))
    assert got == spec["expected"]
'''

# ---------------------------------------------------------------------------
YAML_ADDITIONS = {
    "layouts/placing.yaml": {
        "rank": ["Position", "Pos", "Pos.", "Place"],
        "bib": ["Rider No.", "Rider No", "Bib No.", "Start No.", "art No.", "der No.", "art No", "der No"],
        "time": ["Time", "Final time", "Final Time"],
        "speed": ["Speed Km/hr", "Speed", "Spe", "ed", "eed"],
        "remarks": ["Remarks", "Remar", "ks"],
    },
    "layouts/timed.yaml": {
        "rank": ["Position", "Pos", "Pos.", "Place"],
        "bib": ["art No.", "der No.", "art No", "der No"],
        "speed": ["Spe", "ed", "eed"],
    },
    "layouts/points.yaml": {
        "rank": ["Position", "Pos"],
        "bib": ["Rider No.", "art No.", "der No."],
        "finish_order": ["FO", "Finish Order"],
    },
}


def backup(rel):
    p = ROOT / rel
    if p.exists():
        dest = BACKUP / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)


def write_py(rel, text):
    compile(text, rel, "exec")
    backup(rel)
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    print(f"[OK] wrote {rel}")


def patch_validator():
    rel = "pipeline/validator.py"
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    if "has_key" in s:
        print(f"[SKIP] {rel}: already patched")
        return
    edits = [
        ("Result.objects.update(needs_review=False)",
         "Result.objects.exclude(raw_row__has_key='_import_flag').update(needs_review=False)"),
        ("if not r.display_rank and r.status == 'OK':",
         "if not r.display_rank and r.status == 'OK' and (r.time_ms or r.points):"),
    ]
    for old, new in edits:
        if old not in s:
            print(f"[FAIL] {rel}: expected text not found: {old}")
            return
        s = s.replace(old, new, 1)
    compile(s, rel, "exec")
    backup(rel)
    p.write_text(s, encoding="utf-8")
    print(f"[OK] patched {rel}")


def update_yaml(rel, additions):
    p = ROOT / rel
    if not p.exists():
        print(f"[SKIP] {rel}: not found")
        return
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    cols = data.setdefault("columns", {})
    changed = False
    for canon, aliases in additions.items():
        cur = cols.setdefault(canon, [])
        have = {str(a).lower() for a in cur}
        for a in aliases:
            if a.lower() not in have:
                cur.append(a)
                have.add(a.lower())
                changed = True
    if changed:
        backup(rel)
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=None)
        print(f"[OK] updated {rel}")
    else:
        print(f"[SKIP] {rel}: aliases already present")


def main():
    if not (ROOT / "manage.py").exists():
        sys.exit("Run this from the folder containing manage.py")
    if not (ROOT / "pipeline" / "parsers.py").exists():
        sys.exit("pipeline/parsers.py not found")
    write_py("pipeline/quality.py", QUALITY_PY)
    write_py("results/management/commands/import_pdf.py", IMPORT_PDF_PY)
    write_py("results/management/commands/make_golden.py", MAKE_GOLDEN_PY)
    write_py("results/management/commands/diag_table.py", DIAG_TABLE_PY)
    write_py("tests/test_golden.py", TEST_GOLDEN_PY)
    patch_validator()
    for rel, add in YAML_ADDITIONS.items():
        update_yaml(rel, add)
    print(f"\nBackups in {BACKUP}")
    subprocess.run([sys.executable, "-m", "pytest", "tests/test_parsers_unit.py", "-q"])


if __name__ == "__main__":
    main()
