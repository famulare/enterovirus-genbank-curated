"""`R-SCOPE-2`, branch by branch, including the traps its docstring names.

The rule this replaces was the last unwritten canonical column, recorded as blocked because
coverage geometry against Sabin VP1 reproduced the shipped values on only 86.7% of poliovirus
records. The measurement was right; the model was wrong. Scope is a statement about a record's
*annotation*, so these tests are about labels, text and lengths — not about how much genome a
deposit covers.

`tests/test_canonical_transitions.py` pins the corpus result (zero differences from the preserved
2.4.1 column over all 24,296 shared rows). This file pins the reasoning, so a future edit that
happens to keep the total right still has to keep each branch right.
"""

from __future__ import annotations

from typing import Any

import pytest

from enterovirus_genbank_curated.derive.outcome import RecordView
from enterovirus_genbank_curated.derive.scope import (
    BASIS_CAPSID,
    BASIS_NO_REGION_NAMED,
    BASIS_NON_VP1,
    BASIS_OUTSIDE_POLIOVIRUS,
    BASIS_VP1_COMPLETE,
    BASIS_VP1_PARTIAL,
    BASIS_WHOLE_GENOME,
    sequence_scope,
)

PARAMETERS: dict[str, Any] = {
    "whole_genome_nt": "7000",
    "capsid_nt": "2400",
    "polyprotein_nt": "6000",
    "vp1_nt_by_serotype": {"1": "906", "2": "903", "3": "900", "unknown": "900"},
    "non_poliovirus_scope": "unknown",
}


def view(
    *,
    organism: str = "Poliovirus 1",
    definition: str = "",
    length: int = 500,
    features: tuple[dict[str, str], ...] = (),
    qualifiers: dict[str, str] | None = None,
    decisions: dict[str, str] | None = None,
) -> RecordView:
    return RecordView(
        version="X00001.1",
        accession="X00001",
        record={
            "organism_name": organism,
            "definition": definition,
            "sequence_length_nt": str(length),
        },
        qualifiers=qualifiers or {},
        decisions=decisions or {"is_poliovirus": "TRUE"},
        features=features,
    )


def feature(key: str, label: str = "", length: int = 0, text: str = "") -> dict[str, str]:
    return {"key": key, "label": label or key, "length": str(length), "text": text}


# --- the partition gate -----------------------------------------------------------------------


def test_a_non_poliovirus_record_is_a_determined_unknown_not_a_decline() -> None:
    """`record_type` was derived against Sabin coordinates, so no scope exists outside poliovirus.

    `unknown` is the value the release ships on all 14,217 of those rows. Declining instead would
    claim the question is open when the rule's own scope answers it.
    """
    outcome = sequence_scope(PARAMETERS, view(decisions={"is_poliovirus": "FALSE"}))
    assert outcome.value == "unknown"
    assert outcome.evidence_basis == BASIS_OUTSIDE_POLIOVIRUS
    assert outcome.resolved


# --- the cascade, in precedence order -----------------------------------------------------------


def test_genome_length_alone_is_a_complete_genome() -> None:
    outcome = sequence_scope(PARAMETERS, view(length=7440))
    assert outcome.value == "complete_genome"
    assert outcome.evidence_basis == BASIS_WHOLE_GENOME


def test_text_can_carry_a_complete_genome_below_the_length_floor() -> None:
    """The floor is a sufficient condition, not a necessary one."""
    outcome = sequence_scope(
        PARAMETERS, view(length=6800, definition="Poliovirus 1 complete genome")
    )
    assert outcome.value == "complete_genome"


def test_a_capsid_precursor_feature_outranks_a_vp1_one() -> None:
    outcome = sequence_scope(
        PARAMETERS,
        view(
            length=3000,
            features=(feature("CDS", "CDS P1 capsid precursor", 2500), feature("CDS", "VP1", 906)),
        ),
    )
    assert outcome.value == "capsid"
    assert outcome.evidence_basis == BASIS_CAPSID


def test_a_long_polyprotein_below_genome_length_is_the_capsid() -> None:
    """The upstream stage resolved a polyprotein by *length*, not by the feature."""
    outcome = sequence_scope(
        PARAMETERS, view(length=6500, features=(feature("CDS", "CDS polyprotein", 6200),))
    )
    assert outcome.value == "capsid"


def test_a_long_polyprotein_at_genome_length_is_the_genome() -> None:
    outcome = sequence_scope(
        PARAMETERS, view(length=7200, features=(feature("CDS", "CDS polyprotein", 6200),))
    )
    assert outcome.value == "complete_genome"


@pytest.mark.parametrize(
    ("organism", "vp1_length", "expected"),
    [
        # The floor is serotype-specific, and 903 is where that bites: a complete VP1 for type 2,
        # short of one for type 1. Record length is held at the feature length so the "is the whole
        # record bigger than a VP1" test below does not interfere.
        ("Poliovirus 1", 906, "vp1_complete"),
        ("Poliovirus 1", 903, "vp1_partial"),
        ("Poliovirus 2", 903, "vp1_complete"),
        ("Poliovirus 2", 900, "vp1_partial"),
        ("Poliovirus 3", 900, "vp1_complete"),
    ],
)
def test_the_vp1_floor_is_serotype_specific(organism: str, vp1_length: int, expected: str) -> None:
    outcome = sequence_scope(
        PARAMETERS,
        view(organism=organism, length=vp1_length, features=(feature("CDS", "VP1", vp1_length),)),
    )
    assert outcome.value == expected
    assert outcome.evidence_basis in {BASIS_VP1_COMPLETE, BASIS_VP1_PARTIAL}


def test_a_record_longer_than_a_vp1_is_not_a_vp1_fragment() -> None:
    """The `max(feature lengths, record length)` in the partial branch, which is easy to miss.

    A 1,200 nt record carrying a 903 nt VP1 is not a *partial* VP1 — it is something larger that
    contains a nearly-complete one, and upstream calls it `other`. Porting the branch without this
    line would turn every such record into `vp1_partial`. Found by writing this test, not by
    reading the code.
    """
    outcome = sequence_scope(
        PARAMETERS,
        view(organism="Poliovirus 1", length=1200, features=(feature("CDS", "VP1", 903),)),
    )
    assert outcome.value == "other_fragment"
    assert outcome.evidence_basis == BASIS_NO_REGION_NAMED


def test_named_non_capsid_regions_are_other_fragment() -> None:
    outcome = sequence_scope(
        PARAMETERS, view(length=600, definition="Poliovirus 1 5'UTR region")
    )
    assert outcome.value == "other_fragment"
    assert outcome.evidence_basis == BASIS_NON_VP1


# --- the branch that explains the 745 "errors" ---------------------------------------------------


def test_a_long_record_naming_no_region_is_other_fragment() -> None:
    """The finding that made this column look broken for months.

    745 records the release calls `other_fragment` have a complete VP1, capsid or genome by
    coverage. They are not mislabelled: the deposit names no region, so the final `else` is
    correct. `sequence_scope` says what a record claims to be, not how much of the genome it spans.
    Length alone cannot rescue it — only the 7000 nt genome floor above can, and this sits under it.
    """
    outcome = sequence_scope(PARAMETERS, view(length=6900, definition="Poliovirus 1 gene"))
    assert outcome.value == "other_fragment"
    assert outcome.evidence_basis == BASIS_NO_REGION_NAMED


def test_a_record_the_text_does_not_call_poliovirus_takes_the_default() -> None:
    """The upstream stage never ran its cascade on a text-negative record.

    308 rows depend on reproducing that rather than improving on it: the curated partition can say
    poliovirus where the deposit's own text does not, and the shipped column follows the text.
    """
    outcome = sequence_scope(
        PARAMETERS, view(organism="synthetic construct", length=7440, definition="")
    )
    assert outcome.value == "other_fragment"


def test_a_poliovirus_receptor_record_is_not_a_poliovirus_sequence() -> None:
    """`/host` CD155 deposits mention poliovirus and are not poliovirus. Upstream excluded them
    before anything else, and the order matters — the organism test below would otherwise admit
    some of them."""
    outcome = sequence_scope(
        PARAMETERS,
        view(organism="Homo sapiens", length=7440, definition="poliovirus receptor CD155 mRNA"),
    )
    assert outcome.value == "other_fragment"


def test_a_serotype_from_a_strain_name_is_honoured() -> None:
    """Leon fixes type 3 without a digit anywhere, so its VP1 floor is 900 rather than the
    unstated-serotype default — which happens to be the same number, so this pins the lookup path
    rather than the outcome."""
    outcome = sequence_scope(
        PARAMETERS,
        view(
            organism="Poliovirus 3",
            length=1000,
            qualifiers={"strain": "Leon 37"},
            features=(feature("CDS", "VP1", 900),),
        ),
    )
    assert outcome.value == "vp1_complete"
