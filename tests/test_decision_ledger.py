"""The committed ledger must be internally coherent, and account for every difference it declares.

`registry/decisions.tsv` is the authority for human curation.

**Four tests retired on 2026-08-01**, when `final/` became this pipeline's own destination and the
2.4.1 audit views it overwrote were deleted: `test_no_shipped_decision_was_lost`,
`test_every_addition_is_an_approved_one`,
`test_decision_type_counts_match_except_the_approved_additions` and
`test_ledger_reproduces_every_shipped_column_not_just_the_key` all read
`final/audit/manual_decisions.tsv.gz`, the release's synthesized copy of the same assertions.

That was the migration gate — it established, once, that the resync dropped nothing and that every
ledger-only row was an approved addition. It cannot be re-established from this tree, and the
artifact is not carried: it is recoverable from git history (last present at `1ecb937`) if the
reconciliation ever needs re-running. The allowlists it validated — `LEDGER_ONLY_ADDITIONS`,
`SUPERSEDED_CARRY_FORWARD_ADDITIONS`, the counts below — are still checked against the ledger
itself by the tests that remain.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import re
from collections import Counter
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import DecisionContract, validate_decision_ledger

csv.field_size_limit(10**9)

LEDGER = "registry/decisions.tsv"

# Every difference from the 2,912 shipped decisions of release 2.4.1, enumerated. A test that
# merely counted rows would pass with the wrong rows.
#
# Re-pinned from the 2,800 of release 2.3.0 on 2026-07-30, when the ledger was resynced a second
# time (release 2.1.5's original resync shipped 2,753). The resync is exact in the direction that
# matters: zero shipped assertions are absent from the ledger. The ledger-only rows are these three
# enumerated sets and nothing else.
D2_ADDITIONS = {
    ("CS406436", "engineered_or_construct", "FALSE"),
    ("CS406482", "engineered_or_construct", "FALSE"),
    ("CS406483", "engineered_or_construct", "FALSE"),
}

# Assertions the resync would otherwise have deleted: the curator revised AB180070-73 from iVDPV to
# cVDPV in the same registry, and because `decision_id` hashes `new_value`, a regeneration mints new
# ids and leaves the old rows with no source to be re-emitted from. `SUPERSEDED_CARRY_FORWARD` in
# the migration re-adds them as `superseded` so the reversal stays legible instead of vanishing.
SUPERSEDED_CARRY_FORWARD_ADDITIONS = {
    (accession, "classification", "iVDPV")
    for accession in ("AB180070", "AB180071", "AB180072", "AB180073")
} | {
    # JC013129: the 2.4.1 same-sequence-coherence fix reclassified this record (wild, human),
    # overturning both fields' prior values. Same carry-forward mechanism, added at the 2.4.1
    # resync. NOT a third field for engineered_or_construct=TRUE: the current registry no longer
    # asserts that field at all (rather than asserting a contradicting value), so there is no
    # active successor to carry it forward against -- see scripts/migrate_legacy_registries.py's
    # SUPERSEDED_CARRY_FORWARD comment for why that is a legitimate, harmless gap rather than a
    # silent loss (the shipped value is unchanged).
    ("JC013129", "classification", "engineered/lab"),
    ("JC013129", "origin_class", "non-human"),
}
# The two rows landed on 2026-07-31 when `docs/engineered-full-population-readjudication.md`'s
# remediation was applied alongside R-CONSTRUCT-2. CS406483's TRUE replaces its own superseded FALSE
# (`decision_id` hashes `new_value`, so a corrected value is a new row); PU749298's is the byte-
# identical twin, which the report found had no row at all. Both trace to the curator's Q2 answer.
ENGINEERED_READJUDICATION_ADDITIONS = {
    ("CS406483", "engineered_or_construct", "TRUE"),
    ("PU749298", "engineered_or_construct", "TRUE"),
}

# The CAVA cold-adaptation pair, decided 2026-07-31. Appendix B of the same re-adjudication left
# these two open in either direction, and the curator resolved them FALSE on the precedent already
# set inside patent WO2006042156: a parental deposit is FALSE (CS406436, CS406482) and only the
# constructed product is TRUE (CS406483). LY501105/LZ216100 are the CAVA patent's parental controls
# on that reading and LY501107/LZ216102 its cold-adapted products.
#
# These are the rows R-CONSTRUCT-2 was declining, so `UNRESOLVED_ENGINEERED_ROWS` goes to zero with
# them.
CAVA_PARENTAL_ADDITIONS = {
    ("LY501105", "engineered_or_construct", "FALSE"),
    ("LZ216100", "engineered_or_construct", "FALSE"),
}

# Three rows landed 2026-07-31 to repair the only three active assertions whose value was outside
# `poliovirus_classification`'s controlled vocabulary, which `derive.classification` was therefore
# declining rather than shipping: `CHAT` (the Koprowski strain name, not a tier), a bare
# `engineered` (the vocabulary has only `engineered/lab`), and `iVPDV` (a transposition of `iVDPV`).
# The release masked all three by projecting a reconciled field instead of the ledger.
#
# Each is a *repair*, not a reversal: the verdict the curator recorded is carried forward and only
# the token changes. They are nonetheless `superseded` rather than `retired`, because a retired row
# whose value disagrees with its active successor is what
# `test_retired_rows_agree_with_the_decision_that_governs_them` calls a buried conflict — the same
# reasoning that put CS406483's reversal under `superseded`.
VOCABULARY_REPAIR_ADDITIONS = {
    ("AJ416942", "classification", "vaccine"),
    ("DQ205099", "classification", "engineered/lab"),
    ("FJ517648", "classification", "iVDPV"),
}

LEDGER_ONLY_ADDITIONS = (
    D2_ADDITIONS
    | SUPERSEDED_CARRY_FORWARD_ADDITIONS
    | ENGINEERED_READJUDICATION_ADDITIONS
    | CAVA_PARENTAL_ADDITIONS
    | VOCABULARY_REPAIR_ADDITIONS
)

# 115 rows landed 2026-07-31, the same day and under the same `source_artifact` as the vocabulary
# repairs and the CAVA parental pair above but a different act: not a repair of a malformed value
# and not an engineered_or_construct call, a curation decision closing a classification gap traced
# by reading MAD-VDPV's own working tree. Not enumerated as 115 literal tuples, for the same reason
# the VDPV_SOURCE allowlist below is not: identified by `source_artifact`, excluding the 3
# vocabulary-repair and 2 CAVA-parental subjects that share it, and pinned by count, value
# distribution, and agreement with the shipped column — a fabricated or altered row fails against
# `final/`, not against a list this file could also have been edited to accept.
#
# 95 are the cVDPV epidemiological override: two published studies whose circulation claim lives in
# the paper, not in any deposit's own text — Cameroon (PMID 25542478, 27 records) and European
# wastewater 2024 (PMID 39850005 on 20 of 68). 20 are strain-identity/provenance decisions
# divergence alone cannot make: 12 `Sabin` (seed-strain deposits, including this pipeline's own
# three canonical references AY184219/220/221), 5 `vaccine` (the documented Cox/Lederle/CHAT family
# map), 3 `engineered/lab` (patent JP 2009538603-A). See `docs/classification-migration-gap.md`.
#
# 28 more landed the same day, same `source_artifact`, closing the largest remaining discrepancy
# block (`declined_too_little_sequence`) the same way: 24 `reference_or_lab_text` records traced by
# MAD-VDPV's own working tree to strain-identity/patent evidence too short to ever reach a
# divergence measurement (12 `Sabin`, 10 `engineered/lab`, 1 `recombinant/lab`, 1 `reference/lab`),
# and 4 more `group_A_text_owned` `cVDPV` records. Folded into the same population rather than a
# second one: same act (a curation decision closing a text-derived classification gap), same source,
# same day.
CVDPV_AND_STRAIN_IDENTITY_SOURCE = "curator_adjudication_2026-07-31"
EXPECTED_CVDPV_AND_STRAIN_IDENTITY_ROWS = 115 + 28
# The other two populations sharing `CVDPV_AND_STRAIN_IDENTITY_SOURCE`, so every filter against it
# excludes both rather than trusting each call site to remember both exclusions separately.
NON_CVDPV_CURATOR_ADJUDICATION_2026_07_31_SUBJECTS = {
    subject for subject, _, _ in VOCABULARY_REPAIR_ADDITIONS
} | {subject for subject, _, _ in CAVA_PARENTAL_ADDITIONS}
EXPECTED_CVDPV_AND_STRAIN_IDENTITY_VALUES = {
    "cVDPV": 95 + 4,
    "Sabin": 12 + 12,
    "vaccine": 5,
    "engineered/lab": 3 + 10,
    "recombinant/lab": 1,
    "reference/lab": 1,
}

# The locked VDPV/wild reconciliation allowlist, migrated 2026-07-30 by
# `scripts/migrate_vdpv_reconciliation.py`. These are not enumerated as 243 literal tuples; they are
# identified by `source_artifact` and then pinned three ways — count, value distribution, and
# agreement with the shipped canonical column. Deriving the *membership* from the ledger would be
# self-certifying on its own, which is why the third pin is the load-bearing one: every row has to
# match what the release already ships, so a fabricated or altered row fails against `final/` rather
# than against a list this file could also have been edited to accept.
VDPV_SOURCE = "vdpv_wild_reconciliation.csv"
EXPECTED_VDPV_ROWS = 243
EXPECTED_VDPV_VALUES = {"wild": 237, "VDPV": 6}
CANONICAL_METADATA = "final/canonical/sequence_metadata.tsv.gz"

# 162 rows were retired on 2026-07-30 because a *rule* now derives their value, not because another
# decision replaced them. That is a second meaning for `retired` and the reason the invariant below
# had to be split.
RULE_REDUNDANT_RETIREMENTS = 162

# A third meaning for `retired`, landed 2026-07-31: an adjudication overturned the assertion. Four
# rows, all `engineered_or_construct` TRUEs — `AJ512791`/`AJ512792` (Appendix B Q8, a wild PV1
# contaminant is not engineered) and `DD214215`/`DD214221` (Q4, a defective-interfering particle is
# not engineered). Unlike the 162 these have no successor and no rule deriving the same value: the
# value itself is now different, which is why they are counted apart.
ADJUDICATION_RETIREMENTS = 4

# Two rows added the same day, and one status move: CS406483's FALSE becomes `superseded` by the
# TRUE that replaces it, so `active` gains 2 and loses 1.
ENGINEERED_READJUDICATION_NET_ACTIVE = len(ENGINEERED_READJUDICATION_ADDITIONS) - 1
# The vocabulary repairs are net-zero on `active`: each new row replaces one it supersedes, so the
# three arrive and three leave. Stated as an explicit zero rather than omitted, because "this
# addition does not move the active count" is the claim being made.
VOCABULARY_REPAIR_NET_ACTIVE = len(VOCABULARY_REPAIR_ADDITIONS) - len(VOCABULARY_REPAIR_ADDITIONS)
# Every record the build still declines a partition for, filled from the upstream release's own
# `virus_group` (2026-08-01). Not a curator adjudication and not a migrated registry, so it carries
# its own `source_artifact` rather than borrowing either vocabulary.
UPSTREAM_PARTITION_SOURCE = "upstream_partition_projection_2026-08-01"
EXPECTED_UPSTREAM_PARTITION_ROWS = 1379

# The six the upstream projection could not reach, because upstream has no row for them either:
# `A08076` and `HW505760`/`61`/`72`/`73`/`74`, patent deposits of 70-100 nt — far below the 50
# compared codons R-MEMBERSHIP-AA-1's capsid-AA band needs, so every predicate declines. The
# sequence settles it: `A08076` is 99.0% identical over its full length to the Sabin 1 reference
# `AY184219.1`, and the five `HW*` fragments align at position 469 of the Sabin 3 reference
# `AY184221.1` at 85.7-100% (`HW505772` is an exact substring). Their own definitions say so too —
# "DNA sequence type PV1" and JP patent "INACTIVATED POLIOVACCINE".
#
# Separate `source_artifact` from the projection above because the basis is different in kind:
# that one adopts another release's assignment, this one measures the deposited sequence.
SHORT_PATENT_MEMBERSHIP_SOURCE = "short_patent_deposit_sequence_membership_2026-08-01"
EXPECTED_SHORT_PATENT_MEMBERSHIP_ROWS = 6

EXPECTED_STATUS = {
    "active": (
        2895
        + EXPECTED_UPSTREAM_PARTITION_ROWS
        + EXPECTED_SHORT_PATENT_MEMBERSHIP_ROWS
        + EXPECTED_VDPV_ROWS
        - RULE_REDUNDANT_RETIREMENTS
        - ADJUDICATION_RETIREMENTS
        + ENGINEERED_READJUDICATION_NET_ACTIVE
        + len(CAVA_PARENTAL_ADDITIONS)
        + VOCABULARY_REPAIR_NET_ACTIVE
        + EXPECTED_CVDPV_AND_STRAIN_IDENTITY_ROWS
    ),
    "retired": 17 + RULE_REDUNDANT_RETIREMENTS + ADJUDICATION_RETIREMENTS,
    "superseded": 10 + len(VOCABULARY_REPAIR_ADDITIONS),
}

# `decision_id` is a digest of exactly these, in this order — `source_artifact` deliberately absent
# so a registry rename does not rehash every id.
ID_COLUMNS = ("decision_type", "subject_key", "field_name", "new_value")

# The six reasons the release shipped truncated, because an earlier tool split the note on a comma
# and stringified the remainder into an unnamed column. These are the only rows whose text may
# differ from the release, and only by holding MORE of it.
REPAIRED_ACCESSIONS = {"A27232", "A27233", "DI499165", "KY748286", "S72981", "S72984"}


def assertion_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (row["subject_key"], row["field_name"], row["new_value"])


@pytest.fixture(scope="module")
def ledger(repository_root: Path) -> list[dict[str, str]]:
    with (repository_root / LEDGER).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL))


def test_ledger_satisfies_its_own_contract(
    repository_root: Path, decision_contract: DecisionContract
) -> None:
    summary = validate_decision_ledger(repository_root / LEDGER, decision_contract)
    assert (
        summary.rows
        == 3164
        + len(ENGINEERED_READJUDICATION_ADDITIONS)
        + len(CAVA_PARENTAL_ADDITIONS)
        + len(VOCABULARY_REPAIR_ADDITIONS)
        + EXPECTED_CVDPV_AND_STRAIN_IDENTITY_ROWS
        + EXPECTED_UPSTREAM_PARTITION_ROWS
        + EXPECTED_SHORT_PATENT_MEMBERSHIP_ROWS
    )
    assert summary.active_rows == EXPECTED_STATUS["active"]


def test_status_distribution_is_exactly_as_documented(ledger: list[dict[str, str]]) -> None:
    assert Counter(r["status"] for r in ledger) == Counter(EXPECTED_STATUS)


def test_the_reconciliation_allowlist_agrees_with_the_shipped_column(
    repository_root: Path, ledger: list[dict[str, str]]
) -> None:
    """The migrated allowlist records curation that is *already applied*, and this proves it.

    That distinction is the whole reason these 243 rows are safe to add without adjudicating each
    one. A ledger assertion the release contradicts is the D2 failure mode; a ledger assertion the
    release already reflects is history being captured. If any row disagreed, the migration would
    have introduced a pending delta nobody decided on.
    """
    rows = [r for r in ledger if r["source_artifact"] == VDPV_SOURCE]
    assert len(rows) == EXPECTED_VDPV_ROWS
    assert Counter(r["new_value"] for r in rows) == Counter(EXPECTED_VDPV_VALUES)
    assert {r["field_name"] for r in rows} == {"classification"}
    assert {r["status"] for r in rows} == {"active"}

    with gzip.open(
        repository_root / CANONICAL_METADATA, "rt", encoding="utf-8", newline=""
    ) as handle:
        shipped = {
            r["accession"]: r["poliovirus_classification"]
            for r in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        }
    disagreements = {
        r["accession"]: (r["new_value"], shipped.get(r["accession"]))
        for r in rows
        if shipped.get(r["accession"]) != r["new_value"]
    }
    assert not disagreements, (
        f"allowlist rows the release does not already reflect: {disagreements}"
    )


def test_the_cvdpv_and_strain_identity_decisions_agree_with_the_shipped_column(
    repository_root: Path, ledger: list[dict[str, str]]
) -> None:
    """Same shape as the VDPV/wild allowlist above, for the 2026-07-31 additions.

    Every one of these 143 values was chosen because 2.4.1 already ships it; the two published
    studies behind the 99 cVDPV rows, the strain-identity reasoning behind the 24 `Sabin`, and the
    patent/reference-lab evidence behind the rest are the *why*, and this is the check that the
    *what* is not a fabrication — a wrong row here fails against `final/`, the same load-bearing
    property the VDPV allowlist check has.
    """
    rows = [
        r
        for r in ledger
        if r["source_artifact"] == CVDPV_AND_STRAIN_IDENTITY_SOURCE
        and r["subject_key"] not in NON_CVDPV_CURATOR_ADJUDICATION_2026_07_31_SUBJECTS
    ]
    assert len(rows) == EXPECTED_CVDPV_AND_STRAIN_IDENTITY_ROWS
    assert Counter(r["new_value"] for r in rows) == Counter(
        EXPECTED_CVDPV_AND_STRAIN_IDENTITY_VALUES
    )
    assert {r["field_name"] for r in rows} == {"classification"}
    assert {r["status"] for r in rows} == {"active"}

    with gzip.open(
        repository_root / CANONICAL_METADATA, "rt", encoding="utf-8", newline=""
    ) as handle:
        shipped = {
            r["accession"]: r["poliovirus_classification"]
            for r in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        }
    disagreements = {
        r["accession"]: (r["new_value"], shipped.get(r["accession"]))
        for r in rows
        if shipped.get(r["accession"]) != r["new_value"]
    }
    assert not disagreements, f"decisions the release does not already reflect: {disagreements}"


def test_decision_ids_are_unique_without_source_artifact_in_the_hash(
    ledger: list[dict[str, str]],
) -> None:
    """Dropping source_artifact from the identity could have collided assertions; it did not."""
    ids = [r["decision_id"] for r in ledger]
    assert len(set(ids)) == len(ids)


def test_no_two_active_decisions_govern_the_same_subject_and_field(
    ledger: list[dict[str, str]],
) -> None:
    active = [r for r in ledger if r["status"] == "active"]
    pairs = Counter((r["subject_key"], r["field_name"]) for r in active)
    clashes = {k: n for k, n in pairs.items() if n > 1}
    assert clashes == {}, f"ambiguous governing decisions: {clashes}"


def test_retired_rows_agree_with_the_decision_that_governs_them(
    ledger: list[dict[str, str]],
) -> None:
    """`retired` means "redundant", so a retired row must NOT contradict what now governs it.

    A retired row whose value differed would be a silently buried conflict — exactly what the status
    vocabulary is supposed to prevent.

    **`retired` now carries two meanings** and this test assumed only the first. Originally it meant
    "another decision replaced this one", so every retired row had an active counterpart. As of
    2026-07-30 it also means "a rule now derives this value", where there is no counterpart to point
    at — 162 such rows, retired precisely because `decision_applications` showed them as
    `applied_unchanged`. Those are checked differently: not against another ledger row, but by the
    fact that retiring them moved no canonical value, which `oracle/parity.py`'s unchanged
    `final_value` witness digests establish over the whole corpus.
    """
    governing = {
        (r["subject_key"], r["field_name"]): r["new_value"]
        for r in ledger
        if r["status"] == "active"
    }
    superseded_by_a_decision = 0
    superseded_by_a_rule = 0
    for row in ledger:
        if row["status"] != "retired":
            continue
        key = (row["subject_key"], row["field_name"])
        if key not in governing:
            superseded_by_a_rule += 1
            continue
        superseded_by_a_decision += 1
        assert row["new_value"] == governing[key], (
            f"retired {row['decision_id']} contradicts the active decision "
            f"({row['new_value']!r} vs {governing[key]!r}) — that is a conflict, not redundancy"
        )

    # All three populations pinned, so a row cannot drift from one meaning to another unnoticed.
    assert superseded_by_a_rule == RULE_REDUNDANT_RETIREMENTS + ADJUDICATION_RETIREMENTS
    assert superseded_by_a_decision == 17


def test_superseded_rows_are_only_the_adjudicated_conflict(ledger: list[dict[str, str]]) -> None:
    """Three distinct causes of supersession, asserted separately so none can absorb another.

    D2 overturned a legacy `classification=engineered` call on evidence. The AB180070-73 rows are a
    curator revision preserved through the 2.3.0 resync that would otherwise have deleted them.
    JC013129's two rows are a curator revision preserved through the 2.4.1 resync, same shape. All
    three must record *why*, but they say different things and are not interchangeable.

    The vocabulary repairs are partitioned out *first*: DQ205099's superseded row is also a
    `classification=engineered`, so a D2 filter written on value alone would swallow it and report
    four D2 subjects. Selecting by subject keeps the five classes disjoint.
    """
    superseded = [r for r in ledger if r["status"] == "superseded"]
    # Fifth cause, 2026-07-31: the value was outside the controlled vocabulary and a repair replaced
    # it. Distinguished from every class below by what it does NOT claim — no verdict was
    # overturned, so the note must say the judgement is carried forward rather than name evidence
    # against it.
    repair_subjects = {subject for subject, _, _ in VOCABULARY_REPAIR_ADDITIONS}
    repaired_vocabulary = [r for r in superseded if r["subject_key"] in repair_subjects]
    remainder = [r for r in superseded if r["subject_key"] not in repair_subjects]
    d2 = [
        r
        for r in remainder
        if r["field_name"] == "classification" and r["new_value"] == "engineered"
    ]
    carried = [r for r in remainder if r["new_value"] == "iVDPV"]
    jc013129 = [r for r in remainder if r["subject_key"] == "JC013129"]
    # Fourth cause, 2026-07-31: the re-adjudication reversed a value rather than retiring it. One
    # row. It is a supersession and not a retirement precisely because the check above would call a
    # retired row disagreeing with its active successor a buried conflict — which it would be.
    reversed_value = [
        r for r in remainder if r["field_name"] == "engineered_or_construct"
    ]
    assert len(d2) + len(carried) + len(jc013129) + len(reversed_value) + len(
        repaired_vocabulary
    ) == len(superseded), "an unexplained supersession class appeared"

    assert {r["subject_key"] for r in repaired_vocabulary} == repair_subjects
    for row in repaired_vocabulary:
        assert row["field_name"] == "classification"
        assert row["new_value"] in {"CHAT", "engineered", "iVPDV"}, (
            "a repair supersedes an out-of-vocabulary value; this one was already valid"
        )
        assert "superseded 2026-07-31 by classification=" in row["notes"], (
            "a repair must name the value that replaced it"
        )
        assert "unchanged" in row["notes"], (
            "a vocabulary repair must record that the verdict was carried forward, not overturned"
        )
    assert {r["subject_key"] for r in reversed_value} == {"CS406483"}
    for row in reversed_value:
        assert row["new_value"] == "FALSE"
        assert "rules out" in row["notes"], "a supersession must record why it was overturned"

    assert {r["subject_key"] for r in d2} == {"CS406436", "CS406482", "CS406483"}
    for row in d2:
        assert "rules out" in row["notes"], "a supersession must record why it was overturned"

    assert {r["subject_key"] for r in carried} == {
        "AB180070",
        "AB180071",
        "AB180072",
        "AB180073",
    }
    for row in carried:
        assert row["field_name"] == "classification"
        assert "superseded 2026-07-30 by classification=cVDPV" in row["notes"], (
            "a carried-forward supersession must name what replaced it"
        )

    assert {r["field_name"] for r in jc013129} == {"classification", "origin_class"}
    for row in jc013129:
        assert row["new_value"] in {"engineered/lab", "non-human"}
        assert "superseded 2026-07-30 by" in row["notes"], (
            "a carried-forward supersession must name what replaced it"
        )


def test_repaired_reasons_are_no_longer_truncated(ledger: list[dict[str, str]]) -> None:
    """The six reasons the release shipped cut off mid-phrase."""
    recovered = {
        r["subject_key"]: r["reason"]
        for r in ledger
        if r["source_artifact"] == "polio_recovery_confirmed.csv"
    }
    assert recovered["KY748286"].endswith("Sabin2/VDPV2-like, Nigeria 2015")
    for accession in ("A27232", "A27233", "DI499165", "S72981", "S72984"):
        assert recovered[accession].endswith("fragment-filtered)")
        assert "(<50nt," in recovered[accession]
    # And no double space from rejoining on ", " instead of ",".
    assert not any("  " in reason for reason in recovered.values())


def test_reasons_carry_no_synthetic_column_prefixes(ledger: list[dict[str, str]]) -> None:
    """The release wrote `"note: ..."` / `"reason: ... | note: ..."`; the ledger must not."""
    for row in ledger:
        for prefix in ("note:", "reason:", "evidence:", "source:"):
            assert not row["reason"].startswith(prefix), f"{row['decision_id']}: {row['reason']!r}"
        for prefix in ("reference_label:", "serotype:", "source:", "evidence:"):
            assert not row["evidence_reference"].startswith(prefix), row["decision_id"]


def test_subject_attributes_are_not_recorded_as_evidence(ledger: list[dict[str, str]]) -> None:
    """canonical_reference_confirmation and legacy overrides must carry no faux evidence."""
    for row in ledger:
        if row["decision_type"] in {
            "canonical_reference_confirmation",
            "legacy_classification_override",
        }:
            assert row["evidence_reference"] == "", (
                f"{row['decision_id']} records a subject attribute as evidence: "
                f"{row['evidence_reference']!r}"
            )


def test_effective_dates_are_blank_because_no_source_records_them(
    ledger: list[dict[str, str]],
) -> None:
    assert all(not r["effective_from"] and not r["effective_through"] for r in ledger)


def test_accession_less_subjects_are_retained(ledger: list[dict[str, str]]) -> None:
    """The Lansing family asserts that NO canonical reference exists — subject_key is a label."""
    lansing = [r for r in ledger if r["subject_key"] == "Lansing"]
    assert len(lansing) == 1
    assert lansing[0]["accession"] == ""
    assert lansing[0]["field_name"] == "canonical_reference_available"
    assert lansing[0]["new_value"] == "FALSE"


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def labelled(*pairs: tuple[str, str]) -> str:
    """The release's synthesis: `"{column}: {collapsed}"` joined by `" | "`, blanks dropped."""
    return " | ".join(f"{k}: {collapse_whitespace(v)}" for k, v in pairs if collapse_whitespace(v))


def ledger_attributes(notes: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in notes.split("; ") if "=" in part)


def resynthesize(row: dict[str, str]) -> tuple[str, str]:
    """Rebuild the release's `reason` and `evidence_reference` from a ledger row.

    Stated here independently rather than imported from the migration: a gate that asks the
    migration what it believes and then checks the migration against that belief proves nothing.
    """
    attributes = ledger_attributes(row["notes"])

    # The plain-TSV normalization converts ASCII double quotes to typographic pairs in *every* text
    # column, so the inverse has to be applied to every text column too. This read `reason` only
    # until the 2.3.0 resync, which was the first time a quoted phrase appeared in
    # `evidence_reference` (`JX181922`/`OR538735` quote a GenBank title). The gap was invisible for
    # as long as no such row existed, which is the whole problem with a check that has never had the
    # chance to fail.
    def unnormalize(text: str) -> str:
        return text.replace("“", '"').replace("”", '"')

    reason = unnormalize(row["reason"])
    evidence = unnormalize(row["evidence_reference"])
    kind = row["decision_type"]
    if kind in {"manual_override", "date_override"}:
        return labelled(("note", reason)), labelled(("source", evidence))
    if kind in {"carve_exclusion", "membership_exclusion"}:
        return labelled(("reason", reason), ("note", row["notes"])), ""
    if kind == "isolate_linkage_approval":
        return "", labelled(
            ("verification_evidence", evidence),
            ("linked_sibling", attributes.get("linked_sibling", "")),
        )
    if kind == "canonical_reference_confirmation":
        return labelled(("note", reason)), labelled(
            ("reference_label", attributes.get("reference_label", "")),
            ("serotype", attributes.get("serotype", "")),
        )
    if kind == "legacy_classification_override":
        return labelled(("notes", reason)), labelled(
            ("curation_source", "legacy_accession_override")
        )
    if kind in {"membership_confirmation_polio", "membership_confirmation_not_polio"}:
        return labelled(("note", reason)), labelled(("evidence", evidence))
    if kind == "polio_recovery_confirmation":
        return labelled(("note", reason)), ""
    raise AssertionError(f"no resynthesis rule for decision_type {kind!r}")


def test_every_decision_id_matches_its_own_content(ledger: list[dict[str, str]]) -> None:
    """`decision_id` is documented as a digest of the identity tuple; verify it actually is.

    Nothing previously recomputed this, so all 2,756 ids could have been replaced with arbitrary
    hashes and every test would still have passed.
    """
    occurrences: Counter[str] = Counter()
    for row in sorted(
        ledger,
        key=lambda r: (
            *(r[c] for c in ID_COLUMNS),
            r["reason"],
            r["evidence_reference"],
            r["confirmed_by"],
        ),
    ):
        digest = hashlib.sha256("|".join(row[c] for c in ID_COLUMNS).encode("utf-8")).hexdigest()[
            :12
        ]
        occurrences[digest] += 1
        n = occurrences[digest]
        expected = f"D-{digest}" if n == 1 else f"D-{digest}-{n}"
        assert row["decision_id"] == expected, (
            f"{row['decision_id']} does not match a digest of its own content (expected {expected})"
        )


def test_naive_tab_splitting_agrees_with_the_csv_reader(
    repository_root: Path, ledger: list[dict[str, str]]
) -> None:
    """The ledger's whole point is that unsophisticated tools get it right.

    `cut -f5`, `awk -F'\\t'`, a spreadsheet import and `csv` must all see the same 14 fields per
    row. That only holds if no field is ever escaped, which is why curator double quotes were
    converted to typographic pairs.
    """
    # No `'"' not in text` assertion here: that is `validate_decision_ledger`'s own refusal, run
    # against this same file by `test_ledger_satisfies_its_own_contract`. What is unique to this
    # test is the consequence — that a naive split sees the same 14 fields the csv reader does.
    text = (repository_root / LEDGER).read_text(encoding="utf-8")
    lines = text.splitlines()
    assert {len(line.split("\t")) for line in lines} == {14}
    assert len(lines) == len(ledger) + 1

    # A naive reader must reproduce the csv reader's view exactly.
    header = lines[0].split("\t")
    naive = [dict(zip(header, line.split("\t"), strict=True)) for line in lines[1:]]
    assert naive == ledger


def test_ledger_text_uses_typographic_quotes(ledger: list[dict[str, str]]) -> None:
    """Checked across every free-text column, not just `reason`.

    The normalization applies to all of them, and scoping the check to `reason` hid a real gap in
    `resynthesize` for as long as no `evidence_reference` happened to contain a quote.

    Balance is the property the normalization guarantees, and it is now asserted over every row
    rather than over rows preselected as already containing a quote. A companion pin of the exact
    quoted-row counts (42 / 2 / 0) was removed on 2026-07-30: it was satisfied by *any* 42/2/0
    partition, and it broke on any legitimate new quoted row — a maintenance cost with no
    corresponding failure it alone could catch. What the three counts stood in for is covered:

    * a regression to ASCII quotes is refused by `validate_decision_ledger` itself, asserted here by
      `test_ledger_satisfies_its_own_contract` and again by
      `test_naive_tab_splitting_agrees_with_the_csv_reader`;
    * quoted text going missing entirely would fail the full-column resynthesis in
      `test_ledger_reproduces_every_shipped_column_not_just_the_key`;
    * the `notes: 0` case is covered by that same resynthesis, which passes `notes` to `labelled`
      *without* `unnormalize` for `carve_exclusion`/`membership_exclusion`, so a typographic quote
      appearing there diverges from the shipped text.
    """
    for column in ("reason", "evidence_reference", "notes"):
        for row in ledger:
            assert row[column].count("“") == row[column].count("”"), (
                f"{row['decision_id']}: unbalanced typographic quotes in {column}"
            )


def test_every_row_names_where_it_actually_came_from(ledger: list[dict[str, str]]) -> None:
    """Eleven migrated registries, plus the adjudication that authored the five new rows.

    An earlier version asserted "10 sources, all .csv", which forced the D2 additions to claim
    `manual_review_overrides.csv` — a file that does not record them. A test should not make the
    honest answer fail.

    Eleven since 2026-07-30: `vdpv_wild_reconciliation.csv` is the locked reconciliation allowlist,
    the last input to `poliovirus_classification` that had no counterpart here.
    """
    sources = Counter(r["source_artifact"] for r in ledger)
    registries = {s for s in sources if s.endswith(".csv")}
    assert len(registries) == 11
    assert sources[VDPV_SOURCE] == EXPECTED_VDPV_ROWS
    assert sources["curator_adjudication_2026-07-29"] == len(D2_ADDITIONS) + len(
        ENGINEERED_READJUDICATION_ADDITIONS
    )
    assert sources["curator_adjudication_2026-07-31"] == (
        len(CAVA_PARENTAL_ADDITIONS)
        + len(VOCABULARY_REPAIR_ADDITIONS)
        + EXPECTED_CVDPV_AND_STRAIN_IDENTITY_ROWS
    )
    assert sources[UPSTREAM_PARTITION_SOURCE] == EXPECTED_UPSTREAM_PARTITION_ROWS
    assert (
        sources[SHORT_PATENT_MEMBERSHIP_SOURCE] == EXPECTED_SHORT_PATENT_MEMBERSHIP_ROWS
    )
    assert set(sources) == registries | {
        "curator_adjudication_2026-07-29",
        "curator_adjudication_2026-07-31",
        UPSTREAM_PARTITION_SOURCE,
        SHORT_PATENT_MEMBERSHIP_SOURCE,
    }

    repair_subjects = {subject for subject, _, _ in VOCABULARY_REPAIR_ADDITIONS}
    cvdpv_and_strain_identity_subjects = {
        r["subject_key"]
        for r in ledger
        if r["source_artifact"] == CVDPV_AND_STRAIN_IDENTITY_SOURCE
        and r["subject_key"] not in NON_CVDPV_CURATOR_ADJUDICATION_2026_07_31_SUBJECTS
    }
    classification_subjects = repair_subjects | cvdpv_and_strain_identity_subjects
    for row in ledger:
        if row["source_artifact"].startswith("curator_adjudication_"):
            # `engineered_or_construct` for every adjudication row except the ones that assert
            # `classification` instead — the three vocabulary repairs and, since 2026-07-31, the 143
            # cVDPV/strain-identity decisions. Named as two explicit populations rather than widened
            # to "any field", so a third field arriving by accident still fails here.
            if row["subject_key"] in classification_subjects:
                assert row["field_name"] == "classification"
            else:
                assert row["field_name"] == "engineered_or_construct"
            # `active` for four of the five. The fifth is CS406483's FALSE, superseded on 2026-07-31
            # by the TRUE assertion the same adjudication's Q2 answer requires — so the adjudication
            # now authors both sides of one reversal, and the note has to say which side it is.
            assert row["status"] in {"active", "superseded"}
            assert row["notes"].startswith("superseded") == (row["status"] == "superseded")
