from django.core.management.base import BaseCommand
from pipeline.fetcher import fetch_all

class Command(BaseCommand):
    help = 'Fetches track cycling result PDFs from CFI India website and caches them.'

    def handle(self, *args, **options):
        self.stdout.write("Starting fetch_results pipeline...")
        try:
            results = fetch_all()
            self.stdout.write(self.style.SUCCESS(f"\nFinished. Total championships processed: {len(results)}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during fetch: {str(e)}"))
