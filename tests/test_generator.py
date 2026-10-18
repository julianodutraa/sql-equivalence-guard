from sql_equivalence_guard.generator import generate_table
from sql_equivalence_guard.schema import ColumnSpec, TableSpec

SPEC = TableSpec(
    "t",
    (
        ColumnSpec("a", "int", low=0, high=10),
        ColumnSpec("b", "varchar", nullable=True),
    ),
)


def test_generate_table_is_deterministic():
    rows_1 = generate_table(SPEC, n_rows=20, seed=42, edge_case_bias=0.2)
    rows_2 = generate_table(SPEC, n_rows=20, seed=42, edge_case_bias=0.2)
    assert rows_1 == rows_2


def test_generate_table_different_seed_differs():
    rows_1 = generate_table(SPEC, n_rows=20, seed=1, edge_case_bias=0.0)
    rows_2 = generate_table(SPEC, n_rows=20, seed=2, edge_case_bias=0.0)
    assert rows_1 != rows_2


def test_generate_table_respects_row_count_without_bias():
    rows = generate_table(SPEC, n_rows=15, seed=1, edge_case_bias=0.0)
    assert len(rows) == 15


def test_generate_table_can_inject_nulls_with_bias():
    rows = generate_table(SPEC, n_rows=200, seed=7, edge_case_bias=0.5)
    nulls = sum(1 for row in rows if row[1] is None)
    assert nulls > 0, "expected at least one NULL in column b with nullable=True and bias=0.5"


def test_generate_table_never_injects_nulls_without_bias():
    rows = generate_table(SPEC, n_rows=500, seed=7, edge_case_bias=0.0)
    assert all(row[1] is not None for row in rows)


def test_invalid_bias_rejected():
    import pytest

    with pytest.raises(ValueError):
        generate_table(SPEC, n_rows=5, seed=1, edge_case_bias=1.5)
