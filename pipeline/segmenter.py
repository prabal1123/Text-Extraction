import re
import pdfplumber

def get_spatially_sorted_text(words, y_tolerance=4):
    """Sorts words by vertical position, then horizontal, to defeat scrambled headers."""
    if not words: return ""
    sorted_words = sorted(words, key=lambda w: (round(w['top'] / y_tolerance), w['x0']))
    return " ".join(w['text'] for w in sorted_words)

def segment_pdf(pdf_path):
    communiques_data = []
    current_comm = None
    
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            words = page.extract_words()
            
            # Rule 1: Drop if less than 15 words (blank, fragments, footer-only)
            if len(words) < 15:
                print(f"    -> Dropping page {page_num}: Noise/Blank (<15 words)")
                continue
                
            page_height = page.height
            header_words = [w for w in words if w['top'] < page_height * 0.35]
            header_text = get_spatially_sorted_text(header_words)
            full_text = get_spatially_sorted_text(words)
            
            # Rule 2: Headerless continuation page detection
            is_continuation = False
            if current_comm:
                # Look specifically for a Communique NUMBER pattern, not just the word
                has_comm_number = bool(re.search(r'(?:Communique|No\.?|No\s*:|Last Communique)\s*\d+', header_text, re.IGNORECASE))
                
                race_types = ['Time Trial', 'Pursuit', 'Sprint', 'Keirin', 'Scratch', 'Elimination', 'Point', 'Omnium', 'Madison']
                has_race_type = any(rt.lower() in header_text.lower() for rt in race_types)
                
                if not has_comm_number and not has_race_type:
                    is_continuation = True
            
            if is_continuation:
                print(f"    -> Merging page {page_num} as continuation of Comm. {current_comm['number'] or 'Unnumbered'}")
                current_comm['pages'].append(page_num)
                current_comm['full_text'] += "\n" + full_text
            else:
                if current_comm:
                    communiques_data.append(current_comm)
                
                current_comm = {
                    'pages': [page_num],
                    'header_text': header_text,
                    'full_text': full_text,
                    'number': None 
                }
        
        if current_comm:
            communiques_data.append(current_comm)
            
    return communiques_data
