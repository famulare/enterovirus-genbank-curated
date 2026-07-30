/** Shape of site/data/summary.json, as written by site/pipeline/summary.py.
 *
 * Keep this in step with that module. Nothing here is optional-by-accident: a
 * field that the build always writes is required here, so a schema drift shows up
 * as a type error rather than as `undefined` on the page.
 */

export interface Release {
  version: string;
  built: string;
  /** Day the frozen GenBank snapshot was retrieved, not the day it was built. */
  raw_retrieved: string;
  validation: string;
  n_source_records: number;
  n_records: number;
  n_polio: number;
  n_npev: number;
  n_vouched: number;
  n_provisional: number;
  n_fields: number;
  n_manual_decisions: number;
}

export interface RegionPopulation {
  n: number;
  columns: number;
  median_nt: number;
}

export interface Selection {
  id: string;
  label: string;
  alignment: string;
  frame: "sabin" | "projected";
  reference: string;
  root: string;
  default_trait: string;
  n_aligned: number;
  n_canonical: number;
  n_unaligned: number;
  n_discordant: number;
  regions: Record<string, RegionPopulation>;
}

export interface Region {
  id: string;
  label: string;
  coding: boolean;
  in_divergence: boolean;
  in_distance: boolean;
  in_nucleotide_tree: boolean;
  in_protein_distance: boolean;
  in_protein_tree: boolean;
  min_nt: number;
}

export type TraitKind = "discrete" | "continuous";
export type TraitScope = "record" | "selection" | "panel";

export interface Trait {
  id: string;
  label: string;
  kind: TraitKind;
  scope: TraitScope;
  note?: string;
  n_present?: number;
  n_distinct?: number;
  /** Declared category order, where frequency ranking would be wrong. */
  order?: string[];
}

export interface Finding {
  id: string;
  field: string;
  n: number;
  summary: string;
  detail: string;
}

/** Size of the consensus-coverage artifact, measured per build rather than asserted. */
export interface ConsensusInflation {
  rate: number;
  n_assessed: number;
  n_exceeding: number;
  indel_share: number;
}

export interface Summary {
  schema: number;
  release: Release;
  defaults: { selection: string; region: string };
  selections: Selection[];
  regions: Region[];
  traits: Trait[];
  data_quality: Finding[];
  consensus_inflation: ConsensusInflation;
  integrity_notes: string[];
  thresholds: {
    min_region_nt: number;
    min_region_nt_by_region: Record<string, number>;
    max_discrete_categories: number;
  };
}

export const SCHEMA = 1;

export function assertSchema(summary: Summary): Summary {
  if (summary.schema !== SCHEMA) {
    throw new Error(
      `site/data/summary.json is schema ${summary.schema}, this app reads ${SCHEMA}. ` +
        "Rebuild with: uv run site/pipeline/cli.py build",
    );
  }
  return summary;
}
