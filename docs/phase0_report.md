# Phase 0 report: setup and extraction spike

Samples: `tests/fixtures/2025_77th_rudrapur.pdf` (51 pages, A4 landscape) and
`tests/fixtures/2023_75th_ranchi.pdf` (47 pages, Letter portrait). Raw per-page
data: `docs/phase0_spike.json`. Re-run with `python scripts/spike_report.py`.

## 1. Stack

Django 6 + SQLite, pdfplumber for words, text and tables, PyMuPDF installed as a
helper (not needed yet), pytest + pytest-django. The pipeline package has no
Django imports. Only the storage layer will touch the ORM.

## 2. Are any pages scanned images?

No. Both files have embedded fonts and a text layer on every page that has text.
No page has a page-sized image. OCR is not needed for these two samples.
Open risk: the 65th to 72nd PDFs are unseen.

Every page carries a small logo image (1 in 2025, 2 in 2023). Image count alone
must not be used as a scanned-page signal. `PageData.looks_scanned` uses
largest-image coverage > 60% of the page and < 20 words.

## 3. Page inventory

| | 2025 (77th) | 2023 (75th) |
|---|---|---|
| Pages | 51 | 47 |
| Communique pages | 46 | 45 |
| Blank logo-only pages | 3 (p10, 18, 30) | 0 |
| Footer-only pages | 1 (p14, spill of Comm. 81) | 0 |
| Fragment pages | 1 (p25, 4 words: overflowed date of Comm. 133) | 0 |
| Headerless continuation pages | 0 | 2 (p43 after Comm. 240, p45 after Comm. 242) |
| Communique pages with no number | 0 | 2 (p8, p17, both Omnium) |

Race types seen (communique pages): 2025 = ITT 8, Individual Pursuit 8, Sprint 4,
Keirin 4, Scratch 6, Elimination 1, Madison 1, Omnium 2, Points Race 2,
Team Pursuit 4, Team Sprint 6. 2023 = same set minus Elimination.
All 8 categories appear in both files.

## 4. Extraction quality per layout family

Method: plain text, word coordinates, and pdfplumber tables (`lines` and `text`
strategies) on every communique page. Header sniffing is a naive regex, only to
see what the real classifier will have to deal with.

| Family | Pages (2025 / 2023) | Plain text | Tables (lines strategy) | Verdict |
|---|---|---|---|---|
| Timed (ITT, Ind. Pursuit, Sprint) | 20 / 20 | Clean, one row per line, header first | Found 20/20 and 20/20, one row per rider | Easy. Text or table both work. |
| Placing (Keirin, Scratch, Elimination) | 11 / 10 | Clean | Found 11/11 and 10/10 | Easy. Time and speed appear only on the top rows (Scratch: Gold, or top 4 in 2025 Men Elite); blank below. |
| Team (Team Pursuit, Team Sprint) | 10 / 10 | Rider rows clean; team, time, speed order varies | Found, but see below | Needs word coordinates. |
| Points (Point Race, Omnium, Madison) | 5 / 5 | Header scrambled ("Last Communique ..." first); about half the rows split rank and bib onto separate lines | 1-2 tables per page, 20-29 columns, 30-190 empty cells | Use word coordinates only. |

Team details:
- Lines-table output puts rank, team, time and speed on the first row of a team
  and `None` on the rest (2025 TP p3, 2023 p1). In 2023 p1 (Team Sprint Men Elite)
  some teams collapsed into one row with newline-joined cells (28 rows against
  39 rider lines). Both shapes occur, so the parser should not depend on pdfplumber table cells.
- 2025 Team Pursuit (Men Elite, p3): the Team cell is empty in the table and the
  team names sit in a separate text block at the end of the page. Rank-band y
  ranges plus the team column x range recover them.
- 2023 asterisk bibs (`*426`, `*378`): reserve riders. Parser must keep the `*`
  in raw and strip it into a flag.

Points details:
- Header recovered by coordinates: the Communique number and date sit in the
  top-right block (2025 p8: "Communique 61 / MONDAY, Dec. 22, 2025").
- 2025 Madison has no DOB column and one row per team. 2023 Madison has
  two riders per team, the second on its own row.

## 5. Header fields from naive regex (communique pages only)

2025: communique number, race, category and date found on 46/46. Distance found
on all timed and team pages, 6/11 placing pages (Keirin and Elimination have no
distance) and 0/5 points pages (distance is inside the title, e.g. "25 Km. Point Race").
2023: number, race, category found on 45/45 except the 2 Omnium sheets (no number); date found 43/45.

Header formats the classifier must absorb: `Communique No. 22`, `No: 64`,
`No. 48 classification`, `No. 109 - Classification`, `No. 241 Rev`,
`No. 77 (Revised)`, `Last Communique 61`, placeholder `No…....`.
Dates: `FRIDAY, Dec. 19, 2025`, `Tuesday, 23 Dec 2025`, `Friday, Dec. 1, 2023`.
Titles: `Time Trial` / `INDIVIDUAL TIME TRIAL`, `Ind. Pursuit` / `Individual Pursuit`,
`Point Race` / `Points Race`. Typos in titles: `Final Classificatoin`.

## 6. Findings not in the brief

1. **The 2023 file is the 75th, not the 76th.** `Master_Results_76NTCC1.pdf`
   says "75th Senior ... Ranchi, 30th Nov. to 4th Dec. 2023" on every page. The
   76th (2024) is still missing. Fixture renamed `2023_75th_ranchi.pdf`.
2. **2023 Omnium sheets have no communique number and an unreliable date.** The
   number is the placeholder `No…....`. The sheet date is `12/29/2023` (men) and
   `12/3/2023` (women), and the men's date is clearly a print date, since the event ran 30 Nov to 4 Dec.
   Race date for these must come from the championship range or be left unknown and flagged.
3. **Two continuation pages in 2023, not one.** Comm. 240 (Youth Boys IP,
   rows 36-39 plus two unranked Andaman & Nicobar riders) and Comm. 242 (Youth Boys Time Trial, rows 36-40). Continuation pages repeat the
   championship header but have no communique number, title or column row.
4. **Rank is not time-ordered in pursuits either.** Pursuits are decided by
   final heats, so a faster time can sit lower. Inversions found (a crude text
   check plus manual reading of the Men Elite TP page, which the check misses):
   2023: Men Elite Ind. Pursuit (Silver/Bronze, 4th/5th), Men Elite Team Pursuit
   (Bronze/4th), Women Elite Team Pursuit (Bronze/4th), Men Junior Ind. Pursuit
   (Gold/Silver). 2025: Women Elite Ind. Pursuit (Gold/Silver), Men Elite Team
   Pursuit (2nd/3rd), Men Junior Team Pursuit (2nd/3rd), Women Junior Team Pursuit
   (3rd/4th), Youth Boys Ind. Pursuit (Silver/Bronze), Youth Girls Ind. Pursuit
   (Gold/Silver). The brief treats only Sprint and Team Sprint as non-time-ordered
   and the 2025 Men Elite Team Pursuit as a possible source error. It looks like
   normal pursuit behaviour. Recommendation for Phase 6: `time_ordered: false`
   for pursuits too. This list is from the two samples only and is not exhaustive.
5. **Page-level noise in 2025.** Blank logo pages (10, 18, 30), a footer-only
   spill page (14), and a 4-word date fragment (25). None carries data.
   The segmenter should drop them with a log line, never silently.
6. **DOB formats.** 2025: `dd-mm-yyyy` 707, `dd.mm.yyyy` 174, `dd-Mon-yyyy` 101,
   `dd/mm/yyyy` 75, `dd-Mon-yy` 44, `dd/mmyyyy` 6. 2023: `dd.mm.yyyy` 1065,
   `dd-mm-yyyy` 45, `dd/mm/yyyy` 2. US-order dates appear (`10/18/2006`,
   `03/19/2009`, `05/21/2011`, `09/20/2012`). They are detectable only
   when the day is above 12, so ambiguous ones cannot be told apart. The 2023 file also has a 3-digit year typo, `28.10.209`
   (Aryan, bib 367, Punjab).
7. **Source errors from the brief all confirmed** and locked in as test
   fixtures: `#DIV/0!` (2025 Women Junior Point Race), speed `5.00` (bib 181),
   speed `31.85` (bib 465 and bib 60), bib 427 twice in Women Junior Keirin
   (ranks 9 and 11), Madison skipping rank 6.
8. **Footer date.** Every 2023 page has a print date bottom-left (`01-12-2023`,
   `29-12-2023`, `09-07-2025`). Never use it as the race date.

## 7. Recommendations for Phase 2

- Classify from word coordinates, not plain text. Plain text is only trustworthy on timed and placing pages.
- Identity of a communique = championship + page + race + category (number alone is not unique; Comm. 111 appears twice in 2025).
- Treat "headerless" as: no communique number, no race keyword, has a table, immediately follows a headed page.
- Treat footer-only and < 15-word pages as attachable noise.
- Dates: parse from the header block only; fall back to "unknown" plus a review flag.

## 8. What has not been verified

- Layouts of the 65th to 72nd, 74th and 76th championships.
- Whether any older PDF is scanned.
- The naive row counter used by the spike is not meaningful for points pages.
  The "Tables" column above is a qualitative read there.
