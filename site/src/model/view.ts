/** The single selection state every figure reads, and its URL serialization.
 *
 * DOM-free and dependency-free, so it is testable under `node --test`.
 *
 * DEVIATION from the kit's rung-4 recipe, which serializes scenario state as
 * base64url of canonical JSON: this state is six short enumerated values, not a
 * float-bearing scenario object, so there is no float-formatting drift to guard
 * against. Readable hash parameters are used instead, because a reader of a data
 * explorer will want to construct and hand-edit a link. Validation is still hard —
 * an unknown value degrades to the default and is reported, never accepted.
 */

import type { Summary } from "./types.js";

export type StatusFilter = "all" | "vouched" | "provisional";
export type AxisScale = "linear" | "sqrt";

/** A brushed axis range, in data units. Null means the full data extent. */
export interface Zoom {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

export interface View {
  selection: string;
  region: string;
  trait: string;
  status: StatusFilter;
  /** Include records flagged engineered_or_construct. */
  engineered: boolean;
  /** Accession held open in the detail view, or null. */
  pinned: string | null;
  /** Axis transform. Square root spreads the low-divergence corner, where most of
   *  the interesting structure sits, without hiding the exact zeros a log axis
   *  cannot show. */
  scale: AxisScale;
  /** Brushed range, or null for the full extent. */
  zoom: Zoom | null;
}

const STATUSES: StatusFilter[] = ["all", "vouched", "provisional"];
const SCALES: AxisScale[] = ["linear", "sqrt"];
/** Every parameter name the encoder can emit. The decoder validates against this,
 *  so a name can only be spelled one way. */
const KEYS = ["sel", "region", "color", "status", "engineered", "record", "scale", "zoom"];

export interface Decoded {
  view: View;
  /** Parameters that were present but not understood. Surfaced, never swallowed. */
  rejected: string[];
}

export function defaultView(summary: Summary): View {
  const selection = pickSelection(summary, summary.defaults.selection);
  return {
    selection: selection.id,
    region: summary.defaults.region,
    trait: selection.default_trait,
    status: "all",
    engineered: true,
    pinned: null,
    scale: "sqrt",
    zoom: null,
  };
}

export function pickSelection(summary: Summary, id: string) {
  const found = summary.selections.find((entry) => entry.id === id);
  if (found) return found;
  const fallback = summary.selections[0];
  if (!fallback) throw new Error("summary.json declares no selections");
  return fallback;
}

/** Regions offered for a figure set, in catalog order. */
export function regionsFor(summary: Summary, figure: "divergence" | "distance") {
  const key = figure === "divergence" ? "in_divergence" : "in_distance";
  return summary.regions.filter((region) => region[key]);
}

/** The trait a selection defaults to, and why it may not be the global default.
 *  `poliovirus_classification` is empty for every non-polio record, so the
 *  non-polio and all-genus selections default to virus_type instead. */
export function defaultTraitNote(summary: Summary, selectionId: string): string | null {
  const selection = pickSelection(summary, selectionId);
  if (selection.default_trait === summary.selections[0]?.default_trait) return null;
  const trait = summary.traits.find((entry) => entry.id === selection.default_trait);
  return trait ? `Defaults to ${trait.label} here: classification is empty for these records.` : null;
}

/** Which trait to colour by after a selection change.
 *
 *  An explicitly chosen trait sticks: someone comparing countries across serotypes
 *  should not have to re-pick country each time. The selection's own default is
 *  applied only when the reader never overrode it — detected by the outgoing trait
 *  still being the outgoing selection's default — which is what keeps a move onto
 *  non-polio from landing on `poliovirus_classification`, a column that is empty for
 *  every non-polio record and would paint the whole panel one grey.
 */
export function traitAfterSelectionChange(
  summary: Summary,
  from: string,
  to: string,
  current: string,
): string {
  const outgoing = pickSelection(summary, from).default_trait;
  return current === outgoing ? pickSelection(summary, to).default_trait : current;
}

export function encode(view: View, summary: Summary): string {
  const base = defaultView(summary);
  const parts: string[] = [];
  const add = (key: string, value: string) => parts.push(`${key}=${encodeURIComponent(value)}`);

  if (view.selection !== base.selection) add("sel", view.selection);
  if (view.region !== base.region) add("region", view.region);
  if (view.trait !== traitDefaultFor(summary, view.selection)) add("color", view.trait);
  if (view.status !== base.status) add("status", view.status);
  if (view.engineered !== base.engineered) add("engineered", view.engineered ? "1" : "0");
  if (view.pinned) add("record", view.pinned);
  if (view.scale !== base.scale) add("scale", view.scale);
  if (view.zoom) {
    const { x0, x1, y0, y1 } = view.zoom;
    add("zoom", [x0, x1, y0, y1].map((v) => v.toPrecision(6)).join(","));
  }
  return parts.join("&");
}

function traitDefaultFor(summary: Summary, selectionId: string): string {
  return pickSelection(summary, selectionId).default_trait;
}

export function decode(hash: string, summary: Summary): Decoded {
  const view = defaultView(summary);
  const rejected: string[] = [];
  const raw = hash.replace(/^#/, "");
  if (!raw) return { view, rejected };

  const seen = new Map<string, string>();
  for (const pair of raw.split("&")) {
    if (!pair) continue;
    const index = pair.indexOf("=");
    if (index < 0) {
      rejected.push(pair);
      continue;
    }
    seen.set(pair.slice(0, index), decodeURIComponent(pair.slice(index + 1)));
  }

  const selection = seen.get("sel");
  if (selection !== undefined) {
    if (summary.selections.some((entry) => entry.id === selection)) {
      view.selection = selection;
      view.trait = traitDefaultFor(summary, selection);
    } else {
      rejected.push(`sel=${selection}`);
    }
  }

  const region = seen.get("region");
  if (region !== undefined) {
    if (summary.regions.some((entry) => entry.id === region)) view.region = region;
    else rejected.push(`region=${region}`);
  }

  const trait = seen.get("color");
  if (trait !== undefined) {
    if (summary.traits.some((entry) => entry.id === trait)) view.trait = trait;
    else rejected.push(`color=${trait}`);
  }

  const status = seen.get("status");
  if (status !== undefined) {
    if ((STATUSES as string[]).includes(status)) view.status = status as StatusFilter;
    else rejected.push(`status=${status}`);
  }

  const engineered = seen.get("engineered");
  if (engineered !== undefined) {
    if (engineered === "0" || engineered === "1") view.engineered = engineered === "1";
    else rejected.push(`engineered=${engineered}`);
  }

  const record = seen.get("record");
  if (record !== undefined) {
    // Accessions are validated against the loaded panel, not here — this module
    // knows nothing about which records exist.
    if (/^[A-Za-z0-9_.]{4,20}$/.test(record)) view.pinned = record;
    else rejected.push(`record=${record}`);
  }

  const scale = seen.get("scale");
  if (scale !== undefined) {
    if ((SCALES as string[]).includes(scale)) view.scale = scale as AxisScale;
    else rejected.push(`scale=${scale}`);
  }

  const zoom = seen.get("zoom");
  if (zoom !== undefined) {
    const parsed = parseZoom(zoom);
    if (parsed) view.zoom = parsed;
    else rejected.push(`zoom=${zoom}`);
  }

  // One list, shared with the encoder's parameter names. Keeping a second literal
  // here is how `color` came to be spelled two ways at once.
  for (const key of seen.keys()) {
    if (!KEYS.includes(key)) rejected.push(key);
  }
  return { view, rejected };
}

/** Round-tripping through encode/decode must be the identity, which is what makes
 *  a URL-restored view and a user-edited view the same object. */
export function roundTrip(view: View, summary: Summary): View {
  return decode(encode(view, summary), summary).view;
}

/** Four finite, ordered, non-negative numbers, or null. Rejects rather than clamps:
 *  a half-understood range would silently show the wrong subset of the data. */
function parseZoom(raw: string): Zoom | null {
  const parts = raw.split(",").map(Number);
  if (parts.length !== 4 || parts.some((v) => !Number.isFinite(v) || v < 0)) return null;
  const [x0, x1, y0, y1] = parts as [number, number, number, number];
  if (!(x1 > x0) || !(y1 > y0)) return null;
  return { x0, x1, y0, y1 };
}

function sameZoom(a: Zoom | null, b: Zoom | null): boolean {
  if (a === null || b === null) return a === b;
  return a.x0 === b.x0 && a.x1 === b.x1 && a.y0 === b.y0 && a.y1 === b.y1;
}

export function sameView(a: View, b: View): boolean {
  return (
    a.selection === b.selection &&
    a.region === b.region &&
    a.trait === b.trait &&
    a.status === b.status &&
    a.engineered === b.engineered &&
    a.pinned === b.pinned &&
    a.scale === b.scale &&
    sameZoom(a.zoom, b.zoom)
  );
}

/** How many records the current selection contributes to the current region, and
 *  whether that is few enough to warrant saying so on the figure. */
export function population(summary: Summary, view: View): RegionCount {
  const selection = pickSelection(summary, view.selection);
  const region = selection.regions[view.region];
  return {
    n: region?.n ?? 0,
    columns: region?.columns ?? 0,
    medianNt: region?.median_nt ?? 0,
    ofAligned: selection.n_aligned,
  };
}

export interface RegionCount {
  n: number;
  columns: number;
  medianNt: number;
  ofAligned: number;
}
