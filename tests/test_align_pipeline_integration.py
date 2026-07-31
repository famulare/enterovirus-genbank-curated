"""End-to-end: codon.build_codon_block + structural.build_ncr_blocks + stitch.stitch +
export.alignment.write_alignment, composed together on a tiny synthetic population.

Each module already has its own unit tests against hand-built fixtures; this file exists
specifically to catch an interface mismatch between them (a field name, a width convention, an
ordering assumption) that per-module tests, each mocking the others' outputs, cannot see. Real
`mafft`/`cmalign` throughout, so it follows the established subprocess-per-test pattern (a
`ToolGuard` cannot be installed twice in one process).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REQUIRES_ENV = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".pixi/envs/align/bin/mafft").exists(),
    reason="pixi align environment is not installed; run `pixi install --locked -e align`",
)

# Real, short poliovirus NCR sequences, degapped from this repo's own committed seed alignments
# (registry/alignment_seeds/polio_ncr_{5p,3p}_seed_aln.fa) -- same fixtures test_align_structural.py
# uses, so cmalign has genuine structure to fit.
_NCR3_A = "TAACCCTACCTCAGTCGAATTGGATTGGGTCATACTGTTGTAGGGGTAAATTTTTCTTTAATTCGGAG"
_NCR3_B = "CAACCCTACCTCAGTCGAATTGGATTGGGTTATACTGTTGTAGGGGTAAATTTTTCTTTAATTCGGAG"
_NCR5_A = (
    "TTAAAACAGCTCTGGGGTTGTTCCCACCCCAGAGGCCCACGTGGCGGCCAGTACTCTGGTACTACGGTACCTTTGTACGCCTGTTTTATA"
    "CTCCCTCCCCCATGCAACATTAGAAGCAATTCACAAAGTTCAATAGAGGGGGTACAAACCAGTACCACCACGAACAAGCACTTCTGTTTC"
    "CCCGGTGATCTCGTATAGGCCGTACCCACGGCTGAAAACAAGTGATCCGTTATCCGCTTAGGTACTTCGAGAAACCTAGTATCACCTTGG"
    "GATCTTCGACGCGTTGCACTCAGCACTCTACCCCGAGTGTAGCTTAGGCTGATGAGTCTGGGCATTCCCCACCGGTGACGGTGGCCCAGG"
    "CTGCGTTGGCGGCCTACCCATGGCTAACGCCATGGGACGCTAGTTGTGAACAAGGTGTGAAGAGCCTATTGAGCTACCTAAGAGTCCTCC"
    "GGCCCCTGAATGCGGCTAATCCCAACCACGGAGCAAGTGCCTTCAATCCAGAGGGTGGCTTGTCGTAACGCGCAAGTCTGTGGCGGAACC"
    "GACTACTTTGGGTGTCCGTGTTTCCTTTTATTTTTATTACGGCTGCTTATGGTGACAATCATTGATTGCCATCATAAAGCGAGTTGGATT"
    "GGCCATCCGGTGAAAGTTAAGTATCTCGTCCACTTATCTGTTGGACTTACTCCATTAACTCAACTCACGCCTGATTTGATATCTATAGTG"
    "TTATTGATTTGGAAAAAGCTATCATA"
)
_NCR5_B = (
    "TTAAAACAGCTCTGGGGTTGTTCCCACCCCAGAGGCCCACGTGGCGGCCAGTACTCTGGTACTACGGTACCTTTGTACGCCTGTTTTATA"
    "CCCCCTCCCCCATGCAACCTTAGAAGCAATTCACAAAGTTCAATAGAGGGGGTACAAACCAGTACCAACACGAACAAGCACTTCTGTTTC"
    "CCCGGTGATCTCGTATAGGCTGTACCCACGGCTGAAAACAAGTGATCCGTTATCCGCTTAGGTACTTCGAGAAGCCTAGTACCACCTTGG"
    "GATCTTCGACGCGTTGCACTCAGCACTCTACCCCGAGTGTAGCTTAGGCTGATGAGCCTGGGCATTCCCCACCGGTGACGGTGGCCCAGG"
    "CTGCGTTGGCGGCCTACCCATGGCTAACGCCATGGGACGCTAGTTGTGAACAAGGTGTGAAGAGCCTATTGAGCTACCTAAGAGTCCTCC"
    "GGCCCCTGAATGCGGCTAATCCCAACCACGGAGCAAGTGCCTTCAATCCAGAGGGTGGCTTGTCGTAACGCGCAAGTCTGTGGCGGAACC"
    "GACTACTTTGGGTGTCCGTGTTTCCTTTTATTTTTATTACGGCTGCTTATGGTGACAATCATTGATTGCCATCATAAAGCGAGTTGGATT"
    "GGCCATCCGGTGAAAGTTGAGTATCTCGTCCACTTATCTGTTGGATTTCCCCTATTAACTCAACTCACGCCTGTTTTGATATCTATAGTG"
    "TTATTGATTTGGAAAAAGCTATCATA"
)
_ORF_A = "ATG" + "AAAGAAGATCTGTCTGTTATTCCACGTACC" * 2 + "TAA"
_ORF_B = "ATG" + "GATCTGTCTGTTATTCCACGTACCAAAGAA" * 2 + "TAA"

SCRIPT = """
from pathlib import Path
from Bio.Seq import Seq
from enterovirus_genbank_curated import sandbox_exec as se
from enterovirus_genbank_curated.align import codon, contract, stitch, structural
from enterovirus_genbank_curated.align import scratch as sc, toolchain as tc
from enterovirus_genbank_curated.align.population import AlignedRecord, AlignmentPopulation
from enterovirus_genbank_curated.align.segment import Segmentation
from enterovirus_genbank_curated.export import alignment as export_alignment

ROOT = Path({root!r})
scratch = sc.create()
toolchain = tc.resolve(ROOT, environment=tc.ENV_ALIGN, tools=tc.ROUTINE_TOOLS, scratch=scratch.root)
guard = se.install_tool_guard(
    ROOT, scratch_root=scratch.root,
    allowed_executables=frozenset(str(t.path) for t in toolchain.tools.values()),
)

NCR3_A, NCR3_B = {ncr3_a!r}, {ncr3_b!r}
NCR5_A, NCR5_B = {ncr5_a!r}, {ncr5_b!r}
ORF_A, ORF_B = {orf_a!r}, {orf_b!r}

ncr = contract.NcrSpec(
    five_prime=contract.NcrSideSpec(50, 1000, "registry/alignment_seeds/polio_ncr_5p.cm"),
    three_prime=contract.NcrSideSpec(20, 150, "registry/alignment_seeds/polio_ncr_3p.cm"),
)
codon_spec = contract.CodonSpec(seed_min_aa=5, seed_per_type=2)
spec = contract.AlignmentSpec(
    name="INTEGRATION_unified", stack="unified",
    population=contract.PopulationSpec(virus_groups=(contract.POLIOVIRUS,)),
    expected_rows=3, description="pipeline integration test fixture", codon=codon_spec, ncr=ncr,
)

records = [
    AlignedRecord(
        accession="A", version="A.1", virus_group="poliovirus", virus_type="PV1", family="PV",
        tier="backbone", sequence=NCR5_A + ORF_A + NCR3_A, length_nt=len(NCR5_A + ORF_A + NCR3_A),
    ),
    AlignedRecord(
        accession="B", version="B.1", virus_group="poliovirus", virus_type="PV1", family="PV",
        tier="backbone", sequence=NCR5_B + ORF_B + NCR3_B, length_nt=len(NCR5_B + ORF_B + NCR3_B),
    ),
    AlignedRecord(
        accession="NOPLACE", version="NOPLACE.1", virus_group="poliovirus", virus_type="PV1",
        family="PV", tier="addon", sequence="N" * 10, length_nt=10,
    ),
]
population = AlignmentPopulation(spec=spec, records=tuple(records))

aa_a = str(Seq(ORF_A).translate())[:-1]
aa_b = str(Seq(ORF_B).translate())[:-1]
segmentations = {{
    "A": Segmentation(
        accession="A", method="annotated", strand="+", ncr5=NCR5_A, ncr3=NCR3_A,
        orf_nt=ORF_A[:-3], aa=aa_a, n_internal_stops=0, absence_reason=None,
    ),
    "B": Segmentation(
        accession="B", method="annotated", strand="+", ncr5=NCR5_B, ncr3=NCR3_B,
        orf_nt=ORF_B[:-3], aa=aa_b, n_internal_stops=0, absence_reason=None,
    ),
    "NOPLACE": Segmentation(
        accession="NOPLACE", method="none", strand="", ncr5="", ncr3="", orf_nt="", aa="",
        n_internal_stops=0, absence_reason="no_cds_untranslatable",
    ),
}}

codon_alignment = codon.build_codon_block(
    population, segmentations, toolchain, scratch, guard, threads=1, timeout_s=60, step_offset=0,
)
five, three = structural.build_ncr_blocks(
    population, segmentations, toolchain, scratch, guard, ROOT, threads=1, timeout_s=60,
    step_offset=10,
)
stitched = stitch.stitch(population, segmentations, codon_alignment, five, three)

assert stitched.accessions == ("A", "B", "NOPLACE")
assert set(stitched.aligned_nt) == {{"A", "B", "NOPLACE"}}
for row in stitched.aligned_nt.values():
    assert len(row) == stitched.width_nt
assert stitched.aligned_nt["NOPLACE"] == "-" * stitched.width_nt

noplace_rows = {{r.block: r for r in stitched.coverage if r.accession == "NOPLACE"}}
assert all(not r.present for r in noplace_rows.values())
assert all(r.absence_reason == "no_cds_untranslatable" for r in noplace_rows.values())

a_rows = {{r.block: r for r in stitched.coverage if r.accession == "A"}}
assert all(r.present for r in a_rows.values())

output_dir = scratch.root / "output"
paths = export_alignment.write_alignment(output_dir, spec, stitched)
assert paths["stockholm"].is_file()
assert paths["fasta"].is_file()
assert paths["coverage"].is_file()

import gzip
from Bio import AlignIO
with gzip.open(paths["stockholm"], "rt") as handle:
    text = handle.read()
sto_path = scratch.root / "roundtrip.sto"
sto_path.write_text(text)
parsed = AlignIO.read(sto_path, "stockholm")
assert {{record.id for record in parsed}} == {{"A", "B", "NOPLACE"}}
assert len(parsed[0].seq) == stitched.width_nt

with gzip.open(paths["fasta"], "rt") as handle:
    fasta_text = handle.read()
assert fasta_text.count(">") == 3

with gzip.open(paths["coverage"], "rt") as handle:
    coverage_text = handle.read()
assert coverage_text.count("\\n") == 1 + 3 * 3  # header + 3 records * 3 blocks

se.assert_no_violations(guard)
print("ALL PASS")
"""


def run_real(repository_root: Path) -> subprocess.CompletedProcess[str]:
    script = SCRIPT.format(
        root=str(repository_root), ncr3_a=_NCR3_A, ncr3_b=_NCR3_B, ncr5_a=_NCR5_A, ncr5_b=_NCR5_B,
        orf_a=_ORF_A, orf_b=_ORF_B,
    )
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True, text=True, cwd=repository_root, timeout=120,
    )


@REQUIRES_ENV
def test_codon_structural_stitch_export_compose_end_to_end(repository_root: Path) -> None:
    result = run_real(repository_root)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"expected a clean run:\n{combined}"
    assert "ALL PASS" in result.stdout
