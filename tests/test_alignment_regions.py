"""`reference_region_coordinates.tsv` is byte-reproducible from the normalized source layer.

This is a real parity result, not a shape check: the 39-row table the release ships is regenerated
from `final/source/normalized_tsv/` — which `evgc parity-source` rebuilds from `raw/sequence.gb.zip`
and byte-verifies — and compared byte for byte. It is the first of the nineteen carried alignment
files to stop being merely pinned and start being *derived*.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import contract, regions
from enterovirus_genbank_curated.contracts import ContractError

# The pinned hash from tests/test_carried_files.py. Repeated here on purpose: if the two ever
# disagree, one of the two mechanisms is wrong, and that is worth failing over.
SHIPPED_SHA256 = "41420f9e5a5d3804f6370c0b41fa487365e5dc0a85e1f85c191082f15f9551e1"

EXPECTED_ROWS = 39  # 13 regions x 3 serotypes


def test_the_regenerated_table_is_byte_identical_to_the_shipped_one(
    repository_root: Path,
) -> None:
    built = regions.build(repository_root)
    shipped = (repository_root / regions.OUTPUT_PATH).read_text(encoding="utf-8")
    assert built == shipped
    assert hashlib.sha256(built.encode("utf-8")).hexdigest() == SHIPPED_SHA256


def test_the_build_is_deterministic(repository_root: Path) -> None:
    assert regions.build(repository_root) == regions.build(repository_root)


def test_the_table_has_the_expected_shape(repository_root: Path) -> None:
    rows = regions.derive_regions(repository_root)
    assert len(rows) == EXPECTED_ROWS
    assert len(regions.REGION_ORDER) * 3 == EXPECTED_ROWS
    for serotype in ("PV1", "PV2", "PV3"):
        got = [r.region for r in rows if r.serotype == serotype]
        assert got == list(regions.REGION_ORDER), f"{serotype} regions out of order"


def test_the_regions_tile_the_genome_without_gap_or_overlap(repository_root: Path) -> None:
    """Every base from 1 to the record length is covered exactly once.

    Worth checking independently of byte-parity: it is the property that makes the table usable as a
    coordinate frame, and byte-parity against a file nobody has verified would not establish it.
    """
    rows = regions.derive_regions(repository_root)
    for serotype in ("PV1", "PV2", "PV3"):
        spans = [(r.start, r.end) for r in rows if r.serotype == serotype]
        assert spans[0][0] == 1
        for (_, prev_end), (next_start, _) in zip(spans, spans[1:], strict=False):
            assert next_start == prev_end + 1, f"{serotype} has a gap or overlap at {prev_end}"


def test_the_declared_length_column_is_consistent(repository_root: Path) -> None:
    for region in regions.derive_regions(repository_root):
        assert region.length == region.end - region.start + 1
        assert region.length > 0


def test_the_sabin_frame_width_matches_the_canonical_sequence_length(
    repository_root: Path,
) -> None:
    """7,441 / 7,439 / 7,432 — the same integers the shipped provenance calls
    `n_sabin_reference_columns`, giving the anchored stack a free invariant."""
    from enterovirus_genbank_curated.oracle.release import read_tsv_gz

    header, rows = read_tsv_gz(repository_root / contract.CANONICAL_METADATA)
    acc, length = header.index(contract.ACCESSION), header.index(contract.SEQUENCE_LENGTH_NT)
    lengths = {row[acc].split(".", 1)[0]: int(row[length]) for row in rows}

    derived = regions.derive_regions(repository_root)
    for serotype, expected in (("PV1", 7441), ("PV2", 7439), ("PV3", 7432)):
        accession = contract.SABIN_REFERENCES[serotype]
        assert lengths[accession] == expected
        assert max(r.end for r in derived if r.serotype == serotype) == expected


def test_the_stop_codon_extension_is_real_and_not_cosmetic(repository_root: Path) -> None:
    """`3D` must end past its own `mat_peptide`, or the rule has been silently dropped.

    PV1 is the clearest case: the shipped row ends at 7372 while the mature peptide ends at 7369.
    Asserting the shipped numbers here means a future refactor that ends `3D` at the peptide
    boundary fails rather than shifting the CDS frame by three bases.
    """
    rows = {(r.serotype, r.region): r for r in regions.derive_regions(repository_root)}
    assert rows[("PV1", "3D")].end == 7372
    assert rows[("PV1", "3UTR")].start == 7373
    assert rows[("PV2", "3D")].end == 7371
    assert rows[("PV3", "3D")].end == 7363


def test_the_product_prefix_is_stripped(repository_root: Path) -> None:
    """The qualifiers read `protein VP4`; the table must not."""
    for region in regions.derive_regions(repository_root):
        assert not region.region.startswith(regions.PRODUCT_PREFIX)
        assert " " not in region.region


def test_a_missing_mature_peptide_is_refused(repository_root: Path, monkeypatch) -> None:
    """Fail closed: a frame with a peptide missing must raise, not emit a short table."""
    real = regions._feature_index

    def without_vp1(root: Path):
        features, parts, products = real(root)
        products = {
            fid: value for fid, value in products.items() if value != "protein VP1"
        }
        return features, parts, products

    monkeypatch.setattr(regions, "_feature_index", without_vp1)
    with pytest.raises(ContractError, match="do not match the declared|no product qualifier"):
        regions.derive_regions(repository_root)
