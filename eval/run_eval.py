"""Reproducible mutation-kill-rate sweep: the honest numbers behind the README.

Run with: python eval/run_eval.py
Writes eval/results.json. Deterministic given the fixed BASE_SEED below;
rerunning reproduces byte-identical kill rates.

Each (bias, case) pair is run once for MAX_TRIALS trials, and kill rate
at each smaller checkpoint in TRIAL_CHECKPOINTS is computed as a prefix
of that same trial sequence (trial k with seed base_seed+k is identical
regardless of how many trials the run goes on to do), rather than
re-running the oracle from scratch per checkpoint. This keeps the sweep
fast without changing a single reported number.
"""

from __future__ import annotations

import json
import pathlib
import time

import duckdb

from sql_equivalence_guard.mutations import CASES
from sql_equivalence_guard.oracle import compare_once, generate_dataset

BASE_SEED = 20261018
TRIAL_CHECKPOINTS = [20, 100, 500]
MAX_TRIALS = max(TRIAL_CHECKPOINTS)
BIAS_LEVELS = [0.0, 0.15, 0.35]
ROWS_PER_TRIAL = 40

OUT_PATH = pathlib.Path(__file__).parent / "results.json"


def sweep_one(case, bias: float) -> dict[int, dict]:
    con = duckdb.connect(database=":memory:")
    checkpoints = {c: {"n_differing": 0, "first_difference": None} for c in TRIAL_CHECKPOINTS}
    try:
        for trial in range(MAX_TRIALS):
            seed = BASE_SEED + trial
            dataset = generate_dataset(case.table_specs, ROWS_PER_TRIAL, seed, bias)
            result = compare_once(case.reference_sql, case.candidate_sql, dataset, seed, connection=con)
            for checkpoint in TRIAL_CHECKPOINTS:
                if trial < checkpoint:
                    if not result.equivalent:
                        checkpoints[checkpoint]["n_differing"] += 1
                        if checkpoints[checkpoint]["first_difference"] is None:
                            checkpoints[checkpoint]["first_difference"] = result.diff_summary()
    finally:
        con.close()
    return checkpoints


def main() -> None:
    t_start = time.time()
    results = []
    for bias in BIAS_LEVELS:
        for case in CASES:
            checkpoints = sweep_one(case, bias)
            for n_trials, agg in checkpoints.items():
                results.append(
                    {
                        "case_id": case.case_id,
                        "base_query": case.base_query,
                        "kind": case.kind,
                        "description": case.description,
                        "edge_case_hint": case.edge_case_hint,
                        "edge_case_bias": bias,
                        "n_trials": n_trials,
                        "rows_per_trial": ROWS_PER_TRIAL,
                        "n_differing": agg["n_differing"],
                        "kill_rate": agg["n_differing"] / n_trials,
                        "example_diff": agg["first_difference"],
                    }
                )

    payload = {
        "base_seed": BASE_SEED,
        "rows_per_trial": ROWS_PER_TRIAL,
        "trial_checkpoints": TRIAL_CHECKPOINTS,
        "bias_levels": BIAS_LEVELS,
        "wall_clock_seconds": round(time.time() - t_start, 2),
        "results": results,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, default=str))
    print(f"wrote {OUT_PATH} in {payload['wall_clock_seconds']}s, {len(results)} rows")


if __name__ == "__main__":
    main()
