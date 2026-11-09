import re
import pdfplumber

def get_spatially_sorted_text(words, y_tolerance=4):
    """Sorts words by vertical position, then horizontal, to defeat scrambled headers."""
    if not words: return ""
    sorted_words = sorted(words, key=lambda w: (round(w['top'] / y_tolerance), w['x0']))
    return " ".join(w['text'] for w in sorted_words)

_DOB_CHECK_RE = re.compile(r'\d{1,2}[./-](?:\d{1,2}|[A-Za-z]{3})[./-]\d{2,4}')
_EVENT_KEYWORDS = ['Sprint', 'Keirin', 'Scratch', 'Pursuit', 'Time Trial', 'Elimination', 'Points Race', 'Point Race', 'Omnium', 'Madison']

def is_likely_title_line(line_text):
    text = line_text.strip()
    if not text or len(text) < 4:
        return False
    if _DOB_CHECK_RE.search(text):
        return False
    if re.match(r'^\d+\s+\d+', text):
        return False
    has_keyword = any(kw.lower() in text.lower() for kw in _EVENT_KEYWORDS)
    has_event_num = bool(re.search(r'Event\s*(?:No\.?|[:\-])', text, re.I))
    return has_keyword or has_event_num

def segment_pdf(pdf_path):
    """
    Segments a PDF into communiques / events with page numbers and y-coordinate crop bounds.
    Splits pages into multiple events if multiple distinct event title lines are detected.
    """
    segments = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            words = page.extract_words()
            
            if len(words) < 15:
                print(f"    -> Dropping page {page_num}: Noise/Blank (<15 words)")
                continue
                
            page_height = page.height
            
            # Group words into horizontal text lines by y-position
            lines_dict = {}
            for w in words:
                y = round(w['top'] / 4)
                if y not in lines_dict: lines_dict[y] = []
                lines_dict[y].append(w)
                
            sorted_y = sorted(lines_dict.keys())
            text_lines = []
            for y in sorted_y:
                line_words = sorted(lines_dict[y], key=lambda w: w['x0'])
                line_text = " ".join(w['text'] for w in line_words)
                min_top = min(w['top'] for w in line_words)
                max_bottom = max(w['bottom'] for w in line_words)
                text_lines.append({'text': line_text, 'top': min_top, 'bottom': max_bottom})
                
            full_page_text = " ".join(l['text'] for l in text_lines)
            if re.search(r'START\s*SHEET|STARTLIST', full_page_text, re.IGNORECASE):
                print(f"    -> Dropping page {page_num}: Start Sheet page (no results)")
                continue
                
            title_indices = []
            for idx, l in enumerate(text_lines):
                if l['top'] < page_height * 0.5 and is_likely_title_line(l['text']):
                    if not title_indices or (l['top'] - text_lines[title_indices[-1]]['top'] > 30):
                        title_indices.append(idx)
                        
            if not title_indices:
                header_text = text_lines[0]['text'] if text_lines else ""
                segments.append({
                    'pages': [page_num],
                    'y_top': 0,
                    'y_bottom': page_height,
                    'header_text': header_text,
                    'full_text': full_page_text,
                    'number': None,
                    'event_index': 0
                })
            else:
                for e_idx, t_idx in enumerate(title_indices):
                    t_line = text_lines[t_idx]
                    y_top = t_line['top'] - 10 if e_idx == 0 else text_lines[title_indices[e_idx-1]]['bottom']
                    y_bottom = text_lines[title_indices[e_idx+1]]['top'] if (e_idx + 1 < len(title_indices)) else page_height
                    
                    event_lines = [l['text'] for l in text_lines if y_top <= l['top'] < y_bottom]
                    event_text = "\n".join(event_lines)
                    
                    segments.append({
                        'pages': [page_num],
                        'y_top': max(0, y_top),
                        'y_bottom': min(page_height, y_bottom),
                        'header_text': t_line['text'],
                        'full_text': event_text,
                        'number': None,
                        'event_index': e_idx
                    })
                    
    return segments
