#!/usr/bin/env python3
"""Fix header detection: merged one-cell headers, stacked header rows,
positional sprint columns, and junk-table guard."""
import re, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
BACKUP = ROOT / ".backup_fixes" / datetime.now().strftime("%Y%m%d_%H%M%S_fix3")

NEW_BLOCK = r'''def _split_merged_header(cell, ncols, config):
    """Header text jammed into one cell ('Rank Start No. Name ...'): find the
    column aliases in order. Only accepted if the count equals the column count."""
    text = re.sub(r'\s+', ' ', str(cell).lower())
    cands = []
    for canon, aliases in config['columns'].items():
        for a in aliases:
            a_clean = re.sub(r'\s+', ' ', str(a).lower()).strip()
            if a_clean:
                cands.append((a_clean, canon))
    cands.sort(key=lambda t: -len(t[0]))      # longest alias first
    taken = [False] * len(text)
    found = []
    for a, canon in cands:
        start = 0
        while True:
            pos = text.find(a, start)
            if pos == -1:
                break
            end = pos + len(a)
            left_ok = pos == 0 or not text[pos - 1].isalnum()
            right_ok = end == len(text) or not text[end].isalnum()
            if left_ok and right_ok and not any(taken[pos:end]):
                for k in range(pos, end):
                    taken[k] = True
                found.append((pos, canon, a))
            start = pos + 1
    found.sort()
    if len(found) != ncols:
        return None
    return [c for _, c, _ in found], [a for _, _, a in found]


def _as_header(row_clean, config):
    """Return (mapped, labels) if this row is a header row, else None."""
    nonempty = [c for c in row_clean if c]
    if len(nonempty) == 1 and len(row_clean) >= 3:
        res = _split_merged_header(nonempty[0], len(row_clean), config)
        if res:
            return res
    mapped = [normalize_header(c, config['columns']) for c in row_clean]
    names = {m for m in mapped if m}
    if sum(1 for m in mapped if m) >= 2 and names & {'rank', 'bib', 'points'}:
        return mapped, row_clean
    return None


def _merge_headers(parts):
    """Combine stacked header rows column by column."""
    ncols = max(len(m) for m, _ in parts)
    mapped = [None] * ncols
    labels = [''] * ncols
    for m, l in parts:
        for i in range(len(m)):
            if mapped[i] is None and m[i]:
                mapped[i] = m[i]
            if not labels[i] and l[i]:
                labels[i] = l[i]
    seen = {}
    out = []
    for i in range(ncols):
        h = mapped[i]
        if h:
            n = seen.get(h, 0) + 1
            seen[h] = n
            out.append(h if n == 1 else f"{h}_{n}")
        else:
            lab = labels[i].strip()
            if lab.isdigit():
                out.append(f"sprint_{lab}")
            elif lab:
                out.append("x_" + re.sub(r'\W+', '_', lab.lower()).strip('_'))
            else:
                out.append(f"sprint_c{i}")
    return out


def process_table(table, config, headers=None):
    """Returns (rows, headers_used). The table's own header row(s) always win;
    `headers` from an earlier page is only a fallback for headerless tables."""
    if not table:
        return [], headers

    cleaned = []
    for row in table:
        row_clean = [str(cell).strip().replace('\n', ' ') if cell else '' for cell in row]
        if any(row_clean):
            cleaned.append(row_clean)

    parts = []
    start = 0
    for idx, r in enumerate(cleaned):
        h = _as_header(r, config)
        if h:
            parts.append(h)
            start = idx + 1
        elif parts:
            break                      # header block ended
    active = _merge_headers(parts) if parts else headers
    if active is None:
        return [], headers

    data_rows = []
    for r in cleaned[start:]:
        if _as_header(r, config):      # repeated header row inside the table
            continue
        row_dict = {}
        row_sprints = []
        for i, h in enumerate(active):
            val = r[i] if i < len(r) else ''
            if not h:
                continue
            if h.startswith('sprint_'):
                row_sprints.append(val)    # keep blanks: position = sprint number
            else:
                row_dict[h] = val
        if 'name' in active and not re.search(r'[A-Za-z]', row_dict.get('name', '')):
            continue                   # e.g. a plain table of bib numbers
        if row_dict.get('bib') or row_dict.get('name'):
            row_dict['_sprints'] = row_sprints
            data_rows.append(row_dict)
    return data_rows, active


'''

NEW_TESTS = '''

# ---- fix3 tests ----
TIMED_CFG = {'columns': {
    'rank': ['Rank'], 'bib': ['Start No.', 'Start No'], 'name': ['Name'],
    'dob': ['DOB'], 'team': ['State'], 'time': ['Time'], 'speed': ['@speed', 'Speed'],
}}
POINTS_CFG = {'columns': {
    'rank': ['Rank'], 'bib': ['Bib No.'], 'name': ['Name'], 'dob': ['DOB'],
    'team': ['State'], 'points': ['Points'], 'lap': ['Lap +/-', '+/-', 'Lap'],
}}


def test_merged_header_cell_is_split():
    t = [['Rank Start No. Name DOB State Time @speed', '', '', '', '', '', ''],
         ['1', '2', 'David Beckham', '20.09.2003', 'Andaman & Nicobar', '01:05.423', '55.03']]
    rows, _ = process_table(t, TIMED_CFG)
    assert len(rows) == 1
    assert rows[0]['bib'] == '2' and rows[0]['time'] == '01:05.423' and rows[0]['speed'] == '55.03'


def test_stacked_points_header_and_sprint_positions():
    t = [
        [''] * 15 + ['FO', '+ Lap', '- Lap', 'Points'],
        ['Rank', 'Bib No.', 'Name', 'DOB', 'State'] + [str(i) for i in range(1, 11)] + ['', '', '', ''],
        ['1', '388', 'Kheta Ram Chiga', '07.09.2005', 'Rajasthan',
         '', '', '', '3', '', '5', '', '5', '3', '10', '', '1', '', '46'],
    ]
    rows, _ = process_table(t, POINTS_CFG)
    assert len(rows) == 1
    r = rows[0]
    assert r['bib'] == '388' and r['points'] == '46' and r['lap_2'] == '1'
    assert r['_sprints'] == ['', '', '', '3', '', '5', '', '5', '3', '10']


def test_plain_number_table_is_not_parsed_with_carried_headers():
    t = [['Rank Start No. Name DOB State Time @speed', '', '', '', '', '', ''],
         ['1', '2', 'A B', '01.01.2000', 'X', '01:00.000', '50.00']]
    _, h = process_table(t, TIMED_CFG)
    nums = [['299', '477', '103', '165', '75', '388', '75']]
    rows, _ = process_table(nums, TIMED_CFG, h)
    assert rows == []
'''


def main():
    pf = ROOT / "pipeline" / "parsers.py"
    if not pf.exists():
        sys.exit("Run from the project root (folder with manage.py).")
    src = pf.read_text(encoding="utf-8")
    if "_split_merged_header" in src:
        sys.exit("Already applied.")
    pat = re.compile(r"^def process_table\(.*?(?=^def )", re.M | re.S)
    if not pat.search(src):
        sys.exit("process_table not found.")
    new = pat.sub(lambda m: NEW_BLOCK, src, count=1)
    compile(new, str(pf), "exec")
    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pf, BACKUP / "parsers.py")
    pf.write_text(new, encoding="utf-8")
    print(f"[OK] patched pipeline/parsers.py (backup: {BACKUP})")

    tf = ROOT / "tests" / "test_parsers_unit.py"
    if tf.exists() and "test_merged_header_cell_is_split" not in tf.read_text():
        tf.write_text(tf.read_text() + NEW_TESTS, encoding="utf-8")
        print("[OK] added tests")
    subprocess.run([sys.executable, "-m", "pytest", "tests/test_parsers_unit.py", "-q"])


if __name__ == "__main__":
    main()