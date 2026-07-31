"""Regenerate `final/alignments/reference_region_coordinates.tsv` from the normalized source layer.

This is the one alignment artifact that is byte-reproducible *today*, with no aligner and no
toolchain: it is pure annotation arithmetic over the three Sabin reference records, and every input
it needs is in `final/source/normalized_tsv/`, which `evgc parity-source` already rebuilds from
`raw/sequence.gb.zip` and byte-verifies.

The rule, recovered by comparing against the shipped file and confirmed on all three serotypes and
all 39 rows:

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

from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.oracle.release import read_tsv_gz

OUTPUT_PATH = "final/alignments/reference_region_coordinates.tsv"
COLUMNS = ("serotype", "ref_accession", "region", "start", "end", "length")

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


def _feature_index(repository_root: Path) -> tuple[dict, dict, dict]:
    f_header, f_rows = read_tsv_gz(repository_root / contract.SOURCE_FEATURES)
    p_header, p_rows = read_tsv_gz(repository_root / contract.SOURCE_FEATURE_PARTS)
    q_header, q_rows = read_tsv_gz(repository_root / contract.SOURCE_FEATURE_QUALIFIERS)
    features = [dict(zip(f_header, row, strict=False)) for row in f_rows]
    parts: dict[str, list[dict]] = {}
    for row in p_rows:
        part = dict(zip(p_header, row, strict=False))
        parts.setdefault(part["feature_id"], []).append(part)
    products: dict[str, str] = {}
    for row in q_rows:
        qualifier = dict(zip(q_header, row, strict=False))
        if qualifier["qualifier_name"] == "product":
            products.setdefault(qualifier["feature_id"], qualifier["qualifier_value"])
    return features, parts, products


def _span(parts: list[dict], feature_id: str) -> tuple[int, int]:
    if not parts:
        raise ContractError(f"{feature_id} has no location parts")
    starts = [int(part["start_1based"]) for part in parts]
    ends = [int(part["end_1based_inclusive"]) for part in parts]
    return min(starts), max(ends)


def derive_regions(repository_root: Path) -> list[Region]:
    """Build every region row, in serotype then genome order."""
    features, parts, products = _feature_index(repository_root)

    header, rows = read_tsv_gz(repository_root / contract.CANONICAL_METADATA)
    lengths = {
        row[header.index(contract.ACCESSION)].split(".", 1)[0]: int(
            row[header.index(contract.SEQUENCE_LENGTH_NT)]
        )
        for row in rows
    }

    by_record: dict[str, list[dict]] = {}
    for feature in features:
        by_record.setdefault(feature["record_id"].split(".", 1)[0], []).append(feature)

    out: list[Region] = []
    for serotype in ("PV1", "PV2", "PV3"):
        accession = contract.SABIN_REFERENCES[serotype]
        record_features = by_record.get(accession)
        if not record_features:
            raise ContractError(f"{accession} has no features in {contract.SOURCE_FEATURES}")

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


def render(regions: list[Region]) -> str:
    """Render the table exactly as shipped: tab-delimited, `\\n` terminated, header first."""
    lines = ["\t".join(COLUMNS)]
    lines.extend("\t".join(region.as_row()) for region in regions)
    return "\n".join(lines) + "\n"


def build(repository_root: Path) -> str:
    return render(derive_regions(repository_root))
