# sql-equivalence-guard

A differential-testing oracle that checks whether a SQL rewrite still computes the same thing, and an honest measurement of exactly when that check can be fooled.

## Executive summary

Every data platform accumulates thousands of SQL transformations: dbt models, ETL jobs, reporting views. Engineers rewrite them constantly, to add a column, to speed up a slow join, to simplify a CTE a new hire found confusing. Code review catches syntax problems and style issues. It is much worse at catching the rewrite that is *semantically* different: a `LEFT JOIN` quietly narrowed to a `JOIN`, a `DISTINCT` dropped during a refactor, a `<=` turned into a `<`. These changes compile, they often even look like an improvement, and they silently change the numbers that land in an executive dashboard or a billing calculation.

This project is a small, runnable tool that automates the check a careful reviewer would want to do but rarely has time for: generate a lot of realistic synthetic data, run the old query and the new query against the same data, and see if they agree. Agreement across many random datasets is useful evidence that a rewrite is safe. The project's main technical contribution is being precise and honest about how far that evidence actually goes, because the headline finding here is that it does not go very far by default.

Measured on a corpus of 11 realistic query-pair cases (7 real bugs and 4 genuinely safe rewrites, built from five common data-pipeline query patterns), naive random testing with no bias toward edge cases misses most of the real bugs: it catches a dropped `COALESCE` 0% of the time and a narrowed SLA boundary only 5.8% of the time, even after 500 trials. A single, well-understood fix (biasing the data generator toward NULLs, duplicate keys, and exact threshold values) raises every one of those to 100%, while the four genuinely safe rewrites stay at a strict 0% false-positive rate across 6,000 trials. The honest caveat, and the most interesting single result in the project, is that this bias also exposed a case believed to be a safe rewrite that is not: see "The most interesting finding" below.

For a data engineering organization, the business case is straightforward: a tool that can be pointed at a proposed SQL refactor before merge, and that tells a reviewer "I generated 500 realistic datasets and these two queries agreed on all of them" or "here is a specific, reproducible dataset on which they disagree," converts a code-review judgment call into a falsifiable, re-runnable check. It does not replace review. It replaces the parts of review that are really just "did anyone actually run this against data."

## What this project does not claim

Agreement across N random trials is not a proof of equivalence. It is evidence, bounded by how well the generator's distribution covers the space of inputs the two queries could ever disagree on. A mutation that only manifests on a pattern the generator rarely produces will look exactly like a safe rewrite until the generator is biased toward that specific pattern; this project measures that gap directly instead of hiding it (see the kill-rate tables below). Formal, sound query-equivalence checking (symbolic reasoning over relational algebra, as in tools like Cosette or SQLSolver) exists and gives a real proof for the fragment of SQL it supports; this project is deliberately the cheaper, less complete alternative that works on arbitrary DuckDB-executable SQL, in exchange for giving up soundness. That tradeoff, and where it breaks, is the actual subject of this project.

## Quickstart

```bash
git clone https://github.com/julianodutraa/sql-equivalence-guard.git
cd sql-equivalence-guard
pip install -e ".[dev]"
pytest -q                       # 32 tests, no network, no API key, ~10s
python examples/run_demo.py     # one worked example end to end
python -m sql_equivalence_guard.cli --trials 200 --rows 60 --bias 0.2
```

`examples/run_demo.py` is deterministic and prints, among other things:

```
Ran 30 trials, 30 found a difference (kill rate 100.0%).

Risk level: BEHAVIOR_CHANGE
A difference was found on seed 20261018: 1 row(s) appear only in the reference query
and 1 row(s) appear only in the candidate query, over columns [net_revenue]. [...]
```

No API key or network access is required for any of the above. The optional `LLMNarrator` class (see `narrator.py`) documents how an LLM-backed narration would be wired in, but the package is fully functional, tested, and evaluated without one.

## How it works

1. **Schema-driven random table generation** (`generator.py`). A table is described declaratively (`schema.py`): column names, types, nullability, and two knobs that matter more than the rest of the schema combined: `key_pool_size` (draw from a small shared pool instead of an unrestricted domain, so duplicate keys and join fan-out happen often) and `boundary_values` (inject a specific value, such as an exact SLA threshold, with elevated probability). A single scalar, `edge_case_bias` in `[0, 1]`, controls what fraction of cells are drawn from this "interesting" distribution instead of the bulk one.

2. **The oracle** (`oracle.py`). Both queries run against the same generated tables inside one in-memory DuckDB connection. Results are compared as multisets of rows (order-insensitive) unless both queries contain a top-level `ORDER BY`, in which case order is also compared. Floats are rounded to a configurable tolerance before comparison, so arithmetically equivalent rewrites (`SUM(a - b)` vs `SUM(a) - SUM(b)`) do not register as false positives from floating-point noise.

3. **Trials, not a single check** (`run_trials`). One dataset proves nothing; the real signal is agreement, or disagreement, across many independently seeded datasets. `run_trials` reports a *kill rate*, borrowing the term from mutation testing: the fraction of trials in which a difference was found.

4. **A labeled mutant corpus** (`mutations.py`). Five realistic base queries (daily active users, net revenue with a discount join, top-incident-per-day ranking, an SLA threshold check, and an average with NULL handling), each paired with hand-written realistic mutants (a change a real reviewer could plausibly approve) and hand-written safe rewrites (a different query, same answer, used to measure the false-positive rate). Hand-written, labeled mutants are deliberately preferred over automatic AST-level SQL mutation here: automatic SQL mutators routinely produce invalid or semantically absurd queries, which would make the resulting kill-rate numbers meaningless.

5. **A narrator** (`narrator.py`). Turns a diff into a plain-English risk label. The default, `TemplateNarrator`, is a pure function of the diff statistics: deterministic, offline, and the only narrator this project evaluates with an automated test suite. `LLMNarrator` documents the prompt an LLM-backed version would use and is evaluated separately and manually; see `eval/narrator_review.json`.

## The honest numbers

Full sweep in `eval/results.json` (`python eval/run_eval.py` to reproduce; deterministic given the fixed seed). Kill rate at 500 trials, 40 rows per trial, three edge-case bias levels:

| case | kind | bias 0.0 | bias 0.15 | bias 0.35 |
|---|---|---|---|---|
| q1_drop_distinct | mutant | 7.8% | 100.0% | 100.0% |
| q2_inner_join | mutant | 100.0% | 100.0% | 100.0% |
| q3_wrong_tiebreak_direction | mutant | 100.0% | 100.0% | 100.0% |
| q3_drop_partition | mutant | 100.0% | 100.0% | 100.0% |
| q4_exclusive_boundary | mutant | 5.8% | 100.0% | 100.0% |
| q5_drop_coalesce | mutant | 0.0% | 100.0% | 100.0% |
| q3_safe_rank_rewrite | conditional | 0.0% | 74.6% | 73.6% |
| q1_safe_groupby_rewrite | safe rewrite | 0.0% | 0.0% | 0.0% |
| q2_safe_sum_distribution | safe rewrite | 0.0% | 0.0% | 0.0% |
| q4_safe_demorgan_rewrite | safe rewrite | 0.0% | 0.0% | 0.0% |
| q5_safe_division_rewrite | safe rewrite | 0.0% | 0.0% | 0.0% |

Two honest conclusions, not cherry-picked:

* **Without edge-case bias, random testing is a weak safety net for exactly the bugs that matter most.** A dropped `COALESCE` (`q5_drop_coalesce`) is caught 0% of the time at bias 0.0, because the generator rarely produces NULL rows without being told to. A narrowed SLA boundary (`q4_exclusive_boundary`) is caught only 5.8% of the time, because landing on an exact threshold value by uniform chance, out of a 600-point range, is rare. These are not edge cases in the pejorative sense; they are exactly the inputs real production data contains constantly (NULLs happen, SLA thresholds get hit exactly).
* **The four genuinely safe rewrites never produced a false positive, across 6,000 trials (4 cases times 3 bias levels times 500 trials).** That is the soundness-in-practice half of the story this project can actually support: biasing the generator toward edge cases catches more real bugs without making the oracle trigger-happy on safe code, at least on this corpus.

### The most interesting finding

`q3_safe_rank_rewrite` was designed to be a safe rewrite: replacing `ROW_NUMBER()` with `RANK()` in a "pick the top incident per day" query, reasoned to be equivalent because the tiebreaker column (`incident_id`) makes the sort key unique within each partition. That reasoning is correct, with one hidden assumption: it requires that no two rows are *exact duplicates* of each other. `ROW_NUMBER()` breaks a tie between two byte-identical rows arbitrarily and keeps exactly one of them; `RANK()` assigns both the same rank, so a filter on `rn = 1` returns both. The project's own edge-case generator, which deliberately injects exact-duplicate rows to model an upstream retry or message-replay bug, found this during development. It was not designed into the corpus as a mutant; it surfaced as a bug in the project's own assumptions, caught by the same mechanism being built to catch other people's bugs. The kill rate climbs from 0.0% with no duplicate-row injection to roughly 74% once it is enabled, which is itself informative: this disagreement is common once duplicates exist at all, not a one-in-a-million coincidence, and a production `RANK()`-based deploy that happened to be tested without duplicate-row coverage could ship for a long time before anyone noticed.

### Mutation-kill-rate evaluation as the honest-metrics method

Why mutation-kill-rate, specifically, is the right honesty check for a tool like this: a false "the oracle works" claim is cheap to produce (just show it catching an easy bug) and expensive to detect from the outside. Measuring the kill rate against *known* mutants, including ones chosen to be hard (a boundary value, a NULL-handling change), and reporting the cases where it is low, is what turns "we built a SQL equivalence checker" into a specific, falsifiable, reproducible claim about exactly what it catches and under what generator configuration.

## The narrator evaluation

`narrator.py` ships two implementations. `TemplateNarrator` is deterministic and is what the automated test suite exercises. `LLMNarrator` documents the exact prompt an LLM-backed narrator would receive and is not called by any automated test, because this is a public repository with no API key in it. It was evaluated manually once during development, in `eval/narrator_review.json`: free-form, LLM-style narrations were written from the diff JSON alone (never the ground-truth mutation label) and scored against a three-criterion rubric. The template narrator scored 33/33 by construction, because it never asserts a root cause. The free-form narrations scored 32/33: on `q2_inner_join`, a single ambiguous data point (one aggregate collapsing to zero) was narrated as "most likely" caused by a specific join change, which happened to be correct but was not actually supported by the evidence shown, since a collapse to zero is equally consistent with several other causes. That is the honest, reportable limitation of letting a narrator speculate about causation from a diff: it is usually more informative than a template, and it has a specific, identifiable failure mode.

## What is not in scope

This project does not infer SQL semantics, does not patch queries, and does not formally prove equivalence. It does not handle non-deterministic SQL (`RANDOM()`, `NOW()`) meaningfully; both queries would need to be seeded or mocked, which is left to the caller. It does not generate data respecting arbitrary CHECK constraints or foreign-key integrity beyond the `key_pool_size` mechanism. These are reasonable follow-ups, not silent gaps: the honest-limitations section above is the actual deliverable, not an afterthought.

## Repository layout

```
src/sql_equivalence_guard/
    schema.py        table/column schema model
    generator.py      random table generator with tunable edge-case bias
    oracle.py         differential-testing core: compare_once, run_trials
    mutations.py      the 11-case labeled corpus
    narrator.py        TemplateNarrator (default) and LLMNarrator (documented, optional)
    cli.py             python -m sql_equivalence_guard.cli
tests/                  32 automated tests, pytest, no network required
examples/run_demo.py    the reproducible walkthrough quoted above
eval/
    run_eval.py        reproduces eval/results.json (full kill-rate sweep)
    results.json        the honest numbers tabulated above
    narrator_review.json the manual narrator evaluation described above
ARTICLE.md              longer-form write-up of this project
```

## License

MIT, see `LICENSE`.
