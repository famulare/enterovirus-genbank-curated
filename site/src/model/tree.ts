/** One region's tree, decoded from a tree file.
 *
 *  A rectangular phylogeny is a scatter of tips plus a link layer: x is distance from
 *  the root, y is position in the ladder. Decoding it into the same `Mark` shape the
 *  two scatter figures use is what lets all four chapters share one instrument — the
 *  same colour scale, legend, hover, keyboard traversal, click-to-pin and brush.
 *
 *  Internal nodes are not records and so are not marks. They exist only in the link
 *  layer, which nothing hovers.
 */

export interface TreeRegion {
  /** Record index per tip, in ladder order. A tip's y is its position in this array. */
  tip_record: number[];
  tip_x: number[];
  /** Index into the node arrays. */
  tip_parent: number[];
  tip_coverage: number[];
  /** Median positions this tip shared with the others it was measured against. */
  tip_shared: number[];
  /** Tip indices whose distances rest on too little overlap for the branch length to be
   *  taken at face value. */
  thin: number[];
  /** The shared-position floor `thin` was judged against. */
  confident_shared: number;
  node_x: number[];
  node_ylo: number[];
  node_yhi: number[];
  /** -1 for the root. */
  node_parent: number[];
  n_eligible: number;
  excluded: { below_coverage: number; not_comparable: number };
  columns: number;
  unit: string;
  min_shared: number;
  root: { kind: string; label: string };
  negative_branches: number;
  clamped_total: number;
}

export interface TreeFile {
  schema: number;
  selection: string;
  tip_cap: number;
  nucleotide: Record<string, TreeRegion>;
  protein: Record<string, TreeRegion>;
}

import type { Link } from "./mark.js";

export const TREE_SCHEMA = 1;

export function assertTreeSchema(file: TreeFile): TreeFile {
  if (file.schema !== TREE_SCHEMA) {
    throw new Error(
      `tree file is schema ${file.schema}, this app reads ${TREE_SCHEMA}. ` +
        "Rebuild with: uv run site/pipeline/cli.py build",
    );
  }
  return file;
}

/** The elbow segments of a rectangular tree.
 *
 *  Two per internal node — one vertical spanning its children, one horizontal from its
 *  parent — plus one horizontal per tip. A node's own y is the midpoint of the span it
 *  brackets, which holds because rooting makes every internal node strictly binary.
 */
export function links(tree: TreeRegion): Link[] {
  const out: Link[] = [];
  const nodeY = (index: number) => (tree.node_ylo[index]! + tree.node_yhi[index]!) / 2;

  for (let index = 0; index < tree.node_x.length; index += 1) {
    const x = tree.node_x[index]!;
    out.push({ x0: x, y0: tree.node_ylo[index]!, x1: x, y1: tree.node_yhi[index]! });
    const parent = tree.node_parent[index]!;
    if (parent >= 0) {
      const y = nodeY(index);
      out.push({ x0: tree.node_x[parent]!, y0: y, x1: x, y1: y });
    }
  }

  for (let tip = 0; tip < tree.tip_record.length; tip += 1) {
    const parent = tree.tip_parent[tip]!;
    out.push({ x0: tree.node_x[parent]!, y0: tip, x1: tree.tip_x[tip]!, y1: tip });
  }
  return out;
}
