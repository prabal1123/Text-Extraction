import os
import django

# Set up Django so we can query the database
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import pdfplumber
from results.models import Championship

def get_spatially_sorted_text(words, y_tolerance=4):
    if not words: return ""
    sorted_words = sorted(words, key=lambda w: (round(w['top'] / y_tolerance), w['x0']))
    return " ".join(w['text'] for w in sorted_words)

# Get the exact 2023 (75th edition) PDF
champ = Championship.objects.get(edition=75)
pdf_path = f".cache/pdfs/{champ.pdf_hash}.pdf"

print(f"Reading {pdf_path}...")

with pdfplumber.open(pdf_path) as pdf:
    for page_num in [42, 43, 44, 45]:
        page = pdf.pages[page_num - 1]
        words = page.extract_words()
        header_words = [w for w in words if w['top'] < page.height * 0.35]
        header_text = get_spatially_sorted_text(header_words)
        print(f"--- PAGE {page_num} HEADER ---")
        print(header_text)
        print("------------------------\n")
