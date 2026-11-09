import os
import re
from django.core.management.base import BaseCommand
from django.db import transaction

from pipeline.segmenter import segment_pdf
from pipeline.classifier import classify_communique
from pipeline.parsers import extract_status
from pipeline.quality import (normalize_dob, parse_rows, parse_team_blocks,
                              parse_time_to_ms, total_points)
from results.models import (Championship, Communique, PointsDetail, Race, Result, Rider,
                            Team, TeamMember)

FAMILIES = ["timed", "placing", "team", "points"]


def base_number(num):
    m = re.match(r"\s*(\d+)", str(num or ""))
    return m.group(1) if m else None


def is_revised(num):
    return bool(re.search(r"rev", str(num or ""), re.I))


def rank_to_numeric(display_rank):
    d = (display_rank or "").strip()
    if d.isdigit():
        return int(d)
    return {"gold": 1, "silver": 2, "bronze": 3}.get(d.lower())


def first_val(row, base):
    """First non-empty of base, base_2, base_3 (clipped headers can duplicate)."""
    for key in (base, base + "_2", base + "_3"):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def status_cells(row):
    cells = [first_val(row, "rank"), first_val(row, "time"), first_val(row, "speed")]
    cells += [v for k, v in row.items()
              if k.startswith(("x_rem", "remark")) and isinstance(v, str)]
    return cells


class Command(BaseCommand):
    help = "Parse cached PDFs into Result rows with event splitting and coordinate cropping."

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, nargs="*", help="Only these editions")

    def handle(self, *args, **opts):
        champs = Championship.objects.all().order_by("edition")
        if opts.get("edition"):
            champs = champs.filter(edition__in=opts["edition"])
        totals = {"results": 0, "members": 0, "points": 0, "skipped": 0}
        for champ in champs:
            self.import_championship(champ, totals)
        self.stdout.write(self.style.SUCCESS(
            f"\nPhase 2 Event Splitting Import Complete! Inserted {totals['results']} Result rows, "
            f"{totals['members']} TeamMember rows, and {totals['points']} PointsDetail rows. "
            f"Skipped {totals['skipped']} races (superseded or duplicate)."))

    @staticmethod
    def find_superseded(races):
        groups = {}
        for race in races:
            b = base_number(race.communique.number)
            if b:
                groups.setdefault((b, race.race_type, race.category, race.stage or ""), []).append(race)
        superseded = set()
        for rs in groups.values():
            revised = [r for r in rs if is_revised(r.communique.number)]
            if len(rs) > 1 and revised:
                keep = revised[-1]
                superseded.update(r.id for r in rs if r.id != keep.id)
        return superseded

    def import_championship(self, champ, totals):
        pdf_path = f".cache/pdfs/{champ.pdf_hash}.pdf"
        if not os.path.exists(pdf_path):
            self.stdout.write(self.style.WARNING(
                f"\n{champ.edition}th: cached PDF missing, skipped (existing results kept)."))
            return

        self.stdout.write(self.style.SUCCESS(
            f"\nSegmenting and classifying PDF for {champ.edition}th Edition..."))

        # Re-segment PDF into individual events with crop bounds
        segments = segment_pdf(pdf_path)

        with transaction.atomic():
            # Clear previous results and communiques/races for this championship to rebuild cleanly
            Result.objects.filter(race__communique__championship=champ).delete()
            Race.objects.filter(communique__championship=champ).delete()
            Communique.objects.filter(championship=champ).delete()

            created_races_count = 0
            seen_sigs, seen_numbers = {}, {}

            for seg in segments:
                header_text = seg['header_text']
                full_text = seg['full_text']
                pages = seg['pages']
                page_range = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])
                
                # Classify communique metadata
                class_info = classify_communique(header_text + "\n" + full_text)
                comm_num = int(class_info['number']) if class_info['number'] and str(class_info['number']).isdigit() else None

                comm_obj = Communique.objects.create(
                    championship=champ,
                    number=comm_num,
                    page_range=page_range,
                    y_top=seg['y_top'],
                    y_bottom=seg['y_bottom'],
                    event_index=seg['event_index'],
                    raw_header_text=header_text
                )

                layout_family = class_info['layout_family']
                if layout_family == 'unknown':
                    text_lower = full_text.lower()
                    if 'team sprint' in text_lower or 'team pursuit' in text_lower:
                        layout_family = 'team'
                    elif 'points race' in text_lower or 'madison' in text_lower or 'omnium' in text_lower:
                        layout_family = 'points'
                    elif any(w in text_lower for w in ['time trial', 'pursuit', 'start no', 'time']):
                        layout_family = 'timed'
                    elif any(w in text_lower for w in ['sprint', 'keirin', 'scratch', 'elimination', 'rank']):
                        layout_family = 'placing'

                if layout_family not in FAMILIES:
                    continue

                race_obj, _ = Race.objects.get_or_create(
                    communique=comm_obj,
                    defaults={
                        'category': class_info['category'] if class_info['category'] != 'Unknown' else 'Elite / Junior',
                        'race_type': class_info['race_type'] if class_info['race_type'] != 'Unknown' else 'Extracted Race',
                        'gender': class_info['gender'] if class_info['gender'] != 'Unknown' else 'Men/Women',
                        'stage': class_info['stage'],
                        'layout_family': layout_family
                    }
                )

                # Import results for this segmented race using crop bounds
                self.import_race(race_obj, pdf_path, set(), seen_sigs, seen_numbers, totals)
                created_races_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully processed {created_races_count} segmented events for {champ.edition}th Edition."))

    def import_race(self, race, pdf_path, superseded, seen_sigs, seen_numbers, totals):
        comm = race.communique
        label = f"Comm {comm.number or 'None'} (pg {comm.page_range}, ev {comm.event_index})"
        if race.id in superseded:
            totals["skipped"] += 1
            self.stdout.write(f"  -> {label}: SKIPPED, superseded by a revised communique")
            return

        pages = [int(p) for p in comm.page_range.split("-")]
        if len(pages) == 2:
            pages = list(range(pages[0], pages[1] + 1))

        y_top = comm.y_top
        y_bottom = comm.y_bottom
        is_team = race.layout_family == "team"
        info = {}

        if is_team:
            items = parse_team_blocks(pdf_path, pages, y_top, y_bottom)
            sig = ("T",) + tuple(sorted((b["rank"], b["team"], len(b["members"])) for b in items))
        else:
            items, info = parse_rows(pdf_path, pages, race.layout_family, race.race_type, y_top, y_bottom)
            sig = ("R",) + tuple(sorted(
                (first_val(r, "rank"), first_val(r, "bib"), r.get("name") or "") for r in items))

        if not items:
            self.stdout.write(f"  -> {label}: 0 results ({race.layout_family})")
            return

        sig_key = (race.race_type, race.category, race.stage or "", sig)
        if sig_key in seen_sigs:
            totals["skipped"] += 1
            self.stdout.write(f"  -> {label}: SKIPPED, identical content to {seen_sigs[sig_key]}")
            return
        seen_sigs[sig_key] = label

        extra_flag = ""
        base = base_number(comm.number)
        if base:
            nk = (base, race.race_type, race.category)
            if nk in seen_numbers:
                extra_flag = f"Communique number {base} reused with different content (see {seen_numbers[nk]})"
            else:
                seen_numbers[nk] = label

        if is_team:
            r, m, p = self.save_team_blocks(race, items, extra_flag)
            self.stdout.write(f"  -> {label}: {r} teams, {m} riders (Team)")
        else:
            r, m, p = self.save_rows(race, items, extra_flag, info.get("fallback", False))
            tags = ""
            if info.get("fallback"):
                tags += " [text fallback]"
            if info.get("dropped"):
                tags += f" [dropped {info['dropped']} junk rows]"
            if extra_flag:
                tags += " [number reused]"
            self.stdout.write(f"  -> {label}: {r} results ({race.layout_family}){tags}")

        totals["results"] += r
        totals["members"] += m
        totals["points"] += p

    def get_rider(self, race, name, raw_dob, flags):
        dob, ok = normalize_dob(raw_dob)
        if not ok:
            flags.append(f"DOB not readable: {dob}")
        rider, _ = Rider.objects.get_or_create(name=name, dob=dob, defaults={"gender": race.gender})
        return rider

    def save_rows(self, race, rows, extra_flag, fallback):
        n_results = 0
        members, details = [], []
        for row in rows:
            flags = []
            if extra_flag:
                flags.append(extra_flag)
            if fallback:
                flags.append("parsed from text lines (no table header recognised)")
            if row.get("_flag"):
                flags.append(row["_flag"])
            status = extract_status(status_cells(row))
            display_rank = first_val(row, "rank")
            numeric_rank = rank_to_numeric(display_rank)
            team_name = (row.get("team") or "").strip()
            team_obj = Team.objects.get_or_create(name=team_name)[0] if team_name else None
            name = (row.get("name") or "").strip()
            rider_obj = self.get_rider(race, name, row.get("dob"), flags) if name else None

            raw = dict(row)
            raw["_source_pages"] = race.communique.page_range
            if flags:
                raw["_import_flag"] = "; ".join(flags)
            result = Result.objects.create(
                race=race, rider=rider_obj, team=team_obj, display_rank=display_rank,
                numeric_rank=numeric_rank, status=status, bib=first_val(row, "bib"),
                time_ms=parse_time_to_ms(first_val(row, "time")), speed=first_val(row, "speed"),
                points=total_points(row), raw_row=raw,
                needs_review=bool(flags) or (status != "OK" and not numeric_rank),
            )
            n_results += 1

            for idx, s_val in enumerate(row.get("_sprints", [])):
                s_val = (s_val or "").strip()
                if s_val:
                    details.append(PointsDetail(
                        result=result, sprint_number=idx + 1,
                        points_awarded=int(s_val) if s_val.lstrip("-").isdigit() else 0,
                        sub_scores_json={"raw_value": s_val}))

            partners = row.get("_partners", [])
            if partners:
                if rider_obj:
                    members.append(TeamMember(result=result, rider=rider_obj, is_reserve=False))
                for p in partners:
                    p_name = (p.get("name") or "").strip()
                    if p_name:
                        partner = self.get_rider(race, p_name, p.get("dob"), [])
                        members.append(TeamMember(result=result, rider=partner, is_reserve=False))
        TeamMember.objects.bulk_create(members)
        PointsDetail.objects.bulk_create(details)
        return n_results, len(members), len(details)

    def save_team_blocks(self, race, blocks, extra_flag):
        n_results = 0
        members = []
        for block in blocks:
            flags = []
            if extra_flag:
                flags.append(extra_flag)
            if not block["team"]:
                flags.append("team name not found")
            display_rank = block["rank"]
            numeric_rank = rank_to_numeric(display_rank)
            team_obj = Team.objects.get_or_create(name=block["team"])[0] if block["team"] else None
            raw = dict(block)
            raw["_source_pages"] = race.communique.page_range
            member_objs = []
            for m in block["members"]:
                if m["name"].strip():
                    member_objs.append((self.get_rider(race, m["name"].strip(), m["dob"], flags), m))
            if flags:
                raw["_import_flag"] = "; ".join(flags)
            result = Result.objects.create(
                race=race, rider=None, team=team_obj, display_rank=display_rank,
                numeric_rank=numeric_rank, status=block["status"], bib=None,
                time_ms=parse_time_to_ms(block["time"]), speed=block["speed"],
                raw_row=raw,
                needs_review=bool(flags) or (block["status"] != "OK" and not numeric_rank),
            )
            n_results += 1
            for rider, m in member_objs:
                members.append(TeamMember(result=result, rider=rider, is_reserve=m["is_reserve"]))
        TeamMember.objects.bulk_create(members)
        return n_results, len(members), 0
