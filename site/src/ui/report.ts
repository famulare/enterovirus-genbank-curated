/** The closing chapter: what the release contains, the per-view populations, and
 *  what is currently wrong with the data. All of it recomputed at build time. */

import type { Summary } from "../model/types.js";
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
      schema ${esc(release.schema_version)}</span>
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
      `Records the maintainer has reviewed directly — against these figures and against the
       poliovirus literature. The remaining ${num(release.n_provisional)} are provisional: not
       known to be wrong, just not yet given that depth of review. The review has covered
       poliovirus and not yet non-polio enterovirus, which is why the split falls where it does.`,
    ],
    [
      "Human curation",
      num(release.n_manual_decisions),
      `Records where at least one recorded curation decision was applied by the build. Each is
       traceable to a field-level assertion in the release audit trail.`,
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

/** The consensus-coverage caveat in the method disclosure. Its numbers come from
 *  summary.json rather than the markup for the same reason every other number on the
 *  page does: this one was hand-written in two files and disagreed with the panel for
 *  four releases before anyone recomputed it. */
export function renderConsensusInflation(summary: Summary): void {
  const { rate, n_assessed, n_exceeding, indel_share } = summary.consensus_inflation;
  byId("consensus-inflation").innerHTML =
    `${num(n_exceeding)} of ${num(n_assessed)} non-polio polyprotein records exceed ` +
    `${rate} non-synonymous per codon, and indel codons are ` +
    `${(indel_share * 100).toFixed(1)}% of that group's numerator`;
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

export function renderBuildLine(summary: Summary, buildIdentity: string): void {
  byId("build-line").textContent =
    `Data release ${summary.release.version}, code ${summary.release.code_sha256.slice(0, 12)} · ` +
    `site data ${buildIdentity}`;
}


/** The Sabin frame cannot carry an insertion, and the method disclosure has to say so.
 *
 *  `sabin_region_columns` returns the RF line's alphabetic columns, which are that
 *  serotype's own genome coordinates, so the reference has material at every one of them
 *  and `insertions = span & query_material & ~ref_material` is empty by construction.
 *  Reported, never repaired: this is what the Sabin frame means, not a defect in it. */
export function renderSabinFrameIndels(summary: Summary): void {
  const measured = summary.sabin_frame_indels;
  const target = document.getElementById("sabin-frame-indels");
  if (!target) return;
  if (measured.insertions_possible) {
    const gapped = measured.frames.filter((entry) => entry.gap_columns > 0);
    target.innerHTML =
      `${gapped.map((entry) => `${esc(entry.selection)} (${num(entry.gap_columns)})`).join(", ")}
       carry reference gap columns, so an insertion can be charged there.`;
    return;
  }
  target.innerHTML =
    `measured on this release, all three serotype references —
     ${measured.frames.map((entry) => esc(entry.reference)).join(", ")} — carry material at
     every one of their own ${measured.frames.length === 3 ? "coding" : ""} columns, so the
     count is zero in all three`;
}
