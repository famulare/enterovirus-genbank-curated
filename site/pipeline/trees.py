"""Figure sets 3 and 4: neighbor-joining trees over the same pairwise distances.

The distances are the ones `distances.py` already defines — mismatches over the
positions where both sequences carry readable material, pairwise, with a length
minimum. Nothing is re-derived here, which is the point: the tree and the distance map
cannot disagree about how partial overlap was handled, because they read the same
number.

Two things follow from that shared definition and are worth stating plainly.

**Not every sequence can be on a tree.** Pairwise deletion leaves some pairs with no
comparable positions at all, and neighbor joining needs a complete matrix. So the tips
are `distances.comparable_set` — the largest mutually-comparable set the greedy finds,
capped for cost — and every panel reports how many sequences that left off.

**No substitution model is applied.** Branch lengths are in the same uncorrected
currency as the rest of the site: observed differences per position compared. They are
not substitutions per site, not time, and not corrected for multiple hits, so a long
branch is a statement about observed difference and nothing more.

Neighbor joining is implemented here rather than shelled out to decenttree or rapidNJ.
It is forty lines of deterministic arithmetic, not a heuristic search, and the two
properties that decided it are that a fresh clone needs no bioinformatics toolchain at
all, and that the committed artifacts are hash-gated — so a rebuild has to reproduce
the same tree bit for bit, which a multithreaded tool's tie-breaking will not promise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import contract
import distances
import frame

# Tips per tree. Neighbor joining is O(n^3) — 1,500 tips takes 2 s, 2,500 takes 10 s,
# 4,000 would take a minute — and forty trees are built per release. 2,500 is also past
# the point where a 900 px panel resolves individual tips, so a larger tree would cost
# build time to draw marks on top of each other.
TIP_CAP = 2500


@dataclass
class Unrooted:
    """Neighbor joining's own output: an unrooted tree as a list of weighted edges.
    Tips are nodes `0..n_tips-1`; internal nodes follow."""

    n_tips: int
    n_nodes: int
    edges: list[tuple[int, int, float]]


@dataclass
class Rooted:
    n_tips: int
    root: int
    parent: list[int]
    length: list[float]
    children: list[list[int]] = field(default_factory=list)


def neighbor_join(distance: np.ndarray) -> Unrooted:
    """Saitou-Nei neighbor joining.

    Deterministic: ties in the Q criterion are broken by position in the working
    matrix, whose evolution is itself a deterministic function of the input, so the
    same matrix always yields the same tree. That matters more here than it usually
    does — the trees are committed artifacts behind a hash gate, so a rebuild that
    reordered two zero-length neighbors would show up as a spurious data change.

    The working matrix shrinks in place rather than being masked, which turns the total
    work from n * n^2 into the sum of k^2 over the merges.
    """
    n = int(len(distance))
    if n < 3:
        raise ValueError(f"neighbor joining needs at least 3 tips, got {n}")

    working = np.array(distance, dtype=np.float64, copy=True)
    node = np.arange(n, dtype=np.int64)
    edges: list[tuple[int, int, float]] = []
    next_node = n
    k = n

    while k > 2:
        view = working[:k, :k]
        divergence = view.sum(axis=1)
        criterion = (k - 2) * view - divergence[:, None] - divergence[None, :]
        np.fill_diagonal(criterion, np.inf)
        # Row-major argmin over the symmetric matrix always lands on the copy with the
        # smaller row index, so i < j without a swap.
        i, j = divmod(int(np.argmin(criterion)), k)

        pair_distance = float(view[i, j])
        to_i = 0.5 * pair_distance + (divergence[i] - divergence[j]) / (2 * (k - 2))
        joined = next_node
        next_node += 1
        edges.append((int(node[i]), joined, float(to_i)))
        edges.append((int(node[j]), joined, float(pair_distance - to_i)))

        # The joined node takes slot i; the last active row backfills slot j.
        merged = 0.5 * (view[i] + view[j] - pair_distance)
        working[:k, i] = merged
        working[i, :k] = merged
        working[i, i] = 0.0
        node[i] = joined
        last = k - 1
        if j != last:
            working[:k, j] = working[:k, last]
            working[j, :k] = working[last, :k]
            working[j, j] = 0.0
            node[j] = node[last]
        k -= 1

    edges.append((int(node[0]), int(node[1]), float(working[0, 1])))
    return Unrooted(n_tips=n, n_nodes=next_node, edges=edges)


def clamp_negative(tree: Unrooted) -> tuple[Unrooted, int, float]:
    """Negative branch lengths set to zero, and how much was removed.

    Neighbor joining produces them routinely: the formula distributes a pair's
    distance between two branches and can hand one of them a negative share when the
    distances are not exactly additive, which real ones never are. Setting them to zero
    is the standard remedy. Reported rather than hidden, because a panel with a lot of
    clamping is a panel whose distances are fighting the tree.
    """
    negative = [edge for edge in tree.edges if edge[2] < 0]
    if not negative:
        return tree, 0, 0.0
    clamped = [(a, b, max(0.0, length)) for a, b, length in tree.edges]
    return (
        Unrooted(n_tips=tree.n_tips, n_nodes=tree.n_nodes, edges=clamped),
        len(negative),
        float(-sum(edge[2] for edge in negative)),
    )


def _adjacency(tree: Unrooted) -> list[list[tuple[int, float]]]:
    adjacency: list[list[tuple[int, float]]] = [[] for _ in range(tree.n_nodes)]
    for a, b, length in tree.edges:
        adjacency[a].append((b, length))
        adjacency[b].append((a, length))
    return adjacency


def _farthest(adjacency: list[list[tuple[int, float]]], start: int) -> tuple[int, float, list[int]]:
    """Farthest node from `start`, its distance, and the parent map to walk back."""
    total = {start: 0.0}
    came_from = [-1] * len(adjacency)
    stack = [start]
    best, best_distance = start, 0.0
    while stack:
        current = stack.pop()
        for neighbor, length in adjacency[current]:
            if neighbor in total:
                continue
            total[neighbor] = total[current] + length
            came_from[neighbor] = current
            if total[neighbor] > best_distance:
                best, best_distance = neighbor, total[neighbor]
            stack.append(neighbor)
    return best, best_distance, came_from


def _root_on_edge(tree: Unrooted, a: int, b: int, from_a: float) -> Rooted:
    """Insert a root on the edge (a, b), `from_a` along it, and orient everything away.

    Iterative rather than recursive: a caterpillar tree of 2,500 tips is 2,500 deep and
    would blow the interpreter's stack.
    """
    root = tree.n_nodes
    size = tree.n_nodes + 1
    parent = [-1] * size
    length = [0.0] * size
    children: list[list[int]] = [[] for _ in range(size)]

    adjacency = _adjacency(tree)
    adjacency.append([])  # the root itself, which _adjacency does not know about
    edge_length = next(
        (length for x, y, length in tree.edges if {x, y} == {a, b}),
        0.0,
    )
    adjacency[root] = [(a, from_a), (b, max(0.0, edge_length - from_a))]
    adjacency[a] = [(other, edge) for other, edge in adjacency[a] if other != b] + [
        (root, from_a)
    ]
    adjacency[b] = [(other, edge) for other, edge in adjacency[b] if other != a] + [
        (root, max(0.0, edge_length - from_a))
    ]

    seen = {root}
    stack = [root]
    while stack:
        current = stack.pop()
        for neighbor, branch in adjacency[current]:
            if neighbor in seen:
                continue
            seen.add(neighbor)
            parent[neighbor] = current
            length[neighbor] = branch
            children[current].append(neighbor)
            stack.append(neighbor)

    return Rooted(n_tips=tree.n_tips, root=root, parent=parent, length=length, children=children)


def root_at_tip(tree: Unrooted, tip: int) -> Rooted:
    """Root on the branch leading to one tip — outgroup rooting, at the branch midpoint.

    The midpoint rather than the tip itself, so the outgroup keeps a branch of its own
    and does not appear to sit at the origin of the tree.
    """
    incident = [(a, b, length) for a, b, length in tree.edges if tip in (a, b)]
    if len(incident) != 1:
        raise ValueError(f"tip {tip} has {len(incident)} edges; a tip must have exactly one")
    a, b, edge_length = incident[0]
    other = b if a == tip else a
    return _root_on_edge(tree, tip, other, edge_length / 2)


def midpoint_root(tree: Unrooted) -> Rooted:
    """Root at the middle of the longest path between two tips.

    Used where no outgroup exists. Non-polio enterovirus has no member that is
    ancestral to the rest, so nominating one would assert something untrue; the
    midpoint asserts only that the two most divergent sequences are equally far from
    the root, which is a stated convention rather than a claim.
    """
    adjacency = _adjacency(tree)
    start, _, _ = _farthest(adjacency, 0)
    end, diameter, came_from = _farthest(adjacency, start)

    walk = [end]
    while came_from[walk[-1]] != -1:
        walk.append(came_from[walk[-1]])

    traveled = 0.0
    for index in range(len(walk) - 1):
        here, following = walk[index], walk[index + 1]
        step = next(
            length for x, y, length in tree.edges if {x, y} == {here, following}
        )
        if traveled + step >= diameter / 2:
            return _root_on_edge(tree, here, following, diameter / 2 - traveled)
        traveled += step
    return _root_on_edge(tree, walk[0], walk[1], 0.0)


def layout(tree: Rooted) -> dict:
    """Rectangular coordinates: x is distance from the root, y is tip order.

    Ladderized by descending clade size, so the shape is stable across rebuilds and
    the largest clade reads first. Ties break on the smallest tip index, which makes
    the order total rather than merely consistent.
    """
    order: list[int] = []
    post: list[int] = []
    stack = [tree.root]
    while stack:
        current = stack.pop()
        post.append(current)
        stack.extend(tree.children[current])
    post.reverse()

    size = [0] * len(tree.parent)
    smallest = [len(tree.parent)] * len(tree.parent)
    for node in post:
        if not tree.children[node]:
            size[node] = 1
            smallest[node] = node
        else:
            size[node] = sum(size[child] for child in tree.children[node])
            smallest[node] = min(smallest[child] for child in tree.children[node])
    for node in post:
        tree.children[node].sort(key=lambda child: (-size[child], smallest[child]))

    x = [0.0] * len(tree.parent)
    stack = [tree.root]
    while stack:
        current = stack.pop()
        if not tree.children[current]:
            order.append(current)
            continue
        # Reversed, because a stack pops last-first and the ladder order must survive.
        for child in reversed(tree.children[current]):
            x[child] = x[current] + max(0.0, tree.length[child])
            stack.append(child)

    y = [0.0] * len(tree.parent)
    for position, tip in enumerate(order):
        y[tip] = float(position)
    span_low = [0.0] * len(tree.parent)
    span_high = [0.0] * len(tree.parent)
    for node in post:
        if not tree.children[node]:
            span_low[node] = span_high[node] = y[node]
        else:
            span_low[node] = min(y[child] for child in tree.children[node])
            span_high[node] = max(y[child] for child in tree.children[node])
            y[node] = 0.5 * (span_low[node] + span_high[node])

    internal = [node for node in post if tree.children[node]]
    slot = {node: index for index, node in enumerate(internal)}
    return {
        "tip_order": order,
        "tip_x": [x[tip] for tip in order],
        "tip_parent": [slot[tree.parent[tip]] for tip in order],
        "node_x": [x[node] for node in internal],
        "node_ylo": [span_low[node] for node in internal],
        "node_yhi": [span_high[node] for node in internal],
        "node_parent": [
            -1 if tree.parent[node] < 0 else slot[tree.parent[node]] for node in internal
        ],
    }


def _empty(threshold: int, columns: int, unit: str, below: int, eligible: int) -> dict:
    return {
        "tip_record": [],
        "tip_x": [],
        "tip_parent": [],
        "tip_coverage": [],
        "tip_shared": [],
        "thin": [],
        "confident_shared": 0,
        "node_x": [],
        "node_ylo": [],
        "node_yhi": [],
        "node_parent": [],
        "n_eligible": eligible,
        "excluded": {"below_coverage": below, "not_comparable": 0},
        "columns": columns,
        "unit": unit,
        "min_shared": threshold,
        "root": {"kind": "none", "label": "—"},
        "negative_branches": 0,
        "clamped_total": 0.0,
    }


SCHEMA = 1


def build_selection(
    selection: dict,
    alignment: frame.Alignment,
    columns: dict[str, np.ndarray],
    population,
) -> dict:
    """Every tree for one selection.

    Shipped as its own file rather than inside the panel file: the trees are the largest
    payload on the site and only the two phylogeny chapters read them, so folding them
    into the panels would make the scatter figures wait on data they never touch.
    """
    nucleotide = {
        region: build_region(
            alignment,
            population.rows,
            columns[region],
            selection,
            region,
            population.record_rows,
            distances.NUCLEOTIDE,
        )
        for region in contract.NUCLEOTIDE_TREE_REGIONS
    }
    protein = {
        region: build_region(
            alignment,
            population.rows,
            columns[region],
            selection,
            region,
            population.record_rows,
            distances.RESIDUE,
        )
        for region in contract.PROTEIN_TREE_REGIONS
    }
    return {
        "schema": SCHEMA,
        "selection": selection["id"],
        "tip_cap": TIP_CAP,
        "nucleotide": nucleotide,
        "protein": protein,
    }


def build_region(
    alignment: frame.Alignment,
    rows: np.ndarray,
    columns: np.ndarray,
    selection: dict,
    region: str,
    record_rows: list[int],
    alphabet: distances.Alphabet,
) -> dict:
    """One tree. `rows` indexes the alignment; `record_rows` maps to records.json."""
    block, threshold, width = distances.in_alphabet(
        alignment.matrix[np.ix_(rows, columns)],
        contract.min_nt(region),
        int(len(columns)),
        alphabet,
    )

    eligible = distances.eligible(block, threshold, alphabet)
    if len(eligible) < 3:
        return _empty(
            threshold, width, alphabet.unit, int(len(rows) - len(eligible)), int(len(eligible))
        )

    # The root has to be on the tree, so it is required into the set rather than hoped
    # for. Sabin is a whole genome and would almost always survive the greedy anyway,
    # but "almost always" would leave one panel silently midpoint-rooted.
    wanted_root = selection["root"]
    required = None
    root_tip = None
    if wanted_root != "midpoint" and wanted_root in alignment.index:
        hits = np.flatnonzero(rows[eligible] == alignment.index[wanted_root])
        if len(hits):
            required = int(eligible[hits[0]])

    members = distances.comparable_set(
        block, eligible, threshold, cap=TIP_CAP, required=required, alphabet=alphabet
    )
    shared, matches = distances.counts_against(block, members, members, alphabet)
    distance = distances.distance_from_counts(shared, matches, threshold)
    np.fill_diagonal(distance, 0.0)
    if np.isnan(distance).any():
        raise ValueError(
            f"{selection['id']} {region} {alphabet.name}: "
            f"{int(np.isnan(distance).sum())} tip pairs are undefined"
        )
    if len(members) < 3:
        return _empty(
            threshold, width, alphabet.unit, int(len(rows) - len(eligible)), int(len(eligible))
        )

    if required is not None:
        found = np.flatnonzero(members == required)
        root_tip = int(found[0]) if len(found) else None

    tree, negative, clamped = clamp_negative(neighbor_join(distance))
    rooted = (
        root_at_tip(tree, root_tip) if root_tip is not None else midpoint_root(tree)
    )
    placed = layout(rooted)

    off_diagonal = shared.copy()
    np.fill_diagonal(off_diagonal, np.nan)
    with np.errstate(invalid="ignore"):
        median_shared = np.nanmedian(off_diagonal, axis=1)

    # Every tip's distances are defined — that is the membership rule — but a tip whose
    # distances rest on little shared sequence has a branch length with wide error bars
    # on it. Marked so the reader can discount a long branch that is really a thin one.
    # The floor is the same region-relative one the distance map uses.
    floor = distances.confident_shared(width)
    thin = median_shared < floor

    coverage = alphabet.readable(block[members]).sum(axis=1)
    order = placed["tip_order"]
    return {
        "tip_record": [record_rows[int(members[tip])] for tip in order],
        # Five decimals is finer than a 900 px panel resolves and keeps the committed
        # artifact from churning on float noise.
        "tip_x": [round(value, 5) for value in placed["tip_x"]],
        "tip_parent": placed["tip_parent"],
        "tip_coverage": [int(coverage[tip]) for tip in order],
        "tip_shared": [int(median_shared[tip]) for tip in order],
        "thin": [index for index, tip in enumerate(order) if bool(thin[tip])],
        "confident_shared": int(floor),
        "node_x": [round(value, 5) for value in placed["node_x"]],
        "node_ylo": [round(value, 2) for value in placed["node_ylo"]],
        "node_yhi": [round(value, 2) for value in placed["node_yhi"]],
        "node_parent": placed["node_parent"],
        "n_eligible": int(len(eligible)),
        "excluded": {
            "below_coverage": int(len(rows) - len(eligible)),
            "not_comparable": int(len(eligible) - len(members)),
        },
        # In the comparison unit, not in alignment columns. A protein tree that reported
        # its width as 2,643 beside a threshold of 16 codons would be quoting two
        # different units in one sentence.
        "columns": width,
        "unit": alphabet.unit,
        "min_shared": threshold,
        "root": {
            "kind": "outgroup" if root_tip is not None else "midpoint",
            "label": (
                wanted_root
                if root_tip is not None
                else "midpoint of the longest tip-to-tip path"
            ),
        },
        "negative_branches": negative,
        "clamped_total": round(clamped, 5),
    }
