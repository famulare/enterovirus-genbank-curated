"""Unit tests for the legacy-registry migration's guards.

The migration itself needs `--source-dir` pointing at a private repository, so CI can never run it
end to end. Its fail-closed behaviour is therefore tested here against synthetic inputs: the
disagreement raise, the truncation repair, the quote normalization, the D2 adjudication, the
release-baseline pin and the id assignment are all exercised without touching the private data.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from enterovirus_genbank_curated.contracts import ContractError


def load_migration(repository_root: Path) -> ModuleType:
    """Import the script by path; `scripts/` is not an installed package."""
    path = repository_root / "scripts/migrate_legacy_registries.py"
    spec = importlib.util.spec_from_file_location("migrate_legacy_registries", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mig(repository_root: Path) -> ModuleType:
    return load_migration(repository_root)


def decision(**overrides: str) -> dict[str, str]:
    row = {
        "decision_type": "manual_override",
        "subject_key": "AB000001",
        "accession": "AB000001",
        "field_name": "classification",
        "new_value": "wild",
        "reason": "because",
        "evidence_reference": "PMID:1",
        "confirmed_by": "Mike",
        "source_artifact": "manual_review_overrides.csv",
        "status": "active",
        "effective_from": "",
        "effective_through": "",
        "notes": "",
    }
    row.update(overrides)
    return row


# --- repair_spilled_reason ---------------------------------------------------------------------


def test_repair_rejoins_on_the_original_comma(mig: ModuleType) -> None:
    assert mig.repair_spilled_reason("[' fragment-filtered)']") == " fragment-filtered)"


def test_repair_preserves_empty_elements_so_no_comma_is_swallowed(mig: ModuleType) -> None:
    """Dropping a blank element would silently delete one of the curator's commas."""
    assert mig.repair_spilled_reason("['a', '', 'b']") == "a,,b"


def test_repair_refuses_a_payload_it_does_not_understand(mig: ModuleType) -> None:
    for payload in ("('a', 'b')", "{'a': 1}", "just text", "[oops"):
        with pytest.raises(ContractError):
            mig.repair_spilled_reason(payload)


def test_repair_refuses_a_list_of_non_strings(mig: ModuleType) -> None:
    with pytest.raises(ContractError, match="unexpected spilled reason payload"):
        mig.repair_spilled_reason("[1, 2]")


def test_repair_of_blank_is_blank(mig: ModuleType) -> None:
    assert mig.repair_spilled_reason("   ") == ""


# --- normalize_for_plain_tsv -------------------------------------------------------------------


def test_normalization_pairs_quotes(mig: ModuleType) -> None:
    got = mig.normalize_for_plain_tsv('says "circulating" here', where="x")
    assert got == "says “circulating” here"


def test_normalization_refuses_an_odd_quote_count(mig: ModuleType) -> None:
    with pytest.raises(ContractError, match="odd number"):
        mig.normalize_for_plain_tsv('one " quote', where="x")


def test_normalization_refuses_tabs_and_newlines(mig: ModuleType) -> None:
    for bad in ("a\tb", "a\nb", "a\rb"):
        with pytest.raises(ContractError, match="tab or newline"):
            mig.normalize_for_plain_tsv(bad, where="x")


def test_normalization_refuses_preexisting_typographic_quotes(mig: ModuleType) -> None:
    """Mixing would let pairing produce two opens and one close."""
    with pytest.raises(ContractError, match="already contains a typographic quote"):
        mig.normalize_for_plain_tsv('“a" b"', where="x")


def test_normalization_leaves_unquoted_text_untouched(mig: ModuleType) -> None:
    text = "tier3 engineered/lab — patent fragment (<50nt, fragment-filtered)"
    assert mig.normalize_for_plain_tsv(text, where="x") == text


# --- labelled / joined ------------------------------------------------------------------------


def test_labelled_names_each_attribute(mig: ModuleType) -> None:
    row = {"reference_label": "Sabin1", "serotype": "1", "blank": ""}
    got = mig.labelled(row, ("reference_label", "serotype", "blank"))
    assert got == "reference_label=Sabin1; serotype=1"


def test_labelled_refuses_values_that_would_make_it_ambiguous(mig: ModuleType) -> None:
    with pytest.raises(ContractError, match="ambiguous"):
        mig.labelled({"a": "x; y"}, ("a",))


def test_joined_refuses_multiple_prose_columns(mig: ModuleType) -> None:
    """Curator prose contains ';', so joining two prose columns is unsplittable."""
    with pytest.raises(ContractError, match="unsplittable"):
        mig.joined({"a": "x", "b": "y"}, ("a", "b"))


# --- resolve_duplicate_assertions -------------------------------------------------------------


def test_agreeing_duplicates_are_retired_by_declared_precedence(mig: ModuleType) -> None:
    rows = [
        decision(source_artifact="legacy_accession_classification_overrides.csv",
                 decision_type="legacy_classification_override"),
        decision(source_artifact="manual_review_overrides.csv"),
    ]
    mig.resolve_duplicate_assertions(rows)
    by_source = {r["source_artifact"]: r for r in rows}
    assert by_source["manual_review_overrides.csv"]["status"] == "active"
    legacy = by_source["legacy_accession_classification_overrides.csv"]
    assert legacy["status"] == "retired"
    assert "governed by manual_review_overrides.csv" in legacy["notes"]


def test_disagreeing_duplicates_raise_rather_than_apply_precedence(mig: ModuleType) -> None:
    """A scientific disagreement must reach a human, not be settled by a filename ranking."""
    rows = [
        decision(source_artifact="legacy_accession_classification_overrides.csv",
                 decision_type="legacy_classification_override", new_value="engineered"),
        decision(source_artifact="manual_review_overrides.csv", new_value="wild"),
    ]
    with pytest.raises(ContractError, match="registries disagree"):
        mig.resolve_duplicate_assertions(rows)


def test_duplicate_from_an_unranked_source_raises(mig: ModuleType) -> None:
    rows = [
        decision(source_artifact="date_review_overrides.csv", decision_type="date_override"),
        decision(source_artifact="manual_review_overrides.csv"),
    ]
    with pytest.raises(ContractError, match="no declared precedence"):
        mig.resolve_duplicate_assertions(rows)


def test_a_retired_row_does_not_block_a_later_duplicate_check(mig: ModuleType) -> None:
    """Only `active` rows compete, so retiring one must not mask a second clash."""
    rows = [decision(), decision(status="retired", new_value="engineered")]
    mig.resolve_duplicate_assertions(rows)
    assert [r["status"] for r in rows] == ["active", "retired"]


# --- apply_d2 ---------------------------------------------------------------------------------


def d2_baseline(mig: ModuleType) -> list[dict[str, str]]:
    rows = []
    for accession in mig.D2_ACCESSIONS:
        rows.append(decision(
            subject_key=accession, accession=accession,
            decision_type="legacy_classification_override", new_value="engineered",
            source_artifact="legacy_accession_classification_overrides.csv",
        ))
        rows.append(decision(subject_key=accession, accession=accession, new_value="wild"))
    return rows


def test_d2_supersedes_the_legacy_rows_and_adds_three(mig: ModuleType) -> None:
    rows = mig.apply_d2(d2_baseline(mig))
    superseded = [r for r in rows if r["status"] == "superseded"]
    added = [r for r in rows if r["source_artifact"] == mig.D2_SOURCE]
    assert len(superseded) == 3
    assert len(added) == 3
    assert all(r["notes"].startswith("superseded") for r in superseded)
    assert not any(r["notes"].startswith("superseded") for r in added)


def test_d2_added_rows_inherit_nothing_from_a_neighbour(mig: ModuleType) -> None:
    """An earlier version spread `{**anchor}`, attributing a 2026 call to a registry file."""
    rows = mig.apply_d2(d2_baseline(mig))
    for row in (r for r in rows if r["source_artifact"] == mig.D2_SOURCE):
        assert row["field_name"] == "engineered_or_construct"
        assert row["new_value"] == "FALSE"
        assert row["reason"] != "because", "inherited the neighbour's reason"
        assert row["evidence_reference"] == mig.D2_EVIDENCE
        assert row["status"] == "active"


def test_d2_is_independent_of_registry_row_order(mig: ModuleType) -> None:
    forward = mig.apply_d2(d2_baseline(mig))
    reversed_rows = mig.apply_d2(list(reversed(d2_baseline(mig))))
    key = lambda rows: sorted(  # noqa: E731 - local comparison helper
        tuple(sorted(r.items())) for r in rows if r["source_artifact"] == mig.D2_SOURCE
    )
    assert key(forward) == key(reversed_rows)


def test_d2_raises_if_the_legacy_rows_are_absent(mig: ModuleType) -> None:
    with pytest.raises(ContractError, match="expected to supersede"):
        mig.apply_d2([decision()])


# --- apply_dq205099_annotation ------------------------------------------------------------------


def dq_row(mig: ModuleType, **overrides: str) -> dict[str, str]:
    row = decision(
        subject_key=mig.DQ205099_ACCESSION, accession=mig.DQ205099_ACCESSION,
        decision_type="legacy_classification_override", new_value="engineered",
        source_artifact="legacy_accession_classification_overrides.csv",
    )
    row.update(overrides)
    return row


def test_the_annotation_adds_a_note_and_changes_nothing_else(mig: ModuleType) -> None:
    """The whole point of the DQ205099 disposition: marked, not overturned."""
    before = dq_row(mig)
    rows = mig.apply_dq205099_annotation([dict(before)])
    assert len(rows) == 1, "the annotation must not add a decision row"
    after = rows[0]
    assert after["notes"] == mig.DQ205099_NOTE
    for column, value in before.items():
        if column != "notes":
            assert after[column] == value, f"{column} changed"


def test_the_annotation_preserves_the_curators_raw_reason(mig: ModuleType) -> None:
    """D1 carries what the author typed. The note corrects the record; the reason field does not."""
    raw = "miscoded. This is codon-deoptimized Sabin2: https://example.invalid/patent"
    after = mig.apply_dq205099_annotation([dq_row(mig, reason=raw)])[0]
    assert after["reason"] == raw


def test_the_annotation_appends_rather_than_overwriting_an_existing_note(mig: ModuleType) -> None:
    after = mig.apply_dq205099_annotation([dq_row(mig, notes="attr=1")])[0]
    assert after["notes"] == f"attr=1; {mig.DQ205099_NOTE}"


def test_the_annotation_raises_when_its_subject_is_absent(mig: ModuleType) -> None:
    """A renamed or re-exported legacy file must fail loudly, not drop the note silently."""
    with pytest.raises(ContractError, match="expected exactly one legacy engineered row"):
        mig.apply_dq205099_annotation([decision()])


def test_the_annotation_raises_on_more_than_one_candidate(mig: ModuleType) -> None:
    with pytest.raises(ContractError, match="found 2"):
        mig.apply_dq205099_annotation([dq_row(mig), dq_row(mig)])


def test_the_annotation_refuses_to_run_twice(mig: ModuleType) -> None:
    """Appending the note again would read as a second, corroborating judgment."""
    once = mig.apply_dq205099_annotation([dq_row(mig)])
    with pytest.raises(ContractError, match="already annotated"):
        mig.apply_dq205099_annotation(once)


def test_the_annotation_refuses_a_row_that_was_overturned(mig: ModuleType) -> None:
    """The note asserts the label was upheld, so it must not land on a superseded row.

    Not reachable by mutating the real migration — making D2 cover DQ205099 trips D2's own anchor
    check first — so the guard is exercised directly here rather than left unproven.
    """
    with pytest.raises(ContractError, match="not active"):
        mig.apply_dq205099_annotation([dq_row(mig, status="superseded")])


# A `test_the_annotation_records_the_evidence_it_claims_to` checked seven phrases against
# `mig.DQ205099_NOTE`, this module's own constant. Removed 2026-07-30: asserting a string against
# itself pins a figure to its own spelling, which is the anti-pattern recorded at
# `tests/test_legacy_registry.py`'s divergence test. The same seven phrases are checked against the
# *shipped ledger* in `test_the_fourth_engineered_call_is_annotated_and_still_active`, and the
# `3 nt/7439` figure is recomputed from `final/canonical/sequences.fasta.gz` in
# `test_the_stated_divergences_are_recomputable_from_the_shipped_sequences`, which additionally
# requires a ledger row to state the measured value. Two checks with contact to data outrank a third
# with none.


# --- assign_ids -------------------------------------------------------------------------------


def test_ids_are_content_derived_and_suffixed_on_collision(mig: ModuleType) -> None:
    """Two rows differing only in reason share an identity tuple, so one takes a `-2` suffix."""
    import hashlib

    rows = mig.assign_ids([decision(reason="first"), decision(reason="second")])
    digest = hashlib.sha256(
        "|".join(rows[0][c] for c in mig.ID_COLUMNS).encode("utf-8")
    ).hexdigest()[:12]
    assert sorted(r["decision_id"] for r in rows) == [f"D-{digest}", f"D-{digest}-2"]


def test_ids_differ_when_the_asserted_value_differs(mig: ModuleType) -> None:
    rows = mig.assign_ids([decision(new_value="wild"), decision(new_value="engineered")])
    assert len({r["decision_id"] for r in rows}) == 2


def test_ids_do_not_depend_on_input_order(mig: ModuleType) -> None:
    rows = [decision(reason="a"), decision(field_name="serotype", new_value="2")]
    forward = {r["decision_id"] for r in mig.assign_ids(list(rows))}
    backward = {r["decision_id"] for r in mig.assign_ids(list(reversed(rows)))}
    assert forward == backward


# --- assert_release_baseline ---------------------------------------------------------------------
#
# The private repository is a live working tree, so "re-run the migration" is not a repeatable
# operation over time. New rows there are well-formed and migrate cleanly, which is why the drift is
# silent and has to be checked by count rather than by validity.


def test_the_baseline_pin_passes_on_the_release_era_count(mig: ModuleType) -> None:
    rows = [decision(subject_key=f"AB{n:06d}") for n in range(mig.EXPECTED_BASELINE_DECISIONS)]
    assert mig.assert_release_baseline(rows) is rows


def test_the_baseline_pin_refuses_a_source_that_gained_decisions(mig: ModuleType) -> None:
    """The observed 2026-07-29 case: two `date_override` rows appeared mid-session."""
    rows = [decision(subject_key=f"AB{n:06d}") for n in range(mig.EXPECTED_BASELINE_DECISIONS + 2)]
    with pytest.raises(ContractError) as caught:
        mig.assert_release_baseline(rows)
    message = str(caught.value)
    assert str(mig.EXPECTED_BASELINE_DECISIONS + 2) in message
    assert str(mig.EXPECTED_BASELINE_DECISIONS) in message
    assert "--allow-baseline-drift" in message, "the message must say how to proceed deliberately"


# Two thinner variants were removed on 2026-07-30 — `-1` rows, and `allow_drift=True` accepting a
# drifted count. The two above already bracket the guard from both sides, the second against the
# real observed drift rather than a synthetic one; the `-1` case exercised the same inequality as
# `+2`, and the override case asserted only that a flag documented as "deliberately awkward" does
# what its name says.


def test_the_pinned_baseline_matches_the_committed_ledger(
    mig: ModuleType, repository_root: Path
) -> None:
    """The pin and the shipped artifact must describe the same release.

    This used to assert `EXPECTED_BASELINE_DECISIONS + len(D2_ACCESSIONS) == 2756` — an arithmetic
    identity among two module constants and a literal in this file, which opens no artifact and so
    stays green through exactly the drift it claims to catch. It now counts the committed ledger.
    """
    with (repository_root / "registry/decisions.tsv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    carried = len(mig.SUPERSEDED_CARRY_FORWARD)
    expected = mig.EXPECTED_BASELINE_DECISIONS + len(mig.D2_ACCESSIONS) + carried
    assert len(rows) == expected, (
        f"registry/decisions.tsv holds {len(rows)} decisions but the migration is pinned to "
        f"{mig.EXPECTED_BASELINE_DECISIONS} baseline + {len(mig.D2_ACCESSIONS)} D2 additions + "
        f"{carried} carried-forward supersessions = {expected}. Bumping one without the others is "
        f"the drift the pin exists to catch."
    )


def test_the_shipped_ledger_carries_the_current_d2_evidence(
    mig: ModuleType, repository_root: Path
) -> None:
    """The committed artifact must match the generator that claims to produce it.

    Nothing checked this, which is how the `7435`->`7439` correction reached the module docstring
    and both READMEs while `D2_EVIDENCE` — the string actually written into the ledger — kept the
    old figure. Editing the constant without regenerating, or hand-editing the ledger, fails here.
    """
    with (repository_root / "registry/decisions.tsv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    added = [
        row for row in rows
        if row["source_artifact"] == mig.D2_SOURCE
        and row["field_name"] == "engineered_or_construct"
    ]
    assert len(added) == len(mig.D2_ACCESSIONS), added
    for row in added:
        assert row["evidence_reference"] == mig.D2_EVIDENCE, (
            f"{row['subject_key']}: the shipped evidence_reference is not the current "
            f"D2_EVIDENCE. Regenerate the ledger, or revert the constant."
        )
        assert row["notes"] == mig.D2_ADDED_NOTE, row["subject_key"]

    superseded = [
        row for row in rows
        if row["subject_key"] in mig.D2_ACCESSIONS and row["status"] == "superseded"
    ]
    assert len(superseded) == len(mig.D2_ACCESSIONS), superseded
    for row in superseded:
        assert row["notes"] == mig.D2_SUPERSEDED_NOTE, row["subject_key"]

    assert "7435" not in mig.D2_EVIDENCE, (
        "the Sabin-frame denominator is the curator's, carried verbatim in `reason` under D1. "
        "Migration-authored evidence states the pairwise figure this repository can reproduce."
    )
