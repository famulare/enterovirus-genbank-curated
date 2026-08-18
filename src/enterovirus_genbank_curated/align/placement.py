"""Was each row *placed* coherently, or scattered across the block?

`mafft --addfragments` can spread a short sequence's residues across a wide column range instead of
putting them in one contiguous run. Downstream that is indistinguishable from a sequence riddled
with indels: a 66-residue ORF spread over 223 columns reads as a record with dozens of deletions,
and every codon it does contribute is compared against a non-homologous reference codon.

**Nothing else in this repository can see it.** `validation/alignment.py` reads block widths from
the provenance the same build wrote, and the identity oracle is a whole-population average that
does not move on gap-penalty changes. So a build could scatter a quarter of its addon rows and
every existing gate would report PASS — which is exactly what happened upstream, where `--lop` sat
at MAFFT's default -2.00 through every build and 25.0% of addon rows were badly placed.

Ported 2026-08-15. This repository already carried the *fix* — `CodonSpec.pass2_local_gap_open` is
-24.0, matching the upstream value screened for it — but not the *check*, which is the worse half to
be missing: a parameter is only known-good while something measures it.

## Why the obvious metrics do not work, all measured rather than assumed

* **Count of maximal residue runs.** Ranks the good rows worse. This population is ~88% fragments,
  so the alignment carries many sparse insertion columns and every row skips most of them. On
  `EV_unified`: median 50 runs for confident backbone rows against 4 for the addon tier.
* **Dilution (span / residues).** At matched length (<= 90 aa) the addon tier's median is 3.19
  against the backbone's 3.28 — indistinguishable.
* **Occupancy against globally well-covered columns.** Degenerate: on `EV_unified`'s CDS only 831
  of 7,992 columns are filled by half of *all* rows, so a short fragment outside them scores a
  vacuous 1.0.

What separates them is normalising by **local depth** — the rows that had the opportunity to fill a
column, meaning those whose own first-to-last span covers it:

    consensus column   occupied(col) >= QUORUM * reaching(col)
    occupancy(row)     consensus columns the row fills / consensus columns inside its own span

A contiguously placed fragment fills nearly every consensus column it spans, so it scores ~1.0
however short it is and wherever it sits. A shredded fragment spans consensus columns it does not
fill, so it falls toward zero.

## What it says about this release, and what it does not

Run on 5.0.0's artifacts: NPEV 1.3% badly placed, EV 0.7%, POLIO 0.2%, all against a 5% ceiling,
with median occupancy 1.000 in every case. That is the number this gate exists to hold down.

**It is not an explanation of the block's width, and an earlier version of this docstring claimed it
was.** That claim — that `NPEV_unified` is wide because the `--lop` fix opens honest insertion
columns, so "narrower was worse" — is false, and measuring 2.4.1 rather than reasoning about it is
what showed that. 2.4.1's NPEV CDS is 7,677 columns over 14,050 rows carrying 43,110 N residues with
**zero** all-N columns, at 1.377% badly placed. The pre-filter 5.0.0 build was 14,598 columns
carrying the *same* 43,110 N, at 1.250%. The `--lop` fix bought 0.13 percentage points of placement
and no width at all; the entire ~6,900-column difference was ambiguity padding.

The shipped block, measured on 5.0.0's own bytes: 7,503 CDS columns over 14,218 rows, 25,155 N
residues, 9 columns that are gap-or-N throughout. Those 9 are not a leak — the filter drops whole
*codons*, so an ambiguous nucleotide column whose two codon partners carry real bases stays, and
must.

The lesson worth keeping is the one that produced the wrong claim: placement being good and width
being honest are different properties, and this gate measures only the first. Reading a clean
placement result as a verdict on the width is exactly the substitution it should have prevented.
`codon.drop_unsequenced_codon_columns` addresses the width; this module addresses placement; and
neither stands in for the other.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from enterovirus_genbank_curated.contracts import ContractError

GAP_CHARACTERS = "-."

# Share of the rows *reaching* a column that must occupy it for the column to count as consensus.
# Half is the natural reading, and the addon/backbone separation holds across 0.25-0.75, so the
# result is not sensitive to it.
QUORUM = 0.5

# A row below this fills less than half the consensus columns it spans, which downstream cannot
# tell apart from a heavily deleted sequence.
BADLY_PLACED = 0.5
MAX_BADLY_PLACED_SHARE = 0.05

# The sharpest signal is the shortest coverage band compared against non-addon rows of the *same*
# length: the two add passes run at different gap-open penalties and the tiers have very different
# length distributions, so an unmatched comparison says nothing.
SHORT_CDS_NT = 270
MAX_SHORT_EXCESS_FACTOR = 3.0

ADDON_TIER = "addon"


def row_span(row: str) -> tuple[int, int]:
    """First and last occupied column, or `(-1, -1)` when the row is all gap."""
    first = last = -1
    for index, character in enumerate(row):
        if character not in GAP_CHARACTERS:
            if first < 0:
                first = index
            last = index
    return first, last


def consensus_mask(rows: list[str], quorum: float = QUORUM) -> list[bool]:
    """Which columns a majority of the rows that *reach* them actually occupy."""
    if not rows:
        raise ContractError("placement needs at least one row to build a consensus mask")
    width = len(rows[0])
    occupied = [0] * width
    reaching = [0] * width
    for row in rows:
        first, last = row_span(row)
        if first < 0:
            continue
        for index in range(first, last + 1):
            reaching[index] += 1
            if row[index] not in GAP_CHARACTERS:
                occupied[index] += 1
    return [bool(r) and o >= quorum * r for o, r in zip(occupied, reaching, strict=True)]


def occupancy(row: str, consensus: list[bool]) -> float | None:
    """Share of the consensus columns inside this row's span that it fills.

    `None` when the row spans no consensus column at all. That is the honest answer rather than a
    perfect score, and callers must not average it in — a fragment sitting entirely outside the
    consensus has not been shown to be well placed, only to be unmeasurable this way.
    """
    first, last = row_span(row)
    if first < 0:
        return None
    spanned = filled = 0
    for index in range(first, last + 1):
        if consensus[index]:
            spanned += 1
            if row[index] not in GAP_CHARACTERS:
                filled += 1
    return filled / spanned if spanned else None


def _share_below(values: list[float], threshold: float) -> float:
    return sum(1 for value in values if value < threshold) / len(values) if values else 0.0


def check_addon_placement(
    block: Mapping[str, str], tier_of: Callable[[str], str], label: str
) -> tuple[dict[str, float], list[str]]:
    """`(summary, failures)` for one CDS block. Empty failures means the placement is sound.

    `block` maps accession to that row's CDS columns only — the NCR blocks are placed by `cmalign`
    against a covariance model, not by `--addfragments`, so including them would dilute the signal
    with columns this pass never chose.
    """
    rows = list(block.values())
    consensus = consensus_mask(rows)

    scored: dict[str, list[float]] = {"addon": [], "other": []}
    short: dict[str, list[float]] = {"addon": [], "other": []}
    for accession, row in block.items():
        value = occupancy(row, consensus)
        if value is None:
            continue
        key = "addon" if tier_of(accession) == ADDON_TIER else "other"
        scored[key].append(value)
        if sum(1 for character in row if character not in GAP_CHARACTERS) <= SHORT_CDS_NT:
            short[key].append(value)

    addon = scored["addon"]
    ordered = sorted(addon)
    badly = _share_below(addon, BADLY_PLACED)
    summary = {
        "addon_rows": float(len(addon)),
        "median_occupancy": ordered[len(ordered) // 2] if ordered else float("nan"),
        "badly_placed_share": badly,
        "consensus_columns": float(sum(consensus)),
    }

    failures: list[str] = []
    if badly > MAX_BADLY_PLACED_SHARE:
        failures.append(
            f"{label}: {badly:.1%} of addon rows fill under {BADLY_PLACED:.0%} of the consensus "
            f"columns they span, over the {MAX_BADLY_PLACED_SHARE:.0%} ceiling. The "
            f"--addfragments placement penalty is letting short sequences scatter."
        )
    if short["addon"] and short["other"]:
        addon_share = _share_below(short["addon"], BADLY_PLACED)
        other_share = _share_below(short["other"], BADLY_PLACED)
        summary["short_addon_share"] = addon_share
        summary["short_other_share"] = other_share
        if addon_share > MAX_SHORT_EXCESS_FACTOR * max(other_share, 0.01):
            failures.append(
                f"{label}: short addon rows are "
                f"{addon_share / max(other_share, 0.01):.1f}x worse placed than non-addon rows of "
                f"the same length ({addon_share:.1%} vs {other_share:.1%}), over the "
                f"{MAX_SHORT_EXCESS_FACTOR:.0f}x ceiling"
            )
    return summary, failures

# No single record may open more than this many columns nobody else occupies.
#
# This is a *ceiling*, not a fix, and it exists because of what got through without one. `PX242045`
# opened 2,169 private columns in `NPEV_unified` and `MG692415` 2,022 — between them and
# `MG692413`, 95% of that block's single-row columns and half its width — and every gate in the
# repository reported PASS. `validation/alignment.py` reads widths from the provenance the same
# build wrote; `check_addon_placement` above measures whether rows are *coherent*, and those three
# were perfectly coherent, each a single contiguous run. The defect was visible only by eye, and
# only once somebody asked why the artifact was wide.
#
# `codon.drop_unsequenced_codon_columns` removed the cause — all three runs were ambiguity padding
# — but a filter for the mechanism you already found is not a check for the next one. After it, the
# largest owner in any artifact is 96 columns (`OR129570`, 32 codons in a ~2,200-codon polyprotein,
# real bases): a normal insertion. 200 leaves that room to double while still catching anything of
# the scale that went unnoticed, and there is nothing between 96 and 2,169 to be precise about.
MAX_PRIVATE_COLUMNS_PER_RECORD = 200


def private_column_owners(block: Mapping[str, str]) -> dict[str, int]:
    """How many columns each record is the only occupant of. Records owning none are omitted."""
    rows = list(block.values())
    if not rows:
        return {}
    width = len(rows[0])
    occupied = [0] * width
    for row in rows:
        for index, character in enumerate(row):
            if character not in GAP_CHARACTERS:
                occupied[index] += 1
    private = [index for index in range(width) if occupied[index] == 1]
    owners: dict[str, int] = {}
    for accession, row in block.items():
        count = sum(1 for index in private if row[index] not in GAP_CHARACTERS)
        if count:
            owners[accession] = count
    return owners


# One deposit is over the ceiling and stays over it. Declared by name here rather than silenced by
# raising the ceiling for everyone, so the gate keeps its full strength against the next record and
# this one keeps having to be justified.
#
# `OR538735` carries two internal frameshifts: frame +1 reads as protein at 0.68-0.84 against the
# corpus's own annotated proteins exactly where its declared frame reads 0.00-0.08. That is a
# property of the deposit, not of this pipeline, and no repair here reaches it — it is not a
# boundary-crossing amplicon, so `segment._boundary_cut` declines it, and its private block is
# contiguous with its own body rather than flung away from it, so `codon.gap_flung_clusters`
# declines it too.
#
# Nor is it gateable, which is the part worth recording. 24 records in this corpus show the same
# frameshift pattern; their shifted-window shares spread continuously from 0.015 to 0.50 with no
# empty interval anywhere in it, and ten of them have a *higher* shifted share than `OR538735` while
# placing perfectly well. Any threshold that caught this one would sweep in the other twenty-three
# on a tuned number, which is what every other threshold in this pipeline was chosen to avoid.
#
# Its count still appears in `owners`, so `tests/test_alignment_placement.py`'s pinned table still
# has to state it and a change in it still fails. Exempt from the failure, not from the measurement.
PRIVATE_COLUMN_EXEMPTIONS = {
    "OR538735": "two internal frameshifts; a bad deposit, and not separable from 23 others",
}


def check_private_columns(
    block: Mapping[str, str], label: str, ceiling: int = MAX_PRIVATE_COLUMNS_PER_RECORD,
    exemptions: Mapping[str, str] = MappingProxyType(PRIVATE_COLUMN_EXEMPTIONS),
) -> tuple[dict[str, int], list[str]]:
    """`(owners, failures)`. A record above `ceiling` is holding the block open by itself.

    `owners` reports every record's count including an exempt one — exemption suppresses the
    failure, never the measurement, so a pinned table over `owners` still sees it.
    """
    owners = private_column_owners(block)
    over = sorted(
        (
            (count, accession)
            for accession, count in owners.items()
            if count > ceiling and accession not in exemptions
        ),
        reverse=True,
    )
    failures = [
        f"{label}: {accession} alone occupies {count} columns, over the {ceiling}-column ceiling. "
        f"One record holding a block open is how 7,130 columns of ambiguity padding shipped "
        f"unnoticed; check what that record actually carries there before raising this."
        for count, accession in over
    ]
    return owners, failures
