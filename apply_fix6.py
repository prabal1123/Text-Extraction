"""apply_fix6.py - Omnium text parser, Omnium flag pass-through, and the 74th
Points Race total-points column. All-or-nothing: nothing is written unless all
three edits apply. Backups go to .backup_fixes/<timestamp>_fix6.
Use --no-run to skip the pytest/import/check steps."""
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
BACKUP = ROOT / ".backup_fixes" / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_fix6")

# ---------------------------------------------------------------- quality.py
OMNIUM_BLOCK = r'''# ------------------------------------------------------------ Omnium
_KNOWN_TEAMS = {t.lower() for t in [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Chattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
    "Orissa", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman & Nicobar", "Andaman and Nicobar",
    "A & N", "Chandigarh", "Dadra & Nagar Haveli", "Daman & Diu", "Delhi", "Jammu & Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry", "Pondicherry", "SSCB", "RSPB", "Railways",
    "Services", "Army", "CRPF", "BSF", "CISF", "ITBP", "Assam Rifles",
]}
_EVENT_RE = re.compile(r"\d+ \(\d+\)")
_OMNIUM_RANKED = re.compile(
    r"^(?P<rank>\d{1,2})\s+(?P<bib>\d{1,4})\s+(?P<mid>.+?)\s+"
    r"(?P<e1>\d+ \(\d+\))\s+(?P<e2>\d+ \(\d+\))\s+(?P<e3>\d+ \(\d+\))\s+"
    r"(?P<sub>\d+)\s+(?P<tail>\d.*)$")
_OMNIUM_STATUS = re.compile(r"^(?P<status>DNF|DNS|DSQ|ABD|REL)\s+(?P<bib>\d{1,4})\s+(?P<rest>.+)$")


def _split_name_team(mid):
    """'Bilal Ahmad Dar Jammu & Kashmir' -> ('Bilal Ahmad Dar', 'Jammu & Kashmir', '')."""
    toks = mid.split()
    for k in (4, 3, 2, 1):
        if len(toks) > k and " ".join(toks[-k:]).lower() in _KNOWN_TEAMS:
            return " ".join(toks[:-k]), " ".join(toks[-k:]), ""
    if len(toks) >= 2:
        return " ".join(toks[:-1]), toks[-1], "team guessed from last word"
    return mid, "", "team not found"


def parse_omnium_text(lines):
    """Omnium sheets from text lines. Reads rank, bib, name, team, the three event
    cells, the sub-total and the total (last number on the line). The sprint
    breakdown is not read: blank cells print nothing, so positions are ambiguous."""
    rows = []
    for line in lines:
        line = line.strip()
        m = _OMNIUM_RANKED.match(line)
        if m:
            name, team, flag = _split_name_team(m["mid"])
            last = m["tail"].split()[-1]
            total = last if re.fullmatch(r"-?\d+", last) else ""
            if not total:
                flag = (flag + "; " if flag else "") + "total points not readable"
            row = {"rank": m["rank"], "bib": m["bib"], "name": name, "team": team,
                   "dob": "", "points": total, "x_scratch": m["e1"], "x_tempo": m["e2"],
                   "x_elimination": m["e3"], "x_sub_total": m["sub"],
                   "_sprints": [], "_tail": m["tail"], "_raw": line}
            if flag:
                row["_flag"] = flag
            rows.append(row)
            continue
        m = _OMNIUM_STATUS.match(line)
        if m:
            rest = m["rest"]
            first = _EVENT_RE.search(rest)
            mid = rest[:first.start()] if first else rest
            mid = re.sub(r"(\s+(?:DNF|DNS|DSQ|ABD|REL|\d+))+\s*$", "", mid).strip()
            name, team, flag = _split_name_team(mid)
            row = {"rank": m["status"], "bib": m["bib"], "name": name, "team": team,
                   "dob": "", "points": "", "_events": _EVENT_RE.findall(rest),
                   "_sprints": [], "_raw": line}
            if flag:
                row["_flag"] = flag
            rows.append(row)
    return rows


def parse_omnium_lines(pdf_path, pages):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            rows.extend(parse_omnium_text(_lines(pdf.pages[p_num - 1])))
    return rows


'''

Q_ANCHOR_TOP = "# ------------------------------------------------------------ top level\n"
Q_ANCHOR_HOOK = ('    """Table parse -> footer/validity filter -> text fallback -> Madison grouping."""\n'
                 '    rows = parse_pdf_tables(pdf_path, pages, layout_family)\n')
Q_HOOK_NEW = ('    """Table parse -> footer/validity filter -> text fallback -> Madison grouping."""\n'
              '    if "omnium" in (race_type or "").lower():\n'
              '        return parse_omnium_lines(pdf_path, pages), {"dropped": 0, "fallback": False}\n'
              '    rows = parse_pdf_tables(pdf_path, pages, layout_family)\n')

# ---------------------------------------------------------------- import_pdf.py
I_ANCHOR = ('            if fallback:\n'
            '                flags.append("parsed from text lines (no table header recognised)")\n')
I_NEW = I_ANCHOR + ('            if row.get("_flag"):\n'
                    '                flags.append(row["_flag"])\n')

# ---------------------------------------------------------------- parsers.py
LABEL_FUNC = '''def _label_trailing_points(active, config):
    """Sheets whose last four unlabelled columns before '@speed' are
    FO, +Lap, -Lap, Total Points (74th Points Race)."""
    if ('points' in config['columns'] and 'points' not in active and len(active) >= 9
            and active[-1] == 'x_speed'
            and all(n.startswith('sprint_') for n in active[-5:-1])):
        active[-5:-1] = ['finish_order', 'lap', 'lap_2', 'points']
    return active


'''
P_ANCHOR_DEF = "def process_table(table, config, headers=None):\n"
P_ANCHOR_ACTIVE = "    active = _merge_headers(parts) if parts else headers\n"
P_NEW_ACTIVE = P_ANCHOR_ACTIVE + ("    if parts and active:\n"
                                  "        active = _label_trailing_points(active, config)\n")


def patch_once(text, anchor, new, label):
    if text.count(anchor) != 1:
        return None, f"{label}: anchor found {text.count(anchor)} times (expected 1)"
    return text.replace(anchor, new, 1), None


def build():
    plan, errors = {}, []

    rel = "pipeline/quality.py"
    s = (ROOT / rel).read_text(encoding="utf-8")
    if "parse_omnium_text" in s:
        print(f"[SKIP] {rel}: already patched")
    else:
        s, err = patch_once(s, Q_ANCHOR_TOP, OMNIUM_BLOCK + Q_ANCHOR_TOP, rel + " (block)")
        if not err:
            s, err = patch_once(s, Q_ANCHOR_HOOK, Q_HOOK_NEW, rel + " (hook)")
        errors += [err] if err else []
        plan[rel] = s

    rel = "results/management/commands/import_pdf.py"
    s = (ROOT / rel).read_text(encoding="utf-8")
    if 'row.get("_flag")' in s:
        print(f"[SKIP] {rel}: already patched")
    else:
        s, err = patch_once(s, I_ANCHOR, I_NEW, rel)
        errors += [err] if err else []
        plan[rel] = s

    rel = "pipeline/parsers.py"
    s = (ROOT / rel).read_text(encoding="utf-8")
    if "_label_trailing_points" in s:
        print(f"[SKIP] {rel}: already patched")
    else:
        s, err = patch_once(s, P_ANCHOR_DEF, LABEL_FUNC + P_ANCHOR_DEF, rel + " (func)")
        if not err:
            s, err = patch_once(s, P_ANCHOR_ACTIVE, P_NEW_ACTIVE, rel + " (call)")
        errors += [err] if err else []
        plan[rel] = s
    return plan, errors


CHECK = '''
from results.models import Result
for e in (74, 75, 77):
    q = Result.objects.filter(race__layout_family="points", race__communique__championship__edition=e)
    print(e, "points rows", q.count(), "| OK with no points", q.filter(status="OK", points__isnull=True).count(), "| flagged", q.filter(needs_review=True).count())
q = Result.objects.filter(race__race_type="Omnium")
print("Omnium rows", q.count())
for r in q.filter(needs_review=True):
    print("  flag:", r.race.communique.championship.edition, r.race.category, r.display_rank, r.rider.name if r.rider else None, "|", r.raw_row.get("_import_flag"))
'''


def main():
    if not (ROOT / "manage.py").exists() and "--no-run" not in sys.argv:
        sys.exit("Run this from the folder containing manage.py")
    for rel in ("pipeline/quality.py", "pipeline/parsers.py",
                "results/management/commands/import_pdf.py"):
        if not (ROOT / rel).exists():
            sys.exit(f"{rel} not found")
    plan, errors = build()
    if errors:
        print("[FAIL] nothing was written:")
        for e in errors:
            print("   ", e)
        sys.exit(1)
    for rel, text in plan.items():
        compile(text, rel, "exec")
    for rel, text in plan.items():
        dest = BACKUP / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
        (ROOT / rel).write_text(text, encoding="utf-8")
        print(f"[OK] patched {rel}")
    if plan:
        print(f"\nBackups in {BACKUP}")
    if "--no-run" in sys.argv:
        return
    subprocess.run([sys.executable, "-m", "pytest", "tests/test_parsers_unit.py", "-q"])
    subprocess.run([sys.executable, "manage.py", "import_pdf", "--edition", "74", "75", "77"])
    subprocess.run([sys.executable, "manage.py", "shell", "-c", CHECK])


if __name__ == "__main__":
    main()
