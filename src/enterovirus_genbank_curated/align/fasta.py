"""Plain, unwrapped FASTA read/write for the scratch-tier files a tool invocation actually
consumes and produces — one line per sequence, no line wrapping.

Not the final artifact writer: the committed `.sto.gz`/`_aln.fasta.gz` outputs are a different
concern (gzip, a specific dialect) that belongs to `export/`, reusing its existing gzip writer
rather than adding a second one here.
"""

from __future__ import annotations

from pathlib import Path

from enterovirus_genbank_curated.contracts import ContractError


def read_fasta(path: Path) -> dict[str, str]:
    """{record id: sequence}. The id is the header up to the first whitespace, matching how MAFFT
    itself reads and re-emits FASTA headers."""
    sequences: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if line.startswith(">"):
                if current is not None:
                    sequences[current] = "".join(chunks)
                current = line[1:].split()[0]
                if current in sequences:
                    raise ContractError(f"{path} has two records for {current!r}")
                chunks = []
            elif line:
                chunks.append(line)
    if current is not None:
        sequences[current] = "".join(chunks)
    return sequences


def write_fasta(sequences: dict[str, str], path: Path) -> None:
    """Write in sorted-by-id order. Sorting internally, rather than trusting caller order, is what
    makes two builds byte-identical regardless of which order upstream dicts happened to iterate
    in."""
    with path.open("w", encoding="utf-8") as handle:
        for accession in sorted(sequences):
            handle.write(f">{accession}\n{sequences[accession]}\n")
