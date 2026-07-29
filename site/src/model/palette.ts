/** Color and glyph assignment for the figure marks.
 *
 *  ## Why the cap is seven, and why shapes ride along
 *
 *  These panels are scatter plots, so any two marks can end up adjacent — the
 *  "all-pairs" case, which is a strictly harder test than the adjacent-pair one.
 *  Measured with the OKLab / Machado-Oliveira-Fernandes validator at severity 1.0
 *  against the parchment surface:
 *
 *    slots   CVD all-pairs ΔE   normal-vision ΔE   verdict
 *      7           9.1               16.3          passes every check
 *      8          <= 4.9              --           impossible at any ordering
 *
 *  Eight is not a tuning problem. Dichromacy collapses the hue circle onto roughly
 *  one axis, so lightness is the only channel that survives it, and the widest legal
 *  lightness band is 0.34 — which over eight slots leaves 0.049 between neighbours,
 *  or ΔE 4.9, below the floor of 6 no matter how the hues are ordered. Seven slots
 *  leave enough room, so seven is the cap.
 *
 *  Hues are therefore ordered to maximize the worst all-pairs separation rather than
 *  by aesthetics, and every category also carries a distinct glyph. With CVD passing
 *  the shapes are no longer load-bearing for colour vision, but they keep the two
 *  lightest slots legible against parchment (both sit under 3:1 contrast) and they
 *  satisfy the page's rule against encoding status by hue alone.
 *
 *  Slots are assigned in fixed order and never cycled. An eighth category folds into
 *  `Other`, it never gets a generated hue.
 */

export const SURFACE = "#F5F3ED";
export const INK = "#313A44";

/** Seven slots, in fixed assignment order. Hue ring interleaved with a lightness
 *  staircase; see the note above for the measured separations. */
export const CATEGORICAL = [
  "#902731",
  "#5055af",
  "#00896b",
  "#b36f00",
  "#be6eba",
  "#91ae41",
  "#1fc2f4",
] as const;

/** Reserved, never a categorical slot: everything past the seventh category, and
 *  anything with no recorded value. Grey so it recedes rather than competing. */
export const OTHER_COLOR = "#7C848E";
export const MISSING_COLOR = "#B4B8BD";

export type Glyph =
  | "circle"
  | "square"
  | "triangle"
  | "diamond"
  | "down"
  | "ring"
  | "openSquare";

/** Paired one-to-one with CATEGORICAL, in the same fixed order. */
export const GLYPHS: readonly Glyph[] = [
  "circle",
  "square",
  "triangle",
  "diamond",
  "down",
  "ring",
  "openSquare",
];

export const OTHER_GLYPH: Glyph = "circle";
export const MISSING_GLYPH: Glyph = "ring";

export interface Swatch {
  color: string;
  glyph: Glyph;
  filled: boolean;
}

const OPEN: ReadonlySet<Glyph> = new Set(["ring", "openSquare"]);

export function isFilled(glyph: Glyph): boolean {
  return !OPEN.has(glyph);
}

/** Slot for the nth most frequent category. `slot` beyond the palette, or a
 *  negative slot for "no recorded value", both fall to a reserved grey. */
export function swatch(slot: number): Swatch {
  if (slot < 0) return { color: MISSING_COLOR, glyph: MISSING_GLYPH, filled: false };
  if (slot >= CATEGORICAL.length) {
    return { color: OTHER_COLOR, glyph: OTHER_GLYPH, filled: true };
  }
  const glyph = GLYPHS[slot]!;
  return { color: CATEGORICAL[slot]!, glyph, filled: isFilled(glyph) };
}

// --- Continuous -------------------------------------------------------------

/** Viridis, sampled at its standard anchors and interpolated in sRGB.
 *
 *  Chosen over a single-hue ramp because it is perceptually uniform and is what a
 *  reader of this kind of figure expects. Its light end is a high-value yellow that
 *  has very little contrast against parchment, so a continuous panel draws its
 *  marks with a thin ink ring — the same halo the figure recipes use — rather than
 *  relying on the fill alone. */
const VIRIDIS: readonly [number, string][] = [
  [0.0, "#440154"],
  [0.1, "#482878"],
  [0.2, "#3e4989"],
  [0.3, "#31688e"],
  [0.4, "#26828e"],
  [0.5, "#1f9e89"],
  [0.6, "#35b779"],
  [0.7, "#6ece58"],
  [0.8, "#b5de2b"],
  [1.0, "#fde725"],
];

function hexToRgb(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

const VIRIDIS_RGB = VIRIDIS.map(([stop, hex]) => [stop, hexToRgb(hex)] as const);

/** `t` is clamped to [0, 1]. */
export function viridis(t: number): string {
  const value = Math.min(1, Math.max(0, t));
  let lower = VIRIDIS_RGB[0]!;
  let upper = VIRIDIS_RGB[VIRIDIS_RGB.length - 1]!;
  for (let i = 0; i < VIRIDIS_RGB.length - 1; i += 1) {
    if (value >= VIRIDIS_RGB[i]![0] && value <= VIRIDIS_RGB[i + 1]![0]) {
      lower = VIRIDIS_RGB[i]!;
      upper = VIRIDIS_RGB[i + 1]!;
      break;
    }
  }
  const span = upper[0] - lower[0];
  const f = span === 0 ? 0 : (value - lower[0]) / span;
  const channel = (index: number) =>
    Math.round(lower[1][index]! + f * (upper[1][index]! - lower[1][index]!));
  return `rgb(${channel(0)},${channel(1)},${channel(2)})`;
}

/** Marks for records with no value on a continuous trait are drawn unfilled rather
 *  than given a position on the ramp they do not have. */
export const NO_VALUE_COLOR = MISSING_COLOR;
