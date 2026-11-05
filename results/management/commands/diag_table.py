import pdfplumber
from django.core.management.base import BaseCommand

from pipeline.parsers import load_config, normalize_header
from results.models import Race


class Command(BaseCommand):
    help = "Show raw table rows and header mapping for one communique."

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, required=True)
        parser.add_argument("--comm", required=True)
        parser.add_argument("--rows", type=int, default=4)

    def handle(self, *args, **o):
        races = Race.objects.filter(communique__championship__edition=o["edition"],
                                    communique__number=o["comm"]
                                    ).select_related("communique__championship")
        for race in races:
            c = race.communique
            self.stdout.write(f"\n===== Comm {c.number} pages {c.page_range} | {race.race_type} / "
                              f"{race.category} | layout={race.layout_family}")
            config = load_config(race.layout_family)
            pages = [int(p) for p in c.page_range.split("-")]
            if len(pages) == 2:
                pages = list(range(pages[0], pages[1] + 1))
            with pdfplumber.open(f".cache/pdfs/{c.championship.pdf_hash}.pdf") as pdf:
                for p in pages:
                    page = pdf.pages[p - 1]
                    tables = page.extract_tables()
                    self.stdout.write(f"-- page {p}: {len(tables)} table(s)")
                    for t in tables[:3]:
                        self.stdout.write(f"   table with {len(t)} rows")
                        for row in t[:o["rows"]]:
                            cleaned = [str(x).strip().replace("\n", " ") if x else "" for x in row]
                            self.stdout.write(f"     raw   : {cleaned}")
                            if config:
                                self.stdout.write(
                                    f"     mapped: {[normalize_header(x, config['columns']) for x in cleaned]}")
                    self.stdout.write("   text (first 6 lines):")
                    for line in (page.extract_text() or "").splitlines()[:6]:
                        self.stdout.write(f"     {line}")
