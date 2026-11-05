import os
import re
import hashlib
import requests
from bs4 import BeautifulSoup
import pdfplumber
from results.models import Championship, ImportRun

CACHE_DIR = ".cache/pdfs"
SOURCE_URL = "https://www.cfiindia.in/track-results-1"

def setup_cache():
    os.makedirs(CACHE_DIR, exist_ok=True)

def extract_edition(text):
    match = re.search(r'(\d+)(?:st|nd|rd|th)', text, re.IGNORECASE)
    return int(match.group(1)) if match else None

def extract_year(text):
    match = re.search(r'(20\d{2})', text)
    return int(match.group(1)) if match else None

def get_year_from_pdf(pdf_path):
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = pdf.pages[0].extract_text() or ""
            return extract_year(text)
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {e}")
    return None

def fetch_all():
    setup_cache()
    print(f"Scraping {SOURCE_URL}...")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(SOURCE_URL, headers=headers)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a', href=re.compile(r'_files/ugd/.*\.pdf'))
    
    results = []
    for link in links:
        href = link.get('href')
        if not href.startswith('http'):
            href = f"https://www.cfiindia.in{href}" if href.startswith('/') else f"https://{href}"
        
        text = link.get_text(strip=True)
        edition = extract_edition(text)
        if not edition:
            continue
            
        print(f"\n[{edition}th Edition] Found link: {text}")
        
        championship = Championship.objects.filter(source_url=href).first()
        if championship:
            pdf_path = os.path.join(CACHE_DIR, f"{championship.pdf_hash}.pdf")
            if os.path.exists(pdf_path):
                print(f"  -> Already cached (Hash: {championship.pdf_hash[:8]}...)")
                results.append(championship)
                continue

        print(f"  -> Downloading {href}...")
        dl_resp = requests.get(href, stream=True, headers=headers)
        dl_resp.raise_for_status()
        
        sha256_hash = hashlib.sha256()
        content = bytearray()
        for chunk in dl_resp.iter_content(chunk_size=8192):
            if chunk:
                content.extend(chunk)
                sha256_hash.update(chunk)
        
        pdf_hash = sha256_hash.hexdigest()
        pdf_path = os.path.join(CACHE_DIR, f"{pdf_hash}.pdf")
        
        with open(pdf_path, 'wb') as f:
            f.write(content)
            
        year = extract_year(text)
        if not year:
            print("  -> Year missing in link text, inspecting PDF page 1...")
            year = get_year_from_pdf(pdf_path)
            
        championship, created = Championship.objects.update_or_create(
            edition=edition,
            defaults={
                'year': year,
                'source_url': href,
                'pdf_hash': pdf_hash
            }
        )
        
        ImportRun.objects.create(
            championship=championship,
            status='DOWNLOADED',
            log=f"Downloaded and cached as {pdf_path}"
        )
        
        print(f"  -> Saved to DB (Year: {year})")
        results.append(championship)

    return results