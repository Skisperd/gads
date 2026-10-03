from pathlib import Path

import pytest

from casaradar.config import Search

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")
    return _load


@pytest.fixture
def search():
    return Search(
        name="T2 Lisboa",
        transaction="arrendar",
        property_type="apartamento",
        location={"imovirtual": "lisboa/lisboa", "default": "lisboa"},
        typology=["T1", "T2"],
        price_min=800,
        price_max=1500,
        area_min=50,
    )
