import pdfplumber
from pipeline.segmenter import get_spatially_sorted_text

pdf_path = ".cache/pdfs/06f9c327.pdf" # 2023 hash

with pdfplumber.open(pdf_path) as pdf:
    for page_num in [42, 43, 44, 45]:
        page = pdf.pages[page_num - 1]
        words = page.extract_words()
        header_words = [w for w in words if w['top'] < page.height * 0.35]
        header_text = get_spatially_sorted_text(header_words)
        print(f"--- PAGE {page_num} HEADER ---")
        print(header_text)
        print("------------------------\n")
