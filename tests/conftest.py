import json
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import (
    DECISIONS_SCHEMA_PATH,
    PARITY_SPEC_PATH,
    DecisionContract,
    load_decision_contract,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def fixture_ledger() -> Path:
    return ROOT / "tests/fixtures/decisions.tsv"


@pytest.fixture(scope="session")
def decision_contract() -> DecisionContract:
    return load_decision_contract(ROOT / DECISIONS_SCHEMA_PATH)


@pytest.fixture(scope="session")
def parity_spec() -> dict:
    return json.loads((ROOT / PARITY_SPEC_PATH).read_text(encoding="utf-8"))
