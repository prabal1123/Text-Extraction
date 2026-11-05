"""Page-level extraction: words with coordinates, plain text, image coverage.

Pure Python. No Django imports, so the whole pipeline can be tested straight
from a PDF.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pdfplumber

FOOTER_TOKENS = {
    "communique", "approved", "by", "commissaires", "commissaries",
    "commissaires", "panel",
}
_UNDERSCORES = re.compile(r"^_+$")


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class PageData:
    index: int                    # 1-based page number in the PDF
    width: float
    height: float
    words: list[Word]
    text: str                     # pdfplumber plain text (reading order as extracted)
    image_count: int
    image_coverage: float         # largest single image as a fraction of page area
    chars: int = 0
    lines: list[list[Word]] = field(default_factory=list)

    @property
    def n_words(self) -> int:
        return len(self.words)

    @property
    def has_text_layer(self) -> bool:
        return self.n_words > 0

    @property
    def is_blank(self) -> bool:
        """No text at all (logo-only pages)."""
        return self.n_words == 0

    @property
    def is_footer_only(self) -> bool:
        """Only the 'Communique approved by ...' footer and its rule line."""
        if not self.words:
            return False
        return all(
            w.text.lower() in FOOTER_TOKENS or _UNDERSCORES.match(w.text)
            for w in self.words
        )

    @property
    def looks_scanned(self) -> bool:
        """A page-sized image and little or no text."""
        return self.image_coverage > 0.6 and self.n_words < 20


def group_lines(words: list[Word], y_tol: float = 3.0) -> list[list[Word]]:
    """Cluster words into visual lines by vertical centre, left to right."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.yc, w.x0)):
        if lines and abs(lines[-1][0].yc - w.yc) <= y_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(l, key=lambda w: w.x0) for l in lines]


def _image_coverage(page) -> tuple[int, float]:
    area = float(page.width * page.height) or 1.0
    biggest = 0.0
    for im in page.images:
        w = max(0.0, im["x1"] - im["x0"])
        h = max(0.0, im["bottom"] - im["top"])
        biggest = max(biggest, w * h / area)
    return len(page.images), biggest


def read_pdf(path: str | Path) -> Iterator[PageData]:
    """Yield one PageData per page, lazily (large PDFs are processed page by page)."""
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            raw = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
            words = [Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"]) for w in raw]
            n_img, cover = _image_coverage(page)
            data = PageData(
                index=i,
                width=float(page.width),
                height=float(page.height),
                words=words,
                text=page.extract_text() or "",
                image_count=n_img,
                image_coverage=cover,
                chars=len(page.chars),
                lines=group_lines(words),
            )
            yield data
            page.flush_cache()
