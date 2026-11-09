"""Row validation, DOB normalisation, Madison grouping, text-line fallback,
team-block parsing and golden helpers. Pure Python: no Django imports."""
import re
from datetime import date

import pdfplumber

from pipeline.parsers import extract_status, parse_pdf_tables

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_DOB_RE = re.compile(r"(?<![\d:.])(\d{1,2}[./-](?:[A-Za-z]{3}|\d{1,2})[./-]?\d{2,4})(?![\d:])")
_TIME_RE = re.compile(r"(?<![\d:.])((?:\d{1,2}:)?\d{1,2}:\d{2}\.\d{3}|\d{2,3}\.\d{3})(?![\d:])")
_SPEED_RE = re.compile(r"(?<![\d:.])(\d{1,3}\.\d{2,3}|#DIV/0!)(?!\d)")
_RANK_RE = re.compile(r"^(\d{1,2}|Gold|Silver|Bronze)$", re.I)
_BIB_RE = re.compile(r"^\*?\d{1,4}$")
_STATUS_WORDS = re.compile(r"\b(DNS|DNF|DSQ|ABD|REL|RELEGATED|RELEGATE)\b", re.I)
_FOOTER_RE = re.compile(r"communiq|approved|commissair|commissar|organi[sz]ed by", re.I)


def parse_time_to_ms(value):
    if not value:
        return None
    m = re.search(r"(?:(\d{1,2}):)?(?:(\d{1,2}):)?(\d{1,2})\.(\d{1,3})", str(value))
    if not m:
        return None
    pre = [int(x) for x in (m.group(1), m.group(2)) if x is not None]
    if len(pre) == 2:
        hours, minutes = pre
    elif len(pre) == 1:
        hours, minutes = 0, pre[0]
    else:
        hours, minutes = 0, 0
    secs = int(m.group(3))
    ms = int(m.group(4).ljust(3, "0")[:3])
    return ((hours * 60 + minutes) * 60 + secs) * 1000 + ms


def split_time_speed(text):
    tm = _TIME_RE.search(text)
    time_str = tm.group(1) if tm else ""
    rest = text.replace(time_str, " ", 1) if time_str else text
    sm = _SPEED_RE.search(rest)
    speed_str = sm.group(1) if sm else ""
    if speed_str:
        rest = rest.replace(speed_str, " ", 1)
    return time_str, speed_str, rest


def _year(y):
    y = int(y)
    if y < 100:
        y += 2000 if y <= 26 else 1900
    return y


def normalize_dob(raw):
    s = (raw or "").strip()
    if not s:
        return "", True
    t = s.replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})[./-](\d{2})(\d{4})", t)
    if m:
        d, mo, y = m.groups()
    else:
        m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2}|[A-Za-z]{3})[./-](\d{2,4})", t)
        if not m:
            return s, False
        d, mo, y = m.groups()
    if mo.isalpha():
        mo = _MONTHS.get(mo.lower())
        if not mo:
            return s, False
    else:
        mo = int(mo)
    d = int(d)
    if len(y) == 3:
        return s, False
    y = _year(y)
    if mo > 12 >= d:
        d, mo = mo, d
    try:
        return date(y, mo, d).isoformat(), True
    except ValueError:
        return s, False


def looks_like_footer(row):
    for k, v in row.items():
        if k.startswith("_") or not isinstance(v, str):
            continue
        if _FOOTER_RE.search(v) or v.strip().lower() == "panel":
            return True
    return False


def is_valid_row(row):
    if looks_like_footer(row):
        return False
    name = (row.get("name") or "").strip()
    if name and len(re.findall(r"[A-Za-z]", name)) < 2:
        return False
    bib = (row.get("bib") or "").strip()
    if not name and not re.fullmatch(r"\*?\d{1,4}", bib):
        return False
    return True


def group_madison(rows):
    out = []
    for r in rows:
        own = ((r.get("rank") or "").strip() or (r.get("bib") or "").strip()
               or (r.get("team") or "").strip())
        if out and not own and (r.get("name") or "").strip():
            out[-1].setdefault("_partners", []).append(r)
        else:
            out.append(r)
    return out


def total_points(row):
    best, best_n = None, -1
    for k, v in row.items():
        m = re.fullmatch(r"points(?:_(\d+))?", k)
        if m and isinstance(v, str) and v.strip().lstrip("-").isdigit():
            n = int(m.group(1) or 1)
            if n > best_n:
                best, best_n = int(v.strip()), n
    return best


def _lines(page, y_tol=3.0):
    words = page.extract_words(x_tolerance=2, y_tolerance=3)
    lines = []
    for w in sorted(words, key=lambda w: (w["top"] + w["bottom"]) / 2):
        yc = (w["top"] + w["bottom"]) / 2
        if lines and abs(lines[-1]["yc"] - yc) <= y_tol:
            lines[-1]["words"].append(w)
        else:
            lines.append({"yc": yc, "words": [w]})
    return [" ".join(w["text"] for w in sorted(l["words"], key=lambda w: w["x0"])) for l in lines]


def _clean_team(text):
    t = _STATUS_WORDS.sub(" ", text)
    t = re.sub(r"\s+", " ", t).strip(" :-")
    return t if re.search(r"[A-Za-z]{2}", t) else ""


def split_row_line(line):
    m = _DOB_RE.search(line)
    if not m:
        return None
    left = line[:m.start()].split()
    right = line[m.end():].strip()
    rank = bib = ""
    if len(left) >= 2 and _RANK_RE.match(left[0]) and _BIB_RE.match(left[1]):
        rank, bib, name = left[0], left[1], " ".join(left[2:])
    elif left and _BIB_RE.match(left[0]):
        bib, name = left[0], " ".join(left[1:])
    elif len(left) >= 2 and re.fullmatch(r"Gold|Silver|Bronze", left[0], re.I):
        rank, name = left[0], " ".join(left[1:])
    else:
        name = " ".join(left)
    time_str, speed_str, rest = split_time_speed(right)
    return {
        "rank": rank, "bib": bib, "name": name.strip(), "dob": m.group(1),
        "team": _clean_team(rest), "time": time_str, "speed": speed_str,
        "status": extract_status([right]), "raw": line,
    }


def parse_dob_lines(pdf_path, pages, y_top=None, y_bottom=None):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            page = pdf.pages[p_num - 1]
            if y_top is not None or y_bottom is not None:
                yt = y_top if y_top is not None else 0
                yb = y_bottom if y_bottom is not None else page.height
                page = page.crop((0, yt, page.width, yb))
            for line in _lines(page):
                r = split_row_line(line)
                if r and r["name"]:
                    rows.append({
                        "rank": r["rank"], "bib": r["bib"].lstrip("*"), "name": r["name"],
                        "dob": r["dob"], "team": r["team"], "time": r["time"],
                        "speed": r["speed"],
                        "remarks": r["status"] if r["status"] != "OK" else "",
                        "_sprints": [], "_fallback": True,
                    })
    return rows


def parse_team_blocks(pdf_path, pages, y_top=None, y_bottom=None):
    def norm(s):
        return re.sub(r"\W+", "", (s or "").lower())

    blocks = []
    current = None
    pending_rank = ""
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            page = pdf.pages[p_num - 1]
            if y_top is not None or y_bottom is not None:
                yt = y_top if y_top is not None else 0
                yb = y_bottom if y_bottom is not None else page.height
                page = page.crop((0, yt, page.width, yb))
            for line in _lines(page):
                row = split_row_line(line)
                if row is None:
                    token = line.strip()
                    if re.fullmatch(r"Gold|Silver|Bronze|[1-9]|[12]\d|30", token, re.I):
                        pending_rank = token
                    continue
                if not row["name"]:
                    continue
                rank = row["rank"]
                if not rank and pending_rank:
                    rank, pending_rank = pending_rank, ""
                team, tm, sp, status = row["team"], row["time"], row["speed"], row["status"]
                new = False
                if current is None:
                    new = True
                elif rank and rank != current["rank"]:
                    new = True
                elif team and current["team"] and norm(team) != norm(current["team"]):
                    new = True
                elif tm and current["time"] and tm != current["time"]:
                    new = True
                if new:
                    current = {"rank": rank, "team": team, "time": tm, "speed": sp,
                               "status": status, "members": []}
                    blocks.append(current)
                else:
                    if team and not current["team"]:
                        current["team"] = team
                    if tm and not current["time"]:
                        current["time"] = tm
                    if sp and not current["speed"]:
                        current["speed"] = sp
                    if status != "OK" and current["status"] == "OK":
                        current["status"] = status
                bib = row["bib"]
                current["members"].append({
                    "bib": bib.lstrip("*"), "name": row["name"], "dob": row["dob"],
                    "is_reserve": bib.startswith("*"), "raw": line,
                })
    return blocks


_KNOWN_TEAMS = {t.lower() for t in [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Chattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
    "Orissa", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman & Nicobar", "Andaman and Nicobar",
    "A & N", "Chandigarh", "Dadra & Nagar Haveli", "Daman & Diu", "Delhi", "Jammu & Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry", "Pondicherry", "SSCB", "RSPB", "Railways",
    "Services", "Army", "CRPF", "BSF", "CISF", "ITBP", "Assam Rifles",
]}
_EVENT_RE = re.compile(r"\d+ \(\d+\)")
_OMNIUM_RANKED = re.compile(
    r"^(?P<rank>\d{1,2})\s+(?P<bib>\d{1,4})\s+(?P<mid>.+?)\s+"
    r"(?P<e1>\d+ \(\d+\))\s+(?P<e2>\d+ \(\d+\))\s+(?P<e3>\d+ \(\d+\))\s+"
    r"(?P<sub>\d+)\s+(?P<tail>\d.*)$")
_OMNIUM_STATUS = re.compile(r"^(?P<status>DNF|DNS|DSQ|ABD|REL)\s+(?P<bib>\d{1,4})\s+(?P<rest>.+)$")


def _split_name_team(mid):
    toks = mid.split()
    for k in (4, 3, 2, 1):
        if len(toks) > k and " ".join(toks[-k:]).lower() in _KNOWN_TEAMS:
            return " ".join(toks[:-k]), " ".join(toks[-k:]), ""
    if len(toks) >= 2:
        return " ".join(toks[:-1]), toks[-1], "team guessed from last word"
    return mid, "", "team not found"


def parse_omnium_text(lines):
    rows = []
    for line in lines:
        line = line.strip()
        m = _OMNIUM_RANKED.match(line)
        if m:
            name, team, flag = _split_name_team(m["mid"])
            last = m["tail"].split()[-1]
            total = last if re.fullmatch(r"-?\d+", last) else ""
            if not total:
                flag = (flag + "; " if flag else "") + "total points not readable"
            row = {"rank": m["rank"], "bib": m["bib"], "name": name, "team": team,
                   "dob": "", "points": total, "x_scratch": m["e1"], "x_tempo": m["e2"],
                   "x_elimination": m["e3"], "x_sub_total": m["sub"],
                   "_sprints": [], "_tail": m["tail"], "_raw": line}
            if flag:
                row["_flag"] = flag
            rows.append(row)
            continue
        m = _OMNIUM_STATUS.match(line)
        if m:
            rest = m["rest"]
            first = _EVENT_RE.search(rest)
            mid = rest[:first.start()] if first else rest
            mid = re.sub(r"(\s+(?:DNF|DNS|DSQ|ABD|REL|\d+))+\s*$", "", mid).strip()
            name, team, flag = _split_name_team(mid)
            row = {"rank": m["status"], "bib": m["bib"], "name": name, "team": team,
                   "dob": "", "points": "", "_events": _EVENT_RE.findall(rest),
                   "_sprints": [], "_raw": line}
            if flag:
                row["_flag"] = flag
            rows.append(row)
    return rows


def parse_omnium_lines(pdf_path, pages, y_top=None, y_bottom=None):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for p_num in pages:
            page = pdf.pages[p_num - 1]
            if y_top is not None or y_bottom is not None:
                yt = y_top if y_top is not None else 0
                yb = y_bottom if y_bottom is not None else page.height
                page = page.crop((0, yt, page.width, yb))
            rows.extend(parse_omnium_text(_lines(page)))
    return rows


def parse_rows(pdf_path, pages, layout_family, race_type="", y_top=None, y_bottom=None):
    if "omnium" in (race_type or "").lower():
        return parse_omnium_lines(pdf_path, pages, y_top, y_bottom), {"dropped": 0, "fallback": False}
    rows = parse_pdf_tables(pdf_path, pages, layout_family, y_top, y_bottom)
    total = len(rows)
    rows = [r for r in rows if is_valid_row(r)]
    dropped = total - len(rows)
    fallback = False
    if not rows and layout_family in ("timed", "placing"):
        rows = [r for r in parse_dob_lines(pdf_path, pages, y_top, y_bottom) if is_valid_row(r)]
        fallback = bool(rows)
    if "madison" in (race_type or "").lower():
        rows = group_madison(rows)
    return rows, {"dropped": dropped, "fallback": fallback}


def golden_rows(pdf_path, pages, layout, race_type="", y_top=None, y_bottom=None):
    if layout == "team":
        return [{"rank": b["rank"], "team": b["team"], "time": b["time"],
                 "speed": b["speed"], "status": b["status"],
                 "members": [m["name"] for m in b["members"]]}
                for b in parse_team_blocks(pdf_path, pages, y_top, y_bottom)]
    rows, _ = parse_rows(pdf_path, pages, layout, race_type, y_top, y_bottom)
    out = []
    for r in rows:
        d = {k: (r.get(k) or "") for k in ("rank", "bib", "name", "dob", "team", "time", "speed")}
        d["points"] = total_points(r)
        if r.get("_partners"):
            d["partners"] = [p.get("name", "") for p in r["_partners"]]
        out.append(d)
    return out
