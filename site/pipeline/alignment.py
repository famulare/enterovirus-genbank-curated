"""Figure set 6: the alignment the other five figures reduce to points.

One artifact per selection and region, carrying the normalized alignment codes
themselves rather than a precomputed summary. Two things follow from that choice.

The browser derives both of the figure's cell vocabularies — coverage, and the
per-codon divergence classification that mirrors `divergence.measure` — from one
payload, so they cannot disagree about the bytes they describe. And the deep zoom
can show actual bases, which a state-code payload could not.

The risk it takes on is that the TypeScript derivation drifts from `divergence.py`.
That is closed by a test rather than by a redundant payload: `test/alignment.test.ts`
recomputes the counts from this artifact and asserts they equal `panels/*.json`
exactly, which checks the two implementations against each other instead of checking
Python against itself.

**Span encoding.** A record covers one contiguous stretch of its region and nothing
outside it, so a dense matrix spends 44-92% of its bytes on gap. Each row therefore
ships `[first, last]` and nibble-packed codes for that stretch alone. Row offsets are
not shipped: a row occupies `ceil((last - first + 1) / 2)` bytes and the browser
accumulates the same arithmetic, so an offset table would be a second copy of a
derivable fact.

**A gzipped binary container, not base64 in JSON.** The payload is a length-prefixed
JSON header followed by raw little-endian sections, gzipped whole, and inflated in the
browser with `DecompressionStream` — so the artifact on disk is the artifact on the wire.

Base64 was measured, not assumed, and rejected: gzip compresses base64 text far worse
than the bytes behind it, and the `all` selection came out at 8.62 MB against 5.12 MB
for the same data as raw sections. Uncompressed base64-in-JSON would have been worse
again — 134 MB on disk for `all` alone, which `build.mjs` then copies into `dist/` a
second time.

Sections are ordered so every 4-byte-wide array lands on a 4-byte boundary: the header
is padded to a multiple of four, the `int32` arrays come next, and the byte-wide cell
blocks come last. That lets the browser wrap each array with a zero-copy `Int32Array`
view instead of parsing a few hundred thousand JSON integers.
"""

from __future__ import annotations

import gzip
import json
import struct

import numpy as np

import contract
import frame
import reference

SCHEMA = 1


def _pack(block: np.ndarray) -> bytes:
    """Two codes per byte, high nibble first. Odd widths pad with GAP."""
    if block.shape[-1] % 2:
        block = np.pad(block, [(0, 0)] * (block.ndim - 1) + [(0, 1)])
    return ((block[..., 0::2].astype(np.uint8) << 4) | block[..., 1::2].astype(np.uint8)).tobytes()


def _spans(block: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per row, the first and last column holding material.

    `has_material` rather than `is_base`, so an ambiguity code at the edge of a read
    keeps its place in the span instead of trimming it — the span is where the record
    has sequence, not where the sequence is readable.
    """
    material = frame.has_material(block)
    width = block.shape[1]
    any_material = material.any(axis=1)
    first = np.where(any_material, material.argmax(axis=1), 0).astype(np.int32)
    last = np.where(
        any_material, width - 1 - material[:, ::-1].argmax(axis=1), -1
    ).astype(np.int32)
    return first, last


def _span_cells(block: np.ndarray, first: np.ndarray, last: np.ndarray) -> bytes:
    chunks = [
        _pack(block[index, first[index] : last[index] + 1])
        for index in range(block.shape[0])
        if last[index] >= first[index]
    ]
    return b"".join(chunks)


def build_region(
    alignment: frame.Alignment,
    population,
    columns: np.ndarray,
    selection: dict,
    region: str,
) -> dict:
    """One region's raster payload for one selection.

    Every row of the population appears, including rows that no other figure draws.
    That is deliberate: a record excluded from figure 1 for missing the coverage floor,
    or from a tree for overlapping nothing, is exactly the record whose coverage a
    reader wants to look at, and this is the only figure that can show it.
    """
    block = alignment.matrix[np.ix_(population.rows, columns)]
    first, last = _spans(block)

    header = {
        "schema": SCHEMA,
        "selection": selection["id"],
        "region": region,
        "coding": region in contract.CODING_REGIONS,
        "width": int(len(columns)),
        "n_rows": int(len(population.rows)),
        "min_nt": contract.min_nt(region),
    }
    arrays = {
        "record": np.asarray(population.record_rows, dtype="<i4"),
        "first": first.astype("<i4"),
        "last": last.astype("<i4"),
    }
    blobs = {"cells": _span_cells(block, first, last)}

    # References only where figure 1 has them. The two non-coding regions carry no
    # reference in any figure, so shipping one here would invent a comparison the rest
    # of the site does not make.
    if region in contract.DIVERGENCE_REGIONS:
        refs = reference.resolve(
            alignment, population.rows, columns, selection, population.records, region
        )
        header["references"] = [
            {"kind": kind, "label": label}
            for kind, label in zip(refs.kinds, refs.labels, strict=True)
        ]
        arrays["reference"] = refs.row_index.astype("<i4")
        # Dense rather than span-encoded: there are a few hundred of these at most,
        # and a consensus is a union of its type's coverage with no meaningful span.
        blobs["reference_cells"] = _pack(refs.sequences)

    return {"header": header, "arrays": arrays, "blobs": blobs}


def column_profiles(
    alignment: frame.Alignment,
    population,
    columns_by_region: dict[str, np.ndarray],
) -> dict:
    """Per column, how many of the selection's records are readable there.

    This is the figure's thumbnail strip. A miniature raster would cost a full pass
    over every region's cells on every filter, color and brush change; a coverage
    profile costs one small array per region and is the better thumbnail anyway,
    because comparing coverage across regions is the comparison this figure exists
    to make.
    """
    profiles = {}
    for region in contract.ALIGNMENT_REGIONS:
        columns = columns_by_region[region]
        block = alignment.matrix[np.ix_(population.rows, columns)]
        profiles[region] = {
            "width": int(len(columns)),
            "covered": [int(value) for value in frame.is_base(block).sum(axis=0)],
        }
    return {
        "schema": SCHEMA,
        "selection": "",
        "n_rows": int(len(population.rows)),
        "regions": profiles,
    }


def write_gzipped(path, payload: dict) -> None:
    """Serialize one container and gzip it.

    Deterministic: no mtime and no filename field, so a rebuild that changed nothing
    produces the same bytes and the manifest hash keeps meaning something.
    """
    header = dict(payload["header"])
    sections = []
    for name, array in payload["arrays"].items():
        sections.append({"name": name, "type": "i32", "bytes": int(array.nbytes)})
    for name, blob in payload["blobs"].items():
        sections.append({"name": name, "type": "u8", "bytes": len(blob)})
    header["sections"] = sections

    text = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    # Pad so the first int32 section starts 4-aligned, and every later one inherits
    # that alignment because int32 lengths are multiples of four and the byte-wide
    # blobs are written last.
    text += b" " * (-(len(text) + 4) % 4)

    body = b"".join(
        [struct.pack("<I", len(text)), text]
        + [array.tobytes() for array in payload["arrays"].values()]
        + list(payload["blobs"].values())
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
            handle.write(body)


def read_container(path) -> dict:
    """Inverse of `write_gzipped`. The selftest reads what shipped, not what was built.

    Checking the in-memory payload would only prove the arithmetic; reading the file back
    also proves the container survives serialization, which is the half that can break
    silently when the browser is the only other reader.
    """
    with gzip.open(path, "rb") as handle:
        body = handle.read()
    header_length = struct.unpack("<I", body[:4])[0]
    header = json.loads(body[4 : 4 + header_length])
    out = {"header": header}
    offset = 4 + header_length
    for section in header["sections"]:
        chunk = body[offset : offset + section["bytes"]]
        out[section["name"]] = (
            np.frombuffer(chunk, dtype="<i4")
            if section["type"] == "i32"
            else np.frombuffer(chunk, dtype=np.uint8)
        )
        offset += section["bytes"]
    if offset != len(body):
        raise ValueError(f"{path}: {len(body) - offset} trailing bytes after the last section")
    return out


def unpack_row(cells: np.ndarray, offset: int, length: int) -> np.ndarray:
    """`length` codes starting at nibble-packed byte `offset`."""
    raw = cells[offset : offset + (length + 1) // 2]
    both = np.empty(len(raw) * 2, dtype=np.uint8)
    both[0::2] = raw >> 4
    both[1::2] = raw & 0x0F
    return both[:length]


def row_offsets(first: np.ndarray, last: np.ndarray) -> np.ndarray:
    """Where each row's span begins in `cells`.

    Not shipped: a row occupies `ceil(span / 2)` bytes and the browser accumulates the
    same arithmetic, so an offset table would be a second copy of a derivable fact — and
    a second thing that can disagree with the cells it indexes.
    """
    spans = np.where(last >= first, last - first + 1, 0)
    return np.concatenate([[0], np.cumsum((spans + 1) // 2)]).astype(np.int64)
