/** The closing chapter: what the release contains, the per-view populations, and
 *  what is currently wrong with the data. All of it recomputed at build time. */

import type { Summary } from "../model/types.js";
import { pickSelection, type View } from "../model/view.js";
import { byId, esc, num } from "./dom.js";

/** The retrieval date is read from raw/raw_manifest.json at build time rather than
 *  written into the markup, so it cannot drift from the snapshot it describes. */
export function renderRawDate(summary: Summary): void {
  const iso = summary.release.raw_retrieved;
  const parsed = new Date(`${iso}T00:00:00Z`);
  const node = byId("raw-date");
  node.textContent = Number.isNaN(parsed.valueOf())
    ? iso
    : parsed.toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric",
        timeZone: "UTC",
      });
  node.setAttribute("datetime", iso);
}

export function renderReleaseBand(summary: Summary): void {
  const { release } = summary;
  byId("release-band").innerHTML = `
    <strong>Release ${esc(release.version)}</strong>
    <span>${num(release.n_records)} sequences · ${num(release.n_polio)} poliovirus,
      ${num(release.n_npev)} non-polio · ${release.n_fields} curated fields ·
      contract validation ${esc(release.validation)}</span>
  `;
}

export function renderFacts(summary: Summary): void {
  const { release } = summary;
  const rows: [string, string, string][] = [
    [
      "Sequences",
      num(release.n_records),
      `Included from ${num(release.n_source_records)} candidate GenBank records. One row per
       sequence, keyed by accession.version.`,
    ],
    [
      "Vouched",
      `${num(release.n_vouched)} of ${num(release.n_records)}`,
      `Confirmed canonical reference or membership-verified. The remaining
       ${num(release.n_provisional)} are provisional — name- and annotation-derived — and every
       non-polio record is provisional throughout.`,
    ],
    [
      "Human curation",
      num(release.n_manual_decisions),
      `Records touched by at least one recorded curation decision. Each is traceable to a
       field-level assertion in the release audit trail.`,
    ],
    [
      "Reference alignments",
      `${new Set(summary.selections.map((s) => s.alignment)).size} in use`,
      `Per-serotype poliovirus alignments carry a Sabin coordinate frame; the genus-wide
       alignment carries a consensus frame and supplies the non-polio views.`,
    ],
  ];

  byId("release-facts").innerHTML = rows
    .map(
      ([label, value, prose]) => `
      <article class="datum-row">
        <span>${esc(label)}</span>
        <strong>${value}</strong>
        <p>${esc(prose.replace(/\s+/g, " ").trim())}</p>
      </article>`,
    )
    .join("");
}

export function renderPopulationTable(summary: Summary): void {
  const selections = summary.selections;
  const header = selections.map((s) => `<th scope="col">${esc(s.label)}</th>`).join("");

  const body = summary.regions
    .map((region) => {
      const cells = selections
        .map((selection) => {
          const entry = selection.regions[region.id];
          const n = entry?.n ?? 0;
          const share = selection.n_aligned ? (100 * n) / selection.n_aligned : 0;
          const sparse = share < 25;
          return `<td${sparse ? ' class="is-sparse"' : ""}>${num(n)}<br><small>${share.toFixed(
            0,
          )}%</small></td>`;
        })
        .join("");
      return `<tr data-noncoding="${!region.coding}">
          <th scope="row">${esc(region.label)}<br><small>≥${region.min_nt} nt</small></th>
          ${cells}
        </tr>`;
    })
    .join("");

  byId("population-table").innerHTML = `
    <table>
      <caption class="visually-hidden">Sequences per genome region and serotype</caption>
      <thead><tr><th scope="col">Region</th>${header}</tr></thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

export function renderDataQuality(summary: Summary): void {
  const target = byId("data-quality");
  if (!summary.data_quality.length) {
    target.innerHTML = `<p class="warning notice">No data-quality issues are currently
      detected by the checks this page runs.</p>`;
    return;
  }
  target.innerHTML = summary.data_quality
    .map(
      (finding) => `
      <p class="finding">
        <strong>${esc(finding.summary)}</strong>
        <code>${esc(finding.field)}</code> · <b>${num(finding.n)}</b> records.
        ${esc(finding.detail)}
      </p>`,
    )
    .join("");
}

export function renderIntegrityNotes(summary: Summary): void {
  const target = byId("integrity-notes");
  const discordant = summary.selections
    .filter((selection) => selection.n_discordant > 0)
    .map(
      (selection) =>
        `${num(selection.n_discordant)} in ${esc(selection.alignment)} whose curated type is not ` +
        `${esc(selection.id)}`,
    );

  const notes: string[] = [];
  if (discordant.length) {
    notes.push(
      `<strong>Sequence-based typing disagrees with the curated type.</strong> ` +
        `${discordant.join("; ")}. These are under investigation upstream, and are colorable ` +
        `here as <em>Type concordance</em>.`,
    );
  }
  const unaligned = summary.selections.find((selection) => selection.id === "all");
  if (unaligned && unaligned.n_unaligned > 0) {
    notes.push(
      `<strong>${num(unaligned.n_unaligned)} records appear in no alignment.</strong> ` +
        `They are counted here but cannot be placed in any figure, because every view is built ` +
        `in alignment column space.`,
    );
  }
  for (const note of summary.integrity_notes) {
    notes.push(`<strong>Alignment and table disagree.</strong> ${esc(note)}`);
  }

  target.innerHTML = notes.length
    ? `<h3 class="section-subhead">Classification and coverage notes</h3>` +
      notes.map((note) => `<p class="uncertainty-note">${note}</p>`).join("")
    : "";
}

/** Per-region population for the selection currently chosen. Deliberately not a
 *  sum across selections — `all` already contains the others, so a sum would
 *  double-count and put a meaningless number on the page. */
export function renderPendingCounts(summary: Summary, view: View): void {
  const selection = pickSelection(summary, view.selection);
  for (const holder of document.querySelectorAll<HTMLElement>("[data-counts]")) {
    const key = holder.dataset.counts === "divergence" ? "in_divergence" : "in_distance";
    holder.innerHTML =
      `<span>${esc(selection.label)}</span>` +
      summary.regions
        .filter((region) => region[key])
        .map((region) => {
          const n = selection.regions[region.id]?.n ?? 0;
          const current = region.id === view.region;
          return `<span${n === 0 ? ' class="is-empty"' : ""}${
            current ? ' data-current="true"' : ""
          }>${esc(region.label)} <b>${num(n)}</b>${current ? " (shown)" : ""}</span>`;
        })
        .join("");
  }
}

export function renderBuildLine(summary: Summary, buildIdentity: string): void {
  byId("build-line").textContent =
    `Data release ${summary.release.version}, built ${summary.release.built} · ` +
    `site data ${buildIdentity}`;
}
