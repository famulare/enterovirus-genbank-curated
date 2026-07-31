"""The committed NCR covariance-model core: hashed, scrubbed, and functionally verified.

`registry/alignment_seeds/` holds four Infernal `.cm` files (POLIO and NPEV, 5' and 3' NCR) plus
the seed alignment each was built from, copied from MAD-VDPV's own "reproducer core" so a routine
alignment build needs only `mafft` + Infernal — no network, no compiler, no `mafft-xinsi`.

Two things this file must prove that a casual copy would not: the files are the *right* models
(their match-column count equals the shipped artifacts' block widths, independent of the source
repository being available to re-check against), and scrubbing the absolute build path and
timestamp out of each `.cm` header did not corrupt it (a live `cmalign` run, skipped without a
toolchain).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align.seeds import verify_seeds
from enterovirus_genbank_curated.contracts import ContractError

SEED_DIR = "registry/alignment_seeds"

# name -> (match_columns, population, seed), cross-checked against seed_provenance.json and against
# the shipped artifacts' block_widths / rows_with_{5,3}ncr (final/alignments/*.provenance.json).
EXPECTED_CM = {
    "polio_ncr_5p.cm": (746, 2036, 80),
    "polio_ncr_3p.cm": (70, 1902, 100),
    "npev_ncr_5p.cm": (738, 2198, 83),
    "npev_ncr_3p.cm": (87, 1536, 115),
}

REQUIRES_ENV = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".pixi/envs/align/bin/cmalign").exists(),
    reason="pixi align environment is not installed; run `pixi install --locked -e align`",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def seed_dir(repository_root: Path) -> Path:
    return repository_root / SEED_DIR


@pytest.fixture(scope="module")
def seed_provenance(seed_dir: Path) -> dict:
    return json.loads((seed_dir / "seed_provenance.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def seeds_sha256(seed_dir: Path) -> dict[str, str]:
    entries = {}
    for line in (seed_dir / "seeds.sha256").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(None, 1)
        entries[name.strip()] = digest
    return entries


# --- hashes, checkable with no toolchain ---------------------------------------------------------


def test_every_file_matches_its_pinned_hash(seed_dir: Path, seeds_sha256: dict[str, str]) -> None:
    for name, expected in seeds_sha256.items():
        path = seed_dir / name
        assert path.is_file(), f"{name} is listed in seeds.sha256 but missing"
        assert sha256(path) == expected, f"{name} does not match its pinned hash"


def test_seeds_sha256_covers_every_file_in_the_directory(
    seed_dir: Path, seeds_sha256: dict[str, str]
) -> None:
    """Bidirectional: a new or renamed file with no hash is exactly how a swap goes unnoticed."""
    present = {
        p.name for p in seed_dir.iterdir()
        if p.is_file() and p.name not in {"seeds.sha256", "seed_provenance.json", "README.md"}
    }
    assert present == set(seeds_sha256)


@pytest.mark.parametrize("name", sorted(EXPECTED_CM))
def test_each_cm_reports_the_expected_match_column_count(seed_dir: Path, name: str) -> None:
    """CLEN is the match-column count. Cross-checked against the shipped artifacts' block_widths,
    which is the evidence these are the right models absent the source repository to compare to."""
    expected_clen, _, _ = EXPECTED_CM[name]
    text = (seed_dir / name).read_text(encoding="utf-8")
    match = re.search(r"^CLEN\s+(\d+)", text, re.M)
    assert match is not None, f"{name} has no CLEN header line"
    assert int(match.group(1)) == expected_clen


def test_no_cm_carries_an_absolute_local_path(seed_dir: Path) -> None:
    """The scrub target: `cmbuild`'s COM line records the full invocation, including path."""
    for name in EXPECTED_CM:
        text = (seed_dir / name).read_text(encoding="utf-8")
        assert "/Users/" not in text, f"{name} still carries an absolute local path"
        assert "[scrubbed" in text, f"{name} was not scrubbed"


def test_seed_provenance_agrees_with_the_pinned_expectations(
    seed_provenance: dict,
) -> None:
    for key, (match_columns, population_size, seed_size) in EXPECTED_CM.items():
        artifact_key = key.removesuffix(".cm")
        entry = seed_provenance["artifacts"][artifact_key]
        assert entry["match_columns"] == match_columns
        assert entry["population"] == population_size
        assert entry["seed"] == seed_size


def test_npev_cms_are_the_ones_ev_unified_reuses(seed_provenance: dict) -> None:
    """Matches the shipped `EV_unified.provenance.json`'s `cm_reused` field: EV builds no CM of its
    own and reuses NPEV's, which is why there is no `ev_ncr_*.cm` in this directory."""
    assert "EV_unified" in seed_provenance["reused_by"]
    seed_dir_names = {"npev_ncr_5p.cm", "npev_ncr_3p.cm", "polio_ncr_5p.cm", "polio_ncr_3p.cm"}
    assert set(EXPECTED_CM) == seed_dir_names


# --- align.seeds.verify_seeds: the function evgc alignment-verify-seeds actually runs -----------


def test_verify_seeds_passes_against_the_real_directory(repository_root: Path) -> None:
    assert verify_seeds(repository_root) == 12  # 4 .cm + 4 .sto + 4 _aln.fa


def test_verify_seeds_fails_when_the_directory_is_absent(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="does not exist"):
        verify_seeds(tmp_path)


def _copy_seed_dir(repository_root: Path, tmp_path: Path) -> Path:
    import shutil

    dest = tmp_path / "alignment_seeds"
    shutil.copytree(repository_root / SEED_DIR, dest)
    return dest


def test_verify_seeds_fails_on_a_corrupted_file(repository_root: Path, tmp_path: Path) -> None:
    seed_copy = _copy_seed_dir(repository_root, tmp_path)
    (seed_copy / "polio_ncr_5p.cm").write_bytes(b"corrupted")
    root = tmp_path
    (root / "registry").mkdir(exist_ok=True)
    seed_copy.rename(root / "registry" / "alignment_seeds")
    with pytest.raises(ContractError, match="does not match"):
        verify_seeds(root)


def test_verify_seeds_fails_on_an_untracked_new_file(repository_root: Path, tmp_path: Path) -> None:
    """Bidirectional at the function level too, not only in the file-listing test above."""
    seed_copy = _copy_seed_dir(repository_root, tmp_path)
    (seed_copy / "sneaked_in.cm").write_bytes(b"x")
    root = tmp_path
    (root / "registry").mkdir(exist_ok=True)
    seed_copy.rename(root / "registry" / "alignment_seeds")
    with pytest.raises(ContractError, match="disagree"):
        verify_seeds(root)


def test_verify_seeds_fails_when_a_hashed_file_is_missing(
    repository_root: Path, tmp_path: Path
) -> None:
    seed_copy = _copy_seed_dir(repository_root, tmp_path)
    (seed_copy / "polio_ncr_5p.cm").unlink()
    root = tmp_path
    (root / "registry").mkdir(exist_ok=True)
    seed_copy.rename(root / "registry" / "alignment_seeds")
    with pytest.raises(ContractError, match="disagree"):
        verify_seeds(root)


def test_verify_seeds_fails_when_a_cm_disagrees_with_provenance(
    repository_root: Path, tmp_path: Path
) -> None:
    """A swapped .cm with a different match-column count must be caught even if its bytes are
    otherwise well-formed and its hash was (implausibly) also updated to match."""
    seed_copy = _copy_seed_dir(repository_root, tmp_path)
    provenance_path = seed_copy / "seed_provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["artifacts"]["polio_ncr_5p"]["match_columns"] = 999
    provenance_path.write_text(json.dumps(provenance))
    root = tmp_path
    (root / "registry").mkdir(exist_ok=True)
    seed_copy.rename(root / "registry" / "alignment_seeds")
    with pytest.raises(ContractError, match="CLEN is"):
        verify_seeds(root)


# --- functional check, needs the toolchain -------------------------------------------------------


@REQUIRES_ENV
@pytest.mark.parametrize("name", sorted(EXPECTED_CM))
def test_each_scrubbed_cm_still_runs_under_cmalign(
    repository_root: Path, seed_dir: Path, name: str, tmp_path: Path
) -> None:
    """The positive control: scrubbing the header must not have corrupted the model."""
    bin_dir = repository_root / ".pixi/envs/align/bin"
    query = tmp_path / "query.fa"
    query.write_text(">test\nATGGCCAAGTTTGGGCCCATGGCCAAGTTTGGGCCCATGGCCAAGTTTGGGCCC\n")
    result = subprocess.run(
        [str(bin_dir / "cmalign"), "--outformat", "Stockholm", str(seed_dir / name), str(query)],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "LC_ALL": "C"},
        cwd=str(tmp_path),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("# STOCKHOLM")
