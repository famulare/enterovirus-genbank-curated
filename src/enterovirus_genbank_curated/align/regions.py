"""`final/alignments/reference_region_coordinates.tsv`, read back from the shipped source layer.

A thin wrapper. The derivation moved to `derive/regions.py` on 2026-08-14 so `build-metadata` could
write this file from the tables it already holds, which is what let it stop being a *carried*
artifact — a release file whose producer no build could call, because a build may not read `final/`.

What is left here is the `final/`-reading entry point `align/build.py`'s anchor path needs: it runs
before the tool guard arms and has no parsed tables to hand. `tests/test_module_boundaries.py` names
this module's `final/` access as a deliberate carve-out, and that carve-out is now this file's whole
reason to exist.
"""

from __future__ import annotations

from pathlib import Path

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.derive.regions import Region, derive_regions, render

OUTPUT_PATH = "final/alignments/reference_region_coordinates.tsv"


def _rows(repository_root: Path, relative: str) -> list[dict[str, str]]:
    from enterovirus_genbank_curated.oracle.release import read_tsv_gz

    header, rows = read_tsv_gz(repository_root / relative)
    return [dict(zip(header, row, strict=False)) for row in rows]


def regions_from_release(repository_root: Path) -> list[Region]:
    """Derive the regions from `final/source/normalized_tsv/` plus the canonical lengths."""
    from enterovirus_genbank_curated.oracle.release import read_tsv_gz

    header, rows = read_tsv_gz(repository_root / contract.CANONICAL_METADATA)
    lengths = {
        row[header.index(contract.ACCESSION)].split(".", 1)[0]: int(
            row[header.index(contract.SEQUENCE_LENGTH_NT)]
        )
        for row in rows
    }
    return derive_regions(
        _rows(repository_root, contract.SOURCE_FEATURES),
        _rows(repository_root, contract.SOURCE_FEATURE_PARTS),
        _rows(repository_root, contract.SOURCE_FEATURE_QUALIFIERS),
        lengths,
        contract.SABIN_REFERENCES,
    )


def build(repository_root: Path) -> str:
    return render(regions_from_release(repository_root))
