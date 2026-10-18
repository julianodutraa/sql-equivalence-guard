"""The differential-testing oracle: run two queries on the same data, diff.

Design note on what "equivalent" means here. Two queries are compared as
multisets of output rows unless both contain an explicit ORDER BY, in
which case row order is also compared. This matches the SQL standard's
own position: a query without ORDER BY has no guaranteed row order, so
treating order as meaningful would manufacture false positives out of
an implementation detail of DuckDB's execution plan, not a real
behavior difference.

Numeric columns are compared after rounding to ``float_tolerance``
decimal places, because two arithmetically equivalent rewrites (for
example ``SUM(a) - SUM(b)`` vs ``SUM(a - b)``) can differ in the last
bit of a float without differing in any way that matters to a data
consumer.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence

import duckdb

from sql_equivalence_guard.generator import Row, generate_table
from sql_equivalence_guard.schema import TableSpec

_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


def _has_order_by(sql: str) -> bool:
    """Detect a top-level ORDER BY, ignoring ORDER BY inside OVER(...).

    A naive substring search on "order by" also matches the ORDER BY
    inside a window function's OVER(...) clause (used in Q3's reference
    query, among others), which is a purely local sort for ranking and
    says nothing about the final row order of the query's output. Early
    development of this oracle used the naive version and it produced a
    real false positive: a RANK()-based rewrite that is provably
    equivalent to the ROW_NUMBER()-based reference was reported as a
    behavior change, purely because both queries happened to contain the
    substring "order by" inside their window clauses, which flipped the
    comparison from multiset (correct, no top-level ORDER BY present) to
    order-sensitive list equality (wrong), and DuckDB does not guarantee
    row-fetch order absent a top-level ORDER BY. The fix is a
    parenthesis-depth-aware scan: only an ORDER BY at depth 0 counts.
    """
    depth = 0
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            match = _ORDER_BY_RE.match(sql, i)
            if match:
                return True
        i += 1
    return False


def _normalize_row(row: Sequence, float_tolerance: int) -> Row:
    normalized = []
    for value in row:
        if isinstance(value, float):
            normalized.append(round(value, float_tolerance))
        else:
            normalized.append(value)
    return tuple(normalized)


@dataclass
class OracleResult:
    """Outcome of comparing query A and query B on one generated dataset."""

    equivalent: bool
    seed: int
    n_rows_a: int
    n_rows_b: int
    rows_only_in_a: list[Row] = field(default_factory=list)
    rows_only_in_b: list[Row] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    order_sensitive: bool = False

    def diff_summary(self, max_sample: int = 5) -> dict:
        """A compact, JSON-serializable summary used by the narrator."""
        return {
            "equivalent": self.equivalent,
            "seed": self.seed,
            "n_rows_a": self.n_rows_a,
            "n_rows_b": self.n_rows_b,
            "columns": self.columns,
            "order_sensitive": self.order_sensitive,
            "sample_rows_only_in_a": self.rows_only_in_a[:max_sample],
            "sample_rows_only_in_b": self.rows_only_in_b[:max_sample],
            "total_rows_only_in_a": len(self.rows_only_in_a),
            "total_rows_only_in_b": len(self.rows_only_in_b),
        }


def compare_once(
    sql_a: str,
    sql_b: str,
    tables: dict[str, tuple[TableSpec, list[Row]]],
    seed: int,
    float_tolerance: int = 6,
    connection: "duckdb.DuckDBPyConnection | None" = None,
) -> OracleResult:
    """Execute ``sql_a`` and ``sql_b`` against the same in-memory tables.

    Args:
        sql_a: The reference ("before") query.
        sql_b: The candidate ("after") query.
        tables: Mapping of table name to (schema, rows) already generated
            by the caller, typically via :func:`generate_dataset`.
        seed: Carried through only for bookkeeping in the result.
        float_tolerance: Decimal places used when rounding float columns
            before comparison.
        connection: An optional, already-open DuckDB connection to reuse
            across many calls (for example across trials in
            :func:`run_trials`). Reusing a connection avoids repeated
            process-level connection setup, which otherwise dominates
            the wall-clock cost of a large trial sweep. Tables are
            created fresh (``CREATE OR REPLACE TABLE``) on every call
            either way, so reuse is purely a performance optimization
            and never leaks state between trials. When omitted, a
            private in-memory connection is opened and closed for this
            call only.

    Returns:
        An :class:`OracleResult` describing whether the two queries
        produced the same data on this one dataset.
    """
    con = connection if connection is not None else duckdb.connect(database=":memory:")
    try:
        for name, (spec, rows) in tables.items():
            cols = ", ".join(c.name for c in spec.columns)
            con.execute(f"CREATE OR REPLACE TABLE {name} ({_ddl(spec)})")
            placeholders = ", ".join(["?"] * len(spec.columns))
            if rows:
                con.executemany(f"INSERT INTO {name} ({cols}) VALUES ({placeholders})", rows)

        cursor_a = con.execute(sql_a)
        columns = [d[0] for d in cursor_a.description]
        result_a = cursor_a.fetchall()
        result_b = con.execute(sql_b).fetchall()
    finally:
        if connection is None:
            con.close()

    order_sensitive = _has_order_by(sql_a) and _has_order_by(sql_b)

    norm_a = [_normalize_row(r, float_tolerance) for r in result_a]
    norm_b = [_normalize_row(r, float_tolerance) for r in result_b]

    if order_sensitive:
        equivalent = norm_a == norm_b
        rows_only_in_a = [] if equivalent else [r for r in norm_a if r not in norm_b]
        rows_only_in_b = [] if equivalent else [r for r in norm_b if r not in norm_a]
    else:
        counter_a, counter_b = Counter(norm_a), Counter(norm_b)
        equivalent = counter_a == counter_b
        diff_a = counter_a - counter_b
        diff_b = counter_b - counter_a
        rows_only_in_a = list(diff_a.elements())
        rows_only_in_b = list(diff_b.elements())

    return OracleResult(
        equivalent=equivalent,
        seed=seed,
        n_rows_a=len(result_a),
        n_rows_b=len(result_b),
        rows_only_in_a=rows_only_in_a,
        rows_only_in_b=rows_only_in_b,
        columns=columns,
        order_sensitive=order_sensitive,
    )


_DUCKDB_TYPE = {
    "int": "INTEGER",
    "bigint": "BIGINT",
    "double": "DOUBLE",
    "varchar": "VARCHAR",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
}


def _ddl(spec: TableSpec) -> str:
    parts = []
    for col in spec.columns:
        ddl_type = _DUCKDB_TYPE[col.dtype]
        null_clause = "" if col.nullable else " NOT NULL"
        parts.append(f"{col.name} {ddl_type}{null_clause}")
    return ", ".join(parts)


def generate_dataset(
    table_specs: dict[str, TableSpec], n_rows: int, seed: int, edge_case_bias: float
) -> dict[str, tuple[TableSpec, list[Row]]]:
    """Generate one synthetic dataset for every table used by a query pair."""
    dataset = {}
    for i, (name, spec) in enumerate(table_specs.items()):
        # Offset the seed per table so sibling tables don't share a stream.
        dataset[name] = (spec, generate_table(spec, n_rows, seed=seed * 1_000_003 + i, edge_case_bias=edge_case_bias))
    return dataset


@dataclass
class TrialReport:
    """Aggregate outcome of running the oracle over many random trials."""

    n_trials: int
    n_differing: int
    first_difference: OracleResult | None
    equivalent: bool

    @property
    def kill_rate(self) -> float:
        """Fraction of trials in which a difference was observed.

        Named "kill rate" to match mutation-testing terminology: a trial
        that finds a difference "kills" the mutant under test.
        """
        return self.n_differing / self.n_trials if self.n_trials else 0.0


def run_trials(
    sql_a: str,
    sql_b: str,
    table_specs: dict[str, TableSpec],
    n_trials: int,
    rows_per_trial: int,
    base_seed: int,
    edge_case_bias: float = 0.0,
    float_tolerance: int = 6,
    stop_on_first_difference: bool = False,
) -> TrialReport:
    """Run the oracle over ``n_trials`` independently seeded datasets.

    This is the statistical heart of the package: a single comparison
    proves nothing, but agreement across many independently generated
    datasets is the empirical equivalence evidence this project reports.
    It is explicitly not a soundness proof; see the README section
    "What this project does not claim" for the honest boundary of this
    claim.
    """
    n_differing = 0
    trials_completed = 0
    first_difference = None
    con = duckdb.connect(database=":memory:")
    try:
        for trial in range(n_trials):
            seed = base_seed + trial
            dataset = generate_dataset(table_specs, rows_per_trial, seed, edge_case_bias)
            result = compare_once(sql_a, sql_b, dataset, seed, float_tolerance, connection=con)
            trials_completed += 1
            if not result.equivalent:
                n_differing += 1
                if first_difference is None:
                    first_difference = result
                if stop_on_first_difference:
                    break
    finally:
        con.close()

    return TrialReport(
        n_trials=trials_completed,
        n_differing=n_differing,
        first_difference=first_difference,
        equivalent=(n_differing == 0),
    )
