from django.core.management.base import BaseCommand
from results.models import Race, Result

class Command(BaseCommand):
    help = "Prints per-edition metrics for track cycling results baseline"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=== BASELINE METRICS REPORT ==="))
        
        races = Race.objects.all()
        # Check how edition is linked
        first_race = races.first()
        use_championship = first_race and hasattr(first_race, 'championship') and first_race.championship

        if use_championship:
            editions = sorted(list(set(r.championship.edition for r in races if r.championship and r.championship.edition)))
        else:
            editions = sorted(list(set(r.pdf_filename for r in races if hasattr(r, 'pdf_filename') and r.pdf_filename)))
            if not editions:
                editions = ["All Races"]

        header = f"{'Edition / PDF':<30} | {'Races':<6} | {'0-Res':<6} | {'Results':<8} | {'Flagged %':<10} | {'Text Fallback':<13}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        total_races = 0
        total_zero_res = 0
        total_results = 0
        total_flagged = 0
        total_fallback = 0

        for edition in editions:
            if use_championship:
                edition_races = races.filter(championship__edition=edition)
            elif edition != "All Races":
                edition_races = races.filter(pdf_filename=edition)
            else:
                edition_races = races

            r_count = edition_races.count()
            zero_res_count = 0
            res_count = 0
            flagged_count = 0
            fallback_count = 0

            for race in edition_races:
                results = race.results.all()
                rc = results.count()
                res_count += rc
                if rc == 0:
                    zero_res_count += 1
                
                for r in results:
                    if r.needs_review:
                        flagged_count += 1
                    raw = r.raw_row or {}
                    if raw.get('_import_flag') == 'text_fallback' or 'text_fallback' in str(raw):
                        fallback_count += 1

            flagged_pct = (flagged_count / res_count * 100) if res_count > 0 else 0.0

            total_races += r_count
            total_zero_res += zero_res_count
            total_results += res_count
            total_flagged += flagged_count
            total_fallback += fallback_count

            self.stdout.write(
                f"{str(edition):<30} | {r_count:<6} | {zero_res_count:<6} | {res_count:<8} | {flagged_pct:>9.1f}% | {fallback_count:<13}"
            )

        self.stdout.write("-" * len(header))
        overall_flagged_pct = (total_flagged / total_results * 100) if total_results > 0 else 0.0
        self.stdout.write(
            f"{'TOTALS':<30} | {total_races:<6} | {total_zero_res:<6} | {total_results:<8} | {overall_flagged_pct:>9.1f}% | {total_fallback:<13}"
        )
