"""sql_equivalence_guard: a differential-testing oracle for SQL refactors.

This package answers one narrow question with statistical rigor: after a
data engineer rewrites a SQL transformation (a dbt model, an ETL query, a
"performance optimization" of a reporting view), does the new query still
compute the same thing as the old one?

The oracle never reads the SQL semantically. It generates many random
synthetic tables that satisfy the declared schema, executes both queries
against the same data in DuckDB, and compares the result sets. Agreement
across many trials is evidence of equivalence, never proof: see
``docs`` in the project README for the exact statistical claim this
package is willing to make, and the one it explicitly refuses to make.
"""

from sql_equivalence_guard.oracle import OracleResult, compare_once, run_trials
from sql_equivalence_guard.schema import ColumnSpec, TableSpec
from sql_equivalence_guard.generator import generate_table

__all__ = [
    "OracleResult",
    "compare_once",
    "run_trials",
    "ColumnSpec",
    "TableSpec",
    "generate_table",
]

__version__ = "0.1.0"
