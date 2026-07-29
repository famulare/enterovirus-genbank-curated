/** Tests for the DOM-free view state. Run with `node --run test` from site/. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { assertSchema, type Summary } from "../src/model/types.ts";
import { axis } from "../src/model/panel.ts";
import {
  decode,
  defaultView,
  encode,
  population,
  regionsFor,
  roundTrip,
  sameView,
} from "../src/model/view.ts";

/** The real built artifact, not a fixture — so a schema drift fails here too. */
const summary: Summary = assertSchema(
  JSON.parse(readFileSync(new URL("../data/summary.json", import.meta.url), "utf8")) as Summary,
);

test("summary declares the five selections the site is built around", () => {
  assert.deepEqual(
    summary.selections.map((entry) => entry.id),
    ["PV1", "PV2", "PV3", "NPEV", "all"],
  );
});

test("the default view is the PV1 polyprotein colored by classification", () => {
  const view = defaultView(summary);
  assert.equal(view.selection, "PV1");
  assert.equal(view.region, "polyprotein");
  assert.equal(view.trait, "poliovirus_classification");
  assert.equal(view.pinned, null);
});

test("the default view opens on a square-root axis at full extent", () => {
  const view = defaultView(summary);
  assert.equal(view.scale, "sqrt");
  assert.equal(view.zoom, null);
});

test("a brushed range round-trips through the URL", () => {
  const zoom = { x0: 0.0012, x1: 0.4, y0: 0, y1: 0.255 };
  const back = decode(`#${encode({ ...defaultView(summary), zoom }, summary)}`, summary).view.zoom;
  assert.ok(back, "zoom survives the round trip");
  for (const key of ["x0", "x1", "y0", "y1"] as const) {
    assert.ok(Math.abs(back[key] - zoom[key]) < 1e-6, `${key} preserved`);
  }
});

test("a malformed or inverted range is rejected, not clamped", () => {
  for (const bad of ["1,2,3", "0,1,0,1,2", "a,b,c,d", "0.5,0.1,0,1", "0,1,1,1", "-1,1,0,1"]) {
    const decoded = decode(`#zoom=${bad}`, summary);
    assert.equal(decoded.view.zoom, null, `${bad} rejected`);
    assert.deepEqual(decoded.rejected, [`zoom=${bad}`], `${bad} reported`);
  }
});

test("an unknown axis scale is rejected", () => {
  assert.deepEqual(decode("#scale=log", summary).rejected, ["scale=log"]);
  assert.equal(decode("#scale=linear", summary).view.scale, "linear");
});

test("the square-root axis keeps zero on the axis, is monotone, and spreads the low end", () => {
  const a = axis(0, 0.7, "sqrt");
  assert.equal(a.t(0), 0, "zero maps to the origin");
  assert.ok(Math.abs(a.t(0.7) - 1) < 1e-9, "the maximum maps to the far edge");
  assert.ok(a.t(0.01) > 4 * axis(0, 0.7, "linear").t(0.01), "low values gain room");
  let previous = -1;
  for (const v of [0, 0.001, 0.01, 0.1, 0.3, 0.7]) {
    const at = a.t(v);
    assert.ok(at > previous, `monotone at ${v}`);
    previous = at;
  }
});

test("every axis tick lands inside its own range, on both scales", () => {
  for (const scale of ["linear", "sqrt"] as const) {
    for (const [min, max] of [
      [0, 0.7],
      [0, 0.526],
      [0.0012, 0.4],
      [0, 1],
      [0.2, 0.21],
    ]) {
      const a = axis(min!, max!, scale);
      for (const tick of a.ticks) {
        assert.ok(
          tick >= a.min - 1e-9 && tick <= a.max + 1e-9,
          `${scale} [${min},${max}] tick ${tick} outside [${a.min},${a.max}]`,
        );
      }
    }
  }
});

test("square-root ticks stay legibly separated and never crowd zero", () => {
  const full = axis(0, 0.63, "sqrt");
  assert.ok(full.ticks.length >= 4 && full.ticks.length <= 12, `${full.ticks.length} ticks`);
  for (let i = 1; i < full.ticks.length; i += 1) {
    const gap = full.t(full.ticks[i]!) - full.t(full.ticks[i - 1]!);
    assert.ok(gap > 0.07, `gap ${gap.toFixed(4)} at ${full.ticks[i - 1]}..${full.ticks[i]}`);
  }
  assert.ok(full.ticks.every((t) => t === 0 || t >= 1e-4), "the full view drops the tiny ones");
  // Brushing into the corner must recover the fine ticks the full view thins away.
  const near = axis(0, 0.01, "sqrt");
  assert.ok(
    near.ticks.some((t) => t > 0 && t <= 0.002),
    `a range near zero keeps fine ticks: ${near.ticks.join(", ")}`,
  );
});

test("invert is the inverse of the axis transform", () => {
  for (const scale of ["linear", "sqrt"] as const) {
    const a = axis(0, 0.63, scale);
    for (const v of [0, 0.005, 0.05, 0.25, 0.63]) {
      assert.ok(Math.abs(a.invert(a.t(v)) - v) < 1e-9, `${scale} round-trips ${v}`);
    }
  }
});

test("the default view encodes to an empty hash", () => {
  assert.equal(encode(defaultView(summary), summary), "");
});

test("non-polio selections default to virus_type, because classification is empty there", () => {
  for (const id of ["NPEV", "all"]) {
    const selection = summary.selections.find((entry) => entry.id === id);
    assert.equal(selection?.default_trait, "virus_type", `${id} default trait`);
  }
});

test("encode and decode round-trip every reachable view", () => {
  for (const selection of summary.selections) {
    for (const region of summary.regions) {
      for (const trait of summary.traits) {
        for (const status of ["all", "vouched", "provisional"] as const) {
          const view = {
            selection: selection.id,
            region: region.id,
            trait: trait.id,
            status,
            engineered: false,
            pinned: "AY184219",
            scale: "linear" as const,
            zoom: { x0: 0.01, x1: 0.4, y0: 0, y1: 0.25 },
          };
          assert.ok(sameView(roundTrip(view, summary), view), `${selection.id}/${region.id}/${trait.id}`);
        }
      }
    }
  }
});

test("every parameter the encoder emits is accepted by the decoder", () => {
  // A name spelled one way in encode and another in the decoder's allowlist would
  // be applied AND reported rejected at the same time. This catches that.
  const view = {
    ...defaultView(summary),
    selection: "NPEV",
    region: "P2",
    trait: "species",
    status: "vouched" as const,
    engineered: false,
    pinned: "AY184219",
    scale: "linear" as const,
    zoom: { x0: 0.002, x1: 0.5, y0: 0.001, y1: 0.3 },
  };
  const encoded = encode(view, summary);
  const emitted = encoded.split("&").map((pair) => pair.slice(0, pair.indexOf("=")));
  assert.deepEqual(
    emitted.sort(),
    ["color", "engineered", "record", "region", "scale", "sel", "status", "zoom"],
    "every field is represented",
  );
  assert.deepEqual(decode(`#${encoded}`, summary).rejected, [], "and none is rejected");
});

test("unknown parameters are rejected and reported, never accepted", () => {
  const decoded = decode("#sel=PV9&region=nonsense&color=nope&status=maybe&engineered=x&junk=1", summary);
  assert.deepEqual(decoded.view, defaultView(summary));
  assert.deepEqual(decoded.rejected.sort(), [
    "color=nope",
    "engineered=x",
    "junk",
    "region=nonsense",
    "sel=PV9",
    "status=maybe",
  ]);
});

test("a malformed accession is rejected rather than pinned", () => {
  assert.deepEqual(decode("#record=../../etc/passwd", summary).rejected, ["record=../../etc/passwd"]);
  assert.equal(decode("#record=AY184219", summary).view.pinned, "AY184219");
});

test("changing selection resets the trait to that selection's default", () => {
  assert.equal(decode("#sel=NPEV", summary).view.trait, "virus_type");
  assert.equal(decode("#sel=PV2", summary).view.trait, "poliovirus_classification");
});

test("an explicit color survives a selection change in the same link", () => {
  assert.equal(decode("#sel=NPEV&color=species", summary).view.trait, "species");
});

test("divergence offers coding regions only; distance adds both non-coding regions", () => {
  assert.deepEqual(
    regionsFor(summary, "divergence").map((region) => region.id),
    ["P1", "P2", "P3", "polyprotein"],
  );
  assert.deepEqual(
    regionsFor(summary, "distance").map((region) => region.id),
    ["5NCR", "P1", "P2", "P3", "3NCR"],
  );
});

test("P1 is fully populated in every selection, because typing requires a capsid", () => {
  for (const selection of summary.selections) {
    const p1 = population(summary, { ...defaultView(summary), selection: selection.id, region: "P1" });
    assert.ok(
      p1.n / p1.ofAligned > 0.86,
      `${selection.id} P1 holds ${p1.n} of ${p1.ofAligned} aligned rows`,
    );
  }
});

test("population counts match the release figures established during investigation", () => {
  const expected: Record<string, Record<string, number>> = {
    PV1: { P1: 3732, P2: 753, P3: 423 },
    PV2: { P1: 3604, P2: 1365, P3: 1256 },
    PV3: { P1: 1425, P2: 460, P3: 369 },
  };
  for (const [selection, regions] of Object.entries(expected)) {
    for (const [region, n] of Object.entries(regions)) {
      assert.equal(
        population(summary, { ...defaultView(summary), selection, region }).n,
        n,
        `${selection} ${region}`,
      );
    }
  }
});

test("the 3'NCR carries a lower coverage threshold than every other region", () => {
  const three = summary.regions.find((region) => region.id === "3NCR");
  assert.equal(three?.min_nt, 30);
  for (const region of summary.regions) {
    if (region.id !== "3NCR") assert.equal(region.min_nt, 50, region.id);
  }
});
