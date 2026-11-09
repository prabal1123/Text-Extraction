import re
import os
import yaml
import pdfplumber

def load_config(layout_family):
    path = f'layouts/{layout_family}.yaml'
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def normalize_header(header, config_columns):
    if not header: return None
    header_clean = re.sub(r'\s+', ' ', str(header).strip()).lower()
    for canon_col, aliases in config_columns.items():
        for alias in aliases:
            if re.sub(r'\s+', ' ', str(alias).lower()) == header_clean:
                return canon_col
    for canon_col, aliases in config_columns.items():
        for alias in aliases:
            alias_clean = re.sub(r'\s+', ' ', str(alias).lower())
            if len(alias_clean) > 2 and alias_clean in header_clean:
                return canon_col
    return None

def parse_time_to_ms(time_str):
    if not time_str: return None
    time_str = str(time_str).strip()
    match = re.search(r'(?:(\d{1,2}):)?(\d{1,2})\.(\d{1,3})', time_str)
    if match:
        mins = int(match.group(1)) if match.group(1) else 0
        secs = int(match.group(2))
        ms = int(match.group(3))
        if len(match.group(3)) == 1: ms *= 100
        elif len(match.group(3)) == 2: ms *= 10
        return mins * 60000 + secs * 1000 + ms
    return None

_STATUS_RE = re.compile(r'\b(DNS|DNF|DSQ|ABD|REL|RELEGATED|RELEGATE)\b', re.IGNORECASE)

def extract_status(values):
    """Whole-word match only, so 'Abdul' is not ABD."""
    for val in values:
        m = _STATUS_RE.search(str(val or ''))
        if m:
            tok = m.group(1).upper()
            return 'REL' if tok.startswith('REL') else tok
    return 'OK'


# --- Column Voting & Role Inference for Family B/C ---
_DOB_CELL_RE = re.compile(r'^\d{1,2}[./-](?:\d{1,2}|[A-Za-z]{3})[./-]\d{2,4}$')
_TIME_CELL_RE = re.compile(r'^(?:(\d{1,2}):)?(\d{1,2})\.(\d{3})$')
_SPEED_CELL_RE = re.compile(r'^\d{1,3}\.\d{2,3}$')
_RANK_CELL_RE = re.compile(r'^(?:[1-9]\d*|[I|V|X]+|Gold|Silver|Bronze|\d+(?:st|nd|rd|th))$', re.I)
_BIB_CELL_RE = re.compile(r'^\*?\d{1,4}$')

def infer_column_roles_by_voting(cleaned_table):
    """Votes on column roles across table rows based on content patterns."""
    if not cleaned_table or len(cleaned_table) < 2:
        return None
        
    ncols = max(len(row) for row in cleaned_table)
    col_votes = [{} for _ in range(ncols)]
    
    for row in cleaned_table:
        for col_idx, cell in enumerate(row):
            val = cell.strip()
            if not val:
                continue
            if _DOB_CELL_RE.match(val):
                col_votes[col_idx]['dob'] = col_votes[col_idx].get('dob', 0) + 1
            elif _TIME_CELL_RE.match(val):
                col_votes[col_idx]['time'] = col_votes[col_idx].get('time', 0) + 1
            elif _SPEED_CELL_RE.match(val):
                col_votes[col_idx]['speed'] = col_votes[col_idx].get('speed', 0) + 1
            elif _RANK_CELL_RE.match(val):
                col_votes[col_idx]['rank'] = col_votes[col_idx].get('rank', 0) + 1
            elif _BIB_CELL_RE.match(val):
                col_votes[col_idx]['bib'] = col_votes[col_idx].get('bib', 0) + 1
            elif len(val) >= 3 and not val.isdigit():
                col_votes[col_idx]['name_or_team'] = col_votes[col_idx].get('name_or_team', 0) + 1

    inferred_headers = [None] * ncols
    assigned_roles = set()
    
    for col_idx, votes in enumerate(col_votes):
        if not votes:
            continue
        best_role = max(votes, key=votes.get)
        if best_role not in assigned_roles and best_role != 'name_or_team':
            inferred_headers[col_idx] = best_role
            assigned_roles.add(best_role)
            
    for col_idx, h in enumerate(inferred_headers):
        if h is None:
            if 'bib' in assigned_roles and 'name' not in assigned_roles:
                inferred_headers[col_idx] = 'name'
                assigned_roles.add('name')
            elif 'name' in assigned_roles and 'team' not in assigned_roles:
                inferred_headers[col_idx] = 'team'
                assigned_roles.add('team')
                
    return inferred_headers


def _split_merged_header(cell, ncols, config):
    text = re.sub(r'\s+', ' ', str(cell).lower())
    cands = []
    for canon, aliases in config['columns'].items():
        for a in aliases:
            a_clean = re.sub(r'\s+', ' ', str(a).lower()).strip()
            if a_clean:
                cands.append((a_clean, canon))
    cands.sort(key=lambda t: -len(t[0]))
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
            break
            
    active = _merge_headers(parts) if parts else headers
    
    # Trigger voting fallback if header is unrecognised or missing
    if active is None:
        active = infer_column_roles_by_voting(cleaned)
        start = 0  # no header row to skip

    if active is None:
        return [], headers

    data_rows = []
    last_time = ""
    for r in cleaned[start:]:
        if parts and _as_header(r, config):
            continue
        row_dict = {}
        row_sprints = []
        for i, h in enumerate(active):
            val = r[i] if i < len(r) else ''
            if not h:
                continue
            # Handle ditto marks in time column ("-- do --" means same time as above)
            if h == 'time' and ('do' in val.lower() or '---' in val):
                val = last_time
            elif h == 'time' and val:
                last_time = val
                
            # Strip trailing tokens like Gold/Silver/Bronze/NR from team or time
            if h in ('team', 'time') and val:
                val = re.sub(r'\b(Gold|Silver|Bronze|NR|\+1\s*Lap|Sec\.?)\b', '', val, flags=re.I).strip()

            if h.startswith('sprint_'):
                row_sprints.append(val)
            else:
                row_dict[h] = val
                
        if 'name' in active and not re.search(r'[A-Za-z]', row_dict.get('name', '')):
            continue
        if row_dict.get('bib') or row_dict.get('name'):
            row_dict['_sprints'] = row_sprints
            data_rows.append(row_dict)
    return data_rows, active


def parse_pdf_tables(pdf_path, pages, layout_family, y_top=None, y_bottom=None):
    config = load_config(layout_family)
    data_rows = []
    headers = None
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            page = pdf.pages[p_num - 1]
            if y_top is not None or y_bottom is not None:
                yt = y_top if y_top is not None else 0
                yb = y_bottom if y_bottom is not None else page.height
                page = page.crop((0, yt, page.width, yb))
            
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


_TIME_RE = re.compile(r'(\d{1,2}:\d{2}\.\d{3}|\d{2,3}\.\d{3})')
_SPEED_RE = re.compile(r'(?<![\d:.])(\d{1,3}\.\d{2,3}|#DIV/0!)(?!\d)')

def split_time_speed(text):
    time_m = _TIME_RE.search(text)
    time_str = time_m.group(1) if time_m else ""
    rest = text.replace(time_str, " ", 1) if time_str else text
    speed_m = _SPEED_RE.search(rest)
    speed_str = speed_m.group(1) if speed_m else ""
    if speed_str:
        rest = rest.replace(speed_str, " ", 1)
    return time_str, speed_str, rest


def parse_team_events(pdf_path, pages, y_top=None, y_bottom=None):
    data_rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            page = pdf.pages[p_num - 1]
            if y_top is not None or y_bottom is not None:
                yt = y_top if y_top is not None else 0
                yb = y_bottom if y_bottom is not None else page.height
                page = page.crop((0, yt, page.width, yb))
            words = page.extract_words()
            lines_dict = {}
            for w in words:
                y = round(w['top'] / 6)
                if y not in lines_dict: lines_dict[y] = []
                lines_dict[y].append(w)
            sorted_y = sorted(lines_dict.keys())
            current_team = None
            for y in sorted_y:
                line_words = sorted(lines_dict[y], key=lambda w: w['x0'])
                line_text = " ".join(w['text'] for w in line_words)
                dob_match = re.search(r'\b(\d{1,2}[./-](?:[A-Za-z]{3}|\d{1,2})[./-]?\d{2,4})\b', line_text)
                if not dob_match: continue
                dob = dob_match.group(1)
                left_part = line_text[:dob_match.start()].strip()
                right_part = line_text[dob_match.end():].strip()
                tokens = left_part.split()
                rank, bib, name = "", "", ""
                if len(tokens) >= 2 and re.match(r'^(\d+|Gold|Silver|Bronze)$', tokens[0], re.I) and re.match(r'^\*?\d+$', tokens[1]):
                    rank = tokens[0]
                    bib = tokens[1]
                    name = " ".join(tokens[2:])
                elif len(tokens) >= 1 and re.match(r'^\*?\d+$', tokens[0]):
                    bib = tokens[0]
                    name = " ".join(tokens[1:])
                else:
                    bib = tokens[0] if tokens else ""
                    name = " ".join(tokens[1:]) if len(tokens)>1 else ""
                time_str, speed_str, team_str = split_time_speed(right_part)
                status = extract_status([right_part])
                for s in ['DNS', 'DNF', 'DSQ', 'ABD', 'REL', 'RELEGATE', 'RELEGATED']:
                    team_str = re.sub(rf'\b{s}\b', '', team_str, flags=re.I)
                team_str = re.sub(r'\s+', ' ', team_str).strip()
                if rank or time_str or len(team_str) > 2:
                    current_team = {
                        'rank': rank, 'team': team_str, 'time': time_str, 'speed': speed_str,
                        'status': status if status != 'OK' else 'OK', 'members': []
                    }
                    data_rows.append(current_team)
                if current_team:
                    is_reserve = bib.startswith('*')
                    clean_bib = bib.replace('*', '')
                    current_team['members'].append({
                        'bib': clean_bib, 'name': name, 'dob': dob, 'is_reserve': is_reserve, 'raw': line_text
                    })
    return data_rows
