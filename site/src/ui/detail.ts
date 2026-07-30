/** Two tiers of record inspection.
 *
 *  Hover (or arrow-key focus) shows a compact readout **per figure**: it is feedback on
 *  the mark under the pointer, so it belongs to the figure being pointed at.
 *
 *  Pinning opens **one** inspector for the whole page, after the first figure. Pinning
 *  is cross-chapter — the same record highlights in every figure — so a per-chapter
 *  block rendered the same record twice. The single block reports what each figure
 *  measured about the record, then every field the release records for it.
 */

import type { Mark, MarkSet } from "../model/mark.js";
import type { ChapterSpec } from "./chapter.js";
import type { Records } from "../model/records.js";
import { byId, esc } from "./dom.js";

const GENBANK = "https://www.ncbi.nlm.nih.gov/nuccore/";

export function renderReadout(
  spec: ChapterSpec,
  records: Records,
  set: MarkSet,
  mark: Mark | null,
  held: boolean,
): void {
  const target = byId(`${spec.id}-readout`);
  if (!mark) {
    target.classList.remove("is-active");
    target.innerHTML =
      `<span class="readout-hint">Hover or arrow-key a mark to read it; click to pin every
       field. Drag a box to zoom.</span>`;
    return;
  }
  target.classList.add("is-active");

  const type = records.text("virus_type", mark.record) || "untyped";
  const classification = records.text("poliovirus_classification", mark.record);
  const country = records.text("country", mark.record);
  const date = records.text("collection_date", mark.record);

  const lines = [
    `<span class="readout-key">${esc(records.accession(mark.record))}</span>`,
    `<span>${esc(type)}${classification ? ` · ${esc(classification)}` : ""}</span>`,
    `<span>${esc([country, date].filter(Boolean).join(" · ") || "no place or date recorded")}</span>`,
    ...spec.readout(records, set, mark).map((line) => `<span>${line}</span>`),
  ];
  if (!held) lines.push('<span class="readout-hint">Click to pin</span>');
  target.innerHTML = lines.join("");
}

/** What one figure measured about the pinned record. */
export interface PinnedPanel {
  figure: string;
  region: string;
  rows: [string, string][];
}

/** A value that is not a recorded field — derived here, or specific to the current
 *  selection — but which the color control can paint by, so the inspector has to
 *  account for it or the reader cannot see what they are looking at. */
export interface DerivedField {
  label: string;
  value: string;
  why: string;
}

export function renderPinned(
  records: Records,
  row: number | null,
  panels: PinnedPanel[],
  derived: DerivedField[],
): void {
  const target = byId("record-detail");
  if (row === null) {
    target.innerHTML = "";
    target.removeAttribute("data-open");
    return;
  }
  target.dataset.open = "true";

  const accession = records.accession(row);

  const measured = panels
    .map(
      (panel) => `
      <div class="detail-panel">
        <p class="detail-subhead">${esc(panel.figure)} · ${esc(panel.region)}</p>
        <dl class="detail-measured">
          ${panel.rows
            .map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`)
            .join("")}
        </dl>
      </div>`,
    )
    .join("");

  const derivedRows = derived
    .map(
      (entry) =>
        `<tr><th scope="row">${esc(entry.label)}
           <em class="prov-tag" data-kind="derived" title="${esc(entry.why)}">Derived</em></th>
         <td>${esc(entry.value)}</td></tr>`,
    )
    .join("");

  const recordedRows = records
    .detail(row)
    .filter((entry) => entry.value !== "")
    .map(
      (entry) =>
        `<tr><th scope="row">${esc(entry.label)}${
          entry.derived
            ? ' <em class="prov-tag" data-kind="derived" title="Computed by this site from the' +
              ' fields beside it, not recorded in the release.">Derived</em>'
            : ""
        }</th><td>${esc(entry.value)}</td></tr>`,
    )
    .join("");

  target.innerHTML = `
    <div class="detail-head">
      <div>
        <p class="eyebrow">Pinned record</p>
        <h3>${esc(accession)}</h3>
      </div>
      <button type="button" class="text-button" data-unpin>Clear</button>
    </div>
    <div class="detail-grid">
      <div>
        <p class="detail-subhead detail-group">Measured in these figures</p>
        ${measured}
        <p class="detail-links">
          <a href="${GENBANK}${encodeURIComponent(accession)}" rel="noopener">This record on
            GenBank</a>
          ${
            records.hasManualDecision(row)
              ? ' · <span class="prov-tag" data-kind="derived">Human curation decision recorded</span>'
              : ' · <span class="prov-tag" data-kind="assumption">No human decision recorded</span>'
          }
        </p>
      </div>
      <div class="table-wrap record-table detail-fields">
        <p class="detail-subhead">Every recorded field</p>
        <table><tbody>${derivedRows}${recordedRows}</tbody></table>
      </div>
    </div>
  `;
}
