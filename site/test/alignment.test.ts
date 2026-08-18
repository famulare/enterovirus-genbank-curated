/** Figure 6's raster against figure 1's panels.
 *
 *  The site ships the alignment bases and derives the divergence classification in the
 *  browser, rather than shipping the classification Python already computed. That buys
 *  one payload behind both cell vocabularies and a deep zoom that can show actual bases.
 *  What it risks is that `model/alignment.ts` drifts from `pipeline/divergence.py`.
 *
 *  This file is the price of that choice. It recomputes figure 1's counts through the
 *  TypeScript decoder and asserts they equal the shipped panel exactly — checking two
 *  independent implementations against each other, which is the failure worth guarding.
 *  A Python selftest of a Python-derived payload could not do that.
 *
 *  Read from `data/` rather than from a fixture, on purpose: both workflows build
 *  site/data/ before the npm step, so a schema drift or a rebuild that changed the
 *  numbers fails here rather than in the browser.
 */

import assert from "node:assert/strict";
import { gunzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  COVERAGE,
  DIVERGENCE,
  columnTrack,
  coverageStates,
  decodeAlignment,
  divergenceStates,
  rowCounts,
  type AlignmentBlock,
} from "../src/model/alignment.ts";
import type { PanelFile } from "../src/model/panel.ts";

function block(selection: string, region: string): AlignmentBlock {
  const path = new URL(`../data/alignments/${selection}/${region}.bin.gz`, import.meta.url);
  const raw = gunzipSync(readFileSync(path));
  return decodeAlignment(new Uint8Array(raw.buffer, raw.byteOffset, raw.byteLength));
}

function panel(selection: string): PanelFile {
  return JSON.parse(
    readFileSync(new URL(`../data/panels/${selection}.json`, import.meta.url), "utf8"),
  ) as PanelFile;
}

/** The identity the sixth figure rests on: a point in the divergence scatter is the sum
 *  of its own raster row. Checked over both coordinate frames — PV1 is the Sabin frame
 *  with a single reference and no insertions, `all` is the projected frame with per-type
 *  consensus references, unresolved rows, and real insertion columns. Asserting only
 *  against PV1 would exercise none of the machinery that can actually drift. */
for (const [selection, regions] of [
  ["PV1", ["P1", "P2", "P3", "polyprotein"]],
  ["all", ["P1", "P2", "P3"]],
] as const) {
  test(`${selection}: every divergence point is a row-sum of its raster row`, () => {
    const panelFile = panel(selection);
    let compared = 0;
    for (const region of regions) {
      const raster = block(selection, region);
      const expected = panelFile.divergence[region]!;
      const mismatches: string[] = [];

      for (let slot = 0; slot < expected.record.length; slot += 1) {
        const record = expected.record[slot]!;
        const row = raster.rowForRecord(record);
        assert.notEqual(row, -1, `record ${record} is in the panel but not in the raster`);

        const counts = rowCounts(
          divergenceStates(raster.row(row), raster.referenceRow(row), raster.width),
        );
        if (
          counts.synonymous !== expected.synonymous[slot] ||
          counts.nonsynonymous !== expected.nonsynonymous[slot] ||
          counts.assessable !== expected.assessable[slot] ||
          counts.comparable !== expected.comparable[slot] ||
          counts.indelCodons !== expected.indel_codons[slot]
        ) {
          mismatches.push(
            `${region} record ${record}: got ${counts.synonymous}/${counts.nonsynonymous}` +
              ` over ${counts.assessable}, panel says ${expected.synonymous[slot]}/` +
              `${expected.nonsynonymous[slot]} over ${expected.assessable[slot]}`,
          );
        }
        compared += 1;
      }
      assert.deepEqual(mismatches.slice(0, 3), [], `${selection}/${region} disagrees`);
    }
    assert.ok(compared > 1000, `${compared} records compared`);
  });
}

test("a record with no comparable reference is stated, not silently scored zero", () => {
  // 1,582 non-polio records have no reference: their virus type is unrecorded, or holds
  // too few sequences for a consensus. Figure 1 reports them unmeasurable. The raster
  // must say the same thing rather than drawing a row of identical codons, which would
  // read as "this sequence matches its reference perfectly".
  const raster = block("NPEV", "P1");
  let unreferenced = 0;
  for (let row = 0; row < raster.rows && unreferenced < 5; row += 1) {
    if (raster.referenceRow(row) !== null) continue;
    unreferenced += 1;
    const states = divergenceStates(raster.row(row), null, raster.width);
    assert.ok(
      states.every((state) => state === DIVERGENCE.NO_REFERENCE),
      "every codon reads as unmeasurable",
    );
    assert.equal(rowCounts(states).assessable, 0, "and contributes nothing to the axes");
    assert.equal(raster.referenceLabel(row), "", "and names no reference");
  }
  assert.ok(unreferenced > 0, "NPEV/P1 carries records with no resolvable reference");
});

test("coverage separates absent from deleted, and an ambiguity from both", () => {
  const raster = block("PV1", "P1");
  let checked = 0;
  for (let row = 0; row < raster.rows && checked < 200; row += 1) {
    const first = raster.first[row]!;
    const last = raster.last[row]!;
    if (last < first) continue;
    checked += 1;
    const states = coverageStates(raster.row(row), first, last);
    // Outside the span is ABSENT and never GAP: the record has no material there, which
    // is missing data, not a deletion. Conflating them would charge a fragment an indel
    // for every column it simply does not reach.
    for (let column = 0; column < first; column += 1) {
      assert.equal(states[column], COVERAGE.ABSENT, "before the span");
    }
    for (let column = last + 1; column < raster.width; column += 1) {
      assert.equal(states[column], COVERAGE.ABSENT, "after the span");
    }
    assert.notEqual(states[first], COVERAGE.ABSENT, "the span starts on material");
    assert.notEqual(states[last], COVERAGE.ABSENT, "and ends on material");
  }
  assert.ok(checked > 100, `${checked} rows inspected`);
});

test("the column track counts every visible row, not the sampled ones", () => {
  // The raster samples one record per pixel row once rows outnumber pixels. The track
  // above it does not — it is where the full population is represented, and the figure
  // says so. If it ever started sampling too, the panel would have no honest aggregate.
  const raster = block("PV1", "P1");
  const rows = [...Array(raster.rows).keys()];
  const track = columnTrack(raster, rows);
  assert.equal(track.covered.length, raster.width);

  let total = 0;
  for (const value of track.covered) total += value;
  let expected = 0;
  for (let row = 0; row < raster.rows; row += 1) {
    const cells = raster.row(row);
    for (let column = 0; column < raster.width; column += 1) {
      if (cells[column]! >= 1 && cells[column]! <= 4) expected += 1;
    }
  }
  assert.equal(total, expected, "the track is the full count, column by column");

  // The headline finding this figure exists to show: P1's best column is carried by a
  // large minority, and it is the only region where that is true.
  const best = Math.max(...track.covered);
  assert.ok(best / raster.rows > 0.6, `PV1 P1's best column reaches ${best} of ${raster.rows}`);
});

test("a container that lost bytes fails loudly rather than drawing a wrong figure", () => {
  const path = new URL("../data/alignments/PV3/3NCR.bin.gz", import.meta.url);
  const raw = gunzipSync(readFileSync(path));
  const truncated = new Uint8Array(raw.buffer, raw.byteOffset, raw.byteLength - 8);
  assert.throws(() => decodeAlignment(truncated), /trailing bytes|out of range|RangeError/);
});
