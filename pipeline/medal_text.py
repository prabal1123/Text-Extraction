"""Text parser for medal-only ("Medalists") sheets.

Pure text in, plain dicts out: no Django, no pdfplumber. Feed it the lines of
``page.extract_text()`` from every page of a medalist PDF.

Two layouts exist in the CFI sheets:

* ``rank_first`` (69th-71st, 73rd): category line, event line, then rows that
  start with the rank. Team events list the members on separate rows with the
  rank row sitting in the vertical middle of the team's block; state, time and
  medal may be on any row of the block.
* ``table`` (72nd): one row per rider, starting with the category, with
  Gender / Timing / Medal / Event columns.
"""

import re

MEDALS = {1: "Gold", 2: "Silver", 3: "Bronze"}
MEDAL_RANK = {v: k for k, v in MEDALS.items()}

DOB = r"\d{1,2}[./]\d{1,2}[./]\d{2,4}"
TIME = r"(?:\d{1,2}:)?\d{1,2}\.\d{2,3}"
CATEGORY = (
    r"(?:Men|Women)\s+(?:Elite|Junior)"
    r"|(?:Sub[\s-]*Junior|Youth)\s+(?:Boys|Girls)"
)

CATEGORY_LINE_RE = re.compile(rf"^(?:{CATEGORY})$", re.I)
# One row shape for rank-first sheets: [rank] bib name DOB [state time speed NR medal].
# Which row of a team block carries the rank digit / state / time varies by sheet.
ROW_RE = re.compile(
    rf"^(?:(?P<rank>[1-3])\s+)?(?P<bib>\*?\d+\*?)\s+(?P<name>\*?[A-Za-z].*?)\s*"
    rf"(?P<dob>{DOB})(?:\s*(?P<rest>\S.*))?$"
)
TABLE_ROW_RE = re.compile(
    rf"^(?P<cat>{CATEGORY})\s+(?P<bib>\d+)\s+(?P<name>.+?)\s+(?P<dob>{DOB})\s+"
    r"(?P<rest>.+?)\s+(?P<gender>Male|Female)\s+"
    r"(?P<timing>.+?)\s+(?P<medal>Gold|Silver|Bronze)\s+(?P<event>.+)$",
    re.I,
)
EVENT_LINE_RE = re.compile(
    r"\b(sprint|pursuit|time\s*tr(?:ia|ai)l|scratch|keirin|point|omnium|madison|"
    r"elimination|flying|race)\b",
    re.I,
)
FROM_TO_RE = re.compile(r"\bfrom\s+\d+\w*\s+(?:[A-Za-z]+\.?\s+)?to\s+\d+", re.I)

# Lines that are page furniture, never data.
IGNORE_RES = [
    re.compile(p, re.I)
    for p in (
        r"^\d+(?:st|nd|rd|th)\s+Senior",
        r"National Track Cycling",
        r"^Communiqu",
        r"^Medalists?\b",
        r"^Medalist of\b",
        r"^Rank\b.*\bName\b",
        r"^Category\b.*\bName\b",
        r"^organi[sz]ed by",
        r"^Page\s+\d+\s+of\s+\d+$",
        r"^_+$",
        r"^(?:19|20)\d{2}$",
    )
]

# Longest names first so "Tamil Nadu" wins over a one-word guess.
KNOWN_STATES = sorted(
    [
        "A & N", "Andaman & Nicobar", "Andman & Nicobar", "Andhra Pradesh",
        "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh",
        "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu & Kashmir",
        "J & K", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Leh",
        "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
        "Nagaland", "Odisha", "Orissa", "Puducherry", "Punjab", "Rajasthan",
        "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
        "Uttarakhand", "West Bengal", "SSCB", "RSPB", "SSB", "CRPF", "ITBP",
        "Railways", "Services", "Army", "AIPS", "AAI",
    ],
    key=len,
    reverse=True,
)


def _clean_event(text):
    """Collapse spacing and canonicalise the distance prefix ("1Km." -> "1 Km.")."""
    text = re.sub(r"\s*\([A-Z]{1,4}\)\s*$", "", " ".join(text.split()))

    def fix(m):
        unit = "Km" if m.group(2).lower() == "km" else "Mtr"
        return f"{m.group(1)} {unit}."

    return re.sub(r"^(\d+)\s*(km|mtrs?)\b\.?", fix, text, flags=re.I)


def _clean_category(text):
    text = re.sub(r"[\s-]+", " ", text.strip()).title()
    return text


def event_distance(event):
    """"500 Mtr. Time Trial" -> "500 Mtr"; events without a distance -> None."""
    m = re.match(r"\s*(\d+)\s*(km|mtrs?)\b", event, re.I)
    if not m:
        return None
    return f"{m.group(1)} {'Km' if m.group(2).lower() == 'km' else 'Mtr'}"


def guess_venue(lines):
    """Venue from the title block, or None."""
    lines = [l.strip() for l in lines if l.strip()]
    for line in lines:
        m = re.search(r"\bheld at\s+(.+?)\s+from\b", line, re.I)
        if m:
            return m.group(1).strip(" ,")
    for i, line in enumerate(lines):
        m = FROM_TO_RE.search(line)
        if not m:
            continue
        before = line[: m.start()].strip(" ,")
        if before:
            return before
        if i > 0:
            return lines[i - 1].strip(" ,")
    return None


# Some sheets carry a wrong header. The 72nd PDF repeats the 74th's "Guwahati,
# 11th-15th Dec. 2022" header, but its results match the Hyderabad nationals of
# 27-31 March 2021 (verified against a press report on the Assam medals).
EDITION_OVERRIDES = {72: {"year": 2021, "venue": "Hyderabad"}}


def guess_year(lines):
    """First 20xx year in the title block, or None."""
    for line in lines[:8]:
        m = re.search(r"\b(20\d{2})\b", line)
        if m:
            return int(m.group(1))
    return None


def edition_meta(edition, lines):
    """Year and venue for an edition, with known header errors overridden."""
    meta = {"year": guess_year(lines), "venue": guess_venue(lines), "overridden": False}
    if edition in EDITION_OVERRIDES:
        meta.update(EDITION_OVERRIDES[edition], overridden=True)
    return meta


def _split_state_father(rest):
    """"Manipur L Romen Singh" -> ("Manipur", "L Romen Singh")."""
    for state in KNOWN_STATES:
        m = re.match(rf"{re.escape(state)}\b\s*(.*)$", rest, re.I)
        if m:
            return state, m.group(1)
    head, _, tail = rest.partition(" ")
    return head, tail


def _parse_timing(text):
    """Pieces of a Time / Timing cell -> (time, points, nr)."""
    nr = bool(re.search(r"\bNR\b", text))
    pts = re.search(r"(\d+)\s*Points", text, re.I)
    tm = re.search(TIME, text)
    return (tm.group(0) if tm else ""), (int(pts.group(1)) if pts else None), nr


def _parse_extras(rest):
    """Everything after the DOB on a rank-first row, in any order."""
    out = {"state": "", "time": "", "speed": "", "points": None, "nr": False, "medal": ""}
    state, times, ints = [], [], []
    for tok in (rest or "").split():
        bare = tok.strip("()")
        if bare in MEDAL_RANK:
            out["medal"] = bare
        elif bare == "NR":
            out["nr"] = True
        elif re.fullmatch(TIME, bare):
            times.append(bare)
        elif re.fullmatch(r"\d{1,3}", bare):
            ints.append(int(bare))
        else:
            state.append(tok)
    out["state"] = " ".join(state)
    if times:
        out["time"] = times[0]
        out["speed"] = times[1] if len(times) > 1 else ""
    elif ints:
        out["points"] = ints[-1]
    return out


def _is_team(event):
    return bool(re.search(r"\b(team|madison)\b", event, re.I))


def _person(bib, name, dob):
    return {
        "name": name.lstrip("*").strip(),
        "dob": dob,
        "bib": bib.strip("*"),
        "is_reserve": "*" in bib or name.startswith("*"),
    }


def _result(category, event, rank, medal, state, time, points, nr, speed, person, members):
    return {
        "category": category,
        "event": event,
        "rank": rank,
        "medal": medal,
        "state": state,
        "time": time,
        "points": points,
        "nr": nr,
        "speed": speed,
        "is_team": _is_team(event),
        "name": None if _is_team(event) else person["name"],
        "dob": None if _is_team(event) else person["dob"],
        "bib": None if _is_team(event) else person["bib"],
        "members": members,
        "name_has_father": False,
    }


def _team_sizes(before_n, gaps, after_n):
    """Team sizes so that every rank row sits mid-block (lead = (size-1)//2).

    before_n: rows before the first rank row; gaps: rows between consecutive
    rank rows; after_n: rows after the last. Returns one size per rank row, or
    None. Sizes may differ inside an event (4 vs 5 riders), so each team is
    solved in turn; among consistent solutions the most uniform wins.
    """
    for strict in (True, False):
        best = None

        def rec(k, lead, sizes):
            nonlocal best
            for n in (2 * lead + 1, 2 * lead + 2):
                trail = n - 1 - lead
                if k == len(gaps):
                    if trail == after_n or (not strict and trail < after_n):
                        cand = sizes + [n]
                        if best is None or max(cand) - min(cand) < max(best) - min(best):
                            best = cand
                    continue
                nxt = gaps[k] - trail
                if nxt >= 0:
                    rec(k + 1, nxt, sizes + [n])

        rec(0, before_n, [])
        if best:
            return best
    return None


def _first(rows, key):
    return next((r[key] for r in rows if r[key] not in ("", None)), "" if key != "points" else None)


def _spans_by_state(items, ranks):
    """Grow each team outward from its rank row over rows with the same state.

    Used when every row carries its state (71st). More robust than geometry when
    a page break leaves a team's block off-centre.
    """
    taken, spans = set(), []
    for r in ranks:
        state = items[r][1]["state"]
        lead, j = [], r - 1
        while j >= 0 and items[j][0] == "m" and j not in taken and items[j][1]["state"] == state:
            lead.insert(0, items[j])
            taken.add(j)
            j -= 1
        trail, j = [], r + 1
        while j < len(items) and items[j][0] == "m" and items[j][1]["state"] == state:
            trail.append(items[j])
            taken.add(j)
            j += 1
        spans.append((lead, trail))
    return spans


def _spans_by_geometry(items, ranks):
    """Split unranked rows around rank rows, assuming each rank row is mid-block."""
    blocks, prev = [], -1
    for r in ranks:
        blocks.append(items[prev + 1 : r])
        prev = r
    blocks.append(items[prev + 1 :])
    sizes = _team_sizes(len(blocks[0]), [len(b) for b in blocks[1:-1]], len(blocks[-1]))
    if not sizes:
        return None
    spans = []
    for k, size in enumerate(sizes):
        lead_n = (size - 1) // 2
        trail_n = size - 1 - lead_n
        spans.append(
            (blocks[k][len(blocks[k]) - lead_n :] if lead_n else [], blocks[k + 1][:trail_n] if trail_n else [])
        )
    return spans


def _flush_event(items, category, event, results, unmatched):
    """Turn one event's rows into results; attach team members to rank rows."""
    ranks = [i for i, (kind, _, _) in enumerate(items) if kind == "r"]
    if not ranks:
        unmatched.extend(raw for _, _, raw in items)
        return

    spans = None
    if _is_team(event):
        unranked = [x for x in items if x[0] == "m"]
        if unranked and all(x[1]["state"] for x in unranked) and all(items[r][1]["state"] for r in ranks):
            spans = _spans_by_state(items, ranks)
        else:
            spans = _spans_by_geometry(items, ranks)

    claimed = set()
    for k, r in enumerate(ranks):
        data = items[r][1]
        lead, trail = spans[k] if spans else ([], [])
        claimed.update(id(x) for x in lead + trail)
        rows = [data] + [x[1] for x in lead + trail]
        members = (
            [x[1]["person"] for x in lead] + [data["person"]] + [x[1]["person"] for x in trail]
            if _is_team(event)
            else []
        )
        # state / time / medal may sit on any row of the team's block
        medal = _first(rows, "medal") or MEDALS[data["rank"]]
        results.append(
            _result(
                category, event, data["rank"], medal, _first(rows, "state"), _first(rows, "time"),
                _first(rows, "points"), any(x["nr"] for x in rows), _first(rows, "speed"),
                data["person"], members,
            )
        )
    # rows that no team claimed are reported, never dropped
    unmatched.extend(x[2] for x in items if x[0] == "m" and id(x) not in claimed)


def _parse_rank_first(lines, preamble):
    results, unmatched = [], []
    category = event = None
    items, seen = [], set()

    def flush():
        nonlocal items, seen
        if items:
            _flush_event(items, category, event or "", results, unmatched)
        items, seen = [], set()

    for raw in lines:
        line = raw.strip()
        if not line or line in preamble or any(p.search(line) for p in IGNORE_RES):
            continue
        if FROM_TO_RE.search(line):
            continue
        if CATEGORY_LINE_RE.match(line):
            flush()
            category = _clean_category(line)
            event = None
            continue
        m = ROW_RE.match(line)
        if m:
            row = _parse_extras(m.group("rest"))
            row["person"] = _person(m.group("bib"), m.group("name"), m.group("dob"))
            row["rank"] = int(m.group("rank")) if m.group("rank") else None
            key = (row["person"]["bib"], row["person"]["dob"])
            if row["rank"] is None and key in seen:
                continue  # a page break repeats the last row of the previous page
            seen.add(key)
            items.append(("r" if row["rank"] else "m", row, raw))
            continue
        if EVENT_LINE_RE.search(line) and not re.search(DOB, line):
            flush()
            event = _clean_event(line)
            continue
        unmatched.append(raw)
    flush()
    return results, unmatched


def _parse_table(lines, preamble):
    results, unmatched = [], []
    team_index = {}
    for raw in lines:
        line = raw.strip()
        if not line or line in preamble or any(p.search(line) for p in IGNORE_RES):
            continue
        if FROM_TO_RE.search(line):
            continue
        m = TABLE_ROW_RE.match(line)
        if not m:
            unmatched.append(raw)
            continue
        category = _clean_category(m.group("cat"))
        event = _clean_event(m.group("event"))
        medal = m.group("medal").title()
        time, points, nr = _parse_timing(m.group("timing"))
        state, father = _split_state_father(m.group("rest"))
        person = _person(m.group("bib"), m.group("name"), m.group("dob"))
        person["father"] = father
        if _is_team(event):
            key = (category, event, medal, state, time)
            if key in team_index:
                team_index[key]["members"].append(person)
                team_index[key]["nr"] = team_index[key]["nr"] or nr
                continue
            res = _result(category, event, MEDAL_RANK[medal], medal, state, time, points, nr, "", person, [person])
            team_index[key] = res
        else:
            res = _result(category, event, MEDAL_RANK[medal], medal, state, time, points, nr, "", person, [])
            res["father"] = father
            res["gender"] = m.group("gender").title()
        results.append(res)
    return results, unmatched


SPLIT_RANK_RE = re.compile(r"^(?P<rank>[1-3])\s+(?P<bib>\d+\*?)\s+(?P<medal>Gold|Silver|Bronze)$")
NAME_FIRST_RE = re.compile(rf"^\*?[A-Za-z].*{DOB}")
NO_NAME_ROW_RE = re.compile(rf"^(?P<head>(?:{CATEGORY})\s+\d+)\s+(?P<tail>{DOB}\s.*)$", re.I)
LETTERS_ONLY_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]*$")


def clean_lines(lines):
    """Repair text-extraction damage before parsing.

    * a rank row split in two ("1 126 Gold" + "Name DOB State Time")
    * a table row whose wrapped name sits on the lines above and below it
    * "Male"/"Female" glued to the father's name
    """
    lines = [l.strip() for l in lines if l.strip()]
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        m = SPLIT_RANK_RE.match(line)
        if m and i + 1 < len(lines) and NAME_FIRST_RE.match(lines[i + 1]):
            out.append(f"{m['rank']} {m['bib']} {lines[i + 1]} {m['medal']}")
            i += 2
            continue
        line = re.sub(r"(?<=[a-z])(Male|Female)\b", r" \1", line)
        m = NO_NAME_ROW_RE.match(line)
        if m:
            parts = []

            def fragment(text):
                return LETTERS_ONLY_RE.match(text) and not CATEGORY_LINE_RE.match(text) and not any(
                    p.search(text) for p in IGNORE_RES
                )

            if out and fragment(out[-1]):
                parts.append(out.pop())
            if i + 1 < len(lines) and fragment(lines[i + 1]):
                parts.append(lines[i + 1])
                i += 1
            if parts:
                line = f"{m['head']} {' '.join(parts)} {m['tail']}"
        out.append(line)
        i += 1
    return out


def parse_medal_text(lines):
    """Parse a medalist sheet. Returns (results, unmatched_lines, format).

    ``format`` is "rank_first", "table" or "unknown". ``unmatched_lines`` holds
    every line that was neither page furniture nor a recognised row, so nothing
    is dropped silently.
    """
    lines = clean_lines(lines)
    n_table = sum(1 for l in lines if TABLE_ROW_RE.match(l.strip()))
    n_rank = sum(1 for l in lines if ROW_RE.match(l.strip()))

    # Title block = everything before the first data-ish line; repeated page
    # headers later in the sheet are dropped by matching against it.
    preamble = set()
    for l in lines:
        s = l.strip()
        if CATEGORY_LINE_RE.match(s) or TABLE_ROW_RE.match(s) or ROW_RE.match(s):
            break
        preamble.add(s)

    if n_table > n_rank:
        results, unmatched = _parse_table(lines, preamble)
        return results, unmatched, "table"
    if n_rank:
        results, unmatched = _parse_rank_first(lines, preamble)
        # a Father's Name column is fused into the name text and cannot be split here
        if any(re.match(r"^Rank\b.*Father", l.strip(), re.I) for l in lines):
            for r in results:
                r["name_has_father"] = True
        return results, unmatched, "rank_first"
    return [], [l for l in lines if l.strip() not in preamble], "unknown"
