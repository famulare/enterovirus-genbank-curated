/** The scatter renderer: canvas for the marks, SVG for everything with type on it.
 *
 *  DEVIATION from the page's SVG-first figure recipes, recorded in site/README.md.
 *  These panels carry 400 to 24,000 marks; that many SVG nodes cannot be hovered or
 *  re-colored at interactive speed. So the mark layer is a canvas and the axes,
 *  ticks, labels, frame and inspected-mark highlight stay SVG, which keeps the
 *  typography and the hairline-rule vocabulary exactly as the rest of the page.
 */

import * as palette from "../model/palette.js";
import type { Axis } from "../model/panel.js";
import type { Link, Mark } from "../model/mark.js";

export interface Plot {
  width: number;
  height: number;
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export const FOCUS_PLOT: Plot = { width: 720, height: 520, left: 74, top: 18, right: 16, bottom: 58 };
export const THUMB_PLOT: Plot = { width: 168, height: 132, left: 6, top: 6, right: 6, bottom: 6 };
/** Taller, and with a narrow left gutter because a tree's vertical axis carries no
 *  tick labels. A ladder of 2,500 tips needs every pixel of height it can get. */
export const TREE_PLOT: Plot = { width: 720, height: 900, left: 30, top: 14, right: 20, bottom: 58 };

export interface Frame {
  plot: Plot;
  x: Axis;
  y: Axis;
}

export function inner(plot: Plot): { w: number; h: number } {
  return {
    w: plot.width - plot.left - plot.right,
    h: plot.height - plot.top - plot.bottom,
  };
}

export function toScreen(frame: Frame, x: number, y: number): [number, number] {
  const { w, h } = inner(frame.plot);
  return [frame.plot.left + frame.x.t(x) * w, frame.plot.top + h - frame.y.t(y) * h];
}

/** Screen position back to data units. The brush needs this to turn a dragged
 *  rectangle into an axis range. */
export function toData(frame: Frame, sx: number, sy: number): [number, number] {
  const { w, h } = inner(frame.plot);
  return [
    frame.x.invert((sx - frame.plot.left) / w),
    frame.y.invert((frame.plot.top + h - sy) / h),
  ];
}

/** True when a point lies inside the frame's range, so a zoomed panel does not draw
 *  marks outside its own plot rectangle. */
export function within(frame: Frame, x: number, y: number): boolean {
  return x >= frame.x.min && x <= frame.x.max && y >= frame.y.min && y <= frame.y.max;
}

export interface MarkStyle {
  color: string;
  glyph: palette.Glyph;
}

/** Alpha is held at 0.5 as specified. The low-divergence corner saturates to solid,
 *  which is accepted: that saturation is itself the density signal. */
const ALPHA = 0.5;

function drawGlyph(
  context: CanvasRenderingContext2D,
  glyph: palette.Glyph,
  x: number,
  y: number,
  r: number,
): void {
  context.beginPath();
  switch (glyph) {
    case "square":
    case "openSquare":
      context.rect(x - r, y - r, r * 2, r * 2);
      break;
    case "triangle":
    case "openTriangle" as palette.Glyph:
      context.moveTo(x, y - r * 1.2);
      context.lineTo(x + r * 1.1, y + r * 0.85);
      context.lineTo(x - r * 1.1, y + r * 0.85);
      context.closePath();
      break;
    case "down":
      context.moveTo(x, y + r * 1.2);
      context.lineTo(x + r * 1.1, y - r * 0.85);
      context.lineTo(x - r * 1.1, y - r * 0.85);
      context.closePath();
      break;
    case "diamond":
      context.moveTo(x, y - r * 1.3);
      context.lineTo(x + r * 1.15, y);
      context.lineTo(x, y + r * 1.3);
      context.lineTo(x - r * 1.15, y);
      context.closePath();
      break;
    default:
      context.arc(x, y, r, 0, Math.PI * 2);
  }
}

export interface DrawOptions {
  radius: number;
  /** Flagged records get a cross through them rather than being plotted as though
   *  their value were trustworthy at face value. */
  markFlagged: boolean;
  /** Structure to draw beneath the marks — a tree's branches. */
  links?: Link[] | undefined;
}

/** Branch hairlines. Recessive by design: the branches are the armature and the tips
 *  are the data, so the ink goes on the tips. Clipped to the plot rectangle so a
 *  brushed range does not paint a branch across its own axis labels. */
function drawLinks(
  context: CanvasRenderingContext2D,
  frame: Frame,
  links: Link[],
  weight: number,
): void {
  const { w, h } = inner(frame.plot);
  context.save();
  context.beginPath();
  context.rect(frame.plot.left, frame.plot.top, w, h);
  context.clip();

  context.globalAlpha = 0.5;
  context.strokeStyle = palette.INK;
  context.lineWidth = weight;
  context.beginPath();
  for (const link of links) {
    // A segment with both ends past the same edge cannot cross the plot; skipping it
    // keeps a zoomed tree from stroking tens of thousands of invisible paths.
    if (link.x1 < frame.x.min && link.x0 < frame.x.min) continue;
    if (link.x0 > frame.x.max && link.x1 > frame.x.max) continue;
    if (link.y1 < frame.y.min && link.y0 < frame.y.min) continue;
    if (link.y0 > frame.y.max && link.y1 > frame.y.max) continue;
    const [ax, ay] = toScreen(frame, link.x0, link.y0);
    const [bx, by] = toScreen(frame, link.x1, link.y1);
    context.moveTo(ax, ay);
    context.lineTo(bx, by);
  }
  context.stroke();
  context.restore();
}

export function drawMarks(
  canvas: HTMLCanvasElement,
  frame: Frame,
  marks: Mark[],
  styleOf: (mark: Mark) => MarkStyle,
  options: DrawOptions,
): void {
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(frame.plot.width * ratio);
  canvas.height = Math.round(frame.plot.height * ratio);
  canvas.style.width = "100%";
  canvas.style.height = "auto";

  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, frame.plot.width, frame.plot.height);
  if (options.links?.length) {
    drawLinks(context, frame, options.links, options.radius > 1.4 ? 0.8 : 0.5);
  }
  context.globalAlpha = ALPHA;
  context.lineWidth = 1.1;

  for (const mark of marks) {
    if (!within(frame, mark.x, mark.y)) continue;
    const [sx, sy] = toScreen(frame, mark.x, mark.y);
    const style = styleOf(mark);
    const filled = palette.isFilled(style.glyph);
    // Weight below 1 shrinks the mark: a less certain position reads as a smaller
    // one, without touching the fill that carries the category's identity.
    drawGlyph(context, style.glyph, sx, sy, options.radius * mark.weight);
    if (filled) {
      context.fillStyle = style.color;
      context.fill();
    } else {
      context.strokeStyle = style.color;
      context.stroke();
    }
  }

  if (options.markFlagged) {
    context.globalAlpha = 0.9;
    context.strokeStyle = palette.INK;
    context.lineWidth = 1;
    for (const mark of marks) {
      if (!mark.flagged || !within(frame, mark.x, mark.y)) continue;
      const [sx, sy] = toScreen(frame, mark.x, mark.y);
      // Proportionate to the mark, not a fixed inflation. A constant +2.5 made the
      // cross about twice the dot diameter in a dense panel, so a footnote on one
      // record read as major structure.
      const r = options.radius * 1.35;
      context.beginPath();
      context.moveTo(sx - r, sy - r);
      context.lineTo(sx + r, sy + r);
      context.moveTo(sx + r, sy - r);
      context.lineTo(sx - r, sy + r);
      context.stroke();
    }
  }
  context.globalAlpha = 1;
}

/** Axes, frame, ticks and labels. Returned as markup for `innerHTML`, matching the
 *  page's figure convention. */
export function axesMarkup(frame: Frame, xLabel: string, yLabel: string): string {
  const { plot } = frame;
  const { w, h } = inner(plot);
  const xt = frame.x.ticks;
  const yt = frame.y.ticks;
  const fmt = (value: number) => tickLabel(value, frame);

  const grid = [
    ...xt.map((value) => {
      const [sx] = toScreen(frame, value, 0);
      return `<line class="grid-line" x1="${sx}" y1="${plot.top}" x2="${sx}" y2="${plot.top + h}"/>`;
    }),
    ...yt.map((value) => {
      const [, sy] = toScreen(frame, 0, value);
      return `<line class="grid-line" x1="${plot.left}" y1="${sy}" x2="${plot.left + w}" y2="${sy}"/>`;
    }),
  ].join("");

  const xTicks = xt
    .map((value) => {
      const [sx] = toScreen(frame, value, 0);
      return (
        `<line class="tick-mark" x1="${sx}" y1="${plot.top + h}" x2="${sx}" y2="${plot.top + h + 5}"/>` +
        `<text class="tick" x="${sx}" y="${plot.top + h + 21}" text-anchor="middle">${fmt(value)}</text>`
      );
    })
    .join("");

  const yTicks = yt
    .map((value) => {
      const [, sy] = toScreen(frame, 0, value);
      return (
        `<line class="tick-mark" x1="${plot.left - 5}" y1="${sy}" x2="${plot.left}" y2="${sy}"/>` +
        `<text class="tick" x="${plot.left - 9}" y="${sy + 5}" text-anchor="end">${fmt(value)}</text>`
      );
    })
    .join("");

  return `
    <rect class="plot-bg" x="${plot.left}" y="${plot.top}" width="${w}" height="${h}"/>
    ${grid}
    <rect class="panel-bg" fill="none" x="${plot.left}" y="${plot.top}" width="${w}" height="${h}"/>
    ${xTicks}${yTicks}
    <text class="axis-label" x="${plot.left + w / 2}" y="${plot.height - 6}" text-anchor="middle">${xLabel}</text>
    ${
      yLabel
        ? `<text class="axis-label" transform="translate(${Math.min(14, plot.left - 4)} ${
            plot.top + h / 2
          }) rotate(-90)" text-anchor="middle">${yLabel}</text>`
        : ""
    }
  `;
}

/** Enough decimals for the value itself, rather than a single count for the whole
 *  axis: a square-root axis carries ticks spanning several orders of magnitude. */
function tickLabel(value: number, frame: Frame): string {
  if (value === 0) return "0";
  // On magnitude, not on the signed value: testing `value < 0.001` sent every
  // negative tick down the exponential path, so a signed axis labelled -0.4 as
  // "-4e-1".
  const size = Math.abs(value);
  const span = Math.max(frame.x.max - frame.x.min, frame.y.max - frame.y.min);
  if (size < 0.001) return value.toExponential(0);
  const decimals = size < 0.01 ? 3 : size < 0.1 ? 2 : span < 0.2 ? 3 : 2;
  return value.toFixed(decimals);
}

/** The inspected and held marks, drawn in SVG on top of the canvas so they get the
 *  page's two-tier interaction colors and crisp edges. */
export function highlightMarkup(
  frame: Frame,
  inspected: Mark | null,
  held: Mark | null,
  radius: number,
): string {
  const ring = (point: Mark, className: string) => {
    if (!within(frame, point.x, point.y)) return "";
    const [sx, sy] = toScreen(frame, point.x, point.y);
    return `<circle class="${className}" cx="${sx}" cy="${sy}" r="${radius + 4}" fill="none"/>`;
  };
  return (
    (held ? ring(held, "mark-held") : "") + (inspected ? ring(inspected, "mark-inspected") : "")
  );
}

/** The live brush rectangle, in plot coordinates, clamped to the plot area. */
export function brushMarkup(frame: Frame, box: Box | null): string {
  if (!box) return "";
  const { w, h } = inner(frame.plot);
  const x0 = Math.max(frame.plot.left, Math.min(box.x0, box.x1));
  const x1 = Math.min(frame.plot.left + w, Math.max(box.x0, box.x1));
  const y0 = Math.max(frame.plot.top, Math.min(box.y0, box.y1));
  const y1 = Math.min(frame.plot.top + h, Math.max(box.y0, box.y1));
  if (x1 <= x0 || y1 <= y0) return "";
  return `<rect class="brush" x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}"/>`;
}

export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** Plot-space position from a pointer event, in the frame's own coordinates. */
export function plotPosition(
  canvas: HTMLCanvasElement,
  frame: Frame,
  clientX: number,
  clientY: number,
): [number, number] {
  const rect = canvas.getBoundingClientRect();
  return [
    ((clientX - rect.left) / rect.width) * frame.plot.width,
    ((clientY - rect.top) / rect.height) * frame.plot.height,
  ];
}

/** Nearest mark to a plot-space position, within `limit` pixels. */
export function nearest(
  frame: Frame,
  marks: Mark[],
  px: number,
  py: number,
  limit = 14,
): Mark | null {
  let best: Mark | null = null;
  let bestDistance = limit * limit;
  for (const point of marks) {
    if (!within(frame, point.x, point.y)) continue;
    const [sx, sy] = toScreen(frame, point.x, point.y);
    const dx = sx - px;
    const dy = sy - py;
    const distance = dx * dx + dy * dy;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = point;
    }
  }
  return best;
}

/** Mark radius scales down as the population grows, so a dense panel stays readable
 *  without changing the alpha the specification fixed. */
export function radiusFor(count: number, thumbnail = false): number {
  if (thumbnail) return count > 8000 ? 0.9 : count > 2000 ? 1.2 : 1.8;
  if (count > 15000) return 1.5;
  if (count > 6000) return 2;
  if (count > 1500) return 2.6;
  return 3.4;
}
