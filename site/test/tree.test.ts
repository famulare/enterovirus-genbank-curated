/** The tree model, against the trees actually shipped.
 *
 *  Read from `data/` rather than from a fixture, on purpose: the thing worth catching is
 *  a pipeline change that makes the payload and the renderer disagree, and a fixture
 *  would be written to match whichever side was edited last.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { assertSchema, type Summary } from "../src/model/types.ts";
import { ordinal, ordinalExtent } from "../src/model/panel.ts";
import { assertTreeSchema, links, type TreeFile, type TreeRegion } from "../src/model/tree.ts";
import { assertPanelSchema, axis, type PanelFile } from "../src/model/panel.ts";
import { type Mark, markExtent } from "../src/model/mark.ts";

const summary: Summary = assertSchema(
  JSON.parse(readFileSync(new URL("../data/summary.json", import.meta.url), "utf8")) as Summary,
);

function load(selection: string): TreeFile {
  return assertTreeSchema(
    JSON.parse(
      readFileSync(new URL(`../data/trees/${selection}.json`, import.meta.url), "utf8"),
    ) as TreeFile,
  );
}

function everyTree(): [string, string, string, TreeRegion][] {
  const out: [string, string, string, TreeRegion][] = [];
  for (const selection of summary.selections) {
    const file = load(selection.id);
    for (const block of ["nucleotide", "protein"] as const) {
      for (const [region, tree] of Object.entries(file[block])) {
        if (tree.tip_record.length) out.push([selection.id, block, region, tree]);
      }
    }
  }
  return out;
}

const TREES = everyTree();

test("every selection ships a tree for every region its chapter offers", () => {
  const nucleotide = summary.regions.filter((r) => r.in_nucleotide_tree).map((r) => r.id);
  const protein = summary.regions.filter((r) => r.in_protein_tree).map((r) => r.id);
  assert.deepEqual(nucleotide, ["5NCR", "P1", "P2", "P3", "3NCR"]);
  assert.deepEqual(protein, ["P1", "P2", "P3"]);
  // The polyprotein is deliberately in neither: it is the concatenation of the three
  // parts, and would say nothing they do not say separately.
  const polyprotein = summary.regions.find((r) => r.id === "polyprotein")!;
  assert.equal(polyprotein.in_nucleotide_tree, false);
  assert.equal(polyprotein.in_protein_tree, false);

  for (const selection of summary.selections) {
    const file = load(selection.id);
    assert.deepEqual(Object.keys(file.nucleotide).sort(), [...nucleotide].sort());
    assert.deepEqual(Object.keys(file.protein).sort(), [...protein].sort());
  }
});

test("each tree is rooted, binary, and complete", () => {
  for (const [selection, block, region, tree] of TREES) {
    const where = `${selection} ${block} ${region}`;
    const tips = tree.tip_record.length;
    assert.equal(tree.node_x.length, tips - 1, `${where}: internal node count`);
    assert.equal(
      tree.node_parent.filter((parent) => parent === -1).length,
      1,
      `${where}: exactly one root`,
    );
    for (const array of [tree.tip_x, tree.tip_parent, tree.tip_coverage, tree.tip_shared]) {
      assert.equal(array.length, tips, `${where}: per-tip array length`);
    }
    for (const array of [tree.node_ylo, tree.node_yhi, tree.node_parent]) {
      assert.equal(array.length, tips - 1, `${where}: per-node array length`);
    }
  }
});

test("no branch runs backwards, so a path length is the sum of its branches", () => {
  for (const [selection, block, region, tree] of TREES) {
    const where = `${selection} ${block} ${region}`;
    for (let index = 0; index < tree.node_x.length; index += 1) {
      const parent = tree.node_parent[index]!;
      if (parent < 0) continue;
      assert.ok(
        tree.node_x[parent]! <= tree.node_x[index]! + 1e-9,
        `${where}: node ${index} sits left of its parent`,
      );
    }
    for (let tip = 0; tip < tree.tip_x.length; tip += 1) {
      assert.ok(
        tree.node_x[tree.tip_parent[tip]!]! <= tree.tip_x[tip]! + 1e-9,
        `${where}: tip ${tip} sits left of its parent`,
      );
    }
  }
});

test("the ladder is dense: every position from 0 to n-1 holds exactly one tip", () => {
  for (const [selection, block, region, tree] of TREES) {
    // A tip's y IS its index, so this is really a check that the build emitted tips in
    // ladder order without gaps or repeats — which is what makes the ordinal axis valid.
    const spans = tree.node_ylo.map((low, index) => [low, tree.node_yhi[index]!]);
    const highest = Math.max(...spans.map(([, high]) => high!));
    assert.equal(
      highest,
      tree.tip_record.length - 1,
      `${selection} ${block} ${region}: ladder reaches the last tip`,
    );
    assert.equal(
      Math.min(...spans.map(([low]) => low!)),
      0,
      `${selection} ${block} ${region}: ladder starts at zero`,
    );
  }
});

test("internal node spans bracket their own children", () => {
  for (const [selection, block, region, tree] of TREES) {
    const where = `${selection} ${block} ${region}`;
    const low = new Map<number, number>();
    const high = new Map<number, number>();
    const note = (parent: number, y: number) => {
      low.set(parent, Math.min(low.get(parent) ?? Infinity, y));
      high.set(parent, Math.max(high.get(parent) ?? -Infinity, y));
    };
    for (let tip = 0; tip < tree.tip_x.length; tip += 1) note(tree.tip_parent[tip]!, tip);
    for (let index = 0; index < tree.node_x.length; index += 1) {
      const parent = tree.node_parent[index]!;
      if (parent >= 0) note(parent, (tree.node_ylo[index]! + tree.node_yhi[index]!) / 2);
    }
    for (let index = 0; index < tree.node_x.length; index += 1) {
      assert.ok(
        Math.abs(tree.node_ylo[index]! - low.get(index)!) < 0.02,
        `${where}: node ${index} span low ${tree.node_ylo[index]} vs children ${low.get(index)}`,
      );
      assert.ok(
        Math.abs(tree.node_yhi[index]! - high.get(index)!) < 0.02,
        `${where}: node ${index} span high ${tree.node_yhi[index]} vs children ${high.get(index)}`,
      );
    }
  }
});

test("the link layer draws one elbow per node and one twig per tip", () => {
  for (const [selection, block, region, tree] of TREES) {
    const tips = tree.tip_record.length;
    const drawn = links(tree);
    // One vertical per internal node, one horizontal per internal node except the root,
    // one horizontal per tip: 2(n-1) - 1 + n = 3n - 3.
    assert.equal(
      drawn.length,
      3 * tips - 3,
      `${selection} ${block} ${region}: ${drawn.length} segments for ${tips} tips`,
    );
    const maxX = Math.max(...tree.tip_x);
    for (const link of drawn) {
      for (const value of [link.x0, link.x1]) {
        assert.ok(
          value >= -1e-9 && value <= maxX + 1e-9,
          `${selection} ${block} ${region}: x ${value} outside [0, ${maxX}]`,
        );
      }
      for (const value of [link.y0, link.y1]) {
        assert.ok(
          value >= -1e-9 && value <= tips - 1 + 1e-9,
          `${selection} ${block} ${region}: y ${value} outside the ladder`,
        );
      }
      assert.ok(
        Math.abs(link.x0 - link.x1) < 1e-9 || Math.abs(link.y0 - link.y1) < 1e-9,
        `${selection} ${block} ${region}: a rectangular tree has no diagonal segments`,
      );
    }
  }
});

test("thin tips are a minority, or the encoding says nothing", () => {
  for (const [selection, block, region, tree] of TREES) {
    assert.ok(
      tree.thin.length < tree.tip_record.length,
      `${selection} ${block} ${region}: every tip marked thin`,
    );
    for (const index of tree.thin) {
      assert.ok(
        tree.tip_shared[index]! < tree.confident_shared,
        `${selection} ${block} ${region}: tip ${index} marked thin but clears the floor`,
      );
    }
  }
});

test("an ordinal axis carries no ticks, because a ladder position is not a quantity", () => {
  const axis = ordinalExtent(2500);
  assert.deepEqual(axis.ticks, []);
  assert.equal(axis.min, -0.5);
  assert.equal(axis.max, 2499.5);
  // First and last tips sit inside the plot rather than on its frame.
  assert.ok(axis.t(0) > 0 && axis.t(2499) < 1);
  for (const value of [0, 1, 1249, 2499]) {
    assert.ok(Math.abs(axis.invert(axis.t(value)) - value) < 1e-9, `round trip ${value}`);
  }
});

test("a brushed ordinal range keeps the reader's own edges", () => {
  const axis = ordinal(120, 260);
  assert.deepEqual(axis.ticks, []);
  assert.equal(axis.t(120), 0);
  assert.equal(axis.t(260), 1);
  assert.equal(axis.invert(0.5), 190);
});

test("a degenerate ordinal range does not divide by zero", () => {
  const axis = ordinalExtent(0);
  assert.ok(Number.isFinite(axis.t(0)));
  assert.ok(Number.isFinite(axis.invert(1)));
});

// --- The protein scaling figure, and how the two scatters choose a range ------

function panels(selection: string): PanelFile {
  return assertPanelSchema(
    JSON.parse(
      readFileSync(new URL(`../data/panels/${selection}.json`, import.meta.url), "utf8"),
    ) as PanelFile,
  );
}

test("protein scaling covers the coding regions and counts in codons", () => {
  const regions = summary.regions.filter((r) => r.in_protein_distance).map((r) => r.id);
  assert.deepEqual(regions, ["P1", "P2", "P3"]);
  for (const selection of summary.selections) {
    const file = panels(selection.id);
    assert.deepEqual(Object.keys(file.protein_distance).sort(), [...regions].sort());
    for (const region of regions) {
      const block = file.protein_distance[region]!;
      const nucleotide = file.distance[region]!;
      assert.equal(block.unit, "codons", `${selection.id} ${region} unit`);
      assert.equal(nucleotide.unit, "nt", `${selection.id} ${region} nucleotide unit`);
      // A codon floor of 17 is 51 nt, so it can only ever be stricter than the 50 nt one.
      assert.ok(
        block.min_nt * 3 >= nucleotide.min_nt,
        `${selection.id} ${region}: codon floor ${block.min_nt} is looser than ${nucleotide.min_nt} nt`,
      );
      assert.equal(
        block.columns * 3,
        nucleotide.columns,
        `${selection.id} ${region}: width in codons should be a third of the columns`,
      );
      // Coverage is quoted in the block's own unit, so it can never exceed the width.
      for (const value of block.coverage) {
        assert.ok(value <= block.columns, `${selection.id} ${region}: coverage ${value} > width`);
      }
      for (const name of ["linear", "sqrt"]) {
        const fit = block.transforms[name];
        assert.ok(fit, `${selection.id} ${region} ${name} fit missing`);
        assert.equal(fit!.x.length, block.record.length);
        assert.equal(fit!.y.length, block.record.length);
      }
    }
  }
});

test("a scatter's range comes from the marks it trusts, not the ones it doubts", () => {
  const confident = (x: number, y: number): Mark => ({ record: 0, x, y, weight: 1, flagged: false });
  const thin = (x: number, y: number): Mark => ({ record: 0, x, y, weight: 0.62, flagged: false });
  // The shape that motivated this: a cluster of trusted marks, plus one thin mark an
  // order of magnitude further out.
  const marks = [confident(-0.1, -0.1), confident(0.1, 0.1), thin(0.2, 1.7)];

  const all = markExtent(marks, "linear", axis);
  const trusted = markExtent(marks, "linear", axis, true);
  assert.ok(all.y.max > 1.6, "including every mark, the thin one sets the range");
  assert.ok(trusted.y.max < 0.5, `trusting only the confident marks, ${trusted.y.max} stays tight`);
  assert.ok(all.x.max >= trusted.x.max, "the confident range is never the wider one");

  // With nothing confident, it must still draw rather than collapse to an empty range.
  const nothingTrusted = markExtent([thin(0.2, 1.7), thin(-0.2, -1.7)], "linear", axis, true);
  assert.ok(nothingTrusted.y.max > 1.6, "falls back to every mark when none is confident");
  assert.ok(Number.isFinite(nothingTrusted.y.t(0)));
});
