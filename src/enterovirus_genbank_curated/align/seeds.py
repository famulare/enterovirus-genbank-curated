"""Verify the committed NCR covariance-model core, with no native toolchain required.

`registry/alignment_seeds/` holds four Infernal `.cm` files plus their seed alignments, committed as
inputs-of-record so a routine alignment build never needs `mafft-xinsi`, `RNAalifold`, or a
compiler. This module is the cheap half of that promise: it re-hashes every file and cross-checks
each `.cm`'s match-column count against `seed_provenance.json`, in pure Python, so a swapped or
truncated model fails on every push regardless of whether the aligner toolchain is installed.

Functional verification — that a scrubbed `.cm` still produces a correct alignment under a live
`cmalign` — is a separate, toolchain-gated concern and lives in `tests/test_alignment_seeds.py`,
not here.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from enterovirus_genbank_curated.contracts import ContractError

SEED_DIR = "registry/alignment_seeds"
HASH_MANIFEST = "seeds.sha256"
PROVENANCE_FILE = "seed_provenance.json"

# Files in the directory that are metadata about the seeds, not seeds themselves, and so are not
# listed inside seeds.sha256 (which would otherwise have to hash itself).
NOT_HASHED = frozenset({HASH_MANIFEST, PROVENANCE_FILE, "README.md"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_hash_manifest(seed_dir: Path) -> dict[str, str]:
    path = seed_dir / HASH_MANIFEST
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    entries: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ContractError(f"{path}: malformed line {line!r}")
        digest, name = parts
        entries[name.strip()] = digest
    if not entries:
        raise ContractError(f"{path} declares no hashes")
    return entries


def _load_provenance(seed_dir: Path) -> dict:
    path = seed_dir / PROVENANCE_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"{path} is not valid JSON: {exc}") from exc


def verify_seeds(repository_root: Path) -> int:
    """Re-hash every committed seed file and cross-check each `.cm`'s match-column count.

    Returns the number of files checked, so a caller can assert it is not zero — the same
    zero-coverage guard `oracle.release.verify_release_manifest_hashes` uses, and for the same
    reason: a check that verifies nothing is worse than no check.
    """
    seed_dir = repository_root / SEED_DIR
    if not seed_dir.is_dir():
        raise ContractError(f"{seed_dir} does not exist")

    manifest = _load_hash_manifest(seed_dir)
    present = {
        path.name for path in seed_dir.iterdir() if path.is_file() and path.name not in NOT_HASHED
    }
    declared = set(manifest)
    if present != declared:
        missing_hashes = present - declared
        stale_entries = declared - present
        raise ContractError(
            f"{seed_dir}: {HASH_MANIFEST} and the directory disagree — "
            f"unhashed files {sorted(missing_hashes)}, hashes for missing files "
            f"{sorted(stale_entries)}"
        )

    checked = 0
    for name, expected in sorted(manifest.items()):
        path = seed_dir / name
        actual = _sha256(path)
        if actual != expected:
            raise ContractError(
                f"{name}: sha256 {actual} does not match {HASH_MANIFEST}'s {expected}. These "
                f"files are inputs-of-record with no local producer to re-derive them from; if "
                f"this change is deliberate, update seeds.sha256 and seed_provenance.json."
            )
        checked += 1

    provenance = _load_provenance(seed_dir)
    for name in manifest:
        if not name.endswith(".cm"):
            continue
        key = name.removesuffix(".cm")
        entry = provenance.get("artifacts", {}).get(key)
        if entry is None:
            raise ContractError(f"{PROVENANCE_FILE} has no artifacts entry for {key!r}")
        text = (seed_dir / name).read_text(encoding="utf-8")
        match = re.search(r"^CLEN\s+(\d+)", text, re.M)
        if match is None:
            raise ContractError(f"{name} has no CLEN header line")
        actual_clen = int(match.group(1))
        if actual_clen != entry["match_columns"]:
            raise ContractError(
                f"{name}: CLEN is {actual_clen}, but {PROVENANCE_FILE} declares "
                f"match_columns={entry['match_columns']}"
            )

    if checked == 0:
        raise ContractError(f"{HASH_MANIFEST} declared no hashes to recompute")
    return checked
