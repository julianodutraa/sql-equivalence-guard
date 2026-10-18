"""Declarative schema model used to drive the random table generator.

A schema is intentionally small: it describes just enough about a column
(its type, nullability, and how "interesting" its values should be) for
the generator in ``generator.py`` to produce rows that exercise realistic
edge cases, not just type-correct noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ColumnType = Literal["int", "bigint", "double", "varchar", "boolean", "date", "timestamp"]


@dataclass(frozen=True)
class ColumnSpec:
    """One column in a synthetic table.

    Attributes:
        name: Column name as it appears in the generated table.
        dtype: One of the supported DuckDB-mapped primitive types.
        nullable: Whether NULL is a legal value for this column.
        key_pool_size: When set, values for this column are drawn from a
            small pool of this size instead of the unrestricted domain.
            A small pool makes duplicate keys and join fan-out common,
            which is exactly the condition that exposes DISTINCT and
            JOIN-cardinality mutants.
        low: Lower bound for numeric columns (inclusive).
        high: Upper bound for numeric columns (inclusive).
        boundary_values: Explicit values that the edge-case generator
            should inject with elevated probability (for example the
            exact threshold used in a WHERE clause the query under test
            depends on). This is how the project makes boundary-value
            analysis an explicit, tunable knob instead of an accident of
            uniform random sampling.
    """

    name: str
    dtype: ColumnType
    nullable: bool = False
    key_pool_size: int | None = None
    low: float | None = None
    high: float | None = None
    boundary_values: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class TableSpec:
    """A named table: an ordered list of columns plus a logical row count hint."""

    name: str
    columns: tuple[ColumnSpec, ...]

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]
