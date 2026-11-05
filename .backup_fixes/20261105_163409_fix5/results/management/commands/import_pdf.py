from django.core.management.base import BaseCommand
from results.models import Race, Result, Rider, Team, Championship, TeamMember, PointsDetail
from pipeline.parsers import parse_pdf_tables, parse_team_events, parse_time_to_ms, extract_status

class Command(BaseCommand):
    help = 'Parses tables for timed, placing, team, and points layouts and populates Results.'

    def handle(self, *args, **options):
        championships = Championship.objects.all()
        
        Result.objects.all().delete()
        TeamMember.objects.all().delete()
        PointsDetail.objects.all().delete()
        
        total_results = 0
        total_members = 0
        total_points = 0
        
        for champ in championships:
            pdf_path = f".cache/pdfs/{champ.pdf_hash}.pdf"
            races = Race.objects.filter(communique__championship=champ, layout_family__in=['timed', 'placing', 'team', 'points'])
            
            self.stdout.write(self.style.SUCCESS(f"\nParsing {races.count()} supported races for {champ.edition}th Edition..."))
            
            for race in races:
                pages = [int(p) for p in race.communique.page_range.split('-')]
                if len(pages) == 2: pages = list(range(pages[0], pages[1] + 1))
                
                # --- PROCESS TIMED, PLACING, & POINTS ---
                if race.layout_family in ['timed', 'placing', 'points']:
                    extracted_rows = parse_pdf_tables(pdf_path, pages, race.layout_family)
                    
                    for row in extracted_rows:
                        status = extract_status([row.get('rank', ''), row.get('time', ''), row.get('speed', '')])
                        display_rank = row.get('rank', '').strip()
                        numeric_rank = None
                        if display_rank.isdigit(): numeric_rank = int(display_rank)
                        elif display_rank.lower() == 'gold': numeric_rank = 1
                        elif display_rank.lower() == 'silver': numeric_rank = 2
                        elif display_rank.lower() == 'bronze': numeric_rank = 3
                            
                        team_obj = None
                        if row.get('team', '').strip():
                            team_obj, _ = Team.objects.get_or_create(name=row.get('team', '').strip())
                        
                        rider_obj = None
                        if row.get('name', '').strip():
                            rider_obj, _ = Rider.objects.get_or_create(
                                name=row.get('name', '').strip(), 
                                dob=row.get('dob', '').strip(),
                                defaults={'gender': race.gender}
                            )
                            
                        # Parse total points if available
                        pts_val = row.get('points')
                        total_pts_int = int(pts_val) if pts_val and str(pts_val).lstrip('-').isdigit() else None

                        result = Result.objects.create(
                            race=race, rider=rider_obj, team=team_obj, display_rank=display_rank,
                            numeric_rank=numeric_rank, status=status, bib=row.get('bib', '').strip(),
                            time_ms=parse_time_to_ms(row.get('time')), speed=row.get('speed', '').strip(),
                            points=total_pts_int, raw_row=row, needs_review=(status != 'OK' and not numeric_rank)
                        )
                        total_results += 1
                        
                        # Store unmapped sprint/sub-score columns as PointsDetail
                        sprints = row.get('_sprints', [])
                        for idx, s_val in enumerate(sprints):
                            if s_val.strip():
                                PointsDetail.objects.create(
                                    result=result,
                                    sprint_number=idx + 1,
                                    points_awarded=int(s_val) if s_val.lstrip('-').isdigit() else 0,
                                    sub_scores_json={'raw_value': s_val}
                                )
                                total_points += 1
                        
                    self.stdout.write(f"  -> Processed Comm {race.communique.number or 'None'}: {len(extracted_rows)} results ({race.layout_family})")

                # --- PROCESS TEAM EVENTS ---
                elif race.layout_family == 'team':
                    team_blocks = parse_team_events(pdf_path, pages)
                    
                    for block in team_blocks:
                        display_rank = block['rank']
                        numeric_rank = None
                        if display_rank.isdigit(): numeric_rank = int(display_rank)
                        elif display_rank.lower() == 'gold': numeric_rank = 1
                        elif display_rank.lower() == 'silver': numeric_rank = 2
                        elif display_rank.lower() == 'bronze': numeric_rank = 3
                        
                        team_obj = None
                        if block['team']:
                            team_obj, _ = Team.objects.get_or_create(name=block['team'])
                            
                        result = Result.objects.create(
                            race=race, rider=None, team=team_obj, display_rank=display_rank,
                            numeric_rank=numeric_rank, status=block['status'], bib=None,
                            time_ms=parse_time_to_ms(block['time']), speed=block['speed'],
                            raw_row=block, needs_review=(block['status'] != 'OK' and not numeric_rank)
                        )
                        total_results += 1
                        
                        for member in block['members']:
                            rider_obj, _ = Rider.objects.get_or_create(
                                name=member['name'], dob=member['dob'], defaults={'gender': race.gender}
                            )
                            TeamMember.objects.create(
                                result=result, rider=rider_obj, is_reserve=member['is_reserve']
                            )
                            total_members += 1

                    self.stdout.write(f"  -> Processed Comm {race.communique.number or 'None'}: {len(team_blocks)} teams, {sum(len(b['members']) for b in team_blocks)} riders (Team)")

        self.stdout.write(self.style.SUCCESS(f"\nPhase 5 Complete! Inserted {total_results} Result rows, {total_members} TeamMember rows, and {total_points} PointsDetail rows."))
