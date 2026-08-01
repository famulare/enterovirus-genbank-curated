"""Isolate-linked classification inference: the whole-corpus pass, not the per-record rule.

`derive.isolate_linkage.apply_isolate_linked_inference` is a pure function over
(`views`, `provenance`), so it is testable directly with synthetic records rather than only
through a full corpus build — unlike `derive.classification.poliovirus_classification`, which
this repo tests only at the integration level (`test_metadata_transport.py`,
`test_sequence_evidence.py`). The corpus gate for this module lives here too, at the bottom.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from enterovirus_genbank_curated.build import build_metadata_layer
from enterovirus_genbank_curated.derive.classification import (
    BASIS_LEDGER,
    BASIS_SABIN_LIKE,
    BASIS_TEXT_FALLBACK,
    BASIS_TEXT_REFINEMENT,
    BASIS_VDPV,
    BASIS_WILD,
    UNRESOLVED_INSUFFICIENT_SEQUENCE,
    UNRESOLVED_NO_SEROTYPE,
)
from enterovirus_genbank_curated.derive.isolate_linkage import (
    CLASSIFICATION_FIELD,
    LINKED_BASIS,
    _same_batch,
    apply_isolate_linked_inference,
)
from enterovirus_genbank_curated.derive.outcome import RecordView

SEROTYPE_ORGANISM = "Human poliovirus 1"


def view(version: str, *, isolate: str = "", strain: str = "") -> RecordView:
    accession = version.split(".")[0]
    qualifiers = {}
    if isolate:
        qualifiers["isolate"] = isolate
    if strain:
        qualifiers["strain"] = strain
    return RecordView(
        version=version,
        accession=accession,
        record={"organism_name": SEROTYPE_ORGANISM},
        qualifiers=qualifiers,
        decisions={},
    )


def resolved_row(version: str, value: str, basis: str) -> dict[str, str]:
    return {
        "accession": version.split(".")[0],
        "version": version,
        "canonical_field": CLASSIFICATION_FIELD,
        "final_value": value,
        "source_field": "compared_nt",
        "source_value": "1.000% over 900 nt of VP1 vs AY184219.1",
        "winning_rule_id": "R-CLASS-2",
        "evidence_basis": basis,
        "manual_override": "FALSE",
        "unresolved_reason": "",
    }


def declined_row(version: str, reason: str = UNRESOLVED_INSUFFICIENT_SEQUENCE) -> dict[str, str]:
    return {
        "accession": version.split(".")[0],
        "version": version,
        "canonical_field": CLASSIFICATION_FIELD,
        "final_value": "",
        "source_field": "compared_nt",
        "source_value": "",
        "winning_rule_id": "R-CLASS-2",
        "evidence_basis": BASIS_SABIN_LIKE,
        "manual_override": "FALSE",
        "unresolved_reason": reason,
    }


def other_field_row(version: str) -> dict[str, str]:
    return {
        "accession": version.split(".")[0],
        "version": version,
        "canonical_field": "sample_origin",
        "final_value": "human",
        "source_field": "host",
        "source_value": "Homo sapiens",
        "winning_rule_id": "R-ORIGIN-2",
        "evidence_basis": "host_field",
        "manual_override": "FALSE",
        "unresolved_reason": "",
    }


def test_a_long_key_links_without_corroboration() -> None:
    """A structured isolate key over 3 alphanumeric characters is trusted on its own."""
    views = [
        view("AB000001.1", isolate="Cameroon2019-04512"),
        view("AB000002.1", isolate="Cameroon2019-04512"),
    ]
    provenance = [
        resolved_row("AB000001.1", "wild", BASIS_WILD),
        declined_row("AB000002.1"),
    ]
    result = apply_isolate_linked_inference(views, provenance)
    linked = next(row for row in result if row["version"] == "AB000002.1")
    assert linked["final_value"] == "wild"
    assert linked["evidence_basis"] == LINKED_BASIS
    assert not linked["unresolved_reason"]
    assert linked["source_value"] == "AB000001.1"


def test_a_short_key_declines_without_batch_corroboration() -> None:
    """`L1`-style keys recur across unrelated studies, so a bare match is not enough."""
    views = [
        view("AB000001.1", isolate="L1"),
        view("ZZ999999.1", isolate="L1"),
    ]
    provenance = [
        resolved_row("AB000001.1", "wild", BASIS_WILD),
        declined_row("ZZ999999.1"),
    ]
    result = apply_isolate_linked_inference(views, provenance)
    still_declined = next(row for row in result if row["version"] == "ZZ999999.1")
    assert still_declined["final_value"] == ""
    assert still_declined["unresolved_reason"] == UNRESOLVED_INSUFFICIENT_SEQUENCE


def test_a_short_key_links_with_batch_corroboration() -> None:
    """Same prefix, same digit width, within 200 accession numbers: MAD-VDPV's same-batch rule."""
    views = [
        view("AB000001.1", isolate="L1"),
        view("AB000050.1", isolate="L1"),
    ]
    provenance = [
        resolved_row("AB000001.1", "wild", BASIS_WILD),
        declined_row("AB000050.1"),
    ]
    result = apply_isolate_linked_inference(views, provenance)
    linked = next(row for row in result if row["version"] == "AB000050.1")
    assert linked["final_value"] == "wild"
    assert linked["evidence_basis"] == LINKED_BASIS


def test_disagreeing_siblings_decline_rather_than_guess() -> None:
    views = [
        view("AB000001.1", isolate="Cameroon2019-04512"),
        view("AB000002.1", isolate="Cameroon2019-04512"),
        view("AB000003.1", isolate="Cameroon2019-04512"),
    ]
    provenance = [
        resolved_row("AB000001.1", "wild", BASIS_WILD),
        resolved_row("AB000002.1", "VDPV", BASIS_VDPV),
        declined_row("AB000003.1"),
    ]
    result = apply_isolate_linked_inference(views, provenance)
    still_declined = next(row for row in result if row["version"] == "AB000003.1")
    assert still_declined["final_value"] == ""


@pytest.mark.parametrize("basis", [BASIS_LEDGER, BASIS_TEXT_FALLBACK])
def test_a_decision_or_a_text_guess_does_not_propagate(basis: str) -> None:
    """Measured, not guessed: a decision or the reference-title fallback is itself a step removed
    from a measurement, and propagating either would compound whichever one is wrong."""
    views = [
        view("AB000001.1", isolate="Cameroon2019-04512"),
        view("AB000002.1", isolate="Cameroon2019-04512"),
    ]
    provenance = [
        resolved_row("AB000001.1", "wild", basis),
        declined_row("AB000002.1"),
    ]
    result = apply_isolate_linked_inference(views, provenance)
    still_declined = next(row for row in result if row["version"] == "AB000002.1")
    assert still_declined["final_value"] == ""


def test_a_text_refinement_sibling_does_propagate() -> None:
    """Unlike the ledger and the fallback, a text refinement sits over a real measurement."""
    views = [
        view("AB000001.1", isolate="Cameroon2019-04512"),
        view("AB000002.1", isolate="Cameroon2019-04512"),
    ]
    provenance = [
        resolved_row("AB000001.1", "cVDPV", BASIS_TEXT_REFINEMENT),
        declined_row("AB000002.1"),
    ]
    result = apply_isolate_linked_inference(views, provenance)
    linked = next(row for row in result if row["version"] == "AB000002.1")
    assert linked["final_value"] == "cVDPV"


def test_a_sibling_declined_under_the_same_basis_name_does_not_count_as_firm() -> None:
    """`BASIS_SABIN_LIKE` is also the basis two *decline* branches use (no serotype; no
    divergence) — a declined sibling must not be read as an answer just because its basis name
    coincides with the resolved one."""
    views = [
        view("AB000001.1", isolate="Cameroon2019-04512"),
        view("AB000002.1", isolate="Cameroon2019-04512"),
    ]
    provenance = [
        declined_row("AB000001.1", reason=UNRESOLVED_NO_SEROTYPE),
        declined_row("AB000002.1"),
    ]
    result = apply_isolate_linked_inference(views, provenance)
    still_declined = next(row for row in result if row["version"] == "AB000002.1")
    assert still_declined["final_value"] == ""


def test_no_isolate_or_strain_key_declines() -> None:
    views = [view("AB000001.1")]
    provenance = [declined_row("AB000001.1")]
    result = apply_isolate_linked_inference(views, provenance)
    assert result == provenance


def test_strain_is_used_only_when_isolate_is_blank() -> None:
    views = [
        view("AB000001.1", strain="Cameroon2019-04512"),
        view("AB000002.1", isolate="Cameroon2019-04512"),
    ]
    provenance = [
        resolved_row("AB000001.1", "wild", BASIS_WILD),
        declined_row("AB000002.1"),
    ]
    result = apply_isolate_linked_inference(views, provenance)
    linked = next(row for row in result if row["version"] == "AB000002.1")
    assert linked["final_value"] == "wild"


def test_only_classification_rows_are_ever_touched() -> None:
    views = [
        view("AB000001.1", isolate="Cameroon2019-04512"),
        view("AB000002.1", isolate="Cameroon2019-04512"),
    ]
    provenance = [
        resolved_row("AB000001.1", "wild", BASIS_WILD),
        declined_row("AB000002.1"),
        other_field_row("AB000002.1"),
    ]
    result = apply_isolate_linked_inference(views, provenance)
    untouched = next(row for row in result if row["canonical_field"] == "sample_origin")
    assert untouched == other_field_row("AB000002.1")


def test_same_batch_matches_prefix_width_and_window() -> None:
    assert _same_batch("AB000050", ["AB000001"])
    assert not _same_batch("AB000350", ["AB000001"])  # outside the 200-accession window
    assert not _same_batch("AB50", ["AB000001"])  # different digit width
    assert not _same_batch("CD000050", ["AB000001"])  # different prefix
    assert not _same_batch("not-an-accession", ["AB000001"])


@pytest.mark.slow
def test_the_real_build_links_the_expected_population(repository_root: Path, tmp_path: Path) -> None:
    """Pinned so the linked population cannot silently grow or shrink between builds."""
    result = build_metadata_layer(repository_root, tmp_path)
    linked = [
        row
        for row in result.provenance
        if row["canonical_field"] == CLASSIFICATION_FIELD and row["evidence_basis"] == LINKED_BASIS
    ]
    assert len(linked) == 191
