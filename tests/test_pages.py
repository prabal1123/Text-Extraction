"""Phase 0 smoke tests: page extraction against the two sample PDFs.

Expected values were checked by hand against the PDFs.
"""
import re


def test_page_counts(pages_2025, pages_2023):
    assert len(pages_2025) == 51
    assert len(pages_2023) == 47


def test_no_scanned_pages(pages_2025, pages_2023):
    # Both samples have a real text layer; OCR is not needed for them.
    assert not [p.index for p in pages_2025 + pages_2023 if p.looks_scanned]
    assert sum(p.has_text_layer for p in pages_2025) == 48
    assert all(p.has_text_layer for p in pages_2023)


def test_2025_blank_footer_and_fragment_pages(pages_2025):
    blank = [p.index for p in pages_2025 if p.is_blank]
    footer_only = [p.index for p in pages_2025 if p.is_footer_only]
    fragment = [p.index for p in pages_2025 if 0 < p.n_words < 15 and not p.is_footer_only]
    assert blank == [10, 18, 30]
    assert footer_only == [14]
    assert fragment == [25]  # stray "SUNDAY, Dec. 21, 2025" date overflow


def test_every_blank_page_still_has_a_logo_image(pages_2025):
    # Blank pages are logo-only: image present, no words.
    for p in pages_2025:
        if p.is_blank:
            assert p.image_count >= 1


def _communique_numbers(pages):
    out = {}
    for p in pages:
        m = re.search(r"Communique\s*(?:No)?[.:\s]*([0-9]+)", p.text)
        if m:
            out[p.index] = int(m.group(1))
    return out


def test_2025_communique_numbers_are_not_unique(pages_2025):
    nums = _communique_numbers(pages_2025)
    assert nums[21] == 111 and nums[31] == 111
    assert "Women Elite" in pages_2025[20].text
    assert "Men Junior" in pages_2025[30].text


def test_2023_pages_without_a_communique_number(pages_2023):
    nums = _communique_numbers(pages_2023)
    missing = [p.index for p in pages_2023 if p.index not in nums]
    # 8 and 17 are the Omnium sheets (number is a placeholder "No….....");
    # 43 and 45 are headerless continuation pages.
    assert missing == [8, 17, 43, 45]


def test_2023_continuation_pages_follow_communique_240_and_242(pages_2023):
    assert "Communique No. 240" in pages_2023[41].text
    assert "Communique No. 242" in pages_2023[43].text
    for idx in (43, 45):
        text = pages_2023[idx - 1].text
        assert "Communique" in text and "approved" in text  # footer only
        assert "Final Classification" not in text.split("Communique approved")[0]


def test_2023_revised_communique_label(pages_2023):
    assert "Communique No. 77 (Revised)" in pages_2023[11].text


def test_2025_points_header_is_scrambled_in_plain_text(pages_2025):
    # Plain text starts with "Last Communique ..." instead of the header block.
    assert pages_2025[0].text.startswith("Last Communique No: 64")
    assert pages_2025[18].text.startswith("Last")


def test_word_coordinates_recover_points_header(pages_2025):
    # Page 8 (Omnium): the Communique number sits in the top-right block.
    p = pages_2025[7]
    right_top = [w for w in p.words if w.x0 > p.width * 0.7 and w.top < p.height * 0.35]
    text = " ".join(w.text for w in sorted(right_top, key=lambda w: (round(w.top), w.x0)))
    assert "Communique 61" in text
    assert "MONDAY, Dec. 22, 2025" in text


def test_source_errors_are_present_in_the_pdfs(pages_2025, pages_2023):
    # Phase 6 must flag (not fix) these. Locking them in as fixtures.
    assert "#DIV/0!" in pages_2025[36].text                         # Women Junior Point Race speed
    assert "181 Delvin Jobish 19-02-2009 Kerala 02:51.429 5.00" in pages_2025[40].text
    assert "28.10.209" in pages_2023[42].text                       # 3-digit year typo (p43, spill of Comm. 240)
    # rider 427 appears twice in Women Junior Keirin (ranks 9 and 11)
    # (rank and bib can land on separate text lines, so count bib tokens by word)
    keirin = pages_2025[35]
    assert "KEIRIN" in keirin.text
    assert sum(1 for w in keirin.words if w.text == "427") == 2
