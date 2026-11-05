from results.models import Result, Race

def run_validation():
    flagged_count = 0
    
    # Reset review flags
    Result.objects.exclude(raw_row__has_key='_import_flag').update(needs_review=False)
    
    for race in Race.objects.all():
        results = race.results.all()
        
        # Rule 1: Check for duplicate bibs in the same race (e.g. 2025 Women Junior Keirin #427 anomaly)
        bibs = [r.bib for r in results if r.bib and r.status == 'OK']
        duplicates = set([b for b in bibs if bibs.count(b) > 1])
        
        if duplicates:
            for r in results:
                if r.bib in duplicates:
                    r.needs_review = True
                    r.raw_row['_review_flag'] = f"Duplicate bib {r.bib} found in race"
                    r.save()
                    flagged_count += 1

        # Rule 2: Rank vs Time order check for Timed events (Excluding Pursuits where rank != time order)
        if race.layout_family == 'timed' and 'pursuit' not in race.race_type.lower():
            sorted_by_time = sorted([r for r in results if r.time_ms and r.status == 'OK'], key=lambda x: x.time_ms)
            for idx, r in enumerate(sorted_by_time):
                expected_rank = idx + 1
                if r.numeric_rank and r.numeric_rank != expected_rank:
                    # Time doesn't match official rank order (common in match sprints or tactical rounds)
                    r.needs_review = True
                    r.raw_row['_review_flag'] = f"Rank {r.numeric_rank} differs from time order position {expected_rank}"
                    r.save()
                    flagged_count += 1

        # Rule 3: Flag missing rank or bad status without notes
        for r in results:
            if not r.display_rank and r.status == 'OK' and (r.time_ms or r.points):
                r.needs_review = True
                r.raw_row['_review_flag'] = "Missing rank for OK status result"
                r.save()
                flagged_count += 1

    print(f"Validation complete. Flagged {flagged_count} results for review.")
