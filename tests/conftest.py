from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def pdf_2025():
    return FIXTURES / "2025_77th_rudrapur.pdf"


@pytest.fixture(scope="session")
def pdf_2023():
    return FIXTURES / "2023_75th_ranchi.pdf"


@pytest.fixture(scope="session")
def pages_2025(pdf_2025):
    from pipeline.pages import read_pdf

    return list(read_pdf(pdf_2025))


@pytest.fixture(scope="session")
def pages_2023(pdf_2023):
    from pipeline.pages import read_pdf

    return list(read_pdf(pdf_2023))
