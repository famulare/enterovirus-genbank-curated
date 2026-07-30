/** The control bar. The DOM is the store: state is read out of the elements on
 *  demand rather than mirrored into a parallel object.
 *
 *  The markup is built exactly once, at mount. Everything after that either reads
 *  values out (`readControls`) or pushes values in (`syncControls`) — never a
 *  rebuild, because replacing the markup under a keyboard user destroys focus
 *  mid-interaction. Round-tripping through those two is what makes a URL-restored
 *  view and a user-edited view the same object.
 */

import type { AxisScale, StatusFilter, View } from "../model/view.js";
import { defaultTraitNote, pickSelection, population } from "../model/view.js";
import type { Summary } from "../model/types.js";
import { byId, esc, num, option } from "./dom.js";

const CONTROL_ATTR = "data-view-control";

export function renderControls(summary: Summary, view: View): void {
  const row = byId("control-row");
  row.className = "view-controls";
  row.innerHTML = `
    <label>
      Serotype
      <select id="c-selection" ${CONTROL_ATTR}>
        ${summary.selections
          .map((entry) =>
            option(entry.id, `${entry.label} — ${num(entry.n_aligned)}`, entry.id === view.selection),
          )
          .join("")}
      </select>
      <small id="selection-note"></small>
    </label>

    <label>
      Genome region
      <select id="c-region" ${CONTROL_ATTR}>
        ${summary.regions
          .map((region) =>
            option(
              region.id,
              `${region.label}${region.coding ? "" : " (non-coding)"}`,
              region.id === view.region,
            ),
          )
          .join("")}
      </select>
      <small>Non-coding: distance and phylogeny only.</small>
    </label>

    <label>
      Color by
      <select id="c-trait" ${CONTROL_ATTR}>
        ${summary.traits
          .map((trait) => option(trait.id, trait.label, trait.id === view.trait))
          .join("")}
      </select>
      <small id="trait-note"></small>
    </label>

    <label>
      Curation status
      <select id="c-status" ${CONTROL_ATTR}>
        ${option("all", `All — ${num(summary.release.n_records)}`, view.status === "all")}
        ${option("vouched", `Vouched — ${num(summary.release.n_vouched)}`, view.status === "vouched")}
        ${option(
          "provisional",
          `Provisional — ${num(summary.release.n_provisional)}`,
          view.status === "provisional",
        )}
      </select>
      <small>Vouched is a strict subset, not a separate release.</small>
    </label>

    <label>
      Axis scale
      <select id="c-scale" ${CONTROL_ATTR}>
        ${option("sqrt", "Square root", view.scale === "sqrt")}
        ${option("linear", "Linear", view.scale === "linear")}
      </select>
      <small id="scale-note"></small>
    </label>
  `;

  byId("control-filters").className = "control-filters";
  byId("control-filters").innerHTML = `
    <label class="check-row">
      <input type="checkbox" id="c-engineered" ${CONTROL_ATTR} ${view.engineered ? "checked" : ""}>
      <span>Include engineered and laboratory constructs</span>
    </label>
  `;
}

/** Push a view into the existing controls. Setting `.value` rather than rebuilding
 *  keeps focus where the reader put it. */
export function syncControls(view: View): void {
  byId<HTMLSelectElement>("c-selection").value = view.selection;
  byId<HTMLSelectElement>("c-region").value = view.region;
  byId<HTMLSelectElement>("c-trait").value = view.trait;
  byId<HTMLSelectElement>("c-status").value = view.status;
  byId<HTMLInputElement>("c-engineered").checked = view.engineered;
  byId<HTMLSelectElement>("c-scale").value = view.scale;
}

/** Read the whole view out of the DOM. */
export function readControls(previous: View): View {
  const value = (id: string) => byId<HTMLSelectElement>(id).value;
  return {
    selection: value("c-selection"),
    region: value("c-region"),
    trait: value("c-trait"),
    status: value("c-status") as StatusFilter,
    engineered: byId<HTMLInputElement>("c-engineered").checked,
    pinned: previous.pinned,
    scale: byId<HTMLSelectElement>("c-scale").value as AxisScale,
    // Brushing is a figure interaction, not a control; it survives a control edit.
    zoom: previous.zoom,
  };
}

export function onControlEdit(handler: () => void): void {
  for (const element of document.querySelectorAll<HTMLElement>(`[${CONTROL_ATTR}]`)) {
    const event =
      element instanceof HTMLInputElement && element.type === "range" ? "input" : "change";
    element.addEventListener(event, handler);
  }
}

/** Helper text that depends on the current view. Kept out of renderControls so it
 *  can update without touching the controls themselves. */
export function renderNotes(summary: Summary, view: View): void {
  const selection = pickSelection(summary, view.selection);
  byId("selection-note").innerHTML =
    `Read in <code>${esc(selection.alignment)}</code>, ` +
    (selection.frame === "sabin"
      ? "in Sabin genome coordinates."
      : "with regions projected from Sabin 1.");
  byId("trait-note").textContent = traitNote(summary, view);
  // The one control does something different in each figure, so it says both.
  byId("scale-note").textContent =
    view.scale === "sqrt"
      ? "Divergence: square-root axes, spreading the low corner. Distance: scales the " +
        "square roots of the distances, which is usually the more Euclidean geometry."
      : "Divergence: linear axes. Distance: scales the distances as given, which fits " +
        "more variance into two dimensions but less of it honestly.";
}

function traitNote(summary: Summary, view: View): string {
  const trait = summary.traits.find((entry) => entry.id === view.trait);
  if (!trait) return "";
  const parts: string[] = [];
  if (trait.scope === "selection") parts.push("Depends on the serotype selected.");
  else if (trait.scope === "panel") parts.push("Recomputed for each region shown.");
  else if (trait.kind === "discrete" && trait.n_distinct !== undefined) {
    parts.push(
      `${num(trait.n_distinct)} values on ${num(trait.n_present ?? 0)} records` +
        (trait.n_distinct > summary.thresholds.max_discrete_categories
          ? `; top ${summary.thresholds.max_discrete_categories} get a color.`
          : "."),
    );
  } else if (trait.n_present !== undefined) {
    parts.push(`On ${num(trait.n_present)} records.`);
  }
  if (trait.note) parts.push(trait.note);
  // The "defaults to X here" explanation is redundant once the trait's own note
  // already says the column is empty for these records.
  const fallback = defaultTraitNote(summary, view.selection);
  if (fallback && !trait.note && trait.id === pickSelection(summary, view.selection).default_trait) {
    parts.push(fallback);
  }
  return parts.join(" ");
}

export function renderStatus(summary: Summary, view: View, rejected: string[]): void {
  const line = byId("view-status");
  const selection = pickSelection(summary, view.selection);
  const region = summary.regions.find((entry) => entry.id === view.region);
  const count = population(summary, view);

  if (rejected.length) {
    line.className = "transaction-status invalid";
    line.textContent =
      `Ignored unrecognized link parameters: ${rejected.join(", ")}. Showing defaults.`;
    return;
  }

  line.className = "transaction-status";
  const share = count.ofAligned ? Math.round((100 * count.n) / count.ofAligned) : 0;
  line.textContent =
    `${num(count.n)} of ${num(selection.n_aligned)} ${selection.label} sequences carry at least ` +
    `${region?.min_nt ?? 0} nt in ${region?.label ?? view.region} (${share}%), across ` +
    `${num(count.columns)} alignment columns.`;
}
