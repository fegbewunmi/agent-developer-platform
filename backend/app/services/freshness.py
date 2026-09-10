"""Evidence freshness / candidate eligibility - docs/evaluation-and-promotion.md's
distinction between "evaluation passed at the time" (a historical, immutable fact -
see app/services/gates.py, computed once, at run completion) and "evidence is still
valid for promotion now" (computed live, every time this module is called, never
stored). A version can remain stage=candidate while becoming currently ineligible.

Real, named API gap found during Phase 3 (see docs/open-questions.md and
docs/evaluation-and-promotion.md): agent-eval's `dataset_snapshot_hash` is computed
server-side, over case {key, input, expected} content, and is only ever returned as
part of a RunSummaryResponse - there is no standalone "give me the current dataset
hash" endpoint. Reconstructing that exact hash client-side would mean reimplementing
agent-eval's own dataset-hashing logic, which Phase 3's brief explicitly forbids
("do not reimplement ... dataset logic"). So dataset freshness here uses a distinctly
named, honestly weaker proxy - `dataset_case_set_fingerprint` - built only from what
GET /datasets/{id} actually exposes (case id/key/tags). It catches cases added,
removed, renamed, or re-tagged; it CANNOT catch a case's input/expected content
changing while its key stays the same. This limitation is real and stated wherever
this fingerprint is used, never presented as equivalent to agent-eval's own hash.
"""
import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.agent_eval_client import AgentEvalClient
from app.models.agent import AgentVersionLifecycle
from app.models.enums import Stage
from app.models.evaluation import EvaluationGateResult, EvaluationPolicy, EvaluationRunReference
from app.services import evaluation_policies as policies_service
from app.services.errors import NotFoundError
from app.services.evidence_snapshot import take_capability_grant_snapshot


@dataclass(frozen=True)
class StaleFinding:
    reason: str  # one of app.models.enums.StaleReason's values, or "dataset_fingerprint_changed"
    detail: str


@dataclass(frozen=True)
class FreshnessResult:
    agent_version_id: str
    current_stage: str
    evaluation_run_reference_id: str | None
    historically_passed: bool
    currently_eligible: bool
    stale_findings: list[StaleFinding]


def dataset_case_set_fingerprint(cases: list[dict]) -> str:
    """cases: [{"id":..., "key":..., "tags": [...]}]. See module docstring for exactly
    what this can and cannot detect."""
    normalized = sorted(
        [{"key": c["key"], "tags": sorted(c["tags"])} for c in cases], key=lambda c: c["key"]
    )
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


async def _latest_historically_passing_reference(
    db: AsyncSession, agent_version_id: uuid.UUID
) -> EvaluationRunReference | None:
    """"Historically passing" = every gate computed for that run passed. Ties are
    broken by most recent requested_at."""
    result = await db.execute(
        select(EvaluationRunReference)
        .where(EvaluationRunReference.agent_version_id == agent_version_id)
        .order_by(EvaluationRunReference.requested_at.desc())
    )
    for ref in result.scalars().all():
        gate_result = await db.execute(
            select(EvaluationGateResult).where(EvaluationGateResult.evaluation_run_reference_id == ref.id)
        )
        gates = gate_result.scalars().all()
        if gates and all(g.passed for g in gates):
            return ref
    return None


async def check_freshness(
    db: AsyncSession,
    agent_eval_client: AgentEvalClient,
    agent_version_id: uuid.UUID,
    agent_name: str,
) -> FreshnessResult:
    lifecycle = (
        await db.execute(
            select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == agent_version_id)
        )
    ).scalar_one_or_none()
    if lifecycle is None:
        raise NotFoundError(f"no lifecycle row for agent version {agent_version_id}")

    passing_ref = await _latest_historically_passing_reference(db, agent_version_id)
    if passing_ref is None:
        return FreshnessResult(
            agent_version_id=str(agent_version_id),
            current_stage=lifecycle.stage.value,
            evaluation_run_reference_id=None,
            historically_passed=False,
            currently_eligible=False,
            stale_findings=[],
        )

    findings: list[StaleFinding] = []

    # policy_changed: is the policy this run was gated against still current?
    try:
        current_policy = await policies_service.get_current_policy_for_agent(db, agent_name)
        if current_policy.id != passing_ref.evaluation_policy_id:
            findings.append(
                StaleFinding(
                    "policy_changed",
                    f"evaluated against policy version recorded on the run, but the current policy "
                    f"for {agent_name!r} is now {current_policy.name}@{current_policy.version}",
                )
            )
    except NotFoundError:
        findings.append(StaleFinding("policy_changed", f"no evaluation policy currently exists for {agent_name!r}"))
        current_policy = None

    # evaluator_version_changed: precise, since GET /evaluators gives live versions.
    if current_policy is not None:
        live_evaluators = await agent_eval_client.list_evaluators()
        live_by_key = {e.key: e.version for e in live_evaluators}
        recorded_versions: dict = passing_ref.evaluator_versions or {}
        for key, required_version in current_policy.required_evaluator_keys.items():
            live_version = live_by_key.get(key)
            if live_version is None:
                findings.append(
                    StaleFinding("missing_required_evaluator", f"required evaluator {key!r} no longer exists in agent-eval's catalog")
                )
            elif recorded_versions.get(key) != live_version:
                findings.append(
                    StaleFinding(
                        "evaluator_version_changed",
                        f"evaluator {key!r} is now version {live_version!r}, but the passing run recorded "
                        f"{recorded_versions.get(key)!r}",
                    )
                )

    # dataset_changed (proxy - see module docstring for the exact, honest limitation).
    if passing_ref.external_dataset_id and passing_ref.dataset_case_set_fingerprint:
        try:
            dataset = await agent_eval_client.get_dataset(passing_ref.external_dataset_id)
            live_fingerprint = dataset_case_set_fingerprint(
                [{"key": c.key, "tags": c.tags} for c in (dataset.cases or [])]
            )
            if live_fingerprint != passing_ref.dataset_case_set_fingerprint:
                findings.append(
                    StaleFinding(
                        "dataset_changed",
                        "the dataset's case set (keys/tags) has changed since this evaluation ran - "
                        "note: this platform cannot detect in-place edits to an existing case's "
                        "input/expected content, only structural changes (see freshness.py)",
                    )
                )
        except Exception:  # noqa: BLE001 - agent-eval unavailable during a freshness check
            findings.append(
                StaleFinding("dataset_changed", "could not reach agent-eval to verify current dataset identity")
            )

    # capability_grants_changed: fully precise, entirely our own data.
    current_snapshot = await take_capability_grant_snapshot(db, agent_version_id)
    if passing_ref.capability_grant_snapshot_hash and current_snapshot.hash != passing_ref.capability_grant_snapshot_hash:
        findings.append(
            StaleFinding(
                "capability_grants_changed",
                f"active capability grants changed since evaluation "
                f"(was {passing_ref.capability_grant_snapshot_hash}, now {current_snapshot.hash})",
            )
        )

    currently_eligible = lifecycle.stage == Stage.CANDIDATE and len(findings) == 0

    return FreshnessResult(
        agent_version_id=str(agent_version_id),
        current_stage=lifecycle.stage.value,
        evaluation_run_reference_id=str(passing_ref.id),
        historically_passed=True,
        currently_eligible=currently_eligible,
        stale_findings=findings,
    )
