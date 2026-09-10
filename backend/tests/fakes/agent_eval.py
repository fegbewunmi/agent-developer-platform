"""A fake implementing app.integrations.agent_eval_client.AgentEvalClient's Protocol,
returning responses shaped exactly like the real, re-inspected API (see
app/integrations/agent_eval_client.py's module docstring for the confirmed schemas).
Used by every Phase 3 test that would otherwise need a real agent-eval instance -
"keep external calls mocked in the automated suite" (Phase 3 brief).
"""
import uuid
from dataclasses import dataclass, field

from app.integrations.agent_eval_client import (
    AgentEvalMalformedResponseError,
    AgentEvalTimeoutError,
    AgentEvalUnavailableError,
    CaseComparisonEntry,
    CaseRunSummary,
    ComparisonResult,
    Dataset,
    DatasetCase,
    DimensionStat,
    Evaluator,
    EvaluatorVersionMismatch,
    RunSummary,
)


@dataclass
class FakeAgentEvalClient:
    """Configure `evaluators`, `datasets`, and canned `runs` before use; call
    trigger_run() to have it synthesize a RunSummary from `next_run_case_statuses`/
    `next_run_dimension_stats`, or set `raise_on_trigger` to simulate a failure mode.
    """

    evaluators: list[Evaluator] = field(default_factory=list)
    datasets: list[Dataset] = field(default_factory=list)
    runs: dict[str, RunSummary] = field(default_factory=dict)
    comparisons: dict[tuple[str, str], ComparisonResult] = field(default_factory=dict)

    next_run_dimension_stats: list[DimensionStat] = field(default_factory=list)
    next_run_case_statuses: list[str] = field(default_factory=lambda: ["success"])
    next_run_dataset_snapshot_hash: str = "sha256:fake-dataset-hash"
    raise_on_trigger: Exception | None = None
    trigger_calls: list[dict] = field(default_factory=list)
    get_run_calls: list[tuple[str, str | None]] = field(default_factory=list)

    async def trigger_run(
        self, *, agent_version_id, dataset_id, evaluator_ids, triggered_by, timeout_seconds
    ) -> RunSummary:
        self.trigger_calls.append(
            {"agent_version_id": agent_version_id, "dataset_id": dataset_id, "evaluator_ids": evaluator_ids}
        )
        if self.raise_on_trigger is not None:
            raise self.raise_on_trigger

        run_id = str(uuid.uuid4())
        case_runs = [
            CaseRunSummary(case_run_id=str(uuid.uuid4()), case_key=f"case-{i}", status=status, latency_ms=100.0)
            for i, status in enumerate(self.next_run_case_statuses)
        ]
        run = RunSummary(
            id=run_id,
            agent_version_id=agent_version_id,
            dataset_id=dataset_id,
            dataset_snapshot_hash=self.next_run_dataset_snapshot_hash,
            status="completed" if all(c.status == "success" for c in case_runs) else "completed_with_errors",
            started_at="2026-09-10T00:00:00Z",
            completed_at="2026-09-10T00:01:00Z",
            triggered_by=triggered_by,
            dimension_stats=self.next_run_dimension_stats,
            case_runs=case_runs,
        )
        self.runs[run_id] = run
        return run

    async def get_run(self, run_id: str, tag: str | None = None) -> RunSummary:
        self.get_run_calls.append((run_id, tag))
        if run_id not in self.runs:
            raise AgentEvalMalformedResponseError(f"no such run {run_id}")
        return self.runs[run_id]

    async def compare_runs(self, run_a_id: str, run_b_id: str) -> ComparisonResult:
        key = (run_a_id, run_b_id)
        if key in self.comparisons:
            return self.comparisons[key]
        return ComparisonResult(
            run_a_id=run_a_id,
            run_b_id=run_b_id,
            dataset_id="fake-dataset",
            dataset_drift_detected=False,
            evaluator_version_mismatches=[],
            dimension_stats=[],
            regressions=[],
            improvements=[],
        )

    async def list_evaluators(self) -> list[Evaluator]:
        return self.evaluators

    async def list_datasets(self) -> list[Dataset]:
        return self.datasets

    async def get_dataset(self, dataset_id: str) -> Dataset:
        for d in self.datasets:
            if d.id == dataset_id:
                return d
        raise AgentEvalMalformedResponseError(f"no such dataset {dataset_id}")


def make_evaluator(key: str, version: str = "v1", dimension: str = "task_correctness") -> Evaluator:
    return Evaluator(id=str(uuid.uuid4()), key=key, version=version, type="deterministic", dimension=dimension)


def make_dataset(name: str, cases: list[dict] | None = None, dataset_id: str | None = None) -> Dataset:
    cases = cases if cases is not None else [{"key": "case-1", "tags": []}]
    return Dataset(
        id=dataset_id or str(uuid.uuid4()),
        name=name,
        case_count=len(cases),
        cases=[DatasetCase(id=str(uuid.uuid4()), key=c["key"], tags=c["tags"]) for c in cases],
    )
