"""Write the canonical metadata transport and its coverage declaration.

Two files, and the second is not optional. A table holding thirteen of the twenty-six canonical
columns is easy to mistake for the release table, so every build ships a machine-readable statement
of which columns it filled, which it did not, and why — next to the data, not only in docs.
"""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from typing import Any

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.derive.metadata import (
    CANONICAL_COLUMNS,
    PENDING_COLUMNS,
    TRANSPORTED_COLUMNS,
)
from enterovirus_genbank_curated.export.source import deterministic_text_writer, write_tsv

METADATA_TRANSPORT_RELATIVE = "canonical/sequence_metadata_transport.tsv.gz"
COVERAGE_RELATIVE = "canonical/metadata_transport_coverage.json"
# Keyed relative to the release tree, the way `release_file_manifest.tsv` keys its own paths.
# Recorded for a reader of the artifact; nothing resolves it, and a build module may not name a
# release path at all (`tests/test_module_boundaries.py`).
CANONICAL_TARGET = "canonical/sequence_metadata.tsv.gz"

# Shipped canonical order, restricted to what transports, so the artifact diffs column-wise against
# the release table instead of needing a reordering step first.
TRANSPORT_COLUMN_ORDER = tuple(c for c in CANONICAL_COLUMNS if c in set(TRANSPORTED_COLUMNS))


def write_metadata_transport(
    output_dir: Path, rows: list[dict[str, str]], row_counts: dict[str, int]
) -> int:
    written = write_tsv(output_dir / METADATA_TRANSPORT_RELATIVE, TRANSPORT_COLUMN_ORDER, rows)
    coverage: dict[str, Any] = {
        "artifact": METADATA_TRANSPORT_RELATIVE,
        "canonical_target": CANONICAL_TARGET,
        "canonical_columns": list(CANONICAL_COLUMNS),
        "transported_columns": list(TRANSPORT_COLUMN_ORDER),
        "pending_columns": dict(PENDING_COLUMNS),
        "row_counts": dict(row_counts),
    }
    with deterministic_text_writer(output_dir / COVERAGE_RELATIVE) as handle:
        handle.write(json.dumps(coverage, indent=2) + "\n")
    return written


def read_metadata_transport(output_dir: Path) -> list[dict[str, str]]:
    """Read back a written transport, for a parity run whose build happened in another process.

    Reads with the same quoting the writer used, and requires the declared header exactly — a
    truncated or reordered artifact must fail here rather than produce a comparison against
    whatever columns happened to survive.
    """
    path = output_dir / METADATA_TRANSPORT_RELATIVE
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            if tuple(reader.fieldnames or ()) != TRANSPORT_COLUMN_ORDER:
                raise ContractError(
                    f"{path} header is {reader.fieldnames}, not the declared transport columns"
                )
            return list(reader)
    except OSError as exc:
        raise ContractError(f"cannot read the metadata transport {path}: {exc}") from exc
