"""The committed ledger must reconcile against release 2.1.5 with every difference accounted for.

`registry/decisions.tsv` is now the authority for human curation. These tests check it against the
shipped `final/audit/manual_decisions.tsv.gz` on `(subject_key, field_name, new_value)` — reason and
evidence text differ by design, since the ledger carries the curator's raw words rather than the
release's synthesized `"{column}: {value} | ..."` strings.
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
SHIPPED = "final/audit/manual_decisions.tsv.gz"

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
LEDGER_ONLY_ADDITIONS = D2_ADDITIONS | SUPERSEDED_CARRY_FORWARD_ADDITIONS

EXPECTED_STATUS = {"active": 2895, "retired": 17, "superseded": 9}

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


@pytest.fixture(scope="module")
def shipped(repository_root: Path) -> list[dict[str, str]]:
    with gzip.open(repository_root / SHIPPED, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL))


def test_ledger_satisfies_its_own_contract(
    repository_root: Path, decision_contract: DecisionContract
) -> None:
    summary = validate_decision_ledger(repository_root / LEDGER, decision_contract)
    assert summary.rows == 2921
    assert summary.active_rows == EXPECTED_STATUS["active"]


def test_no_shipped_decision_was_lost(
    ledger: list[dict[str, str]], shipped: list[dict[str, str]]
) -> None:
    """The migration must not drop a single human assertion."""
    missing = Counter(map(assertion_key, shipped)) - Counter(map(assertion_key, ledger))
    assert sum(missing.values()) == 0, f"decisions lost in migration: {dict(missing)}"


def test_every_addition_is_an_approved_one(
    ledger: list[dict[str, str]], shipped: list[dict[str, str]]
) -> None:
    added = Counter(map(assertion_key, ledger)) - Counter(map(assertion_key, shipped))
    assert set(added) == LEDGER_ONLY_ADDITIONS, (
        f"unapproved additions: {set(added) - LEDGER_ONLY_ADDITIONS}"
    )


def test_decision_type_counts_match_except_the_approved_additions(
    ledger: list[dict[str, str]], shipped: list[dict[str, str]]
) -> None:
    got = Counter(r["decision_type"] for r in ledger)
    want = Counter(r["decision_type"] for r in shipped)
    want["manual_override"] += len(LEDGER_ONLY_ADDITIONS)
    assert got == want


def test_status_distribution_is_exactly_as_documented(ledger: list[dict[str, str]]) -> None:
    assert Counter(r["status"] for r in ledger) == Counter(EXPECTED_STATUS)


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
    """`retired` means "redundant", so a retired row must NOT contradict the active one.

    A retired row whose value differed would be a silently buried conflict — exactly what the
    status vocabulary is supposed to prevent.
    """
    governing = {
        (r["subject_key"], r["field_name"]): r["new_value"]
        for r in ledger
        if r["status"] == "active"
    }
    for row in ledger:
        if row["status"] != "retired":
            continue
        key = (row["subject_key"], row["field_name"])
        assert key in governing, f"retired {row['decision_id']} has no active counterpart"
        assert row["new_value"] == governing[key], (
            f"retired {row['decision_id']} contradicts the active decision "
            f"({row['new_value']!r} vs {governing[key]!r}) — that is a conflict, not redundancy"
        )


def test_superseded_rows_are_only_the_adjudicated_conflict(ledger: list[dict[str, str]]) -> None:
    """Three distinct causes of supersession, asserted separately so none can absorb another.

    D2 overturned a legacy `classification=engineered` call on evidence. The AB180070-73 rows are a
    curator revision preserved through the 2.3.0 resync that would otherwise have deleted them.
    JC013129's two rows are a curator revision preserved through the 2.4.1 resync, same shape. All
    three must record *why*, but they say different things and are not interchangeable.
    """
    superseded = [r for r in ledger if r["status"] == "superseded"]
    d2 = [
        r
        for r in superseded
        if r["field_name"] == "classification" and r["new_value"] == "engineered"
    ]
    carried = [r for r in superseded if r["new_value"] == "iVDPV"]
    jc013129 = [r for r in superseded if r["subject_key"] == "JC013129"]
    assert len(d2) + len(carried) + len(jc013129) == len(superseded), (
        "an unexplained supersession class appeared"
    )

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


def test_ledger_reproduces_every_shipped_column_not_just_the_key(
    ledger: list[dict[str, str]], shipped: list[dict[str, str]]
) -> None:
    """The load-bearing gate: full-fidelity, not a projection onto three columns.

    Matching only `(subject_key, field_name, new_value)` leaves `reason`, `evidence_reference`,
    `confirmed_by`, `accession`, `source_artifact` and `decision_id` structurally invisible — every
    curator rationale in the file could be blanked or swapped and the check would still pass.

    The release's synthesis is a deterministic function of curator text, so it inverts. Every
    shipped row is rebuilt from the ledger and compared on all of it, with the only permitted
    difference enumerated below.
    """

    def identity(row: dict[str, str]) -> tuple[str, ...]:
        return tuple(row[column] for column in ID_COLUMNS)

    by_identity = {identity(r): r for r in shipped}
    assert len(by_identity) == len(shipped), "shipped identities are not unique"

    unmatched, differences = [], []
    for row in ledger:
        key = identity(row)
        if key not in by_identity:
            unmatched.append(key)
            continue
        want = by_identity[key]
        reason, evidence = resynthesize(row)
        if reason != want["reason"]:
            differences.append(("reason", row["subject_key"], reason, want["reason"]))
        assert evidence == want["evidence_reference"], f"{key}: evidence diverged"
        for column in ("confirmed_by", "accession", "source_artifact"):
            assert row[column] == want[column], f"{key}: {column} diverged"

    assert {u[1] for u in unmatched} == {a for a, _, _ in LEDGER_ONLY_ADDITIONS}, (
        f"rows absent from the release that are not the approved additions: {unmatched}"
    )

    # The ONLY permitted text difference: six reasons the release truncated. The ledger must hold
    # strictly more text, never different text.
    assert {d[1] for d in differences} == REPAIRED_ACCESSIONS
    for _, subject, rebuilt, shipped_text in differences:
        assert rebuilt.startswith(shipped_text), (
            f"{subject}: the repair changed the curator's text rather than extending it\n"
            f"  ledger:  {rebuilt}\n  release: {shipped_text}"
        )


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
    """Ten migrated registries, plus the adjudication that authored the three new rows.

    An earlier version asserted "10 sources, all .csv", which forced the D2 additions to claim
    `manual_review_overrides.csv` — a file that does not record them. A test should not make the
    honest answer fail.
    """
    sources = Counter(r["source_artifact"] for r in ledger)
    registries = {s for s in sources if s.endswith(".csv")}
    assert len(registries) == 10
    assert sources["curator_adjudication_2026-07-29"] == len(D2_ADDITIONS)
    assert set(sources) == registries | {"curator_adjudication_2026-07-29"}

    for row in ledger:
        if row["source_artifact"] == "curator_adjudication_2026-07-29":
            assert row["field_name"] == "engineered_or_construct"
            assert row["status"] == "active"
            # A supersession note on an active row would reintroduce the confusion this avoids.
            assert not row["notes"].startswith("superseded")
