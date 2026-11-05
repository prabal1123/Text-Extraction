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


def process_table(table, config, headers=None):
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


def parse_pdf_tables(pdf_path, pages, layout_family):
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


_TIME_RE = re.compile(r'(\d{1,2}:\d{2}\.\d{3}|\d{2,3}\.\d{3})')
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


def parse_team_events(pdf_path, pages):
    data_rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            page = pdf.pages[p_num - 1]
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
