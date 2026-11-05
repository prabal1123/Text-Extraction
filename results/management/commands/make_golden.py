import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from pipeline.quality import golden_rows
from results.models import Race

FIXTURES = {
    77: "tests/fixtures/2025_77th_rudrapur.pdf",
    75: "tests/fixtures/2023_75th_ranchi.pdf",
}


class Command(BaseCommand):
    help = "Write unverified golden files for the given communiques. Check them against the PDF, then set verified to true."

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, required=True)
        parser.add_argument("--comm", nargs="+", required=True)

    def handle(self, *args, **o):
        out_dir = Path("tests/golden")
        out_dir.mkdir(parents=True, exist_ok=True)
        for comm in o["comm"]:
            races = Race.objects.filter(
                communique__championship__edition=o["edition"], communique__number=comm,
                layout_family__in=["timed", "placing", "team", "points"],
            ).select_related("communique__championship")
            if not races:
                self.stdout.write(f"No race found for edition {o['edition']} comm {comm}")
            for race in races:
                c = race.communique
                pages = [int(p) for p in c.page_range.split("-")]
                if len(pages) == 2:
                    pages = list(range(pages[0], pages[1] + 1))
                pdf = FIXTURES.get(o["edition"])
                if not pdf or not Path(pdf).exists():
                    pdf = f".cache/pdfs/{c.championship.pdf_hash}.pdf"
                expected = golden_rows(pdf, pages, race.layout_family, race.race_type)
                name = re.sub(r"\W+", "_", f"{o['edition']}_{comm}_p{c.page_range}")
                path = out_dir / f"{name}.json"
                path.write_text(json.dumps({
                    "verified": False, "pdf": pdf, "pages": pages,
                    "layout": race.layout_family, "race_type": race.race_type,
                    "category": race.category, "expected": expected,
                }, indent=2))
                self.stdout.write(f"\nWrote {path}  ({race.race_type} / {race.category}, "
                                  f"pages {pages}, {len(expected)} rows)")
                for row in expected[:6]:
                    self.stdout.write(f"   {row}")
        self.stdout.write("\nNext: compare each file to the PDF page, fix any wrong values, "
                          'then set "verified": true.')
