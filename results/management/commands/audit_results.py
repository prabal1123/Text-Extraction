from django.core.management.base import BaseCommand
from pipeline.normalizer import normalize_database
from pipeline.validator import run_validation
from results.models import Result, Championship

class Command(BaseCommand):
    help = 'Runs data normalization, cross-championship identity linking, and validation checks.'

    def handle(self, *args, **options):
        self.stdout.write("Running Database Normalization...")
        normalize_database()
        
        self.stdout.write("Running Validation & Flagging Rules...")
        run_validation()
        
        total_flagged = Result.objects.filter(needs_review=True).count()
        self.stdout.write(self.style.SUCCESS(f"\nAudit complete! Total results requiring review: {total_flagged}"))
        
        # Print a quick summary report grouped by championship
        for champ in Championship.objects.filter(communiques__isnull=False).distinct().order_by('edition'):
            flagged_in_champ = Result.objects.filter(race__communique__championship=champ, needs_review=True).count()
            self.stdout.write(f"  - {champ.edition}th Edition ({champ.year}): {flagged_in_champ} flagged items")
