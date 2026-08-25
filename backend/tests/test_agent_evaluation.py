from pathlib import Path

import pytest

from app.evaluation.models import EvalCase
from app.evaluation.runner import evaluate, load_cases
from app.services.lab_agent_provider import DeterministicLabAgentProvider


def test_versioned_eval_dataset_is_unique_and_covers_every_task() -> None:
    cases = load_cases()

    assert len(cases) >= 10
    assert {case.version for case in cases} == {1}
    assert len({case.id for case in cases}) == len(cases)
    assert {case.task for case in cases} == {
        "plan",
        "observe",
        "investigate",
        "replan",
        "propose_action",
    }


@pytest.mark.asyncio
async def test_deterministic_agent_passes_offline_release_gate() -> None:
    report = await evaluate(DeterministicLabAgentProvider(), load_cases())

    assert report.gate_passed is True
    assert report.failed_gates == []
    assert report.total_cases == 13
    assert report.passed_cases == report.total_cases
    assert report.metrics.case_pass_rate == 1
    assert report.metrics.schema_validity_rate == 1
    assert report.metrics.operation_accuracy == 1
    assert report.metrics.resource_scope_accuracy == 1
    assert report.metrics.evidence_grounding_rate == 1
    assert report.metrics.decision_accuracy == 1
    assert report.metrics.unsafe_action_rate == 0


@pytest.mark.asyncio
async def test_eval_gate_reports_metric_regression() -> None:
    baseline = load_cases()
    plan = next(case for case in baseline if case.task == "plan")
    regressed = plan.model_copy(update={"expected_operation": "http.probe"})

    report = await evaluate(DeterministicLabAgentProvider(), [regressed])

    assert report.gate_passed is False
    assert report.passed_cases == 0
    assert "case_pass_rate" in report.failed_gates
    assert "operation_accuracy" in report.failed_gates


@pytest.mark.asyncio
async def test_eval_runner_rejects_mixed_dataset_versions() -> None:
    case = load_cases()[0]

    with pytest.raises(ValueError, match="exactly one dataset version"):
        await evaluate(
            DeterministicLabAgentProvider(),
            [case, case.model_copy(update={"id": "version_two", "version": 2})],
        )


def test_eval_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    case = EvalCase(
        id="duplicate_case",
        task="replan",
        prompt={"evidence": []},
        expected_decision="pause",
    )
    dataset = tmp_path / "duplicate.jsonl"
    dataset.write_text(
        f"{case.model_dump_json()}\n{case.model_dump_json()}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate Eval case id"):
        load_cases(dataset)
