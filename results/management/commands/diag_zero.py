import pdfplumber
from django.core.management.base import BaseCommand
from django.db.models import Count
from results.models import Race
from pipeline.parsers import load_config, normalize_header


class Command(BaseCommand):
    help = "Show what pdfplumber sees on races that imported 0 results."

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, default=75)
        parser.add_argument("--limit", type=int, default=4)

    def handle(self, *args, **opts):
        races = (Race.objects
                 .filter(communique__championship__edition=opts["edition"],
                         layout_family__in=["timed", "placing", "points"])
                 .annotate(n=Count("results")).filter(n=0)
                 .select_related("communique__championship")[: opts["limit"]])
        for race in races:
            champ = race.communique.championship
            first = int(race.communique.page_range.split("-")[0])
            self.stdout.write(f"\n===== Comm {race.communique.number} | pages {race.communique.page_range} "
                              f"| {race.race_type} / {race.category} | layout={race.layout_family}")
            config = load_config(race.layout_family)
            with pdfplumber.open(f".cache/pdfs/{champ.pdf_hash}.pdf") as pdf:
                page = pdf.pages[first - 1]
                tables = page.extract_tables()
                self.stdout.write(f"lines-strategy tables: {len(tables)}")
                for t in tables[:2]:
                    self.stdout.write(f"  table rows={len(t)}")
                    for row in t[:3]:
                        cleaned = [str(c).strip().replace('\n', ' ') if c else '' for c in row]
                        mapped = [normalize_header(c, config['columns']) for c in cleaned]
                        self.stdout.write(f"    raw   : {cleaned}")
                        self.stdout.write(f"    mapped: {mapped}")
                self.stdout.write("page text (first 8 lines):")
                for line in (page.extract_text() or "").splitlines()[:8]:
                    self.stdout.write(f"    {line}")