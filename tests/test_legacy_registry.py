"""Contracts for the frozen legacy registries carried in `registry/legacy/`.

These four CSVs are the only surviving output of two pipeline stages that read external files
which no longer exist. They cannot be regenerated, so they are pinned by hash: an accidental edit,
a re-export, or a line-ending change fails here rather than silently redefining history.

The hash pin is the whole freeze. A companion `EXPECTED_ROWS` pin was removed on 2026-07-30: a row
count is a pure function of the bytes the hash already fixes, so it could not fail alone. Verified
both ways — deleting a row reddened the hash test and the row-count test together, while editing one
character inside a field reddened only the hash. The four counts remain tabulated in
[`registry/legacy/README.md`](../registry/legacy/README.md), where the hash pin keeps them true.

The load-bearing claims in `registry/legacy/README.md` are enforced here rather than asserted in
prose:

- the 30 load-bearing rows reconcile exactly with the ledger decisions that cite them, so
  `source_artifact` is a resolvable reference and not a dangling filename;
- nothing in the build reads this directory, so carrying the files does not quietly reintroduce a
  frozen upstream input;
- the four `engineered` calls, and specifically that only **three** of them are patent deposits.
  DQ205099 is the fourth, and it is annotated rather than adjudicated. Reasoning about it as a D2
  twin is the mistake these tests exist to prevent a second time.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest
from Bio import SeqIO
from Bio.Align import PairwiseAligner

from enterovirus_genbank_curated.contracts import read_tsv_gz

LEGACY_DIR = "registry/legacy"
LEDGER = "registry/decisions.tsv"
SOURCE_RECORDS = "final/source/normalized_tsv/records.tsv.gz"
SOURCE_QUALIFIERS = "final/source/normalized_tsv/feature_qualifiers.tsv.gz"
CANONICAL_FASTA = "final/canonical/sequences.fasta.gz"

# sha256 of each carried file, as copied from the private repository on 2026-07-29.
FROZEN = {
    "legacy_2026_bridge.csv":
        "51912a154d6ac626a676ab1056898af46bcefb8c5133cef32e0b717c0b3375c5",
    "legacy_accession_classification_overrides.csv":
        "aa673ce0acbbe42d1a6ef4f0d94df945f7d3a03aa5d12abff495c448b3804051",
    "legacy_date_location_extract.csv":
        "2116e79b0adfd451d413851e1bfe77030deb52e9af6a83c70cfeacac214766a3",
    "legacy_title_key_table.csv":
        "0d5f4bce32134b46d17aa49f01a746fac9605456e130320cb53be6925daea38a",
}

LOAD_BEARING = "legacy_accession_classification_overrides.csv"

# Patterns that must never reach a public repository. The private pipeline embedded absolute
# home-directory paths in several scripts, so this is a real rather than a theoretical risk.
FORBIDDEN = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"/Users/[A-Za-z0-9._-]+"),
    re.compile(r"/home/[A-Za-z0-9._-]+"),
    re.compile(r"gatesfoundation", re.IGNORECASE),
)


@pytest.fixture(scope="module")
def legacy_dir(repository_root: Path) -> Path:
    return repository_root / LEGACY_DIR


def engineered_accessions(legacy_dir: Path) -> set[str]:
    with (legacy_dir / LOAD_BEARING).open(newline="", encoding="utf-8") as handle:
        return {
            row["accession"] for row in csv.DictReader(handle)
            if row["classification"] == "engineered"
        }


def ledger_rows(repository_root: Path) -> list[dict[str, str]]:
    with (repository_root / LEDGER).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_each_frozen_file_matches_its_pinned_hash(legacy_dir: Path, name: str) -> None:
    path = legacy_dir / name
    assert path.is_file(), f"{name} is missing; it cannot be regenerated"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == FROZEN[name], (
        f"{name} has changed. These files are frozen historical output with no upstream left to "
        f"re-derive them from; if the change is deliberate, update FROZEN and say why in "
        f"registry/legacy/README.md."
    )


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_no_frozen_file_carries_private_detail(legacy_dir: Path, name: str) -> None:
    text = (legacy_dir / name).read_text(encoding="utf-8")
    for pattern in FORBIDDEN:
        assert not pattern.search(text), f"{name} matches {pattern.pattern}"


def test_the_load_bearing_file_reconciles_with_the_ledger(
    legacy_dir: Path, repository_root: Path
) -> None:
    """Every ledger decision citing this file is reproduced by the file, and vice versa.

    This is what makes `source_artifact` an auditable reference. Thirty rows were migrated in
    stage 2; the CSV they came from is now committed beside them, so a reader can check the
    migration rather than take it on trust.
    """
    with (legacy_dir / LOAD_BEARING).open(newline="", encoding="utf-8") as handle:
        source = {row["accession"]: row for row in csv.DictReader(handle)}

    ledger = {
        row["accession"]: row
        for row in ledger_rows(repository_root)
        if row["source_artifact"] == LOAD_BEARING
    }

    assert set(ledger) == set(source), (
        f"only in ledger: {sorted(set(ledger) - set(source))}; "
        f"only in file: {sorted(set(source) - set(ledger))}"
    )
    for accession, row in source.items():
        migrated = ledger[accession]
        assert migrated["decision_type"] == "legacy_classification_override"
        assert migrated["field_name"] == "classification"
        assert migrated["new_value"] == row["classification"], accession
        assert migrated["reason"] == row["notes"], accession


def test_the_legacy_file_asserts_engineered_for_four_accessions(legacy_dir: Path) -> None:
    """D2's premise, checked against the file rather than restated.

    The adjudication superseded three legacy `engineered` calls. The file asserts `engineered` for
    a **fourth**, DQ205099, which D2 did not cover because no 2026 review contradicted it. That
    asymmetry is deliberate and open — see `registry/legacy/README.md` — so it is pinned here
    rather than left as a surprise for whoever reads the ledger next.
    """
    assert engineered_accessions(legacy_dir) == {
        "CS406436", "CS406482", "CS406483", "DQ205099",
    }


def test_only_three_of_the_four_engineered_calls_are_patent_deposits(
    legacy_dir: Path, repository_root: Path
) -> None:
    """The fourth is a different kind of record, and the difference is why D2 does not extend to it.

    Restating "four patent deposits" is what made DQ205099 look like a D2 twin: same legacy verdict,
    same cited patent, same falsifying divergence measurement. It is not one. GenBank puts the D2
    trio in division `PAT` as numbered sequences lifted out of WO2006042156, and DQ205099 in `VRL`
    as a CDC direct submission of an infectious clone. An infectious cDNA clone genuinely is a
    construct, so D2's remedy would make that record less accurate rather than more.

    Checked against the shipped source layer, because this is the fact the reasoning turns on.
    """
    header, rows = read_tsv_gz(repository_root / SOURCE_RECORDS)
    index = {name: position for position, name in enumerate(header)}
    divisions = {
        row[index["accession"]]: (row[index["division"]], row[index["definition"]])
        for row in rows
        if row[index["accession"]] in engineered_accessions(legacy_dir)
    }
    assert set(divisions) == {"CS406436", "CS406482", "CS406483", "DQ205099"}

    patent = {a for a, (division, _) in divisions.items() if division == "PAT"}
    assert patent == {"CS406436", "CS406482", "CS406483"}, (
        f"the D2 trio must be the patent deposits; got {sorted(patent)}"
    )
    for accession in patent:
        assert "Patent WO2006042156" in divisions[accession][1], accession

    division, definition = divisions["DQ205099"]
    assert division == "VRL", "DQ205099 is not a patent sequence; do not reason about it as one"
    assert "clone S2R9" in definition, definition

    # The single fact that upholds the `engineered` label: an infectious cDNA clone *is* a
    # construct, so `engineered_or_construct=TRUE` is right and D2's remedy would be wrong. It was
    # previously pinned only as a substring of the note asserting it, which is no evidence at all —
    # the source layer ships the qualifiers, so they are checked here.
    qualifier_header, qualifier_rows = read_tsv_gz(repository_root / SOURCE_QUALIFIERS)
    qindex = {name: position for position, name in enumerate(qualifier_header)}
    qualifiers = {
        (row[qindex["qualifier_name"]], row[qindex["qualifier_value"]])
        for row in qualifier_rows
        if row[qindex["feature_id"]].startswith("DQ205099.")
    }
    assert ("clone", "S2R9") in qualifiers, sorted(qualifiers)[:20]
    assert ("note", "infectious clone") in qualifiers, (
        "the DQ205099 disposition rests on this qualifier: an infectious clone is a construct, so "
        "the engineered call stands even though the codon-deoptimization rationale is false. "
        "Without it the annotate-rather-than-adjudicate decision has no evidence."
    )


def test_the_fourth_engineered_call_is_annotated_and_still_active(repository_root: Path) -> None:
    """The falsified rationale is marked in the ledger, and the verdict it justifies is untouched.

    Both halves matter. Without the note, the next reader measures 3 nt from Sabin 2 and re-raises
    a resolved question. Without `active` + `engineered`, an annotation would have quietly become an
    adjudication.
    """
    ledger = ledger_rows(repository_root)
    rows = [
        row for row in ledger
        if row["subject_key"] == "DQ205099"
        and row["source_artifact"] == LOAD_BEARING
    ]
    assert len(rows) == 1, f"expected one legacy row for DQ205099, got {len(rows)}"
    row = rows[0]

    assert row["status"] == "active"
    assert row["new_value"] == "engineered"
    assert "codon-deoptimized Sabin2" in row["reason"], (
        "the curator's raw cell text must survive verbatim under D1; the note corrects it, the "
        "reason field does not"
    )
    for phrase in ("3 nt/7439", "VRL", "S2R9", "16537593", "engineered_or_construct=TRUE stands"):
        assert phrase in row["notes"], f"annotation lost {phrase!r}"


def test_the_stated_divergences_are_recomputable_from_the_shipped_sequences(
    repository_root: Path,
) -> None:
    """Every divergence figure the D2 and DQ205099 dispositions turn on, recomputed from the data.

    This closes the hole that let a stale figure ship. The notes were previously checked only as
    substrings of themselves — `"3 nt/7439" in row["notes"]` — which pins a number to its own
    spelling and not to anything measurable, so the docs and `D2_EVIDENCE` disagreed by four
    positions while every assertion passed. All six sequences are in the release, so the measurement
    is a few seconds of work and is the only thing that can actually contradict the prose.

    The denominator convention matters and is asserted deliberately: these are the comparable
    (mutually ungapped) positions of a pairwise global alignment. The curator's own `reason` text
    reports the same substitution counts over 7,435 positions from a Sabin-frame multiple alignment
    that is not carried publicly, and under D1 that text stays as written.
    """
    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score, aligner.mismatch_score = 1, -1
    aligner.open_gap_score, aligner.extend_gap_score = -10, -0.5
    aligner.end_gap_score = 0.0

    wanted = {"AY238473", "AY184220", "CS406436", "CS406482", "CS406483", "DQ205099"}
    sequences: dict[str, str] = {}
    with gzip.open(repository_root / CANONICAL_FASTA, "rt", encoding="utf-8") as handle:
        for record in SeqIO.parse(handle, "fasta"):
            accession = record.id.split("|")[0].split(".")[0]
            if accession in wanted:
                sequences[accession] = str(record.seq).upper()
    missing = wanted - set(sequences)
    assert not missing, f"the release no longer ships {sorted(missing)}"

    ledger = ledger_rows(repository_root)

    # (query, reference, expected substitutions, expected comparable positions)
    expected = [
        ("CS406436", "AY238473", 4, 6621),
        ("CS406482", "AY238473", 4, 7439),
        ("CS406483", "AY238473", 6, 7439),
        ("DQ205099", "AY184220", 3, 7439),
    ]
    for query, reference, subs, denominator in expected:
        alignment = aligner.align(sequences[reference], sequences[query])[0]
        top, bottom = str(alignment[0]), str(alignment[1])
        pairs = [(a, b) for a, b in zip(top, bottom, strict=True) if a != "-" and b != "-"]
        assert len(pairs) == denominator, (
            f"{query} vs {reference}: {len(pairs)} comparable positions, not {denominator}. "
            f"The ledger notes and registry/README.md state the old figure; fix all three together."
        )
        mismatches = sum(1 for a, b in pairs if a != b)
        assert mismatches == subs, f"{query} vs {reference}: {mismatches} substitutions, not {subs}"
        # The load-bearing inference: orders of magnitude below wholesale codon rewriting.
        assert mismatches / len(pairs) < 0.001

        # The measurement has to be bound to the text that states it, or this test degenerates into
        # comparing hardcoded literals to the data while the shipped prose drifts freely. That is
        # exactly what happened: the ledger kept `4-6 nt/7435` after the docs were corrected, and
        # every assertion still passed.
        figure = f"{mismatches} nt/{len(pairs)}"
        stating = [
            row for row in ledger
            if row["subject_key"] == query
            and figure in f"{row['notes']} {row['evidence_reference']}"
        ]
        assert stating, (
            f"no ledger row for {query} states the measured {figure}. The migration-authored notes "
            f"and evidence must carry the figure this test recomputes; a stale number here is "
            f"invisible to every other check."
        )

    # DQ205099's note names its three substitutions and the claim that they are unclustered.
    alignment = aligner.align(sequences["AY184220"], sequences["DQ205099"])[0]
    top, bottom = str(alignment[0]), str(alignment[1])
    called = [
        f"{a}{position + 1}{b}"
        for position, (a, b) in enumerate(zip(top, bottom, strict=True))
        if a != "-" and b != "-" and a != b
    ]
    assert called == ["A2616G", "A3303T", "T5640A"], called


def test_dq205099_is_the_only_ledger_decision_for_its_subject(repository_root: Path) -> None:
    """Why it escaped D2, pinned as a fact rather than left as an anecdote.

    D2 fired on a contradiction between two registries. DQ205099 has exactly one decision in the
    whole ledger, so there was nothing to contradict it — "no reviewer objected" is the reason it
    survived, not evidence that anyone checked it. If a second decision ever lands on this subject,
    the annotation's framing needs revisiting and this test says so.
    """
    subjects = [row for row in ledger_rows(repository_root) if row["subject_key"] == "DQ205099"]
    assert len(subjects) == 1, (
        f"DQ205099 now has {len(subjects)} decisions: "
        f"{[(r['source_artifact'], r['field_name'], r['new_value']) for r in subjects]}. "
        f"Re-read the DQ205099 annotation in scripts/migrate_legacy_registries.py before shipping."
    )


def test_the_guard_refuses_a_read_of_the_legacy_directory(repository_root: Path) -> None:
    """`registry/legacy/` is provenance, not input, and that is enforced at runtime.

    This replaced a grep of `src/**/*.py` for the literal `registry/legacy`. The grep was a proxy
    for the property, and a bad one twice over: segment-wise `root / "registry" / "legacy"` evaded
    it entirely, and it could not tell a stage that *reads* the directory from `sandbox.py`, which
    names it in order to forbid it — the false positive that retired it. The audit hook keys on the
    resolved path, so segment-wise composition and symlinks are both covered. A hardlink is not:
    it is a second name for the same inode, not a path that resolves into the tree.
    """
    probe = (
        "import sys\n"
        "from pathlib import Path\n"
        "from enterovirus_genbank_curated.sandbox import install_input_guard\n"
        f"root = Path({str(repository_root)!r})\n"
        "install_input_guard(root)\n"
        # Composed segment-wise on purpose: the spelling the retired grep could not see.
        "target = root / 'registry' / 'legacy' / 'legacy_accession_classification_overrides.csv'\n"
        "target.open(encoding='utf-8').read()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=repository_root
    )
    assert result.returncode != 0, (
        "a guarded build read registry/legacy/ without complaint. If a stage now genuinely needs "
        "this data, promote the values into registry/decisions.tsv instead of reading the frozen "
        "file."
    )
    assert "UndeclaredInputError" in result.stderr, result.stderr
    # Without a message check this passes on *any* violation — a future lazy import tripping a read
    # root would satisfy it while saying nothing about the frozen tree.
    assert "read by nothing" in result.stderr, result.stderr
    assert "registry/legacy" in result.stderr, result.stderr


def test_the_legacy_directory_guard_can_fail(repository_root: Path) -> None:
    """Negative control for the test above: the same read of a *non*-frozen registry path is
    allowed. Without this, a guard that refused every read would make the check above pass
    vacuously."""
    probe = (
        "from pathlib import Path\n"
        "from enterovirus_genbank_curated.sandbox import install_input_guard\n"
        f"root = Path({str(repository_root)!r})\n"
        "install_input_guard(root)\n"
        "(root / 'registry' / 'decisions.tsv').open(encoding='utf-8').readline()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=repository_root
    )
    assert result.returncode == 0, result.stderr
