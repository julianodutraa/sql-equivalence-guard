"""Random synthetic table generator with a tunable edge-case bias.

Pure uniform random generation is a poor fuzzer for SQL semantics: most
interesting bugs live at the edges (NULLs, exact threshold values,
duplicate keys, empty strings) which uniform sampling over a wide domain
visits only by accident. This module implements two independently
controllable sources of randomness:

1. The "bulk" distribution: ordinary, broad-domain random values.
2. The "edge-case" distribution: NULLs (when the column is nullable),
   values drawn from ``ColumnSpec.boundary_values``, and values drawn
   from a small shared pool (when ``key_pool_size`` is set) so that
   duplicates and join fan-out happen often instead of almost never.

``edge_case_bias`` is the probability, per cell, of drawing from the
edge-case distribution instead of the bulk one. The mutation-kill-rate
experiment in ``eval/`` sweeps this parameter explicitly, because it is
the single biggest lever on whether property-based testing finds a given
bug at all.
"""

from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta

from sql_equivalence_guard.schema import ColumnSpec, TableSpec

Row = tuple


def _bulk_value(col: ColumnSpec, rng: random.Random):
    if col.dtype in ("int", "bigint"):
        low = int(col.low) if col.low is not None else 0
        high = int(col.high) if col.high is not None else 1000
        return rng.randint(low, high)
    if col.dtype == "double":
        low = col.low if col.low is not None else 0.0
        high = col.high if col.high is not None else 1000.0
        return round(rng.uniform(low, high), 4)
    if col.dtype == "varchar":
        length = rng.randint(3, 10)
        return "".join(rng.choices(string.ascii_lowercase, k=length))
    if col.dtype == "boolean":
        return rng.choice([True, False])
    if col.dtype == "date":
        base = date(2026, 1, 1)
        return base + timedelta(days=rng.randint(0, 59))
    if col.dtype == "timestamp":
        base = datetime(2026, 1, 1)
        return base + timedelta(minutes=rng.randint(0, 59 * 24 * 60))
    raise ValueError(f"unsupported dtype {col.dtype!r}")


def _edge_value(col: ColumnSpec, rng: random.Random, key_pools: dict):
    choices = []
    if col.nullable:
        choices.append("__NULL__")
    if col.boundary_values:
        choices.extend(["__BOUNDARY__"] * 2)
    if col.key_pool_size:
        choices.extend(["__POOL__"] * 2)
    if not choices:
        return _bulk_value(col, rng)

    pick = rng.choice(choices)
    if pick == "__NULL__":
        return None
    if pick == "__BOUNDARY__":
        return rng.choice(col.boundary_values)
    if pick == "__POOL__":
        pool = key_pools.setdefault(col.name, [_bulk_value(col, rng) for _ in range(col.key_pool_size)])
        return rng.choice(pool)
    raise AssertionError(pick)


def generate_table(spec: TableSpec, n_rows: int, seed: int, edge_case_bias: float = 0.0) -> list[Row]:
    """Generate ``n_rows`` synthetic rows for ``spec``, deterministically.

    Args:
        spec: The table schema to populate.
        n_rows: Number of rows to generate.
        seed: Seed for the private ``random.Random`` instance. Two calls
            with the same ``(spec, n_rows, seed, edge_case_bias)`` always
            produce byte-identical output; this is what makes a failing
            trial reproducible from a bare seed.
        edge_case_bias: Probability in [0, 1] that any given cell is drawn
            from the edge-case distribution instead of the bulk one.

    Returns:
        A list of row tuples, in column order given by ``spec.columns``.
    """
    if not 0.0 <= edge_case_bias <= 1.0:
        raise ValueError("edge_case_bias must be in [0, 1]")

    rng = random.Random(seed)
    key_pools: dict = {}
    rows: list[Row] = []
    for _ in range(n_rows):
        row = []
        for col in spec.columns:
            if rng.random() < edge_case_bias:
                row.append(_edge_value(col, rng, key_pools))
            else:
                row.append(_bulk_value(col, rng))
        rows.append(tuple(row))

    # Inject a small number of exact-duplicate full rows when bias is high;
    # exact-duplicate rows are what exposes a missing DISTINCT, as opposed
    # to merely duplicate keys, which expose join fan-out.
    if edge_case_bias > 0 and n_rows >= 4:
        n_dupes = max(1, int(n_rows * edge_case_bias * 0.1))
        for _ in range(n_dupes):
            rows.append(rng.choice(rows))

    return rows
