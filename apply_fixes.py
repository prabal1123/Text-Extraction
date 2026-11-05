#!/usr/bin/env python3
"""Applies the parser fixes to the track_results project.

Usage (from the folder containing manage.py):
    python apply_fixes.py --dry-run     # show what would change
    python apply_fixes.py               # apply (backups go to .backup_fixes/<timestamp>/)
"""
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DRY = "--dry-run" in sys.argv
ROOT = Path.cwd()
BACKUP = ROOT / ".backup_fixes" / datetime.now().strftime("%Y%m%d_%H%M%S")

# --------------------------------------------------------------------------
# New code blocks
# --------------------------------------------------------------------------
NEW_EXTRACT_STATUS = r'''_STATUS_RE = re.compile(r'\b(DNS|DNF|DSQ|ABD|REL|RELEGATED|RELEGATE)\b', re.IGNORECASE)

def extract_status(values):
    """Whole-word match only, so 'Abdul' is not ABD."""
    for val in values:
        m = _STATUS_RE.search(str(val or ''))
        if m:
            tok = m.group(1).upper()
            return 'REL' if tok.startswith('REL') else tok
    return 'OK'


'''

NEW_PROCESS_TABLE = r'''def process_table(table, config, headers=None):
    """Returns (rows, headers). Pass `headers` from an earlier page/table so
    headerless continuation pages can still be parsed."""
    if not table:
        return [], headers
    data_rows = []
    for row in table:
        row_clean = [str(cell).strip().replace('\n', ' ') if cell else '' for cell in row]
        if not any(row_clean):
            continue
        mapped_headers = [normalize_header(c, config['columns']) for c in row_clean]
        valid_matches = sum(1 for m in mapped_headers if m)
        is_header_row = valid_matches >= 2 and (
            'rank' in mapped_headers or 'bib' in mapped_headers or 'points' in mapped_headers
        )
        if not headers and is_header_row:
            headers = mapped_headers
            continue
        if headers and is_header_row:
            continue
        if headers:
            row_dict = {}
            row_sprints = []
            for i, h in enumerate(headers):
                if i < len(row_clean):
                    val = row_clean[i]
                    if h:
                        row_dict[h] = val
                    elif val:
                        row_sprints.append(val)
            if row_dict.get('bib') or row_dict.get('name'):
                row_dict['_sprints'] = row_sprints
                data_rows.append(row_dict)
    return data_rows, headers


'''

NEW_PARSE_PDF_TABLES = r'''def parse_pdf_tables(pdf_path, pages, layout_family):
    config = load_config(layout_family)
    if not config:
        return []
    data_rows = []
    headers = None  # carried across pages of the same communique
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            page = pdf.pages[p_num - 1]
            page_rows = []
            for table in page.extract_tables():
                rows, headers = process_table(table, config, headers)
                page_rows.extend(rows)
            if not page_rows:
                text_settings = {"vertical_strategy": "text", "horizontal_strategy": "text"}
                for table in page.extract_tables(table_settings=text_settings):
                    rows, headers = process_table(table, config, headers)
                    page_rows.extend(rows)
            data_rows.extend(page_rows)
    return data_rows


'''

TIME_SPEED_HELPER = r'''_TIME_RE = re.compile(r'(\d{1,2}:\d{2}\.\d{3}|\d{2,3}\.\d{3})')
_SPEED_RE = re.compile(r'(?<![\d:.])(\d{1,3}\.\d{2,3}|#DIV/0!)(?!\d)')

def split_time_speed(text):
    """Return (time_str, speed_str, remainder). The time is removed first so
    the speed pattern can't match inside it."""
    time_m = _TIME_RE.search(text)
    time_str = time_m.group(1) if time_m else ""
    rest = text.replace(time_str, " ", 1) if time_str else text
    speed_m = _SPEED_RE.search(rest)
    speed_str = speed_m.group(1) if speed_m else ""
    if speed_str:
        rest = rest.replace(speed_str, " ", 1)
    return time_str, speed_str, rest


'''

TEAM_BLOCK_BODY = (
    "time_str, speed_str, team_str = split_time_speed(right_part)\n"
    "{i}status = extract_status([right_part])\n"
    "{i}for s in ['DNS', 'DNF', 'DSQ', 'ABD', 'REL', 'RELEGATE', 'RELEGATED']:\n"
    "{i}    team_str = re.sub(rf'\\b{{s}}\\b', '', team_str, flags=re.I)\n"
    "{i}team_str = re.sub(r'\\s+', ' ', team_str).strip()\n"
)

TEST_FILE = r'''from pipeline.parsers import extract_status, process_table, split_time_speed

CFG = {'columns': {
    'rank': ['Rank'], 'bib': ['Start No.'], 'name': ['Name'],
    'dob': ['DOB'], 'team': ['State'], 'time': ['Time'],
}}
HEADER = ["Rank", "Start No.", "Name", "DOB", "State", "Time"]


def test_names_containing_status_letters_are_not_statuses():
    assert extract_status(["5", "101", "02:51.429"]) == "OK"
    assert extract_status(["Abdul Rahman", "Reliance Team"]) == "OK"


def test_real_statuses_are_detected():
    assert extract_status(["", "DNS"]) == "DNS"
    assert extract_status(["Relegated"]) == "REL"
    assert extract_status(["abd"]) == "ABD"


def test_headerless_continuation_page_is_parsed_with_carried_headers():
    page1 = [HEADER, ["1", "101", "Ravi Kumar", "01-01-2005", "Kerala", "02:51.429"]]
    page2 = [["36", "201", "Some Rider", "01-01-2009", "Punjab", "03:10.100"]]
    rows1, headers = process_table(page1, CFG)
    rows2, _ = process_table(page2, CFG, headers)
    assert len(rows1) == 1
    assert len(rows2) == 1 and rows2[0]["bib"] == "201"


def test_headerless_table_without_carry_yields_nothing():
    page2 = [["36", "201", "Some Rider", "01-01-2009", "Punjab", "03:10.100"]]
    rows, headers = process_table(page2, CFG)
    assert rows == [] and headers is None


def test_time_is_not_mistaken_for_speed():
    time_str, speed_str, rest = split_time_speed("Kerala 02:51.429 31.85")
    assert (time_str, speed_str) == ("02:51.429", "31.85")
    assert rest.split() == ["Kerala"]


def test_odd_speed_values_land_in_speed_not_team_name():
    _, speed, rest = split_time_speed("Kerala 02:51.429 5.00")
    assert speed == "5.00" and rest.split() == ["Kerala"]
    _, speed, rest = split_time_speed("Delhi 02:50.100 #DIV/0!")
    assert speed == "#DIV/0!" and rest.split() == ["Delhi"]
'''


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def replace_function(src, name, new_block):
    """Replace a top-level `def name(...)` up to the next top-level def."""
    pat = re.compile(rf"^def {name}\(.*?(?=^def |\Z)", re.M | re.S)
    if not pat.search(src):
        raise ValueError(f"function '{name}' not found")
    return pat.sub(lambda m: new_block, src, count=1)


def patch_parsers(src):
    if "split_time_speed" in src:
        raise ValueError("already patched")
    src = replace_function(src, "extract_status", NEW_EXTRACT_STATUS)
    src = replace_function(src, "process_table", NEW_PROCESS_TABLE)
    src = replace_function(src, "parse_pdf_tables", NEW_PARSE_PDF_TABLES)

    block = re.compile(
        r"^([ \t]*)time_match = re\.search.*?^\1team_str = team_str\.strip\(\)\n",
        re.M | re.S,
    )
    m = block.search(src)
    if not m:
        raise ValueError("time/speed block in parse_team_events not found")
    indent = m.group(1)
    body = TEAM_BLOCK_BODY.format(i=indent)
    src = block.sub(lambda mm: indent + body, src, count=1)

    marker = "def parse_team_events("
    if marker not in src:
        raise ValueError("parse_team_events not found")
    src = src.replace(marker, TIME_SPEED_HELPER + marker, 1)
    return src


def patch_import_pdf(src):
    old = "status = extract_status(row.values())"
    new = "status = extract_status([row.get('rank', ''), row.get('time', ''), row.get('speed', '')])"
    if new in src:
        raise ValueError("already patched")
    if old not in src:
        raise ValueError("expected extract_status(row.values()) line not found")
    return src.replace(old, new, 1)


def apply(path, patcher):
    p = ROOT / path
    if not p.exists():
        print(f"  [SKIP] {path}: file not found")
        return False
    original = p.read_text(encoding="utf-8")
    try:
        updated = patcher(original)
    except ValueError as e:
        print(f"  [SKIP] {path}: {e}")
        return False
    compile(updated, str(p), "exec")  # syntax check before writing anything
    if DRY:
        print(f"  [DRY]  {path}: would be patched")
        return True
    dest = BACKUP / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    p.write_text(updated, encoding="utf-8")
    print(f"  [OK]   {path}: patched (backup in {dest})")
    return True


def main():
    if not (ROOT / "manage.py").exists():
        sys.exit("Run this from the project root (the folder containing manage.py).")
    print("Dry run, no files will change.\n" if DRY else "Applying fixes...\n")

    apply("pipeline/parsers.py", patch_parsers)
    apply("results/management/commands/import_pdf.py", patch_import_pdf)

    test_path = ROOT / "tests" / "test_parsers_unit.py"
    if test_path.exists():
        print("  [SKIP] tests/test_parsers_unit.py: already exists")
    elif DRY:
        print("  [DRY]  tests/test_parsers_unit.py: would be created")
    else:
        test_path.write_text(TEST_FILE, encoding="utf-8")
        print("  [OK]   tests/test_parsers_unit.py: created")

    # Warn about other callers of process_table (it now returns a tuple)
    for f in ROOT.rglob("*.py"):
        parts = set(f.parts)
        if ".venv" in parts or ".backup_fixes" in parts or f.name == "apply_fixes.py":
            continue
        if f.name == "parsers.py" and f.parent.name == "pipeline":
            continue
        if "process_table(" in f.read_text(encoding="utf-8", errors="ignore"):
            print(f"  [WARN] {f.relative_to(ROOT)} calls process_table(); it now returns (rows, headers)")

    if not DRY:
        print("\nRunning the new unit tests...")
        subprocess.run([sys.executable, "-m", "pytest", "tests/test_parsers_unit.py", "-q"])
        print("\nNext: python manage.py import_pdf && python manage.py audit_results")
        print(f"To undo: copy the files from {BACKUP} back over the originals.")


if __name__ == "__main__":
    main()