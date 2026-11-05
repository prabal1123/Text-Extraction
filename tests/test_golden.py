import json
from pathlib import Path

import pytest

from pipeline.quality import golden_rows

GOLDEN = Path(__file__).parent / "golden"
FILES = sorted(GOLDEN.glob("*.json")) if GOLDEN.exists() else []


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_golden(path):
    spec = json.loads(path.read_text())
    if not spec.get("verified"):
        pytest.skip("not hand-verified yet")
    pdf = Path(spec["pdf"])
    if not pdf.exists():
        pytest.skip(f"{pdf} is missing")
    got = golden_rows(str(pdf), spec["pages"], spec["layout"], spec.get("race_type", ""))
    assert got == spec["expected"]
