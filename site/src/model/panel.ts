/** One region's scatter, decoded from a panel file.
 *
 *  Counts are shipped as integers and divided here, so the tooltip can state the
 *  exact numerator and denominator rather than a rounded rate. Jitter is applied on
 *  top of the true position, at the amplitude and with the offsets the build chose,
 *  so it is identical on every render and across rebuilds.
 */

import type { AxisScale, Zoom } from "./view.js";

export interface PanelFile {
  schema: number;
  selection: string;
  alignment: string;
  frame: string;
  n_rows: number;
  orphaned: number;
  jitter_scale: number;
  jitter_amplitude: number;
  divergence: Record<string, DivergenceRegion>;
  distance: Record<string, DistanceRegion>;
}

export interface DivergenceRegion {
  record: number[];
  comparable: number[];
  assessable: number[];
  synonymous: number[];
  nonsynonymous: number[];
  indel_codons: number[];
  indel_events: number[];
  frameshift: number[];
  reference: number[];
  jitter_x: number[];
  jitter_y: number[];
  references: { kind: string; label: string }[];
  excluded: { below_coverage: number; no_reference: number };
  codons: number;
  min_nt: number;
}

export interface DistanceFit {
  x: number[];
  y: number[];
  explained: number;
  negative_share: number;
}

export interface DistanceRegion {
  record: number[];
  resolved: number[];
  /** Indices into `record` whose placement rests on too little overlap. */
  thin: number[];
  landmarks: number;
  excluded: { below_coverage: number };
  columns: number;
  min_nt: number;
  /** One fit per dissimilarity transform. Which records are placed and how well is
   *  shared; only the coordinates and the goodness of fit differ. */
  transforms: Record<string, DistanceFit>;
}

export const PANEL_SCHEMA = 1;

export function assertPanelSchema(file: PanelFile): PanelFile {
  if (file.schema !== PANEL_SCHEMA) {
    throw new Error(
      `panel file is schema ${file.schema}, this app reads ${PANEL_SCHEMA}. ` +
        "Rebuild with: uv run site/pipeline/cli.py build",
    );
  }
  return file;
}

/** An axis with a transform, a range, and ticks that land inside it.
 *
 *  Two scales. **Linear** is the default reading and the one comparable to figures
 *  made elsewhere. **Square root** spreads the low-divergence corner where most of
 *  the structure sits — Sabin-like sequences sit at 0.001 while wild-type sits at
 *  0.52, so on a linear axis the entire VDPV gradient compresses into the leftmost
 *  few percent. Square root is used rather than log because zero is a real, occupied
 *  position here (the reference measured against itself) and log cannot show it.
 *
 *  Ticks are chosen so the last one never falls outside the range. Deriving the
 *  maximum first and the step afterwards lets that happen — a 0.7 axis with a 0.2
 *  step wants a tick at 0.8 — and the stray tick's grid line then renders outside
 *  the plot rectangle.
 */
export interface Axis {
  min: number;
  max: number;
  scale: AxisScale;
  ticks: number[];
  /** Data value -> fraction along the axis, in [0, 1]. */
  t: (value: number) => number;
  /** Fraction along the axis -> data value. */
  invert: (fraction: number) => number;
}

const NICE = [1, 2, 2.5, 5, 10];
/** One-two-five per decade. Under a square-root transform these space out legibly,
 *  which evenly-stepped ticks do not. */
const LADDER = [1, 2, 5];

function niceStep(span: number, target: number): number {
  const rough = span / target;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  return NICE.map((n) => n * magnitude).find((n) => n >= rough) ?? 10 * magnitude;
}

function linearTicks(min: number, max: number, target: number): number[] {
  const step = niceStep(max - min, target);
  const first = Math.ceil(min / step - 1e-9);
  const last = Math.floor(max / step + 1e-9);
  const out: number[] = [];
  for (let i = first; i <= last; i += 1) out.push(Number((step * i).toFixed(10)));
  return out;
}

/** Minimum gap between adjacent square-root ticks, as a fraction of the axis.
 *
 *  A one-two-five ladder generates ticks across every decade below the maximum, and
 *  under a square root the small ones collapse together: on a 0-0.63 axis, 1e-5
 *  sits 0.4% along and its whole decade lands inside the leftmost few percent. So
 *  candidates are generated wide and then thinned by how far apart they actually
 *  render, which also means a brushed range near zero keeps the fine ticks it needs.
 */
/*  Sized for the horizontal axis, where labels sit side by side: a five-character
 *  label like `0.005` is about 40px, and 0.075 of the 630px plot is 47px. The
 *  vertical axis stacks its labels and would tolerate a much smaller gap, but one
 *  constant keeps the two axes' tick densities comparable, which matters when the
 *  reader is judging a diagonal. */
const MIN_TICK_GAP = 0.075;

function sqrtTicks(min: number, max: number): number[] {
  const lo = Math.sqrt(min);
  const span = Math.sqrt(max) - lo;
  const at = (value: number) => (span <= 0 ? 0 : (Math.sqrt(value) - lo) / span);

  const candidates: number[] = [];
  if (min <= 0) candidates.push(0);
  const lowest = Math.floor(Math.log10(Math.max(max, 1e-12))) - 5;
  for (let exponent = lowest; exponent <= 1; exponent += 1) {
    for (const base of LADDER) {
      const value = Number((base * 10 ** exponent).toPrecision(12));
      if (value > min + 1e-12 && value < max) candidates.push(value);
    }
  }
  candidates.sort((a, b) => a - b);

  // Keep the endpoint, then walk inward from it so the labelled edge is never the
  // one dropped, and thin anything that would render on top of its neighbour.
  const kept: number[] = [Number(max.toPrecision(12))];
  for (let i = candidates.length - 1; i >= 0; i -= 1) {
    const value = candidates[i]!;
    if (at(kept[kept.length - 1]!) - at(value) >= MIN_TICK_GAP) kept.push(value);
  }
  return kept.reverse();
}

export function axis(
  rawMin: number,
  rawMax: number,
  scale: AxisScale,
  target = 5,
): Axis {
  // A signed range is legal on a linear axis — an embedding coordinate has no
  // meaningful zero end — but not under a square root, which has no real value below
  // zero. Callers that can produce negative values are linear-only.
  const min = scale === "sqrt" ? Math.max(0, rawMin) : rawMin;
  let max = Math.max(rawMax, min + Number.EPSILON);
  let ticks: number[];

  if (scale === "linear") {
    // Snap the maximum up to a whole number of steps so the last tick is the edge.
    // Only meaningful for a zero-anchored axis; a signed range keeps the data's own
    // limits and simply places whatever nice ticks fall inside them.
    const step = niceStep(max - min, target);
    if (min === 0) {
      max = Number((step * Math.max(1, Math.ceil(max / step - 1e-9))).toFixed(10));
    }
    ticks = linearTicks(min, max, target);
  } else {
    ticks = sqrtTicks(min, max);
  }

  const lo = scale === "sqrt" ? Math.sqrt(min) : min;
  const hi = scale === "sqrt" ? Math.sqrt(max) : max;
  const span = hi - lo;

  return {
    min,
    max,
    scale,
    ticks,
    t: (value) => {
      if (span <= 0) return 0;
      const mapped = scale === "sqrt" ? Math.sqrt(Math.max(0, value)) : value;
      return (mapped - lo) / span;
    },
    invert: (fraction) => {
      const mapped = lo + fraction * span;
      return scale === "sqrt" ? mapped * mapped : mapped;
    },
  };
}

/** The frame a brushed range asks for, with no headroom — the reader chose the edges. */
export function zoomed(zoom: Zoom, scale: AxisScale): { x: Axis; y: Axis } {
  return { x: axis(zoom.x0, zoom.x1, scale), y: axis(zoom.y0, zoom.y1, scale) };
}
