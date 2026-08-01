"""Stamp a build as a release: what it contains, what it is missing, and what it was built from.

`final/` is release 2.4.1 and is immutable here. This module writes the manifests that make a *new*
build citable in the same way — a build manifest naming its inputs and its coverage, and a file
manifest hashing every artifact — so a consumer can tell one build from another without diffing
gigabytes.

## The version is 4.0.0

Release 4.0.0 ships the accumulated 3.0.0-3.3.0 line below as one major bump, for two reasons.
First, it is the release at which reconciliation against the hand-curated 2.4.1 baseline is complete
in the sense this pipeline can make that claim: every one of the 536 remaining
`poliovirus_classification` differences is categorized rather than merely counted (see
`docs/classification-migration-gap.md`), 97.8% of the shared carve agrees, and the residue is either
an epidemiological judgement no sequence property carries or a named, reverted attempt (chimera
detection) rather than an unexplained gap. Second, this is the version reference multiple-sequence
alignments ship under — not yet in this build, but the version number is reserved for that pairing
rather than incrementing again once they land.

Release 3.0.0 was the major break within that accumulated line. Three properties of it are
incompatible with 2.4.1 for anyone reading the columns, and all three still hold here:

* `engineered_or_construct` moves TRUE to FALSE on 511 records, because 2.4.1's predicate matched
  the database division code as free text and reported where a sequence was deposited;
* `sequence_scope` is **empty**, where 2.4.1 filled all 24,301 rows;
* about 3,400 `poliovirus_classification` cells and 2,200 `virus_type` cells are blank-because-
  undetermined, where 2.4.1 filled them from inputs this pipeline does not have.

3.1.0 added one thing: `R-MEMBERSHIP-AA-1` now decides carve membership for records whose GenBank
lineage does not name the `Enterovirus` genus, so the row set is 24,308 rather than 24,285. That is
23 rows *added* and none removed, and no column semantics change — a consumer's existing queries
return the same answers for the same accessions. Hence a minor bump.

The 23 are the honest consequence of measuring rather than assuming. 15 of them are records 2.4.1
carves and 3.0.0 could not reach, which was 3.0.0's largest declared gap. The other 8 are records
2.4.1 does *not* carve and the declared rule says it should: six are byte-identical to a record the
release already carves, and two are poliovirus capsid by the catalog's own amino-acid threshold.
`derive/metadata.UNDECLARED_EXCLUSIONS` names all eight and `audit/membership_rescue.tsv` shows the
distance or the twin that admitted each one.

Two records remain outside: `E00765.1` and `E01571.1`, which sit in the rule's undecided 8-15% band.

3.2.0 added two more things, both additive in the same sense.

**A curated classification now entails poliovirus membership.** A curator asserting
`classification=cVDPV` has asserted a poliovirus, because that vocabulary is poliovirus-only —
there is no non-polio reading of `cVDPV` or `nOPV-L`. The precedence check in `derive/partition.py`
tested the organism name before the ledger, so 259 records whose organism name is `Enterovirus C`
or `Enterovirus coxsackiepol` (the polio-*containing* species, hence uninformative on its own)
declined `virus_group`, and then declined `poliovirus_classification` for "following" a partition
that a paper-based judgement in the ledger had already settled. All 259 fill `virus_group`,
`curation_status` and `poliovirus_classification`, all 259 land on the value 2.4.1 already ships,
and none was filled before.

**Two audit views the build could already produce were written.** `audit/rules.tsv.gz`
reproduces `final/audit/rules.tsv.gz` byte-for-byte, and the divergence measurement R-CLASS-2
decides `poliovirus_classification` from — previously computed on every build and discarded once
the verdict was recorded — got its own audit view. Both were new files; no existing column or file
changed shape.

3.3.0 adds one more, to the same rule and the same view. **A capsid (P1: VP4-VP2-VP3-VP1)
nucleotide fallback for records VP1 alone cannot reach.** 1,911 carved, name-serotyped records have
no usable VP1; `derive/evidence.compare_capsid_nt` measures divergence over the whole capsid
instead, over the same published thresholds — the same VP1-first / P1-fallback precedence
MAD-VDPV's own sequence classifier states outright. 148 records newly resolve, all agreeing with the
shipped classification wherever 2.4.1 has one to compare against, which is why `audit/
classification_divergence.tsv.gz` carries that name rather than `vp1_divergence.tsv.gz`: a `basis`
column now names which region decided each row.

The fallback needed a guard VP1 does not. VP1 in poliovirus has no indels relative to Sabin — a
measured fact, and the reason an ungapped single-offset comparison is exact there — but that fact
does not extend to VP4, VP2 or VP3. Two records surfaced this directly: a run of mismatches at the
unrelated-sequence rate beginning at one exact position, resolved by shifting the query one
nucleotide from that point on. A real indel in a coding, replicating poliovirus genome must be a
multiple of three to preserve the reading frame, so a one-nucleotide break is a single bad base
call in the deposit, not biology. `derive/evidence.py` declines the whole comparison when any
150 nt chunk of it deviates from the window's own divergence by more than a measured floor — the
three broken windows this found sit at 21.5, 21.8 and 55.2 percentage points of internal deviation;
the next-highest genuine one sits at 8.1.

`docs/classification-migration-gap.md` accounts for every one of the 2,011 remaining differences
from 2.4.1's `poliovirus_classification` by category — mostly epidemiological attribution (`cVDPV`
vs `iVDPV` vs `wild`) that no property of a sequence carries, which is why this pipeline still ships
`VDPV` or blank rather than guessing.

## Why the manifest names hashes rather than a git sha

A git sha identifies a checkout, not the data. What determines this build is three inputs — the
frozen archive, the decision ledger and the rule catalog — plus the code. All four are hashed here,
so two builds can be compared for equality without either tree being present, and a difference
points at *which* of the four moved.

There is no git sha at all, and that started as a constraint and ended as the better design.
Reading `.git` is refused under `--guard-inputs` in a git worktree, where `.git` points at
`<main repo>/.git/worktrees/<name>/` and really is outside the clone. But a commit would have been
the weaker stamp anyway: it covers documentation and test edits that cannot change an artifact, and
misses uncommitted ones that can.

## What is deliberately absent

No wall-clock timestamp. A date in a hashed artifact makes the same inputs produce different bytes
tomorrow, which would destroy the one property that makes a rebuild checkable. The release is
identified by its inputs and its commit, both of which are facts about the build rather than about
when it happened.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from enterovirus_genbank_curated.contracts import (
    CANONICAL_COLUMNS,
    DECISIONS_LEDGER_PATH,
    ContractError,
    sha256_file,
)
from enterovirus_genbank_curated.derive.metadata import PENDING_COLUMNS, TRANSPORTED_COLUMNS
from enterovirus_genbank_curated.export.source import deterministic_text_writer, write_tsv
from enterovirus_genbank_curated.registry.rules import RULES_CATALOG_PATH

RELEASE_VERSION = "4.0.0"
SCHEMA_VERSION = "2.4.1"
BASELINE_RELEASE = "2.4.1"

BUILD_MANIFEST_RELATIVE = "audit/build_manifest.json"
FILE_MANIFEST_RELATIVE = "audit/release_file_manifest.tsv"
FILE_MANIFEST_COLUMNS = ("path", "hash_scope", "sha256", "authoritative", "notes")
FILE_BYTES = "file_bytes"

# Every artifact this build writes, declared rather than discovered. The manifest writer used to
# `rglob` its destination, which was harmless while the destination was always an empty scratch
# directory and wrong the moment the build was pointed at `final/`: it would have hashed the carried
# alignment layer, the source layer and a stray `.DS_Store` into a manifest claiming they were this
# build's output. Declaring the list also turns a writer that silently stopped emitting something
# into a failed build rather than a shorter manifest.
BUILD_ARTIFACT_RELATIVES = (
    "audit/build_manifest.json",
    "audit/classification_divergence.tsv.gz",
    "audit/decision_applications.tsv.gz",
    "audit/membership_rescue.tsv",
    "audit/projection_provenance.tsv.gz",
    "audit/rules.tsv.gz",
    "canonical/metadata_transport_coverage.json",
    "canonical/sequence_metadata.tsv.gz",
    "canonical/sequence_metadata_transport.tsv.gz",
    "canonical/sequence_metadata_vouched.tsv.gz",
    "canonical/sequences.fasta.gz",
    "curation/curation_queue.tsv",
)


def code_digest(repository_root: Path) -> str:
    """One digest over every `.py` file under `src/`, identifying the code that produced the build.

    This replaces the git sha an earlier draft recorded, and the replacement is not a workaround.
    Reading `.git` fails under `--guard-inputs` in a git worktree, where `.git` is a pointer to
    `<main repo>/.git/worktrees/<name>/` and really is outside the clone — and the guard records the
    *attempt*, so catching the error is not enough; the read must not happen.

    It is also the better stamp. A commit identifies a checkout, including changes to documentation
    and tests that cannot alter an artifact, and says nothing about uncommitted edits. This says
    exactly what it means: these bytes of code, over the inputs hashed beside it, produce this
    release.
    """
    digest = hashlib.sha256()
    for path in sorted((repository_root / "src").rglob("*.py")):
        digest.update(path.relative_to(repository_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def column_coverage(
    rows: Sequence[Mapping[str, str]], provenance: Iterable[Mapping[str, str]]
) -> dict[str, dict[str, object]]:
    """Per canonical column: how it was reached, how many cells it filled, how many it declined.

    This is the block that makes a partial release honest rather than merely incomplete. A blank
    cell in the table cannot say whether a rule chose blank or declined; here the two are separate
    numbers, and `declined` counts the cells whose value a curator still owes.
    """
    declined: dict[str, int] = {}
    rules: dict[str, set[str]] = {}
    for row in provenance:
        field = row["canonical_field"]
        rules.setdefault(field, set()).add(row["winning_rule_id"])
        if row["unresolved_reason"]:
            declined[field] = declined.get(field, 0) + 1

    coverage: dict[str, dict[str, object]] = {}
    for column in CANONICAL_COLUMNS:
        filled = sum(1 for row in rows if row[column])
        # `locality` is both: `derive/metadata.py` fills it from `/geo_loc_name` and
        # R-GEO-LOCALITY-2 projects the same closed-form rule with provenance. Reporting only one of
        # the two would make a reader think the other did not happen.
        if column in TRANSPORTED_COLUMNS and column in rules:
            source = "transported_and_projected"
        elif column in TRANSPORTED_COLUMNS:
            source = "transported"
        elif column in rules:
            source = "projected"
        else:
            source = "pending"
        entry: dict[str, object] = {
            "source": source,
            "filled": filled,
            "blank": len(rows) - filled,
            "declined": declined.get(column, 0),
        }
        if column in rules:
            entry["rules"] = sorted(rules[column])
        if column in PENDING_COLUMNS:
            entry["pending_reason"] = PENDING_COLUMNS[column]
        coverage[column] = entry
    return coverage


def write_release_manifests(
    output_dir: Path,
    repository_root: Path,
    *,
    rows: Sequence[Mapping[str, str]],
    provenance: Sequence[Mapping[str, str]],
    row_counts: Mapping[str, int],
    application_tally: Mapping[str, int],
    raw_input: Mapping[str, object],
) -> dict[str, str]:
    """Write the build manifest, then hash every artifact into the file manifest.

    Order matters: the file manifest covers the build manifest, so the build manifest is written
    first. Nothing hashes the file manifest itself — a file cannot contain its own digest — and that
    is stated in its own `notes` column rather than left for a reader to notice.
    """
    coverage = column_coverage(rows, provenance)
    empty = sorted(name for name, entry in coverage.items() if entry["filled"] == 0)
    undeclared = [name for name in empty if name not in PENDING_COLUMNS]
    if undeclared:
        raise ContractError(
            f"refusing to stamp a release whose columns {undeclared} are empty without a declared "
            f"reason; add them to PENDING_COLUMNS or find out why they emptied"
        )

    manifest = {
        "release_version": RELEASE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "baseline_release": BASELINE_RELEASE,
        "derivation": (
            "Rebuilt from raw/sequence.gb.zip and registry/ alone, by the rules in "
            "registry/rules.json. No curated master, no network, no path outside the clone, and no "
            "read of final/, which is the comparison target."
        ),
        "code_sha256": code_digest(repository_root),
        "inputs": {
            # Both hashes the parity spec declares, because they answer different questions: the
            # archive hash identifies the file in the clone, the uncompressed hash identifies the
            # GenBank text, and a re-zip with a different compressor changes only the first.
            "raw_archive_sha256": raw_input["archive_sha256"],
            "raw_uncompressed_sha256": raw_input["uncompressed_sha256"],
            "raw_record_count": raw_input["record_count"],
            "decisions_sha256": sha256_file(repository_root / DECISIONS_LEDGER_PATH),
            "rules_sha256": sha256_file(repository_root / RULES_CATALOG_PATH),
        },
        "row_counts": dict(row_counts),
        "decision_applications": dict(application_tally),
        "completeness": {
            "canonical_columns": len(CANONICAL_COLUMNS),
            "transported": len(TRANSPORTED_COLUMNS),
            "projected": sum(
                1 for e in coverage.values() if str(e["source"]).endswith("projected")
            ),
            "pending": sorted(PENDING_COLUMNS),
            "columns_with_declined_cells": {
                name: entry["declined"]
                for name, entry in sorted(coverage.items())
                if entry["declined"]
            },
            "reading_a_blank_cell": (
                "A blank is not a claim that the value is absent in nature. It is either a value a "
                "rule chose (a locality that would repeat admin1) or a cell no rule could decide. "
                "audit/projection_provenance.tsv.gz carries unresolved_reason per cell and "
                "curation/curation_queue.tsv groups the undecided ones into questions."
            ),
        },
        "column_coverage": coverage,
    }
    path = output_dir / BUILD_MANIFEST_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_text_writer(path) as handle:
        handle.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    entries = []
    for relative in BUILD_ARTIFACT_RELATIVES:
        artifact = output_dir / relative
        if not artifact.is_file():
            raise ContractError(
                f"refusing to stamp a release missing its own declared artifact {relative}"
            )
        entries.append(
            {
                "path": relative,
                "hash_scope": FILE_BYTES,
                "sha256": sha256_file(artifact),
                "authoritative": "TRUE",
                "notes": "",
            }
        )
    entries.append(
        {
            "path": FILE_MANIFEST_RELATIVE,
            "hash_scope": "self",
            "sha256": "",
            "authoritative": "TRUE",
            "notes": "this file; a manifest cannot carry its own digest",
        }
    )
    write_tsv(output_dir / FILE_MANIFEST_RELATIVE, FILE_MANIFEST_COLUMNS, entries)
    return {entry["path"]: entry["sha256"] for entry in entries}
