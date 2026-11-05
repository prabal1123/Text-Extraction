from pipeline.parsers import extract_status, process_table, split_time_speed

CFG = {'columns': {
    'rank': ['Rank'], 'bib': ['Start No.'], 'name': ['Name'],
    'dob': ['DOB'], 'team': ['State'], 'time': ['Time'],
}}
HEADER = ["Rank", "Start No.", "Name", "DOB", "State", "Time"]


def test_names_containing_status_letters_are_not_statuses():
    assert extract_status(["5", "101", "02:51.429"]) == "OK"
    assert extract_status(["Abdul Rahman", "Reliance Team"]) == "OK"


def test_real_statuses_are_detected():
    assert extract_status(["", "DNS"]) == "DNS"
    assert extract_status(["Relegated"]) == "REL"
    assert extract_status(["abd"]) == "ABD"


def test_headerless_continuation_page_is_parsed_with_carried_headers():
    page1 = [HEADER, ["1", "101", "Ravi Kumar", "01-01-2005", "Kerala", "02:51.429"]]
    page2 = [["36", "201", "Some Rider", "01-01-2009", "Punjab", "03:10.100"]]
    rows1, headers = process_table(page1, CFG)
    rows2, _ = process_table(page2, CFG, headers)
    assert len(rows1) == 1
    assert len(rows2) == 1 and rows2[0]["bib"] == "201"


def test_headerless_table_without_carry_yields_nothing():
    page2 = [["36", "201", "Some Rider", "01-01-2009", "Punjab", "03:10.100"]]
    rows, headers = process_table(page2, CFG)
    assert rows == [] and headers is None


def test_time_is_not_mistaken_for_speed():
    time_str, speed_str, rest = split_time_speed("Kerala 02:51.429 31.85")
    assert (time_str, speed_str) == ("02:51.429", "31.85")
    assert rest.split() == ["Kerala"]


def test_odd_speed_values_land_in_speed_not_team_name():
    _, speed, rest = split_time_speed("Kerala 02:51.429 5.00")
    assert speed == "5.00" and rest.split() == ["Kerala"]
    _, speed, rest = split_time_speed("Delhi 02:50.100 #DIV/0!")
    assert speed == "#DIV/0!" and rest.split() == ["Delhi"]


def test_tables_own_header_wins_over_carried_headers():
    other = ["Rank", "Start No.", "Name", "DOB", "State", "Time"]
    carried = [normalize for normalize in [None, None, None, None, None, None]]
    own = [["Start No.", "Name", "Rank", "DOB", "State", "Time"],
           ["301", "Kiran", "4", "01-01-2006", "Goa", "03:00.000"]]
    _, h = process_table([other, ["1", "101", "A", "01-01-2005", "X", "02:00.000"]], CFG)
    rows, _ = process_table(own, CFG, h)   # different column order than carried
    assert rows[0]["bib"] == "301" and rows[0]["rank"] == "4"


# ---- fix3 tests ----
TIMED_CFG = {'columns': {
    'rank': ['Rank'], 'bib': ['Start No.', 'Start No'], 'name': ['Name'],
    'dob': ['DOB'], 'team': ['State'], 'time': ['Time'], 'speed': ['@speed', 'Speed'],
}}
POINTS_CFG = {'columns': {
    'rank': ['Rank'], 'bib': ['Bib No.'], 'name': ['Name'], 'dob': ['DOB'],
    'team': ['State'], 'points': ['Points'], 'lap': ['Lap +/-', '+/-', 'Lap'],
}}


def test_merged_header_cell_is_split():
    t = [['Rank Start No. Name DOB State Time @speed', '', '', '', '', '', ''],
         ['1', '2', 'David Beckham', '20.09.2003', 'Andaman & Nicobar', '01:05.423', '55.03']]
    rows, _ = process_table(t, TIMED_CFG)
    assert len(rows) == 1
    assert rows[0]['bib'] == '2' and rows[0]['time'] == '01:05.423' and rows[0]['speed'] == '55.03'


def test_stacked_points_header_and_sprint_positions():
    t = [
        [''] * 15 + ['FO', '+ Lap', '- Lap', 'Points'],
        ['Rank', 'Bib No.', 'Name', 'DOB', 'State'] + [str(i) for i in range(1, 11)] + ['', '', '', ''],
        ['1', '388', 'Kheta Ram Chiga', '07.09.2005', 'Rajasthan',
         '', '', '', '3', '', '5', '', '5', '3', '10', '', '1', '', '46'],
    ]
    rows, _ = process_table(t, POINTS_CFG)
    assert len(rows) == 1
    r = rows[0]
    assert r['bib'] == '388' and r['points'] == '46' and r['lap'] == '1' and r['lap_2'] == ''
    assert r['_sprints'] == ['', '', '', '3', '', '5', '', '5', '3', '10']


def test_plain_number_table_is_not_parsed_with_carried_headers():
    t = [['Rank Start No. Name DOB State Time @speed', '', '', '', '', '', ''],
         ['1', '2', 'A B', '01.01.2000', 'X', '01:00.000', '50.00']]
    _, h = process_table(t, TIMED_CFG)
    nums = [['299', '477', '103', '165', '75', '388', '75']]
    rows, _ = process_table(nums, TIMED_CFG, h)
    assert rows == []
