"""Write the normalized source relations as TSV, Parquet and a convenience DuckDB.

Determinism is the point. Two builds from the same input must produce the same bytes, so:

* gzip is written with `mtime=0` — `gzip.open` otherwise embeds a wall clock and the bytes differ
  on every run;
* the line terminator is pinned to `\\n` rather than inheriting the platform's;
* column order comes from the declared `TABLE_COLUMNS`, not from dict iteration order.

Quoting is `csv`'s default QUOTE_MINIMAL. Columns listed in `RAW_COLUMNS` hold submitter prose and
may contain tabs and newlines, so they *must* be quoted — and every reader must use the same
quoting or it will count continuation lines as rows.

DuckDB file bytes are deliberately not reproducible; the release manifest records a
logical-content hash for that file instead.
"""

from __future__ import annotations

import csv
import gzip
import io
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from enterovirus_genbank_curated.genbank.parse import INTEGER_COLUMNS, TABLE_COLUMNS


@contextmanager
def deterministic_text_writer(path: Path) -> Iterator[io.TextIOWrapper]:
    """Open a text stream whose bytes do not depend on when it was written.

    Gzip when the suffix is `.gz`. Two things matter here beyond `mtime=0`:

    * `GzipFile` does not own a `fileobj` passed to it, so closing the `GzipFile` does not close
      the underlying `BufferedWriter`. Relying on refcount collection to flush it is a CPython
      implementation detail that truncates the file under other runtimes. Both are closed here.
    * The caller writes to a sibling temp path which is renamed into place only on success, so a
      failure mid-write leaves no file rather than a short one that still decompresses cleanly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f".{path.name}.partial")
    raw = scratch.open("wb")
    try:
        if path.suffix == ".gz":
            binary: Any = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
        else:
            binary = raw
        stream = io.TextIOWrapper(binary, encoding="utf-8", newline="")
        try:
            yield stream
            stream.flush()
        finally:
            stream.close()
            if binary is not raw:
                binary.close()
    except BaseException:
        raw.close()
        scratch.unlink(missing_ok=True)
        raise
    raw.close()
    scratch.replace(path)


def write_tsv(
    path: Path,
    columns: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> int:
    """Write a TSV (gzipped when the suffix is `.gz`). Returns the data-row count.

    Values are written as the parser produced them. The writer deliberately does NOT re-apply
    `collapse()`/`verbatim()`: the parser has already chosen per column, and a second `collapse()`
    over a prose column could only destroy whitespace the first pass preserved. Non-string values
    are a parser bug and raise rather than being coerced into something plausible.
    """
    with deterministic_text_writer(path) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(columns), delimiter="\t", lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        count = 0
        for row in rows:
            undeclared = set(row) - set(columns)
            if undeclared:
                raise ValueError(f"{path.name}: row has undeclared columns {sorted(undeclared)}")
            emitted = {}
            for column in columns:
                value = row.get(column, "")
                if not isinstance(value, str):
                    raise TypeError(
                        f"{path.name}.{column}: expected str from the parser, got "
                        f"{type(value).__name__}"
                    )
                emitted[column] = value
            writer.writerow(emitted)
            count += 1
    return count


def source_column_type(column: str) -> str:
    return "BIGINT" if column in INTEGER_COLUMNS else "VARCHAR"


def write_source_tsv(output_dir: Path, tables: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    """Write every declared relation to `<output_dir>/normalized_tsv/<name>.tsv.gz`."""
    counts: dict[str, int] = {}
    for name, columns in TABLE_COLUMNS.items():
        if name not in tables:
            raise ValueError(f"missing declared source table: {name}")
        counts[name] = write_tsv(
            output_dir / "normalized_tsv" / f"{name}.tsv.gz", columns, tables[name]
        )
    undeclared = sorted(set(tables) - set(TABLE_COLUMNS))
    if undeclared:
        raise ValueError(f"undeclared source tables were produced: {undeclared}")
    return counts


def write_source_relational(output_dir: Path) -> None:
    """Load the written TSVs into DuckDB and emit Parquet, with integer columns really typed.

    Every column is read as VARCHAR and integer columns are then cast explicitly, with `NULLIF('')`
    so an absent ordinal becomes NULL rather than a cast error.

    Note a real difference between tiers, faithfully inherited from v2.1.5: DuckDB's `read_csv_auto`
    maps *every* empty unquoted field to NULL, VARCHAR included. So the relational tier cannot
    distinguish "empty string" from "absent" in text columns, while the TSV tier can — e.g.
    `references.remark` has 41,477 empty strings in the TSV and 41,477 NULLs in the Parquet. The
    TSVs are the loss-preserving tier; Parquet and DuckDB are conveniences.
    """
    import duckdb

    db_path = output_dir / "genbank_source.duckdb"
    parquet_dir = output_dir / "parquet"
    parquet_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)

    connection = duckdb.connect(str(db_path))
    try:
        for name, columns in TABLE_COLUMNS.items():
            tsv_path = output_dir / "normalized_tsv" / f"{name}.tsv.gz"
            if not tsv_path.is_file():
                raise FileNotFoundError(f"expected {tsv_path} before the relational export")
            escaped = str(tsv_path).replace("'", "''")
            select = ", ".join(
                f'CAST(NULLIF("{c}", \'\') AS BIGINT) AS "{c}"'
                if source_column_type(c) == "BIGINT"
                else f'"{c}"'
                for c in columns
            )
            connection.execute(
                f'CREATE TABLE "{name}" AS SELECT {select} '
                f"FROM read_csv_auto('{escaped}', delim='\\t', header=true, all_varchar=true)"
            )
            destination = str(parquet_dir / f"{name}.parquet").replace("'", "''")
            connection.execute(
                f"COPY \"{name}\" TO '{destination}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
    finally:
        connection.close()
