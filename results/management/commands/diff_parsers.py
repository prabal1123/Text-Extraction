import glob
import importlib.util
from django.core.management.base import BaseCommand
from results.models import Race
import pipeline.parsers as new


class Command(BaseCommand):
    help = "Compare the previous parser (from .backup_fixes) with the current one on one communique."

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, required=True)
        parser.add_argument("--comm", type=str, required=True)

    def handle(self, *args, **o):
        backups = sorted(glob.glob(".backup_fixes/*_fix3/parsers.py"))
        if not backups:
            self.stdout.write("No fix3 backup found.")
            return
        spec = importlib.util.spec_from_file_location("old_parsers", backups[-1])
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)

        races = Race.objects.filter(
            communique__championship__edition=o["edition"],
            communique__number=o["comm"],
            layout_family__in=["timed", "placing", "points"],
        ).select_related("communique__championship")

        key = lambda r: (r.get("bib", ""), r.get("name", ""), r.get("rank", ""))
        for race in races:
            champ = race.communique.championship
            pages = [int(p) for p in race.communique.page_range.split("-")]
            if len(pages) == 2:
                pages = list(range(pages[0], pages[1] + 1))
            pdf = f".cache/pdfs/{champ.pdf_hash}.pdf"
            old_rows = old.parse_pdf_tables(pdf, pages, race.layout_family)
            new_rows = new.parse_pdf_tables(pdf, pages, race.layout_family)
            self.stdout.write(f"\nComm {o['comm']} pages {pages}: old={len(old_rows)} new={len(new_rows)}")
            old_k, new_k = {key(r) for r in old_rows}, {key(r) for r in new_rows}
            for k in sorted(old_k - new_k):
                self.stdout.write(f"  only in OLD: {k}")
            for k in sorted(new_k - old_k):
                self.stdout.write(f"  only in NEW: {k}")