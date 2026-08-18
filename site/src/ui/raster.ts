/** The raster layer: the alignment itself, drawn as an image.
 *
 *  DEVIATION, recorded in site/README.md alongside the three the kit already carries.
 *  The other five figures draw marks on a canvas over an SVG axis; this one draws an
 *  ImageData. A region is up to 7,512 columns wide and a selection up to 24,305 rows
 *  deep, which is 182 million cells — three orders of magnitude past what a mark layer
 *  can carry, and the reason this is a picture rather than a scatter.
 *
 *  ## What a pixel means, and what it does not
 *
 *  Nothing here can draw 182 million cells into 550,000 pixels honestly by averaging,
 *  and the two binning axes are not the same operation:
 *
 *  **Along columns, inside one record** a pixel covers a handful of that record's own
 *  positions, so painting the highest-priority state present is a true statement about
 *  one sequence: something in these five columns differs. Priority runs indel, then
 *  non-synonymous, then synonymous, then identical, then unreadable, then absent.
 *
 *  **Across rows** it is not. Twenty-nine records sharing a pixel row have nothing in
 *  common, and blending them would invent a sequence that does not exist while a floor
 *  on the opacity — which an earlier draft of this figure proposed — would flatten
 *  one-in-a-hundred and fifty-in-a-hundred to the same ink and wash the panel to a
 *  single colour at the densities this data actually has. So rows are **sampled**: each
 *  pixel row draws exactly one record, deterministically chosen, and therefore always
 *  names a real sequence a reader can hover, pin and look up. How many records the
 *  sampling passed over is returned here and stated on the figure.
 *
 *  The honest aggregate over every visible row is the column track above the plot,
 *  which is computed from `model/alignment.columnTrack` and never samples. That
 *  division — sampled picture, complete track — is the whole of this figure's claim
 *  about its own fidelity.
 */

import * as palette from "../model/palette.js";
import type { Axis } from "../model/panel.js";
import type { Plot } from "./scatter.js";
import { inner as scatterInner } from "./scatter.js";
import { AlignmentBlock, COVERAGE, DIVERGENCE } from "../model/alignment.js";

export type Vocabulary = "coverage" | "divergence";

/** Draw order within a column bin. Earlier wins, so the rarer and more consequential
 *  state survives being binned with its quiet neighbours. */
const DIVERGENCE_PRIORITY = [
  DIVERGENCE.DELETION,
  DIVERGENCE.INSERTION,
  DIVERGENCE.NONSYNONYMOUS,
  DIVERGENCE.SYNONYMOUS,
  DIVERGENCE.IDENTICAL,
  DIVERGENCE.NO_REFERENCE,
  DIVERGENCE.UNCOMPARABLE,
];

const COVERAGE_PRIORITY = [
  COVERAGE.GAP,
  COVERAGE.AMBIGUOUS,
  COVERAGE.BASE,
  COVERAGE.ABSENT,
];

/** Semantic colours for the divergence vocabulary. These are the figure's own scale,
 *  not the shared trait palette: what a codon did to figure 1's axes is a different
 *  question from which category its record belongs to, and giving them one palette
 *  would make a serotype look like a substitution. */
const DIVERGENCE_INK: Record<number, [number, number, number] | null> = {
  [DIVERGENCE.UNCOMPARABLE]: null,
  [DIVERGENCE.IDENTICAL]: [214, 216, 210],
  [DIVERGENCE.SYNONYMOUS]: [80, 85, 175],
  [DIVERGENCE.NONSYNONYMOUS]: [144, 39, 49],
  [DIVERGENCE.DELETION]: [108, 20, 70],
  [DIVERGENCE.INSERTION]: [179, 111, 0],
  [DIVERGENCE.NO_REFERENCE]: [180, 184, 189],
};

/** Coverage borrows the shared trait colour for a readable base, so clade structure and
 *  coverage extent read off one picture and a colour means the same thing here as in
 *  every other chapter. Only the three non-base states get their own ink. */
const AMBIGUOUS_INK: [number, number, number] = [180, 184, 189];
const GAP_INK: [number, number, number] = [108, 20, 70];

export interface RasterSpec {
  block: AlignmentBlock;
  /** Visible raster rows, already filtered and in the reader's chosen order. */
  rows: number[];
  vocabulary: Vocabulary;
  /** Trait colour per raster row, used for a readable base in the coverage vocabulary. */
  colorOf: (rasterRow: number) => string;
  /** Column axis. Its range is the brushed column window, or the whole region. */
  x: Axis;
}

export interface RasterStats {
  /** Records that got a pixel row of their own. */
  drawn: number;
  /** Records the row sampling passed over. Stated on the figure, never hidden. */
  passedOver: number;
  columnsPerPixel: number;
  rowsPerPixel: number;
  /** Which raster row each pixel row drew, so a hover can name it. */
  rowAtPixel: Int32Array;
}

function parseInk(color: string): [number, number, number] {
  const hex = color.replace("#", "");
  return [
    parseInt(hex.slice(0, 2), 16),
    parseInt(hex.slice(2, 4), 16),
    parseInt(hex.slice(4, 6), 16),
  ];
}

const inkCache = new Map<string, [number, number, number]>();
function ink(color: string): [number, number, number] {
  let found = inkCache.get(color);
  if (!found) {
    found = parseInk(color);
    inkCache.set(color, found);
  }
  return found;
}

/** Paint one region's rows into the plot rectangle.
 *
 *  Returns what it had to leave out, because a figure that samples has to say so.
 */
export function drawRaster(
  canvas: HTMLCanvasElement,
  plot: Plot,
  spec: RasterSpec,
): RasterStats {
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(plot.width * ratio);
  canvas.height = Math.round(plot.height * ratio);
  canvas.style.width = "100%";
  canvas.style.height = "auto";

  const context = canvas.getContext("2d");
  const { w, h } = scatterInner(plot);
  const pixelW = Math.max(1, Math.round(w * ratio));
  const pixelH = Math.max(1, Math.round(h * ratio));
  const rowAtPixel = new Int32Array(pixelH).fill(-1);
  if (!context) {
    return { drawn: 0, passedOver: 0, columnsPerPixel: 0, rowsPerPixel: 0, rowAtPixel };
  }
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.clearRect(0, 0, canvas.width, canvas.height);

  const total = spec.rows.length;
  const image = context.createImageData(pixelW, pixelH);
  const data = image.data;

  const columnLo = Math.max(0, Math.floor(spec.x.min));
  const columnHi = Math.min(spec.block.width, Math.ceil(spec.x.max));
  const columnSpan = Math.max(1, columnHi - columnLo);
  const codonWidth = spec.vocabulary === "divergence" ? 3 : 1;

  const priority = spec.vocabulary === "divergence" ? DIVERGENCE_PRIORITY : COVERAGE_PRIORITY;
  const rank = new Int32Array(16).fill(priority.length);
  priority.forEach((state, index) => {
    rank[state] = index;
  });

  let drawn = 0;
  for (let py = 0; py < pixelH; py += 1) {
    // Which visible rows land on this pixel row, and which one of them speaks for it.
    const from = Math.floor((py * total) / pixelH);
    const to = Math.max(from + 1, Math.floor(((py + 1) * total) / pixelH));
    if (from >= total) break;
    // The middle of the band rather than its edge: deterministic across renders, and it
    // does not bias toward whichever end the current ordering happens to put first.
    const index = Math.min(total - 1, from + ((to - from) >> 1));
    const rasterRow = spec.rows[index]!;
    rowAtPixel[py] = rasterRow;
    drawn += 1;

    const row = spec.block.row(rasterRow);
    const first = spec.block.first[rasterRow]!;
    const last = spec.block.last[rasterRow]!;
    const states =
      spec.vocabulary === "divergence"
        ? divergenceFor(spec.block, rasterRow, row)
        : coverageFor(row, first, last);
    const baseInk = ink(spec.colorOf(rasterRow));

    const rowStart = py * pixelW * 4;
    for (let px = 0; px < pixelW; px += 1) {
      const cLo = columnLo + Math.floor((px * columnSpan) / pixelW);
      const cHi = Math.max(cLo + 1, columnLo + Math.floor(((px + 1) * columnSpan) / pixelW));

      let best = -1;
      let bestRank = priority.length;
      for (let column = cLo; column < cHi && column < spec.block.width; column += 1) {
        const state = states[Math.floor(column / codonWidth)];
        if (state === undefined) continue;
        const r = rank[state]!;
        if (r < bestRank) {
          bestRank = r;
          best = state;
        }
      }
      if (best < 0) continue;

      let rgb: [number, number, number] | null;
      if (spec.vocabulary === "divergence") {
        rgb = DIVERGENCE_INK[best] ?? null;
      } else if (best === COVERAGE.BASE) rgb = baseInk;
      else if (best === COVERAGE.AMBIGUOUS) rgb = AMBIGUOUS_INK;
      else if (best === COVERAGE.GAP) rgb = GAP_INK;
      else rgb = null;
      if (!rgb) continue;

      const at = rowStart + px * 4;
      data[at] = rgb[0];
      data[at + 1] = rgb[1];
      data[at + 2] = rgb[2];
      data[at + 3] = 255;
    }
  }

  context.putImageData(image, Math.round(plot.left * ratio), Math.round(plot.top * ratio));
  return {
    drawn,
    passedOver: Math.max(0, total - drawn),
    columnsPerPixel: columnSpan / pixelW,
    rowsPerPixel: total / pixelH,
    rowAtPixel,
  };
}

const coverageScratch = new Map<number, Uint8Array>();

function coverageFor(row: Uint8Array, first: number, last: number): Uint8Array {
  let out = coverageScratch.get(row.length);
  if (!out) {
    out = new Uint8Array(row.length);
    coverageScratch.set(row.length, out);
  }
  for (let column = 0; column < row.length; column += 1) {
    const code = row[column]!;
    if (code >= 1 && code <= 4) out[column] = COVERAGE.BASE;
    else if (code === 5) out[column] = COVERAGE.AMBIGUOUS;
    else out[column] = column >= first && column <= last ? COVERAGE.GAP : COVERAGE.ABSENT;
  }
  return out;
}

function divergenceFor(block: AlignmentBlock, rasterRow: number, row: Uint8Array): Uint8Array {
  // `block.row` hands back a shared scratch buffer, so the reference has to be read
  // into its own array before the query is used — which `referenceRow` already does.
  const reference = block.referenceRow(rasterRow);
  const codons = Math.floor(block.width / 3);
  const out = new Uint8Array(codons);
  if (!reference) {
    out.fill(DIVERGENCE.NO_REFERENCE);
    return out;
  }
  let spanFirst = -1;
  let spanLast = -1;
  for (let column = 0; column < block.width; column += 1) {
    const q = row[column]!;
    const r = reference[column]!;
    if (q >= 1 && q <= 4 && r >= 1 && r <= 4) {
      if (spanFirst < 0) spanFirst = column;
      spanLast = column;
    }
  }
  for (let codon = 0; codon < codons; codon += 1) {
    const at = codon * 3;
    let comparable = true;
    let deletion = false;
    let insertion = false;
    let same = true;
    for (let k = 0; k < 3; k += 1) {
      const column = at + k;
      const q = row[column]!;
      const r = reference[column]!;
      const qBase = q >= 1 && q <= 4;
      const rBase = r >= 1 && r <= 4;
      if (!qBase || !rBase) comparable = false;
      if (q !== r) same = false;
      if (spanFirst >= 0 && column >= spanFirst && column <= spanLast) {
        if (r !== 0 && q === 0) deletion = true;
        else if (q !== 0 && r === 0) insertion = true;
      }
    }
    if (deletion) out[codon] = DIVERGENCE.DELETION;
    else if (insertion) out[codon] = DIVERGENCE.INSERTION;
    else if (!comparable) out[codon] = DIVERGENCE.UNCOMPARABLE;
    else if (same) out[codon] = DIVERGENCE.IDENTICAL;
    else out[codon] = codonDiffers(row, reference, at);
  }
  return out;
}

const TCAG = new Uint8Array([0, 2, 1, 3, 0, 0]);
const AMINO =
  "FFLLSSSSYY**CC*W" +
  "LLLLPPPPHHQQRRRR" +
  "IIIMTTTTNNKKSSRR" +
  "VVVVAAAADDEEGGGG";

function codonDiffers(row: Uint8Array, reference: Uint8Array, at: number): number {
  const q = AMINO[(TCAG[row[at]!]! * 4 + TCAG[row[at + 1]!]!) * 4 + TCAG[row[at + 2]!]!];
  const r =
    AMINO[
      (TCAG[reference[at]!]! * 4 + TCAG[reference[at + 1]!]!) * 4 + TCAG[reference[at + 2]!]!
    ];
  return q === r ? DIVERGENCE.SYNONYMOUS : DIVERGENCE.NONSYNONYMOUS;
}

/** Below this many columns and rows, the panel can draw the alignment itself.
 *
 *  This is why the payload ships bases rather than the precomputed state codes: at the
 *  bottom of the zoom a reader sees the actual sequence against its actual reference,
 *  which is the only place on the site where that is true. A state-code payload would
 *  have bottomed out one step earlier, at one coloured cell per codon. */
export const LETTER_COLUMNS = 150;
export const LETTER_ROWS = 48;

export function canDrawLetters(columns: number, rows: number): boolean {
  return columns <= LETTER_COLUMNS && rows <= LETTER_ROWS && rows > 0;
}

const SYMBOL = ["-", "A", "C", "G", "T", "N"];

/** The alignment as characters, with the reference above it.
 *
 *  Colour still carries the vocabulary, so the reading a reader learned from the binned
 *  view holds at the bottom of the zoom: a red letter is the non-synonymous codon it was
 *  red for three zoom levels up. Codon boundaries are ruled in a coding region, because
 *  the divergence vocabulary classifies codons and a reader has to be able to see where
 *  one ends.
 */
export function drawLetters(
  canvas: HTMLCanvasElement,
  plot: Plot,
  spec: RasterSpec,
): RasterStats {
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(plot.width * ratio);
  canvas.height = Math.round(plot.height * ratio);
  canvas.style.width = "100%";
  canvas.style.height = "auto";
  const context = canvas.getContext("2d");
  const rowAtPixel = new Int32Array(Math.max(1, Math.round(scatterInner(plot).h * ratio))).fill(-1);
  if (!context) {
    return { drawn: 0, passedOver: 0, columnsPerPixel: 0, rowsPerPixel: 0, rowAtPixel };
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, plot.width, plot.height);

  const { w, h } = scatterInner(plot);
  const columnLo = Math.max(0, Math.floor(spec.x.min));
  const columnHi = Math.min(spec.block.width, Math.ceil(spec.x.max));
  const columns = Math.max(1, columnHi - columnLo);
  // One extra lane at the top for the reference.
  const lanes = spec.rows.length + 1;
  const cellW = w / columns;
  const cellH = h / lanes;

  context.font = `${Math.min(cellH * 0.78, cellW * 1.5, 13).toFixed(1)}px ui-monospace, SFMono-Regular, Menlo, monospace`;
  context.textAlign = "center";
  context.textBaseline = "middle";

  // Codon rules first, so the letters sit on top of them.
  if (spec.block.header.coding) {
    context.strokeStyle = "rgb(49 58 68 / 16%)";
    context.lineWidth = 0.5;
    context.beginPath();
    for (let column = columnLo; column <= columnHi; column += 1) {
      if (column % 3) continue;
      const x = plot.left + (column - columnLo) * cellW;
      context.moveTo(x, plot.top);
      context.lineTo(x, plot.top + h);
    }
    context.stroke();
  }

  const reference = spec.rows.length ? spec.block.referenceRow(spec.rows[0]!) : null;
  if (reference) {
    context.fillStyle = "#313A44";
    for (let column = columnLo; column < columnHi; column += 1) {
      const x = plot.left + (column - columnLo + 0.5) * cellW;
      context.fillText(SYMBOL[reference[column]!] ?? "?", x, plot.top + cellH * 0.5);
    }
  }
  context.strokeStyle = "rgb(49 58 68 / 55%)";
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(plot.left, plot.top + cellH);
  context.lineTo(plot.left + w, plot.top + cellH);
  context.stroke();

  for (let index = 0; index < spec.rows.length; index += 1) {
    const rasterRow = spec.rows[index]!;
    const row = spec.block.row(rasterRow);
    const first = spec.block.first[rasterRow]!;
    const last = spec.block.last[rasterRow]!;
    const states =
      spec.vocabulary === "divergence"
        ? divergenceFor(spec.block, rasterRow, row)
        : coverageFor(row, first, last);
    const baseInk = ink(spec.colorOf(rasterRow));
    const y = plot.top + cellH * (index + 1.5);

    for (let column = columnLo; column < columnHi; column += 1) {
      const state = states[spec.vocabulary === "divergence" ? Math.floor(column / 3) : column];
      if (state === undefined) continue;
      let rgb: [number, number, number] | null;
      if (spec.vocabulary === "divergence") {
        rgb = DIVERGENCE_INK[state] ?? null;
        // Identical codons are drawn as quiet ink rather than the near-white the binned
        // view uses; at this size a letter has to be readable to be worth drawing.
        if (state === DIVERGENCE.IDENTICAL) rgb = [150, 154, 148];
      } else if (state === COVERAGE.BASE) rgb = baseInk;
      else if (state === COVERAGE.AMBIGUOUS) rgb = AMBIGUOUS_INK;
      else if (state === COVERAGE.GAP) rgb = GAP_INK;
      else rgb = [200, 202, 197];
      if (!rgb) rgb = [150, 154, 148];
      context.fillStyle = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
      context.fillText(
        SYMBOL[row[column]!] ?? "?",
        plot.left + (column - columnLo + 0.5) * cellW,
        y,
      );
    }
  }

  return {
    drawn: spec.rows.length,
    passedOver: 0,
    columnsPerPixel: columns / Math.max(1, w * ratio),
    rowsPerPixel: lanes / Math.max(1, h * ratio),
    rowAtPixel,
  };
}

/** The record under a pointer. Rows are sampled, so this is the record the pixel row
 *  actually drew — never a neighbour it stands in for. */
export function rowAtPixel(stats: RasterStats, plot: Plot, offsetY: number): number {
  const ratio = window.devicePixelRatio || 1;
  const py = Math.round((offsetY - plot.top) * ratio);
  if (py < 0 || py >= stats.rowAtPixel.length) return -1;
  return stats.rowAtPixel[py]!;
}

/** The alignment column under a pointer. */
export function columnAtPixel(x: Axis, plot: Plot, offsetX: number): number {
  const { w } = scatterInner(plot);
  const fraction = (offsetX - plot.left) / w;
  if (fraction < 0 || fraction > 1) return -1;
  return Math.floor(x.min + fraction * (x.max - x.min));
}

/** Legend swatches for whichever vocabulary is showing. */
export function legendEntries(
  vocabulary: Vocabulary,
): { label: string; color: string; note?: string }[] {
  if (vocabulary === "divergence") {
    return [
      { label: "Identical to reference", color: "rgb(214,216,210)" },
      { label: "Synonymous", color: "rgb(80,85,175)" },
      { label: "Non-synonymous", color: "rgb(144,39,49)" },
      { label: "Deletion", color: "rgb(108,20,70)", note: "charged one per codon touched" },
      { label: "Insertion", color: "rgb(179,111,0)" },
      { label: "No reference", color: "rgb(180,184,189)", note: "unmeasurable in figure 01" },
    ];
  }
  return [
    { label: "Readable base", color: palette.INK, note: "drawn in the record's own colour" },
    { label: "Ambiguity code", color: "rgb(180,184,189)", note: "material, but unreadable" },
    { label: "Deletion inside the span", color: "rgb(108,20,70)" },
  ];
}
