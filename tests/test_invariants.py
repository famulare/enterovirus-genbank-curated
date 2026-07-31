"""Negative controls for the cross-column invariants.

A review established that replacing both invariant functions with no-ops left the entire suite
green — `pytest`, `pytest -m slow`, `validate-contracts` and `parity-metadata` all passed. So the
claims in `derive/geo.py` and `docs/reproducibility.md` that these are *enforced* were prose with
nothing behind them: R2 exactly, and specifically the standard `docs/reproducibility.md` holds the
sandbox to — every rule has a test that fails when the rule is removed.

One test per property, each constructing the breach directly. If an invariant is gutted, these fail.
"""

from __future__ import annotations

import pytest

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.derive.dates import PRECISION_NOT_APPLICABLE
from enterovirus_genbank_curated.derive.geo import (
    BASIS_NO_ADMIN1,
    BASIS_NO_GEOGRAPHY,
    BASIS_PARSED,
    BASIS_SUPPRESSED,
)
from enterovirus_genbank_curated.validation.invariants import (
    assert_date_precision_invariant,
    assert_locality_basis_invariant,
)


def locality_row(basis: str, value: str, version: str = "AB000001.1") -> dict[str, str]:
    return {
        "version": version,
        "canonical_field": "locality",
        "final_value": value,
        "evidence_basis": basis,
    }


def transport_row(country: str, admin1: str, version: str = "AB000001.1") -> dict[str, str]:
    return {"version": version, "country": country, "admin1": admin1}


def date_rows(date: str, precision: str, version: str = "AB000001.1") -> list[dict[str, str]]:
    return [
        {"version": version, "canonical_field": "collection_date", "final_value": date},
        {
            "version": version,
            "canonical_field": "collection_date_precision",
            "final_value": precision,
        },
    ]


# --- locality: the four properties ----------------------------------------------------------------


def test_a_blank_locality_claiming_a_parsed_basis_is_caught() -> None:
    """Property 1. This is the case the earlier `continue` let through silently."""
    with pytest.raises(ContractError, match="locality basis invariant"):
        assert_locality_basis_invariant(
            [locality_row(BASIS_PARSED, "")], [transport_row("Pakistan", "Sindh")]
        )


def test_a_populated_locality_claiming_a_blank_basis_is_caught() -> None:
    """Property 1, the other direction."""
    with pytest.raises(ContractError, match="locality basis invariant"):
        assert_locality_basis_invariant(
            [locality_row(BASIS_SUPPRESSED, "Sindh, Karachi")], [transport_row("Pakistan", "Sindh")]
        )


def test_a_suppression_with_no_admin1_to_suppress_is_caught() -> None:
    """Property 2 — the whole reason the basis was split in the first place."""
    with pytest.raises(ContractError, match="admin1 is blank"):
        assert_locality_basis_invariant(
            [locality_row(BASIS_SUPPRESSED, "")], [transport_row("Pakistan", "")]
        )


@pytest.mark.parametrize(
    ("basis", "country", "admin1"),
    [
        (BASIS_NO_ADMIN1, "Pakistan", "Sindh"),   # claims no admin1 while carrying one
        (BASIS_NO_ADMIN1, "", ""),                # claims a country it does not have
        (BASIS_NO_GEOGRAPHY, "Pakistan", ""),     # claims nothing deposited, but a country was
        (BASIS_NO_GEOGRAPHY, "", "Sindh"),
    ],
)
def test_a_blank_basis_contradicting_the_records_geography_is_caught(
    basis: str, country: str, admin1: str
) -> None:
    """Properties 3 and 4."""
    with pytest.raises(ContractError, match="locality basis invariant"):
        assert_locality_basis_invariant(
            [locality_row(basis, "")], [transport_row(country, admin1)]
        )


def test_a_locality_row_with_no_transport_row_cannot_be_checked_and_fails() -> None:
    """Previously skipped all four checks, so an unverifiable basis passed as a verified one."""
    with pytest.raises(ContractError, match="no transport row"):
        assert_locality_basis_invariant([locality_row(BASIS_SUPPRESSED, "")], [])


def test_the_locality_invariant_refuses_to_pass_vacuously() -> None:
    """An invariant examining nothing is indistinguishable from one that is not running."""
    with pytest.raises(ContractError, match="examined no rows"):
        assert_locality_basis_invariant([], [])


def test_a_conforming_locality_set_passes() -> None:
    """Positive control: without it, a check that refused everything would look like success."""
    counts = assert_locality_basis_invariant(
        [
            locality_row(BASIS_PARSED, "Sindh, Karachi", "A.1"),
            locality_row(BASIS_SUPPRESSED, "", "B.1"),
            locality_row(BASIS_NO_ADMIN1, "", "C.1"),
            locality_row(BASIS_NO_GEOGRAPHY, "", "D.1"),
        ],
        [
            transport_row("Pakistan", "Sindh", "A.1"),
            transport_row("Pakistan", "Sindh", "B.1"),
            transport_row("Pakistan", "", "C.1"),
            transport_row("", "", "D.1"),
        ],
    )
    assert counts == {
        BASIS_PARSED: 1,
        BASIS_SUPPRESSED: 1,
        BASIS_NO_ADMIN1: 1,
        BASIS_NO_GEOGRAPHY: 1,
    }


# --- date and precision ---------------------------------------------------------------------------


def test_a_blank_date_with_a_real_precision_is_caught() -> None:
    with pytest.raises(ContractError, match="blank date with precision"):
        assert_date_precision_invariant(date_rows("", "year"))


def test_a_populated_date_with_na_precision_is_caught() -> None:
    with pytest.raises(ContractError, match=f"precision {PRECISION_NOT_APPLICABLE}"):
        assert_date_precision_invariant(date_rows("2013", PRECISION_NOT_APPLICABLE))


def test_the_date_invariant_refuses_to_pass_vacuously() -> None:
    """Including the case where only one of the two columns is present.

    A field dropped from the catalog binding used to make this invariant silently examine nothing.
    """
    with pytest.raises(ContractError, match="examined no rows"):
        assert_date_precision_invariant([])
    only_precision = [date_rows("2013", "year")[1]]
    with pytest.raises(ContractError, match="examined no rows"):
        assert_date_precision_invariant(only_precision)


def test_a_conforming_date_set_passes() -> None:
    assert assert_date_precision_invariant(
        date_rows("2013", "year", "A.1") + date_rows("", PRECISION_NOT_APPLICABLE, "B.1")
    ) == 1
