import re
import pdfplumber
from results.models import Rider, Team, Result, TeamMember

def parse_medalist_pdf(pdf_path, race_obj):
    """
    Parses consolidated medalist summary PDFs and creates Result rows,
    skipping duplicates based on rider, race, and display rank.
    Returns a tuple of (imported_count, skipped_count).
    """
    imported_count = 0
    skipped_count = 0
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    cells = [str(c).strip().replace('\n', ' ') for c in row if c is not None]
                    if len(cells) < 8:
                        continue
                        
                    if 'Bib' in cells[0] or 'Name' in cells[0] or 'Category' in cells[0]:
                        continue
                        
                    category = cells[0] if len(cells) > 0 else "Elite"
                    bib = cells[1] if len(cells) > 1 else ""
                    name = cells[2] if len(cells) > 2 else ""
                    dob = cells[3] if len(cells) > 3 else ""
                    state = cells[4] if len(cells) > 4 else ""
                    timing = cells[7] if len(cells) > 7 else ""
                    medal = cells[8] if len(cells) > 8 else (cells[6] if len(cells) > 6 else "")
                    event = cells[9] if len(cells) > 9 else (cells[-1] if len(cells) > 0 else "")
                    
                    if not name or len(name) < 2:
                        continue
                        
                    medal_lower = medal.lower()
                    display_rank = medal
                    numeric_rank = 1 if 'gold' in medal_lower else (2 if 'silver' in medal_lower else (3 if 'bronze' in medal_lower else None))
                    
                    team_obj = Team.objects.get_or_create(name=state)[0] if state else None
                    rider_obj = Rider.objects.filter(name=name).first()
                    if not rider_obj:
                        rider_obj = Rider.objects.create(name=name, gender='Men/Women')
                    
                    exists = Result.objects.filter(
                        race=race_obj,
                        rider=rider_obj,
                        display_rank=display_rank
                    ).exists()
                    
                    if exists:
                        skipped_count += 1
                        continue
                    
                    Result.objects.create(
                        race=race_obj,
                        rider=rider_obj,
                        team=team_obj,
                        display_rank=display_rank,
                        numeric_rank=numeric_rank,
                        status='OK',
                        bib=bib,
                        speed=timing,
                        raw_row={'raw_cells': cells, 'event': event, 'category': category},
                        needs_review=False
                    )
                    imported_count += 1
                    
    return imported_count, skipped_count
