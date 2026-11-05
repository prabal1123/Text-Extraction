import re
from collections import Counter
from django.core.management.base import BaseCommand
from django.db.models import Count
from results.models import Result, Race, Communique


class Command(BaseCommand):
    help = "Summarise review flags, empty races, unclassified races and duplicate communique numbers."

    def handle(self, *args, **opts):
        w = self.stdout.write

        flags, per_race, sample = Counter(), Counter(), {}
        qs = Result.objects.filter(needs_review=True).select_related("race__communique__championship")
        for r in qs:
            flag = re.sub(r"\d+", "#", r.raw_row.get("_review_flag", f"status={r.status}"))
            c = r.race.communique
            ed = c.championship.edition
            flags[(ed, flag[:60])] += 1
            k = (ed, c.number, r.race.race_type, r.race.category, r.race.layout_family, c.page_range)
            per_race[(k, flag[:30])] += 1
            sample.setdefault((k, flag[:30]),
                              {a: b for a, b in r.raw_row.items() if a != "_sprints"})

        w("=== FLAGS BY EDITION AND REASON")
        for (ed, flag), n in sorted(flags.items(), key=lambda t: (-t[1], t[0])):
            w(f"{n:4d}  {ed}th  {flag}")

        w("\n=== FLAGGED RACES (count | edition, comm, race, category, layout, pages | reason)")
        for (k, flag), n in per_race.most_common(25):
            w(f"{n:3d} | {k} | {flag}")
            w(f"      e.g. {str(sample[(k, flag)])[:260]}")

        w("\n=== RACES WITH 0 RESULTS")
        for r in (Race.objects.annotate(n=Count("results")).filter(n=0)
                  .select_related("communique__championship")):
            w(f"{r.communique.championship.edition}th Comm {r.communique.number} "
              f"{r.race_type} / {r.category} / {r.layout_family} pg {r.communique.page_range}")

        w("\n=== UNCLASSIFIED OR PARTLY CLASSIFIED RACES")
        for r in Race.objects.select_related("communique__championship"):
            if ("Unknown" in (r.category, r.race_type, r.gender, r.age_group)
                    or "Implied" in r.category or r.layout_family == "unknown"):
                w(f"{r.communique.championship.edition}th Comm {r.communique.number} pg {r.communique.page_range}: "
                  f"type={r.race_type} cat={r.category} layout={r.layout_family}")

        w("\n=== DUPLICATE COMMUNIQUE NUMBERS WITHIN AN EDITION")
        seen = {}
        for c in Communique.objects.select_related("championship").order_by("championship__edition", "id"):
            seen.setdefault((c.championship.edition, c.number), []).append(c)
        for (ed, num), comms in seen.items():
            if num and len(comms) > 1:
                for c in comms:
                    w(f"{ed}th Comm {num} pg {c.page_range}: {c.raw_header_text[:230]}")
