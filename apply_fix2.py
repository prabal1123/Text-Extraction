#!/usr/bin/env python3
"""Corrects process_table: a table's own header wins; carried headers are only a fallback."""
import re, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
BACKUP = ROOT / ".backup_fixes" / datetime.now().strftime("%Y%m%d_%H%M%S_fix2")

NEW_PROCESS_TABLE = r'''def process_table(table, config, headers=None):
    """Returns (rows, headers_used). A table's own header row always wins;
    `headers` (from an earlier page) is only a fallback for tables that have none."""
    if not table:
        return [], headers

    cleaned = []
    for row in table:
        row_clean = [str(cell).strip().replace('\n', ' ') if cell else '' for cell in row]
        if any(row_clean):
            cleaned.append(row_clean)

    def as_header(row_clean):
        mapped = [normalize_header(c, config['columns']) for c in row_clean]
        ok = sum(1 for m in mapped if m) >= 2 and (
            'rank' in mapped or 'bib' in mapped or 'points' in mapped
        )
        return mapped if ok else None

    active = None
    start = 0
    for idx, r in enumerate(cleaned):
        m = as_header(r)
        if m:
            active = m
            start = idx + 1      # rows before the header are not data
            break
    if active is None:
        active = headers         # fallback: headerless continuation table
    if active is None:
        return [], headers

    data_rows = []
    for r in cleaned[start:]:
        if as_header(r):         # repeated header row inside the table
            continue
        row_dict = {}
        row_sprints = []
        for i, h in enumerate(active):
            if i < len(r):
                val = r[i]
                if h:
                    row_dict[h] = val
                elif val:
                    row_sprints.append(val)
        if row_dict.get('bib') or row_dict.get('name'):
            row_dict['_sprints'] = row_sprints
            data_rows.append(row_dict)
    return data_rows, active


'''

EXTRA_TEST = '''

def test_tables_own_header_wins_over_carried_headers():
    other = ["Rank", "Start No.", "Name", "DOB", "State", "Time"]
    carried = [normalize for normalize in [None, None, None, None, None, None]]
    own = [["Start No.", "Name", "Rank", "DOB", "State", "Time"],
           ["301", "Kiran", "4", "01-01-2006", "Goa", "03:00.000"]]
    _, h = process_table([other, ["1", "101", "A", "01-01-2005", "X", "02:00.000"]], CFG)
    rows, _ = process_table(own, CFG, h)   # different column order than carried
    assert rows[0]["bib"] == "301" and rows[0]["rank"] == "4"
'''


def main():
    pf = ROOT / "pipeline" / "parsers.py"
    if not pf.exists():
        sys.exit("Run from the project root (folder with manage.py).")
    src = pf.read_text(encoding="utf-8")
    if "headers_used" in src:
        sys.exit("Already applied.")
    pat = re.compile(r"^def process_table\(.*?(?=^def )", re.M | re.S)
    if not pat.search(src):
        sys.exit("process_table not found.")
    new = pat.sub(lambda m: NEW_PROCESS_TABLE, src, count=1)
    compile(new, str(pf), "exec")
    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pf, BACKUP / "parsers.py")
    pf.write_text(new, encoding="utf-8")
    print(f"[OK] patched pipeline/parsers.py (backup: {BACKUP})")

    tf = ROOT / "tests" / "test_parsers_unit.py"
    if tf.exists() and "own_header_wins" not in tf.read_text():
        tf.write_text(tf.read_text() + EXTRA_TEST, encoding="utf-8")
        print("[OK] added regression test")
    subprocess.run([sys.executable, "-m", "pytest", "tests/test_parsers_unit.py", "-q"])


if __name__ == "__main__":
    main()