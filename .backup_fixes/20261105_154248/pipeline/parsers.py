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

def extract_status(row_values):
    statuses = ['DNS', 'DNF', 'DSQ', 'ABD', 'REL', 'RELEGATE', 'RELEGATED']
    for val in row_values:
        val_str = str(val).upper().strip()
        for s in statuses:
            if s in val_str:
                return 'REL' if 'REL' in s else s
    return 'OK'

def process_table(table, config):
    if not table: return []
    data_rows = []
    headers = None
    for row in table:
        row_clean = [str(cell).strip().replace('\n', ' ') if cell else '' for cell in row]
        if not any(row_clean): continue
        mapped_headers = [normalize_header(c, config['columns']) for c in row_clean]
        valid_matches = sum(1 for m in mapped_headers if m)
        is_header_row = valid_matches >= 2 and ('rank' in mapped_headers or 'bib' in mapped_headers or 'points' in mapped_headers)
        if not headers and is_header_row:
            headers = mapped_headers
            continue
        if headers and is_header_row: continue
        if headers:
            row_dict = {}
            row_sprints = []
            for i, h in enumerate(headers):
                if i < len(row_clean):
                    val = row_clean[i]
                    if h:
                        row_dict[h] = val
                    elif val:
                        # Unmapped wide columns (e.g. individual sprint scores in points race)
                        row_sprints.append(val)
            
            if row_dict.get('bib') or row_dict.get('name'):
                row_dict['_sprints'] = row_sprints
                data_rows.append(row_dict)
    return data_rows

def parse_pdf_tables(pdf_path, pages, layout_family):
    config = load_config(layout_family)
    if not config: return []
    data_rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            page = pdf.pages[p_num - 1]
            page_rows = []
            for table in page.extract_tables():
                page_rows.extend(process_table(table, config))
            if not page_rows:
                for table in page.extract_tables(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"}):
                    page_rows.extend(process_table(table, config))
            data_rows.extend(page_rows)
    return data_rows

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
                time_match = re.search(r'(\d{1,2}:\d{2}\.\d{3}|\d{2,3}\.\d{3})', right_part)
                time_str = time_match.group(1) if time_match else ""
                speed_match = re.search(r'(\d{2,3}\.\d{2,3}|#DIV/0!)', right_part)
                speed_str = speed_match.group(1) if speed_match else ""
                status = extract_status([right_part])
                team_str = right_part
                if time_str: team_str = team_str.replace(time_str, "")
                if speed_str: team_str = team_str.replace(speed_str, "")
                for s in ['DNS', 'DNF', 'DSQ', 'ABD', 'REL', 'RELEGATE', 'RELEGATED']:
                    team_str = re.sub(rf'\b{s}\b', '', team_str, flags=re.I)
                team_str = team_str.strip()
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
