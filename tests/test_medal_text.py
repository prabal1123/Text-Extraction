from pipeline.medal_text import edition_meta, event_distance, guess_venue, parse_medal_text

RANK_FIRST = """69th Senior, 46th Junior 32nd Sub-Junior
National Track Cycling Championship 2016
LNCPE Cycling Velodrome, Trivandrum, Kerala from 21 to 25th Dec. 2016
Communique No. 182
Medalists
Men Elite
Rank Start No. Name DOB State Time
Team Sprint
338 Ranjit Singh 24.08.1993
1 329 Sanu Raj P. 02.03.1998 SSCB 1:05.969 NR Gold
334 Deepak Mehta 14.07.1990
316 Vikaram Duhan 02.04.1989
2 318 Karanveer Singh 31.12.1993 RSPB 1:06.407 Silver
325 Amarjieet Singh Negi 26.03.1993
97 Ranjit Singh 27.08.1997
3 113 Amit Kumar 15.12.1994 Haryana 1:07.173 Bronze
112 Sahil Kumar 07.04.1998
4 Km. Ind. Pursuit
1 330 Manjeet Singh 12.10.1993 SSCB 4:56.725 Gold
2 326 Manohar Lal 16.03.1996 RSPB 5:01.049 Silver
30 Km. Point Race
1 331 Satbir Singh 26.06.1987 SSCB 71 Gold
2 378 B. Mugesh 24.02.1995 Telangana 39 Silver
"""

TABLE = """Medalist of 72nd National Track Cycling Championships held at Guwahati from 11th to 15th Dec.
Category Bib No. Name DOB State Father Name Gender Timing Medal Event
Men Elite 224 Laitonjam Ronaldo Singh 02.06.2002 Manipur L Romen Singh Male 1:06.091 Sec. Silver 1 Km. Time Trial (ME)
Men Elite 261 Amarjeet Singh 26.03.1993 Punjab Bawa Singh Male 1:05.943 Sec. (NR) Gold 1 Km. Time Trial (ME)
Men Elite 5 Esow 10.03.2001 A & N Alban Male 01:02.922 Sec. Silver Team Sprint (ME)
Men Elite 6 Paul Collingwood 25.01.2002 A & N Jacob Male 01:02.922 Sec. Silver Team Sprint (ME)
Men Elite 7 David Beckhame 29.09.2003 A & N Israel Male 01:02.922 Sec. Silver Team Sprint (ME)
Women Junior 24 Gongutri Bordoloi 06.09.2002 Assam Mihiram Bordoloi Female 42 Points Gold 10 Km. Point Race (WJ)
Sub Junior Girls 39 Reet Kapoor 26.08.2004 Chandigarh Gurmeet Singh Female - Bronze 4 Km. Scratch Race (SJG)
"""


def test_rank_first_format():
    res, unmatched, fmt = parse_medal_text(RANK_FIRST.splitlines())
    assert fmt == "rank_first"
    assert len(res) == 7
    assert unmatched == []
    ts = [r for r in res if r["event"] == "Team Sprint"]
    assert [r["medal"] for r in ts] == ["Gold", "Silver", "Bronze"]
    assert ts[0]["category"] == "Men Elite"
    assert ts[0]["state"] == "SSCB"
    assert ts[0]["time"] == "1:05.969"
    assert ts[0]["nr"] is True
    assert [m["name"] for m in ts[0]["members"]] == ["Ranjit Singh", "Sanu Raj P.", "Deepak Mehta"]
    pts = [r for r in res if r["event"] == "30 Km. Point Race"]
    assert pts[0]["points"] == 71
    assert pts[0]["state"] == "SSCB"
    assert pts[1]["points"] == 39


def test_table_format():
    res, unmatched, fmt = parse_medal_text(TABLE.splitlines())
    assert fmt == "table"
    assert len(res) == 5
    assert unmatched == []
    team = [r for r in res if r["is_team"]]
    assert len(team) == 1
    assert len(team[0]["members"]) == 3
    assert team[0]["state"] == "A & N"
    assert team[0]["medal"] == "Silver"
    tt = [r for r in res if r["event"] == "1 Km. Time Trial"]
    gold = next(r for r in tt if r["medal"] == "Gold")
    assert gold["name"] == "Amarjeet Singh"
    assert gold["state"] == "Punjab"
    assert gold["time"] == "1:05.943"
    assert gold["nr"] is True
    pr = next(r for r in res if r["event"] == "10 Km. Point Race")
    assert pr["points"] == 42
    sj = next(r for r in res if r["event"] == "4 Km. Scratch Race")
    assert sj["time"] == ""
    assert sj["category"] == "Sub Junior Girls"


def test_helpers():
    assert event_distance("500 Mtr. Time Trial") == "500 Mtr"
    assert event_distance("4 Km. Ind. Pursuit") == "4 Km"
    assert event_distance("Team Sprint") is None
    assert guess_venue(RANK_FIRST.splitlines()) == "LNCPE Cycling Velodrome, Trivandrum, Kerala"
    assert guess_venue(TABLE.splitlines()) == "Guwahati"


def test_edition_meta_override():
    meta = edition_meta(72, TABLE.splitlines())
    assert (meta["year"], meta["venue"], meta["overridden"]) == (2021, "Hyderabad", True)
    meta = edition_meta(69, RANK_FIRST.splitlines())
    assert (meta["year"], meta["venue"], meta["overridden"]) == (
        2016, "LNCPE Cycling Velodrome, Trivandrum, Kerala", False)


STATE_ON_EVERY_ROW = """Women Elite
4 Km. Team Pursuit
314 Monorama Devi 01.04.1996 RSPB
316 Nayana Rajesh 28.07.1998 RSPB
1 318 Vaishnavi Gabhane 21.10.1999 RSPB 05:32.857 Gold
315 *Sonali Chanu 11.03.1997 RSPB
317 Amritha Reghunathan 15.06.1998 RSPB
293 Pardeep Kaur 10.11.1999 Punjab
2 294 Jagjeet Kaur 17.05.1994 Punjab 05:45.303 Silver
292 *Priyanka 04.04.1993 Punjab
297 Rajbir Kaur 08.08.1995 Punjab
Page 2 of 7
292 Priyanka 04.04.1993 Punjab
295 Jasmine Kaur 19.09.1999 Punjab
103 Neeraj Devi 22.09.1994 Haryana
101 Aashu Sharma 15.03.1998 Haryana
3 102 Suman 22.03.1995 Haryana 06:15.839 Bronze
105 *Pooja Rani 20.10.1999 Haryana
106 Monika Devi 20.06.1989 Haryana
"""

FATHER_COLUMN = """Men Elite
Rank Start No. Name Father's Name DOB State Time speed
4 Km. Team Pursuit
434 Mula Ram Sh. Narayan Ram 28.12.2002
430 Manjeet Singh Sh. Amrit Lal 12.10.1993 SSCB 04:37.784 51.84
1 432 Dinesh Kumar Sh. Mahendra Patel 30.01.2000
433 Sahil Kumar Sh. Sumer Chand 07.04.1998
437 Dinesh Kumar Sh. Chandr Pal Singh 01.02.1995
1Km. Time Trial
1 298 Laitonjam Ronaldo Singh L. Romen Singh 22.06.2002 Manipur 01:05.794 NR 54.72
"""


def test_state_on_every_row_and_page_break_duplicate():
    res, unmatched, fmt = parse_medal_text(STATE_ON_EVERY_ROW.splitlines())
    assert fmt == "rank_first"
    assert unmatched == []
    assert [r["medal"] for r in res] == ["Gold", "Silver", "Bronze"]
    assert [r["state"] for r in res] == ["RSPB", "Punjab", "Haryana"]
    assert [len(r["members"]) for r in res] == [5, 5, 5]
    assert res[0]["time"] == "05:32.857"
    assert res[0]["members"][3]["is_reserve"] is True
    assert [m["name"] for m in res[1]["members"]].count("Priyanka") == 1


def test_father_column_and_missing_medal_word():
    res, unmatched, fmt = parse_medal_text(FATHER_COLUMN.splitlines())
    assert unmatched == []
    team = next(r for r in res if r["is_team"])
    assert (team["medal"], team["state"], team["time"], team["speed"]) == ("Gold", "SSCB", "04:37.784", "51.84")
    assert len(team["members"]) == 5
    assert team["name_has_father"] is True
    solo = next(r for r in res if not r["is_team"])
    assert solo["event"] == "1 Km. Time Trial"
    assert (solo["state"], solo["time"], solo["speed"], solo["nr"]) == ("Manipur", "01:05.794", "54.72", True)


def test_damaged_text_is_repaired():
    split_row = [
        "Men Junior",
        "Team Sprint",
        "202 Abhishek Kashid 13.03.2000",
        "1 126 Gold",
        "Venkappa Kengalagutti 12.06.2001 Karnataka 4:54.393",
        "123 Santosh Kurani 16.04.1998",
    ]
    res, unmatched, _ = parse_medal_text(split_row)
    assert unmatched == []
    assert (res[0]["state"], res[0]["time"], res[0]["medal"]) == ("Karnataka", "4:54.393", "Gold")
    assert len(res[0]["members"]) == 3

    wrapped = [
        "Category Bib No. Name DOB State Father Name Gender Timing Medal Event",
        "Mayanglambam Wattaba",
        "Youth Boys 236 01.11.2006 Manipur M Manihar Meitei Male 2:38.760 Sec. Silver 2 Km. Ind. Pursuit (YB)",
        "Meitei",
        "Men Junior 278 Harsiret Singh Malhotra 18.08.2003 Punjab Gurinder Singh MalhotraMale "
        "4:45.909 Sec. Gold 4 Km. Ind. Pursuit (MJ)",
    ]
    res, unmatched, fmt = parse_medal_text(wrapped)
    assert fmt == "table"
    assert unmatched == []
    assert res[0]["name"] == "Mayanglambam Wattaba Meitei"
    assert res[1]["name"] == "Harsiret Singh Malhotra"
    assert res[1]["gender"] == "Male"


STATE_ON_EVERY_ROW = """Women Elite
4 Km. Team Pursuit
314 Monorama Devi 01.04.1996 RSPB
316 Nayana Rajesh 28.07.1998 RSPB
1 318 Vaishnavi Gabhane 21.10.1999 RSPB 05:32.857 Gold
315 *Sonali Chanu 11.03.1997 RSPB
317 Amritha Reghunathan 15.06.1998 RSPB
293 Pardeep Kaur 10.11.1999 Punjab
2 294 Jagjeet Kaur 17.05.1994 Punjab 05:45.303 Silver
292 *Priyanka 04.04.1993 Punjab
297 Rajbir Kaur 08.08.1995 Punjab
Page 2 of 7
292 Priyanka 04.04.1993 Punjab
295 Jasmine Kaur 19.09.1999 Punjab
103 Neeraj Devi 22.09.1994 Haryana
101 Aashu Sharma 15.03.1998 Haryana
3 102 Suman 22.03.1995 Haryana 06:15.839 Bronze
105 *Pooja Rani 20.10.1999 Haryana
106 Monika Devi 20.06.1989 Haryana
"""

FATHER_COLUMN = """Men Elite
Rank Start No. Name Father's Name DOB State Time speed
4 Km. Team Pursuit
434 Mula Ram Sh. Narayan Ram 28.12.2002
430 Manjeet Singh Sh. Amrit Lal 12.10.1993 SSCB 04:37.784 51.84
1 432 Dinesh Kumar Sh. Mahendra Patel 30.01.2000
433 Sahil Kumar Sh. Sumer Chand 07.04.1998
437 Dinesh Kumar Sh. Chandr Pal Singh 01.02.1995
1Km. Time Trial
1 298 Laitonjam Ronaldo Singh L. Romen Singh 22.06.2002 Manipur 01:05.794 NR 54.72
"""


def test_state_on_every_row_and_page_break_duplicate():
    res, unmatched, fmt = parse_medal_text(STATE_ON_EVERY_ROW.splitlines())
    assert fmt == "rank_first"
    assert unmatched == []
    assert [r["medal"] for r in res] == ["Gold", "Silver", "Bronze"]
    assert [r["state"] for r in res] == ["RSPB", "Punjab", "Haryana"]
    assert [len(r["members"]) for r in res] == [5, 5, 5]
    assert res[0]["time"] == "05:32.857"
    assert res[0]["members"][3]["is_reserve"] is True
    assert [m["name"] for m in res[1]["members"]].count("Priyanka") == 1


def test_father_column_and_missing_medal_word():
    res, unmatched, fmt = parse_medal_text(FATHER_COLUMN.splitlines())
    assert unmatched == []
    team = next(r for r in res if r["is_team"])
    assert (team["medal"], team["state"], team["time"], team["speed"]) == ("Gold", "SSCB", "04:37.784", "51.84")
    assert len(team["members"]) == 5
    assert team["name_has_father"] is True
    solo = next(r for r in res if not r["is_team"])
    assert solo["event"] == "1 Km. Time Trial"
    assert (solo["state"], solo["time"], solo["speed"], solo["nr"]) == ("Manipur", "01:05.794", "54.72", True)


def test_damaged_text_is_repaired():
    split_row = [
        "Men Junior",
        "Team Sprint",
        "202 Abhishek Kashid 13.03.2000",
        "1 126 Gold",
        "Venkappa Kengalagutti 12.06.2001 Karnataka 4:54.393",
        "123 Santosh Kurani 16.04.1998",
    ]
    res, unmatched, _ = parse_medal_text(split_row)
    assert unmatched == []
    assert (res[0]["state"], res[0]["time"], res[0]["medal"]) == ("Karnataka", "4:54.393", "Gold")
    assert len(res[0]["members"]) == 3

    wrapped = [
        "Category Bib No. Name DOB State Father Name Gender Timing Medal Event",
        "Mayanglambam Wattaba",
        "Youth Boys 236 01.11.2006 Manipur M Manihar Meitei Male 2:38.760 Sec. Silver 2 Km. Ind. Pursuit (YB)",
        "Meitei",
        "Men Junior 278 Harsiret Singh Malhotra 18.08.2003 Punjab Gurinder Singh MalhotraMale "
        "4:45.909 Sec. Gold 4 Km. Ind. Pursuit (MJ)",
    ]
    res, unmatched, fmt = parse_medal_text(wrapped)
    assert fmt == "table"
    assert unmatched == []
    assert res[0]["name"] == "Mayanglambam Wattaba Meitei"
    assert res[1]["name"] == "Harsiret Singh Malhotra"
    assert res[1]["gender"] == "Male"
