/** Mount. Loads the built artifacts, renders the chrome and both figure chapters, and
 *  keeps the URL hash and the control DOM in step with each other.
 *
 *  One selection state drives every chapter, so a color, a filter or a region chosen
 *  once applies everywhere and a record noticed in one figure is findable in the next.
 *  Brushing is the exception: a zoom belongs to the figure it was drawn on, so it is
 *  tracked per chapter rather than in the shared view. */

import { assertSchema, type Summary } from "./model/types.js";
import {
  decode,
  defaultView,
  encode,
  sameView,
  traitAfterSelectionChange,
  type View,
  type Zoom,
} from "./model/view.js";
import { Records, type RecordTable } from "./model/records.js";
import type { Mark } from "./model/mark.js";
import {
  DISTANCE,
  DIVERGENCE,
  NUCLEOTIDE_TREE,
  PROTEIN_DISTANCE,
  PROTEIN_TREE,
} from "./model/specs.js";
import * as chapter from "./ui/chapter.js";
import * as alignmentChapter from "./ui/alignment.js";
import {
  assertProfileSchema,
  loadAlignment,
  type AlignmentBlock,
  type ProfileFile,
} from "./model/alignment.js";
import type { Vocabulary } from "./ui/raster.js";
import {
  onControlEdit,
  readControls,
  renderControls,
  renderNotes,
  renderStatus,
  syncControls,
} from "./ui/controls.js";
import {
  renderBuildLine,
  renderConsensusInflation,
  renderSabinFrameIndels,
  renderDataQuality,
  renderFacts,
  renderIntegrityNotes,
  renderPopulationTable,
  renderRawDate,
  renderReleaseBand,
} from "./ui/report.js";
import {
  renderPinned,
  renderReadout,
  type DerivedField,
  type PinnedPanel,
} from "./ui/detail.js";
import { byId, num } from "./ui/dom.js";

interface Manifest {
  build_identity: string;
}

// Page order. Each id matches an element id prefix in index.html.
const SPECS = [DIVERGENCE, DISTANCE, NUCLEOTIDE_TREE, PROTEIN_DISTANCE, PROTEIN_TREE];

let summary: Summary;
let records: Records;
let view: View;
let rejected: string[] = [];
let writingHash = false;

/** Chapter 06's own state. It is not in `SPECS` because it is not a `ChapterSpec`: a
 *  raster row is an extent, not a point, so it brings its own hit test and its own
 *  strip. Everything shared — filters, colour, pin, the URL — still reaches it. */
let alignmentState: alignmentChapter.AlignmentState | null = null;
let alignmentVocabulary: Vocabulary = "coverage";
/** One region's cells at a time, keyed `selection/region`. Holding all six regions of
 *  `all` would be 55 MB for five the reader is not looking at, so the previous one is
 *  dropped on switch. */
let alignmentCells: { key: string; block: AlignmentBlock } | null = null;
let alignmentProfiles: { key: string; profile: ProfileFile } | null = null;
let alignmentHeld: number | null = null;
/** The chapter costs nothing until the reader reaches it. */
let alignmentMounted = false;
let alignmentPending = false;
/** Set once a reader on a narrow viewport has accepted the download. */
let alignmentAccepted = false;

/** Per-chapter runtime state. `zoom` lives here, not in the shared view, because a
 *  brushed range means something only on the figure it was drawn on. */
const chapters = new Map<
  string,
  { state: chapter.ChapterState | null; zoom: Zoom | null; heldRecord: number | null }
>(SPECS.map((spec) => [spec.id, { state: null, zoom: null, heldRecord: null }]));

async function loadJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

function slot(id: string) {
  const found = chapters.get(id);
  if (!found) throw new Error(`unknown chapter ${id}`);
  return found;
}

function refreshChrome(): void {
  syncControls(view);
  renderNotes(summary, view);
  renderStatus(summary, view, rejected);
}

/** A chapter's own view: the shared selection, with that chapter's brush applied. */
function chapterView(id: string): View {
  return { ...view, zoom: slot(id).zoom };
}

async function rebuild(spec: (typeof SPECS)[number]): Promise<void> {
  const entry = slot(spec.id);
  const container = byId(`${spec.id}-strip`).closest(".figure");
  container?.setAttribute("aria-busy", "true");
  try {
    const sets = await spec.sets(
      view.selection,
      chapter.regionsFor(summary, spec),
      view.scale,
    );
    entry.state = chapter.buildState(
      spec,
      summary,
      records,
      chapterView(spec.id),
      sets,
      entry.heldRecord,
    );
    chapter.render(entry.state);
    paintInspection(spec.id);
  } catch (error) {
    byId(`${spec.id}-note`).textContent =
      `Could not load this figure: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    container?.removeAttribute("aria-busy");
  }
}

/** Redraw without refetching — for a filter, color or brush change. */
function redraw(id: string): void {
  const entry = slot(id);
  if (!entry.state) return;
  chapter.applyView(entry.state, chapterView(id));
  chapter.render(entry.state);
  paintInspection(id);
}

function paintInspection(id: string): void {
  const entry = slot(id);
  if (!entry.state) return;
  const spec = entry.state.spec;
  const set = chapter.currentSet(entry.state);
  renderReadout(spec, records, set, entry.state.held ?? entry.state.inspected, !!entry.state.held);
  paintPinned();
  wireRenderedControls(id);
}

/** One inspector for the page, assembled from every chapter that holds the record.
 *
 *  Also the only place `type_concordance` and the panel-scoped coverage can be read:
 *  the color control can paint by both, but neither is a recorded field, so without
 *  this the reader could see a color they could not look up. */
function paintPinned(): void {
  const row = [...chapters.values()].find((entry) => entry.heldRecord !== null)?.heldRecord ?? null;
  if (row === null) {
    renderPinned(records, null, [], []);
    return;
  }

  const panels: PinnedPanel[] = [];
  for (const spec of SPECS) {
    const state = slot(spec.id).state;
    if (!state) continue;
    const set = chapter.currentSet(state);
    const mark = state.held ?? set.marks.find((m) => m.record === row);
    if (!mark) continue;
    panels.push({
      figure: spec.title,
      region: summary.regions.find((r) => r.id === state.region)?.label ?? state.region,
      rows: spec.measured(set, mark),
    });
  }

  if (alignmentState) {
    const rasterRow = alignmentState.block.rowForRecord(row);
    if (rasterRow >= 0) {
      panels.push({
        figure: "Alignment",
        region:
          summary.regions.find((r) => r.id === alignmentState!.region)?.label ??
          alignmentState.region,
        rows: alignmentChapter.measured(alignmentState, rasterRow),
      });
    }
  }

  const derived: DerivedField[] = [];
  const anyState = slot(SPECS[0]!.id).state;
  if (anyState) {
    const concordance = chapter.concordanceValue(summary, records, {
      ...view,
      trait: "type_concordance",
    });
    const value = concordance?.(row);
    if (value) {
      derived.push({
        label: summary.traits.find((t) => t.id === "type_concordance")?.label ?? "Type concordance",
        value,
        why: "Curated virus_type judged against the alignment this record was placed in, so it depends on the serotype selected.",
      });
    }
  }

  renderPinned(records, row, panels, derived);
}

/** Buttons that live inside re-rendered markup need rebinding, not one listener at
 *  mount. */
function wireRenderedControls(id: string): void {
  byId("record-detail")
    .querySelector<HTMLButtonElement>("[data-unpin]")
    ?.addEventListener("click", () => setHeld(id, null));
  byId(`${id}-note`)
    .querySelector<HTMLButtonElement>("[data-reset-zoom]")
    ?.addEventListener("click", () => {
      slot(id).zoom = null;
      redraw(id);
    });
  byId(`${id}-note`)
    .querySelector<HTMLButtonElement>("[data-send-to-alignment]")
    ?.addEventListener("click", () => {
      const zoom = slot(id).zoom;
      if (!zoom) return;
      // The rectangle travels, not the record list — 400 indices would not fit a
      // readable link, and the chapter that drew the box can resolve it again. Only the
      // alignment chapter reads it, so no other population moves under the reader.
      view.restrict = { from: id, rect: zoom };
      writeHash();
      byId(alignmentChapter.ID).scrollIntoView({ behavior: "smooth", block: "start" });
      requestAlignment();
    });
}

/** The alignment chapter's own rebuild.
 *
 *  Separate from `rebuild` because its source is not a `ChapterSpec.sets` — that
 *  interface decodes every region of a selection at once, which is right when one panel
 *  file holds them all and wrong when a single region is 25 MB.
 */
async function rebuildAlignment(): Promise<void> {
  if (!alignmentMounted || alignmentPending) return;
  const regions = alignmentChapter.regionsFor(summary);
  const region = alignmentChapter.resolveRegion(regions, view.region);
  const key = `${view.selection}/${region}`;
  const container = byId(`${alignmentChapter.ID}-strip`).closest(".figure");

  alignmentPending = true;
  container?.setAttribute("aria-busy", "true");
  try {
    if (alignmentProfiles?.key !== view.selection) {
      const response = await fetch(`data/alignments/${view.selection}/profile.json`, {
        cache: "no-cache",
      });
      if (!response.ok) throw new Error(`profile: HTTP ${response.status}`);
      alignmentProfiles = {
        key: view.selection,
        profile: assertProfileSchema((await response.json()) as ProfileFile),
      };
    }
    if (alignmentCells?.key !== key) {
      // Drop the old region before fetching the new one, so the two are never resident
      // together.
      alignmentCells = null;
      alignmentCells = {
        key,
        block: await loadAlignment(`data/alignments/${view.selection}/${region}.bin.gz`),
      };
    }

    const resolved = resolveRestrict(region);
    alignmentState = alignmentChapter.buildState(
      summary,
      records,
      view,
      region,
      alignmentCells.block,
      alignmentProfiles.profile,
      {
        vocabulary: alignmentVocabulary,
        external: externalOrder(),
        restrictTo: resolved && "records" in resolved ? resolved.records : null,
        restrictDroppedFrom: resolved && "dropped" in resolved ? resolved.dropped : null,
        previousHeld: alignmentHeld,
      },
    );
    alignmentChapter.render(alignmentState);
    wireAlignmentControls();
  } catch (error) {
    byId(`${alignmentChapter.ID}-note`).textContent =
      `Could not load the alignment: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    alignmentPending = false;
    container?.removeAttribute("aria-busy");
  }
}

/** Sort keys for the two orderings this chapter cannot compute alone.
 *
 *  A place in the tree's ladder and a non-synonymous rate are other figures'
 *  measurements. Reading them off those chapters' loaded state keeps one definition of
 *  each rather than a second implementation here that could disagree. */
function externalOrder(): Map<number, number> | null {
  if (view.order === "ladder") {
    const state = slot(NUCLEOTIDE_TREE.id).state;
    if (!state) return null;
    const keys = new Map<number, number>();
    for (const mark of chapter.currentSet(state).marks) keys.set(mark.record, mark.y);
    return keys.size ? keys : null;
  }
  if (view.order === "divergence") {
    const state = slot(DIVERGENCE.id).state;
    if (!state) return null;
    const keys = new Map<number, number>();
    for (const mark of chapter.currentSet(state).marks) keys.set(mark.record, -mark.y);
    return keys.size ? keys : null;
  }
  return null;
}

/** The set another chapter's brush handed over, resolved against that chapter's own
 *  marks. The rectangle travels in the URL rather than the record list, so this is where
 *  it becomes a set again — and the count the figure reports is the one resolved here,
 *  not the one baked into the link, because `encode` rounds the edges. */
function resolveRestrict(region: string): { records: Set<number> } | { dropped: string } | null {
  const restrict = view.restrict;
  if (!restrict) return null;
  const state = slot(restrict.from).state;
  if (!state) return null;

  // A rectangle means something only on the axes it was drawn on, and a chapter's axes
  // are per region. The two chapters do not always land on the same one — the
  // polyprotein exists in divergence and here but not in the distance chapters, so
  // `resolveRegion` drops those to P1. Carrying the set across anyway would answer a
  // question about P1 with a picture of the polyprotein, which is worse than refusing.
  if (state.region !== region) {
    return { dropped: state.region };
  }

  const set = chapter.currentSet(state);
  const { x0, x1, y0, y1 } = restrict.rect;
  const inside = new Set<number>();
  for (const mark of set.marks) {
    if (mark.x >= x0 && mark.x <= x1 && mark.y >= y0 && mark.y <= y1) inside.add(mark.record);
  }
  return inside.size ? { records: inside } : null;
}

/** Re-speak the readout for whatever row is under the cursor or pinned. */
function refreshAlignmentReadout(): void {
  if (!alignmentState) return;
  const row = alignmentState.inspected >= 0 ? alignmentState.inspected : (alignmentState.held ?? -1);
  alignmentChapter.renderRowReadout(alignmentState, row);
}

function wireAlignmentControls(): void {
  const note = byId(`${alignmentChapter.ID}-note`);
  note.querySelector<HTMLButtonElement>("[data-reset-zoom]")?.addEventListener("click", () => {
    view.zoom = null;
    if (alignmentState) {
      alignmentState.zoom = null;
      alignmentChapter.render(alignmentState);
      wireAlignmentControls();
      refreshAlignmentReadout();
    }
  });
  note.querySelector<HTMLButtonElement>("[data-clear-restrict]")?.addEventListener("click", () => {
    view.restrict = null;
    writeHash();
    void rebuildAlignment();
  });
  for (const button of byId(`${alignmentChapter.ID}-legend`).querySelectorAll<HTMLButtonElement>(
    "[data-vocab]",
  )) {
    button.addEventListener("click", () => {
      alignmentVocabulary = button.dataset.vocab as Vocabulary;
      if (alignmentState) {
        alignmentState.vocabulary = alignmentVocabulary;
        alignmentChapter.render(alignmentState);
        wireAlignmentControls();
        // The readout has to be re-spoken, not just the picture: `pointermove` returns
        // early when the row under the cursor has not changed, so without this the
        // reader is left holding a codon readout for a row described in coverage terms.
        refreshAlignmentReadout();
      }
    });
  }
}

function commit(next: View, { reload }: { reload: boolean }): void {
  view = next;
  rejected = [];
  writeHash();
  refreshChrome();
  for (const spec of SPECS) {
    if (reload || !slot(spec.id).state) void rebuild(spec);
    else redraw(spec.id);
  }
  // Always a rebuild, never a redraw: a region change means different cells, and the
  // ordering, the filters and the handed-over set are all resolved during the build.
  void rebuildAlignment();
}

function handleEdit(): void {
  const next = readControls(view);
  if (sameView({ ...next, zoom: view.zoom }, view)) return;
  if (next.selection !== view.selection) {
    next.trait = traitAfterSelectionChange(summary, view.selection, next.selection, view.trait);
  }
  // A new selection, region or scale means new marks — the scale selects which
  // embedding the distance chapter shows, not just how its axis is drawn. A filter or
  // color change is only a redraw, and the color assignment is deliberately not
  // rebuilt. Rebuilding is cheap after the first load: the panel file is cached, so
  // this re-decodes rather than refetches.
  const reload =
    next.selection !== view.selection ||
    next.region !== view.region ||
    next.scale !== view.scale;
  if (next.selection !== view.selection) {
    for (const entry of chapters.values()) {
      entry.zoom = null;
      entry.heldRecord = null;
    }
  }
  commit({ ...next, zoom: null }, { reload });
}

function writeHash(): void {
  const encoded = encode({ ...view, zoom: null }, summary);
  const target = encoded ? `#${encoded}` : "#top";
  if (location.hash === target) return;
  writingHash = true;
  history.replaceState(null, "", target);
  writingHash = false;
}

function handleHashChange(): void {
  if (writingHash) return;
  const decoded = decode(location.hash, summary);
  view = decoded.view;
  rejected = decoded.rejected;
  refreshChrome();
  for (const spec of SPECS) void rebuild(spec);
}

function setInspected(id: string, mark: Mark | null): void {
  const entry = slot(id);
  if (!entry.state || entry.state.inspected === mark) return;
  entry.state.inspected = mark;
  chapter.renderHighlight(entry.state);
  const set = chapter.currentSet(entry.state);
  renderReadout(entry.state.spec, records, set, mark ?? entry.state.held, !!entry.state.held);
}

function setHeld(id: string, mark: Mark | null): void {
  const entry = slot(id);
  if (!entry.state) return;
  entry.state.held = mark;
  entry.heldRecord = mark ? mark.record : null;
  // A pinned record is a cross-chapter idea: pinning here highlights the same record
  // in the other figure, which is what makes the two views one instrument.
  for (const [other, otherEntry] of chapters) {
    if (other === id || !otherEntry.state) continue;
    otherEntry.heldRecord = entry.heldRecord;
    otherEntry.state.held =
      entry.heldRecord === null
        ? null
        : (otherEntry.state.visibleMarks.find((m) => m.record === entry.heldRecord) ?? null);
    chapter.renderHighlight(otherEntry.state);
    paintInspection(other);
  }
  alignmentHeld = entry.heldRecord;
  if (alignmentState) {
    const rasterRow = alignmentHeld === null ? -1 : alignmentState.block.rowForRecord(alignmentHeld);
    alignmentState.held = rasterRow >= 0 && alignmentState.visible.includes(rasterRow) ? rasterRow : null;
    alignmentChapter.renderHighlight(alignmentState);
  }
  view.pinned = mark ? records.accession(mark.record) : null;
  writeHash();
  chapter.renderHighlight(entry.state);
  paintInspection(id);
}

function wireChapter(spec: (typeof SPECS)[number]): void {
  const canvas = byId<HTMLCanvasElement>(`${spec.id}-canvas`);
  const id = spec.id;
  /** A press becomes a zoom if the pointer travels past this many plot units, and a
   *  pin if it does not — one gesture serves both without a modifier. */
  const DRAG_THRESHOLD = 5;
  let start: [number, number] | null = null;
  let moved = false;

  canvas.addEventListener("pointerdown", (event) => {
    const state = slot(id).state;
    if (event.button !== 0 || !state) return;
    start = chapter.positionAt(state, event.clientX, event.clientY);
    moved = false;
    if (start) canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    const state = slot(id).state;
    if (!state) return;
    if (start) {
      const at = chapter.positionAt(state, event.clientX, event.clientY);
      if (!at) return;
      if (Math.abs(at[0] - start[0]) > DRAG_THRESHOLD || Math.abs(at[1] - start[1]) > DRAG_THRESHOLD) {
        moved = true;
      }
      if (moved) {
        state.brush = { x0: start[0], y0: start[1], x1: at[0], y1: at[1] };
        setInspected(id, null);
        chapter.renderHighlight(state);
      }
      return;
    }
    setInspected(id, chapter.markAt(state, event.clientX, event.clientY));
  });

  canvas.addEventListener("pointerup", (event) => {
    const state = slot(id).state;
    if (!state || !start) return;
    const at = chapter.positionAt(state, event.clientX, event.clientY);
    const from = start;
    const dragged = moved;
    start = null;
    moved = false;
    state.brush = null;

    if (dragged && at) {
      const zoom = chapter.boxToZoom(state, { x0: from[0], y0: from[1], x1: at[0], y1: at[1] });
      // A box holding nothing is a slip, not an instruction; leave the view alone.
      if (zoom) {
        slot(id).zoom = zoom;
        redraw(id);
      } else {
        chapter.renderHighlight(state);
      }
      return;
    }
    const mark = chapter.markAt(state, event.clientX, event.clientY);
    if (mark) setHeld(id, mark);
  });

  const cancel = () => {
    const state = slot(id).state;
    start = null;
    moved = false;
    if (state) {
      state.brush = null;
      chapter.renderHighlight(state);
    }
  };
  canvas.addEventListener("pointercancel", cancel);
  canvas.addEventListener("pointerleave", () => {
    if (!start) setInspected(id, null);
  });

  canvas.addEventListener("dblclick", () => {
    if (slot(id).zoom) {
      slot(id).zoom = null;
      redraw(id);
    }
  });

  // Keyboard parity: every value reachable by hover must be reachable without a
  // pointer, so arrows walk the cloud and Enter pins.
  canvas.addEventListener("keydown", (event) => {
    const state = slot(id).state;
    if (!state) return;
    const marks = chapter.ordered(state);
    if (!marks.length) return;
    const at = state.inspected ? marks.indexOf(state.inspected) : -1;
    let next = at;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowUp":
        next = at < 0 ? 0 : Math.min(marks.length - 1, at + 1);
        break;
      case "ArrowLeft":
      case "ArrowDown":
        next = at < 0 ? marks.length - 1 : Math.max(0, at - 1);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = marks.length - 1;
        break;
      case "Enter":
        if (state.inspected) setHeld(id, state.inspected);
        event.preventDefault();
        return;
      case "Escape":
        if (slot(id).zoom) {
          slot(id).zoom = null;
          redraw(id);
        }
        setInspected(id, null);
        setHeld(id, null);
        return;
      default:
        return;
    }
    event.preventDefault();
    setInspected(id, marks[next] ?? null);
  });

  byId(`${id}-strip`).addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>(".thumb");
    if (!button?.dataset.region) return;
    // A region change invalidates every chapter's brush: the same rectangle means
    // something different once the axes have moved.
    for (const entry of chapters.values()) entry.zoom = null;
    commit({ ...view, region: button.dataset.region, zoom: null }, { reload: false });
  });
}

/** The raster's own pointer and keyboard handling.
 *
 *  Deliberately not `wireChapter`. That function's gestures resolve to a mark through
 *  `scatter.nearest`, which picks by two-dimensional distance; here a row is identified
 *  by vertical position alone, and the horizontal axis is a column index rather than a
 *  second coordinate of the same point.
 */
function wireAlignment(): void {
  const canvas = byId<HTMLCanvasElement>(`${alignmentChapter.ID}-canvas`);
  const DRAG_THRESHOLD = 5;
  let start: [number, number] | null = null;
  let moved = false;
  /** Keyboard traversal walks the column track, so this is a column index, not a row. */
  let cursor = -1;

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !alignmentState) return;
    start = alignmentChapter.positionAt(event.clientX, event.clientY);
    moved = false;
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    const state = alignmentState;
    if (!state) return;
    if (start) {
      const at = alignmentChapter.positionAt(event.clientX, event.clientY);
      if (Math.abs(at[0] - start[0]) > DRAG_THRESHOLD || Math.abs(at[1] - start[1]) > DRAG_THRESHOLD) {
        moved = true;
      }
      if (moved) {
        state.brush = { x0: start[0], y0: start[1], x1: at[0], y1: at[1] };
        alignmentChapter.renderHighlight(state);
      }
      return;
    }
    const row = alignmentChapter.rowAt(state, event.clientX, event.clientY);
    if (row === state.inspected) return;
    state.inspected = row;
    alignmentChapter.renderHighlight(state);
    alignmentChapter.renderRowReadout(state, row);
  });

  canvas.addEventListener("pointerup", (event) => {
    const state = alignmentState;
    if (!state || !start) return;
    const at = alignmentChapter.positionAt(event.clientX, event.clientY);
    const from = start;
    const dragged = moved;
    start = null;
    moved = false;
    state.brush = null;

    if (dragged) {
      const zoom = alignmentChapter.boxToZoom(state, {
        x0: from[0],
        y0: from[1],
        x1: at[0],
        y1: at[1],
      });
      if (zoom) {
        state.zoom = zoom;
        alignmentChapter.render(state);
        wireAlignmentControls();
      } else {
        alignmentChapter.renderHighlight(state);
      }
      return;
    }
    const row = alignmentChapter.rowAt(state, event.clientX, event.clientY);
    if (row >= 0) {
      setHeldFromAlignment(row);
      alignmentChapter.renderRowReadout(state, row);
    }
  });

  canvas.addEventListener("pointerleave", () => {
    const state = alignmentState;
    if (start || !state) return;
    state.inspected = -1;
    alignmentChapter.renderHighlight(state);
    alignmentChapter.renderRowReadout(state, state.held ?? -1);
  });

  canvas.addEventListener("pointercancel", () => {
    start = null;
    moved = false;
    if (alignmentState) {
      alignmentState.brush = null;
      alignmentChapter.renderHighlight(alignmentState);
    }
  });

  canvas.addEventListener("dblclick", () => {
    if (alignmentState?.zoom) {
      alignmentState.zoom = null;
      alignmentChapter.render(alignmentState);
      wireAlignmentControls();
    }
  });

  canvas.addEventListener("keydown", (event) => {
    const state = alignmentState;
    if (!state || !state.track) return;
    let handled = true;
    switch (event.key) {
      case "ArrowRight":
        cursor = alignmentChapter.columnStep(state, cursor, 1);
        break;
      case "ArrowLeft":
        cursor = alignmentChapter.columnStep(state, cursor, -1);
        break;
      case "PageUp":
        cursor = alignmentChapter.columnStep(state, cursor, 50);
        break;
      case "PageDown":
        cursor = alignmentChapter.columnStep(state, cursor, -50);
        break;
      case "ArrowDown":
      case "ArrowUp": {
        // The secondary axis. Only once the brush has made the stack a list — above that
        // the rows are sampled, so most presses would select a record not on screen.
        if (!alignmentChapter.rowsAreSteppable(state)) return;
        const next = alignmentChapter.rowStep(state, state.inspected, event.key === "ArrowDown" ? 1 : -1);
        if (next < 0) return;
        event.preventDefault();
        state.inspected = next;
        alignmentChapter.renderHighlight(state);
        alignmentChapter.renderRowReadout(state, next);
        return;
      }
      case "Enter":
        if (state.inspected >= 0) {
          event.preventDefault();
          setHeldFromAlignment(state.inspected);
          alignmentChapter.renderRowReadout(state, state.inspected);
        }
        return;
      case "Escape":
        if (state.zoom) {
          state.zoom = null;
          alignmentChapter.render(state);
          wireAlignmentControls();
        }
        cursor = -1;
        state.inspected = -1;
        alignmentChapter.renderHighlight(state);
        return;
      default:
        handled = false;
    }
    if (!handled) return;
    event.preventDefault();
    // The readout speaks the track, because the track is what the keyboard is walking:
    // one column, and how much of the visible population can be read there.
    const covered = state.track.covered[cursor] ?? 0;
    const differing = state.track.differing[cursor] ?? 0;
    const target = byId(`${alignmentChapter.ID}-readout`);
    target.classList.add("is-active");
    target.innerHTML =
      `<span class="readout-key">column ${num(cursor + 1)}</span>` +
      `<span><b>${num(covered)}</b> of ${num(state.visible.length)} visible sequences readable here</span>` +
      (state.block.header.coding
        ? `<span><b>${num(differing)}</b> differ from their reference</span>`
        : "");
  });

  byId(`${alignmentChapter.ID}-strip`).addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>(".thumb");
    if (!button?.dataset.region) return;
    // A region change here is a refetch, not a redraw: the cells are per region.
    view.zoom = null;
    commit({ ...view, region: button.dataset.region, zoom: null }, { reload: false });
  });
}

/** Pinning from the raster, pushed out to every other chapter so the record highlights
 *  everywhere — the same contract `setHeld` gives the five scatter chapters. */
function setHeldFromAlignment(rasterRow: number): void {
  const state = alignmentState;
  if (!state) return;
  const record = state.block.record[rasterRow]!;
  const same = state.held === rasterRow;
  state.held = same ? null : rasterRow;
  alignmentHeld = same ? null : record;

  for (const [id, entry] of chapters) {
    if (!entry.state) continue;
    entry.heldRecord = alignmentHeld;
    entry.state.held =
      alignmentHeld === null
        ? null
        : (entry.state.visibleMarks.find((m) => m.record === alignmentHeld) ?? null);
    chapter.renderHighlight(entry.state);
    paintInspection(id);
  }
  view.pinned = alignmentHeld === null ? null : records.accession(record);
  writeHash();
  alignmentChapter.renderHighlight(state);
  paintPinned();
}

/** Load the chapter now, whoever asked.
 *
 *  Scrolling to it is the common path, but not the only one: a shared link carrying a
 *  handed-over set is asking for this figure by name, and so is the button that made
 *  the link. Routing every entry point through here is what keeps the laziness from
 *  turning into a figure that silently never loads. */
/** Below this width, the payload is offered rather than fetched.
 *
 *  `all`/polyprotein is 2.9 MB over the wire and ~25 MB of typed array once inflated,
 *  which is a real cost on a phone and a real risk against a per-tab memory ceiling. A
 *  reader who wants it can still have it; what they should not get is a figure that
 *  spends their data plan because they scrolled past it. */
const AUTOLOAD_MIN_WIDTH = 700;

function requestAlignment(): void {
  alignmentMounted = true;
  void rebuildAlignment();
}

/** Offer the figure instead of loading it, on a viewport where the cost is worth a
 *  choice. Skipped when the reader has already asked for it by other means — a
 *  handed-over set, or a second visit after they accepted once. */
function offerAlignment(): void {
  if (alignmentAccepted || window.innerWidth >= AUTOLOAD_MIN_WIDTH || view.restrict) {
    requestAlignment();
    return;
  }
  byId(`${alignmentChapter.ID}-note`).innerHTML =
    `This figure loads the alignment itself, which is a few megabytes on a narrow
     connection. <button type="button" class="text-button" data-load-alignment>Load
     it</button>`;
  byId(`${alignmentChapter.ID}-note`)
    .querySelector<HTMLButtonElement>("[data-load-alignment]")
    ?.addEventListener("click", () => {
      alignmentAccepted = true;
      requestAlignment();
    });
}

/** Mount the chapter the first time it comes into view.
 *
 *  A region of `all` is up to 25 MB resident and 2.9 MB over the wire. Loading that at
 *  mount would make every reader pay for a figure most will scroll past, and would put
 *  it inside the `Promise.all` that gates first paint.
 *
 *  Where the observer cannot answer — no `IntersectionObserver`, or a viewport it can
 *  never report an intersection against — the figure loads rather than staying blank.
 *  A missing figure with no explanation is a worse failure than an eager fetch. */
function observeAlignment(): void {
  if (typeof IntersectionObserver === "undefined") {
    offerAlignment();
    return;
  }
  const target = byId(alignmentChapter.ID);
  const observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      offerAlignment();
    },
    { rootMargin: "600px" },
  );
  observer.observe(target);
}

async function main(): Promise<void> {
  const [loadedSummary, manifest, recordTable] = await Promise.all([
    loadJson<Summary>("data/summary.json"),
    loadJson<Manifest>("data/manifest.json"),
    loadJson<RecordTable>("data/records.json"),
  ]);
  summary = assertSchema(loadedSummary);
  records = new Records(recordTable);

  const decoded = decode(location.hash, summary);
  view = decoded.view;
  rejected = decoded.rejected;

  renderRawDate(summary);
  renderReleaseBand(summary);
  renderFacts(summary);
  renderPopulationTable(summary);
  renderDataQuality(summary);
  renderConsensusInflation(summary);
  renderSabinFrameIndels(summary);
  renderIntegrityNotes(summary);
  renderBuildLine(summary, manifest.build_identity);

  renderControls(summary, view);
  onControlEdit(handleEdit);
  for (const spec of SPECS) wireChapter(spec);
  wireAlignment();
  observeAlignment();
  refreshChrome();
  await Promise.all(SPECS.map((spec) => rebuild(spec)));

  // A pinned accession restored from the URL has to wait for the panels to exist.
  if (view.pinned) {
    const first = slot(DIVERGENCE.id).state;
    const target = first?.visibleMarks.find(
      (mark) => records.accession(mark.record) === view.pinned,
    );
    if (target) setHeld(DIVERGENCE.id, target);
  }

  // A link carrying a handed-over set is asking for chapter 06 by name, so it does not
  // wait to be scrolled to. Resolved after the rebuild above, because the rectangle can
  // only become a set once the chapter that drew it has its marks.
  if (view.restrict) requestAlignment();

  byId("reset-view").addEventListener("click", () => {
    for (const entry of chapters.values()) {
      entry.zoom = null;
      entry.heldRecord = null;
    }
    commit(defaultView(summary), { reload: true });
  });
  window.addEventListener("hashchange", handleHashChange);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  const band = byId("release-band");
  band.innerHTML = `<strong>Could not load the release summary.</strong><span>${message}</span>`;
  band.classList.add("is-stale");
  console.error(error);
});
