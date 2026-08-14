"""Reference region coordinates: pure annotation arithmetic over the three Sabin records.

The derivation lived in `align/regions.py` and read `final/source/normalized_tsv/` off disk, which
made it an alignment-layer routine and left `reference_region_coordinates.tsv` a *carried* file — a
release artifact with a producer that no build could call, because a build may not read `final/`.

The core is here now, taking the parsed tables `build-metadata` already holds in memory, so the file
is written by the build that computes it. `align/regions.py` keeps its `final/`-reading wrapper for
`alignment-build`'s anchor path, which runs before the tool guard arms and has no in-memory tables.

Nothing about the arithmetic changed. The rule, recovered by comparing against the shipped file and
confirmed on all three serotypes and all 39 rows:

- `5UTR` spans 1 to `CDS_start - 1`;
- each `mat_peptide` contributes one row at its own coordinates, with its `product` qualifier as the
  region label;
- `3D` is **extended to `CDS_end`** rather than stopping at its own `mat_peptide` boundary, because
  the CDS includes the stop codon and the final mature peptide does not. PV1 is the clearest case:
  the shipped row ends at 7372 where the `mat_peptide` ends at 7369;
- `3UTR` spans `CDS_end + 1` to the record length.

Region labels need a prefix strip: the `product` qualifiers are `"protein VP4"` … `"protein 3D"`,
not the bare names the shipped table carries.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from enterovirus_genbank_curated.contracts import ContractError

COLUMNS = ("serotype", "ref_accession", "region", "start", "end", "length")

# The three Sabin records the region frame is built from. Declared here rather than in
# `align/contract.py` because the frame is a fact about the annotation, not about any alignment:
# `derive/evidence.py` measures divergence against these, `export/audit.py` writes their
# coordinates, and `align/` reads them back. `align.contract` re-exports the name it has used.
SABIN_REFERENCES = {"PV1": "AY184219", "PV2": "AY184220", "PV3": "AY184221"}

# Order the shipped file uses: the 5' untranslated region, the twelve mature peptides in genome
# order, then the 3' untranslated region.
REGION_ORDER = (
    "5UTR",
    "VP4", "VP2", "VP3", "VP1",
    "2A", "2B", "2C",
    "3A", "3B", "3C", "3D",
    "3UTR",
)

# `product` qualifiers are spelled "protein VP4". The shipped table carries "VP4".
PRODUCT_PREFIX = "protein "

# The mature peptide whose row is extended to the end of the CDS, absorbing the stop codon.
STOP_CODON_REGION = "3D"


@dataclass(frozen=True)
class Region:
    serotype: str
    ref_accession: str
    region: str
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def as_row(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.serotype,
            self.ref_accession,
            self.region,
            str(self.start),
            str(self.end),
            str(self.length),
        )


def _span(parts: Sequence[Mapping[str, str]], feature_id: str) -> tuple[int, int]:
    if not parts:
        raise ContractError(f"{feature_id} has no location parts")
    starts = [int(part["start_1based"]) for part in parts]
    ends = [int(part["end_1based_inclusive"]) for part in parts]
    return min(starts), max(ends)


def derive_regions(
    features: Iterable[Mapping[str, str]],
    location_parts: Iterable[Mapping[str, str]],
    qualifiers: Iterable[Mapping[str, str]],
    lengths: Mapping[str, int],
    sabin_references: Mapping[str, str],
) -> list[Region]:
    """Every region row, in serotype then genome order.

    Takes the three feature tables and a `{accession: length}` map rather than a repository root, so
    the same code serves a build holding parsed tables and a wrapper reading them back off disk.
    """
    parts: dict[str, list[Mapping[str, str]]] = {}
    for part in location_parts:
        parts.setdefault(part["feature_id"], []).append(part)
    products: dict[str, str] = {}
    for qualifier in qualifiers:
        if qualifier["qualifier_name"] == "product":
            products.setdefault(qualifier["feature_id"], qualifier["qualifier_value"])

    by_record: dict[str, list[Mapping[str, str]]] = {}
    for feature in features:
        by_record.setdefault(feature["record_id"].split(".", 1)[0], []).append(feature)

    out: list[Region] = []
    for serotype in ("PV1", "PV2", "PV3"):
        accession = sabin_references[serotype]
        record_features = by_record.get(accession)
        if not record_features:
            raise ContractError(f"{accession} has no features in the source layer")

        cds = [f for f in record_features if f["feature_key"] == "CDS"]
        if len(cds) != 1:
            raise ContractError(
                f"{accession} has {len(cds)} CDS features; the region frame assumes exactly one"
            )
        cds_start, cds_end = _span(parts.get(cds[0]["feature_id"], []), cds[0]["feature_id"])

        peptides: dict[str, tuple[int, int]] = {}
        for feature in record_features:
            if feature["feature_key"] != "mat_peptide":
                continue
            label = products.get(feature["feature_id"], "").removeprefix(PRODUCT_PREFIX)
            if not label:
                raise ContractError(f"{feature['feature_id']} has no product qualifier")
            if label in peptides:
                raise ContractError(f"{accession} has two mat_peptides labelled {label!r}")
            peptides[label] = _span(parts.get(feature["feature_id"], []), feature["feature_id"])

        expected = set(REGION_ORDER) - {"5UTR", "3UTR"}
        if set(peptides) != expected:
            raise ContractError(
                f"{accession} mature peptides {sorted(peptides)} do not match the declared "
                f"frame {sorted(expected)}"
            )

        length = lengths[accession]
        for region in REGION_ORDER:
            if region == "5UTR":
                start, end = 1, cds_start - 1
            elif region == "3UTR":
                start, end = cds_end + 1, length
            else:
                start, end = peptides[region]
                if region == STOP_CODON_REGION:
                    # Absorb the stop codon: the CDS includes it, the mature peptide does not.
                    end = cds_end
            out.append(Region(serotype, accession, region, start, end))
    return out


def render(regions: Sequence[Region]) -> str:
    """Render the table exactly as shipped: tab-delimited, `\\n` terminated, header first."""
    lines = ["\t".join(COLUMNS)]
    lines.extend("\t".join(region.as_row()) for region in regions)
    return "\n".join(lines) + "\n"
