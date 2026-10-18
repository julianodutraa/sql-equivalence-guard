import os

import pytest

from sql_equivalence_guard.mutations import CASES
from sql_equivalence_guard.narrator import LLMNarrator, TemplateNarrator
from sql_equivalence_guard.oracle import generate_dataset, compare_once


def _diff_for(case_id: str, seed: int, bias: float) -> dict:
    case = next(c for c in CASES if c.case_id == case_id)
    dataset = generate_dataset(case.table_specs, n_rows=40, seed=seed, edge_case_bias=bias)
    result = compare_once(case.reference_sql, case.candidate_sql, dataset, seed=seed)
    return result.diff_summary()


def test_template_narrator_labels_equivalent_diff_as_safe():
    diff = _diff_for("q1_safe_groupby_rewrite", seed=1, bias=0.0)
    narration = TemplateNarrator().narrate(diff)
    assert narration.risk_level == "SAFE"
    assert "evidence of equivalence" in narration.text


def test_template_narrator_labels_real_difference_as_behavior_change():
    diff = _diff_for("q2_inner_join", seed=1, bias=0.2)
    narration = TemplateNarrator().narrate(diff)
    if diff["equivalent"]:
        pytest.skip("this seed happened not to trigger the mutant; not the narrator's concern")
    assert narration.risk_level == "BEHAVIOR_CHANGE"
    assert "reproducible counterexample" in narration.text


def test_template_narrator_is_deterministic():
    diff = _diff_for("q4_exclusive_boundary", seed=42, bias=0.4)
    n1 = TemplateNarrator().narrate(diff)
    n2 = TemplateNarrator().narrate(diff)
    assert n1 == n2


def test_llm_narrator_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    diff = _diff_for("q1_safe_groupby_rewrite", seed=1, bias=0.0)
    with pytest.raises(RuntimeError):
        LLMNarrator().narrate(diff)


def test_llm_narrator_build_prompt_is_a_string():
    diff = _diff_for("q1_safe_groupby_rewrite", seed=1, bias=0.0)
    prompt = LLMNarrator().build_prompt(diff)
    assert isinstance(prompt, str)
    assert "BEHAVIOR_CHANGE" in prompt
