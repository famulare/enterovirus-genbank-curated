"""Write the curation queue.

Plain TSV rather than gzip: this file exists to be opened, sorted and filled in by a person, and a
curator should not have to decompress their own worklist.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from enterovirus_genbank_curated.curate.queue import QUEUE_COLUMNS, QueueGroup
from enterovirus_genbank_curated.export.source import write_tsv

QUEUE_RELATIVE = "curation/curation_queue.tsv"


def write_curation_queue(output_dir: Path, groups: Iterable[QueueGroup]) -> int:
    return write_tsv(
        output_dir / QUEUE_RELATIVE, QUEUE_COLUMNS, [group.as_row() for group in groups]
    )
