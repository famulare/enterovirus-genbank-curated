"""Same-sequence consistency invariants for the `engineered_or_construct` column.

Two byte-identical sequences are the same genotype. `engineered` is a claim *about a genotype* —
whether someone deliberately produced it for a purpose — so two records carrying the identical
`sequence_sha256` cannot generally disagree about it. The exception is real but narrow, and it is
the reason there are two invariants here rather than one:

- **Invariant A** constrains same-sequence *patent and synthetic* deposits. Two `PAT`/`SYN`
  deposits of the same bytes cannot differ on whether that genotype was deliberately produced.
  There is no legitimate exemption, so this needs no allowlist and can be enforced absolutely.

- **Invariant B** (`test_no_same_sequence_split_without_an_allowlist_entry`) constrains the
  general case, where a legitimate exemption *does* exist: the curator's CDC-convention rule means
  a primary `VRL` deposit of a vaccine seed strain is `engineered=TRUE` while a field isolate whose
  genome is byte-identical to it stays FALSE. That is a real distinction between a manufactured
  product and a virus sampled out of the world, so Invariant B is escaped by an explicit reviewed
  allowlist rather than by a rule.

Why these exist at all: the D2 adjudication set `CS406482` to FALSE while leaving `PU749297` —
byte-identical, the same patent sequence re-deposited in a 2024 continuation — at TRUE. Nothing in
the suite noticed, because no check compared same-sequence records. Invariant A is that check, and
`test_invariant_a_would_have_caught_the_d2_defect` pins it to the specific defect it exists to
prevent, so the guard cannot be quietly weakened into one that passes for the wrong reason.

See `docs/engineered-full-population-readjudication.md` §7 for the measurement behind the scoping
choice, including why a sequence-length floor was rejected in favour of an explicit allowlist.

Mutation evidence
-----------------

Recorded because this repository's rule is that a check is not finished until a mutation proves it
fires (`docs/review-backlog.md`, root cause R3), and because an in-memory control alone cannot show
that the *real* test path — reading the shipped `.tsv.gz` — detects a real change. Both mutations
below were applied to `final/canonical/sequence_metadata.tsv.gz` itself and reverted, with the
sha256 confirmed identical afterwards (`369b6c0b…`).

1. `CS406436` TRUE→FALSE, one record, leaving its byte-identical twin `PU749305` at TRUE. Three
   tests went red, including `test_same_sequence_patent_and_synthetic_deposits_agree`, which named
   the pair. This is the D2 defect reproduced in the shipped bytes rather than in a dict, so
   Invariant A is confirmed load-bearing on the path that actually runs in CI.
2. `CS406436` **and** `PU749305` both TRUE→FALSE, so the group agrees. Invariant A stayed **green**
   and only the population pins went red — confirming Invariant A discriminates *disagreement*
   specifically, and does not merely react to any change in the column.
"""

from __future__ import annotations

import collections
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import read_tsv_gz

CANONICAL_METADATA = "final/canonical/sequence_metadata.tsv.gz"
SOURCE_RECORDS = "final/source/normalized_tsv/records.tsv.gz"

ENGINEERED_COLUMN = "engineered_or_construct"

# Divisions whose members can never legitimately disagree with each other (Invariant A).
DELIBERATE_DEPOSIT_DIVISIONS = frozenset({"PAT", "SYN"})

# Invariant B escape hatch. Every entry is a record that legitimately carries TRUE while a
# byte-identical record carries FALSE, with the reason it is allowed to. Empty is the goal state:
# it means no same-sequence group disagrees anywhere in the release.
SAME_SEQUENCE_EXEMPTIONS: dict[str, str] = {}

# Measured on the shipped release. Pinned so that a future change which *stops* constraining
# records — by moving them out of PAT/SYN, or by dropping them from canonical — fails loudly
# instead of turning the invariant into a check over an empty set.
EXPECTED_CONSTRAINED_GROUPS = 178
EXPECTED_CONSTRAINED_RECORDS = 374

# Population pins for the column itself. Nothing anywhere pinned these before, which is precisely
# how the values drifted far enough to need a full re-adjudication: 543 records shipped TRUE and no
# check knew what the number was supposed to be.
#
# `EXPECTED_PAT_TRUE == EXPECTED_PAT_IN_CANONICAL` is not a curation outcome. It is the signature of
# the defect: `\bPAT\b` matched as free text inside a 20-field blob, so *every* patent-division
# record is flagged engineered regardless of what its sequence is. When the rule is rewritten this
# equality is the first thing that should break.
EXPECTED_TRUE_TOTAL = 543
EXPECTED_TRUE_AT_LEAST_3000NT = 58
EXPECTED_PAT_IN_CANONICAL = 506
EXPECTED_PAT_TRUE = 506
EXPECTED_SYN_IN_CANONICAL = 7
EXPECTED_SYN_TRUE = 7

LONG_SEQUENCE_NT = 3000


@pytest.fixture(scope="module")
def engineered_by_accession(repository_root: Path) -> dict[str, str]:
    header, rows = read_tsv_gz(repository_root / CANONICAL_METADATA)
    index = {name: position for position, name in enumerate(header)}
    return {row[index["accession"]]: row[index[ENGINEERED_COLUMN]] for row in rows}


@pytest.fixture(scope="module")
def sha256_by_accession(repository_root: Path) -> dict[str, str]:
    header, rows = read_tsv_gz(repository_root / CANONICAL_METADATA)
    index = {name: position for position, name in enumerate(header)}
    return {row[index["accession"]]: row[index["sequence_sha256"]] for row in rows}


@pytest.fixture(scope="module")
def division_by_accession(repository_root: Path) -> dict[str, str]:
    header, rows = read_tsv_gz(repository_root / SOURCE_RECORDS)
    index = {name: position for position, name in enumerate(header)}
    return {row[index["accession"]]: row[index["division"]] for row in rows}


@pytest.fixture(scope="module")
def length_by_accession(repository_root: Path) -> dict[str, int]:
    header, rows = read_tsv_gz(repository_root / CANONICAL_METADATA)
    index = {name: position for position, name in enumerate(header)}
    return {row[index["accession"]]: int(row[index["sequence_length_nt"]]) for row in rows}


def group_by_sequence(
    engineered: dict[str, str],
    sha256: dict[str, str],
    division: dict[str, str],
    *,
    restrict_to_divisions: frozenset[str] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """Bucket accessions by `sequence_sha256`, carrying each one's engineered value.

    `restrict_to_divisions` narrows the population to records whose *source* division is in the
    given set, which is what makes Invariant A exemption-free.
    """
    groups: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for accession, value in engineered.items():
        keep = restrict_to_divisions is None or division.get(accession) in restrict_to_divisions
        if not keep:
            continue
        groups[sha256[accession]].append((accession, value))
    return dict(groups)


def disagreeing_groups(
    groups: dict[str, list[tuple[str, str]]],
) -> dict[str, list[tuple[str, str]]]:
    return {
        digest: sorted(members)
        for digest, members in groups.items()
        if len({value for _, value in members}) > 1
    }


def test_the_engineered_column_is_a_clean_boolean(engineered_by_accession: dict[str, str]) -> None:
    """A disagreement check is meaningless if the column carries blanks or free text."""
    values = set(engineered_by_accession.values())
    assert values == {"TRUE", "FALSE"}, f"unexpected {ENGINEERED_COLUMN} values: {sorted(values)}"


def test_every_canonical_record_resolves_to_a_source_division(
    engineered_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Invariant A's scoping depends on this join being total.

    `group_by_sequence` uses `division.get(accession)`, which yields `None` for a missing
    accession and silently drops it from the PAT/SYN population. If canonical ever carried a
    record absent from the source records table, Invariant A would stop constraining it without
    any test noticing — the coverage pins would move, but only if the record was already counted.
    Assert the join is total so that failure mode cannot arise quietly.
    """
    unresolved = sorted(a for a in engineered_by_accession if a not in division_by_accession)
    assert unresolved == [], (
        f"{len(unresolved)} canonical accessions have no source-layer division, so Invariant A "
        f"silently excludes them: {unresolved[:10]}"
    )


def test_the_engineered_population_matches_its_pins(
    engineered_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
    length_by_accession: dict[str, int],
) -> None:
    """Drift detector for the counts that moved silently and forced the re-adjudication.

    A change here is not necessarily a defect — the planned rule rewrite is expected to move every
    one of these numbers. It has to be *deliberate*, which means updating the pin and the
    disposition tables in `docs/engineered-full-population-readjudication.md` together.
    """
    true_accessions = {a for a, v in engineered_by_accession.items() if v == "TRUE"}
    assert len(true_accessions) == EXPECTED_TRUE_TOTAL, (
        f"{len(true_accessions)} records ship {ENGINEERED_COLUMN}=TRUE, pinned at "
        f"{EXPECTED_TRUE_TOTAL}"
    )

    long_true = {a for a in true_accessions if length_by_accession[a] >= LONG_SEQUENCE_NT}
    assert len(long_true) == EXPECTED_TRUE_AT_LEAST_3000NT, (
        f"{len(long_true)} records ship TRUE at >={LONG_SEQUENCE_NT} nt, pinned at "
        f"{EXPECTED_TRUE_AT_LEAST_3000NT}. This is the hand-adjudicated population; if it changed, "
        f"the disposition table in the re-adjudication doc is now incomplete."
    )

    for division, expected_total, expected_true in (
        ("PAT", EXPECTED_PAT_IN_CANONICAL, EXPECTED_PAT_TRUE),
        ("SYN", EXPECTED_SYN_IN_CANONICAL, EXPECTED_SYN_TRUE),
    ):
        members = {a for a in engineered_by_accession if division_by_accession.get(a) == division}
        flagged = members & true_accessions
        assert len(members) == expected_total, (
            f"{len(members)} canonical records are division {division}, pinned at {expected_total}"
        )
        assert len(flagged) == expected_true, (
            f"{len(flagged)} of {len(members)} {division} records ship TRUE, pinned at "
            f"{expected_true}"
        )


def test_the_blanket_patent_flag_is_recorded_as_a_known_defect(
    engineered_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Every single patent-division record ships TRUE, and that is the bug, not a finding.

    Asserted rather than merely documented so the situation cannot be quietly *partially* fixed:
    flipping some patent records without rewriting the predicate would leave a half-migrated column
    that reads as if it had been adjudicated. When the rule rewrite lands this test must be deleted
    along with the pins above, deliberately.
    """
    patent = {a for a in engineered_by_accession if division_by_accession.get(a) == "PAT"}
    flagged = {a for a in patent if engineered_by_accession[a] == "TRUE"}
    assert flagged == patent, (
        "some patent records now ship FALSE, so the blanket flag is partially corrected: "
        f"{len(patent) - len(flagged)} of {len(patent)}. Finish the predicate rewrite and retire "
        "this test rather than leaving the column half-adjudicated."
    )


def test_same_sequence_patent_and_synthetic_deposits_agree(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Invariant A. Unconditional: no allowlist, no length floor."""
    groups = group_by_sequence(
        engineered_by_accession,
        sha256_by_accession,
        division_by_accession,
        restrict_to_divisions=DELIBERATE_DEPOSIT_DIVISIONS,
    )
    constrained = {digest: members for digest, members in groups.items() if len(members) > 1}

    assert len(constrained) == EXPECTED_CONSTRAINED_GROUPS, (
        f"Invariant A now constrains {len(constrained)} sha256 groups, not "
        f"{EXPECTED_CONSTRAINED_GROUPS}. If that is intended, update the pin; if it dropped, the "
        f"invariant may have stopped covering the records it exists to cover."
    )
    assert sum(len(m) for m in constrained.values()) == EXPECTED_CONSTRAINED_RECORDS

    failures = disagreeing_groups(constrained)
    assert failures == {}, (
        "byte-identical patent/synthetic deposits disagree on "
        f"{ENGINEERED_COLUMN}: {failures}. Two deposits of the same bytes are the same genotype; "
        "adjudicate the group, not one member of it."
    )


def test_invariant_a_would_have_caught_the_d2_defect(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Falsification control: the guard must fail on the defect that motivated it.

    D2 asserted `engineered_or_construct=FALSE` for `CS406482` and said nothing about `PU749297`,
    which carries the identical sequence. Reproduce that split and require a red.
    """
    assert sha256_by_accession["CS406482"] == sha256_by_accession["PU749297"], (
        "this control depends on CS406482 and PU749297 being byte-identical; if the sequences "
        "changed, re-derive the control rather than deleting it"
    )

    mutated = dict(engineered_by_accession)
    mutated["CS406482"] = "FALSE"
    mutated["PU749297"] = "TRUE"

    groups = group_by_sequence(
        mutated,
        sha256_by_accession,
        division_by_accession,
        restrict_to_divisions=DELIBERATE_DEPOSIT_DIVISIONS,
    )
    failures = disagreeing_groups(groups)

    assert failures, (
        "Invariant A passed a CS406482/PU749297 split — it cannot detect its own defect"
    )
    flagged = {accession for members in failures.values() for accession, _ in members}
    assert {"CS406482", "PU749297"} <= flagged


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Invariant B fails on 12 known sha256 groups until the 44 re-deposit flips and A09260 "
        "reach final/canonical (docs/engineered-full-population-readjudication.md §4, §7, "
        "Appendix B). Note what will NOT clear this: adding the ledger rows. This test reads "
        "final/canonical/sequence_metadata.tsv.gz, and nothing in this repository writes that "
        "file — `git log -- final/canonical` has exactly one commit, the initial release. The "
        "values only move when the private pipeline rebuilds and re-ships the canonical layer, so "
        "this stays xfail across the whole ledger stage by design. Marked strict so the suite "
        "turns RED the moment the rebuild lands and makes it pass — that is the signal to delete "
        "this marker, not to leave a passing xfail lying around."
    ),
)
def test_no_same_sequence_split_without_an_allowlist_entry(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Invariant B. Any TRUE sharing a sequence with a FALSE needs a reviewed exemption.

    Expected-failing today, deliberately: the outstanding set is recorded in the assertion message
    rather than hidden behind a skip, so `pytest -rx` prints exactly which groups are still
    unadjudicated. Goes green with `SAME_SEQUENCE_EXEMPTIONS` empty once stage 2 lands.
    """
    groups = group_by_sequence(engineered_by_accession, sha256_by_accession, division_by_accession)
    offenders: dict[str, list[str]] = {}
    for digest, members in groups.items():
        values = {value for _, value in members}
        if values != {"TRUE", "FALSE"}:
            continue
        unexplained = sorted(
            accession
            for accession, value in members
            if value == "TRUE" and accession not in SAME_SEQUENCE_EXEMPTIONS
        )
        if unexplained:
            offenders[digest] = unexplained

    assert offenders == {}, (
        f"{len(offenders)} sha256 groups carry a TRUE alongside a byte-identical FALSE with no "
        f"entry in SAME_SEQUENCE_EXEMPTIONS: "
        f"{ {d[:12]: a for d, a in sorted(offenders.items())} }. Either flip them, or record why "
        f"the split is legitimate."
    )
