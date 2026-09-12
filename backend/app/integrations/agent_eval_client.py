"""The one place this codebase knows Agent Evaluation Platform's real API shape -
isolated here per docs/repo-structure.md so the rest of the codebase depends on this
platform's own domain types, not agent-eval's response schemas.

Built directly against the real, re-inspected API (confirmed live during Phase 3 via
its running instance's /openapi.json, both locally and once deployed to Cloud Run):

    POST /runs         {agent_version_id, dataset_id, evaluator_ids[], triggered_by?,
                         timeout_seconds?} -> 201 RunSummaryResponse (SYNCHRONOUS -
                         blocks for the full run, confirmed unchanged since Phase 0/agent-eval's
                         own ADR-0005)
    GET  /runs/{id}     -> RunSummaryResponse
    GET  /runs/compare  ?run_a_id&run_b_id -> ComparisonResponse
    GET  /agents        -> [{id, name, adapter_key, versions: [{id, version_label, ...}]}]
    GET  /datasets      -> [{id, name, description, case_count}]
    GET  /evaluators    -> [{id, key, version, type, dimension, description}]
    GET  /health        -> {"status": "ok"}
    POST /agents/{agent_id}/versions {version_label, config, description?} -> 201
                         {id, version_label, description, created_at} - added Phase 8
                         (agent-eval commit cdf8cf0) specifically for Orion to register a
                         live evaluation target for a version it publishes with real
                         provenance (docs/adrs/0024-ci-publishing-machine-identity.md).

No auth on the local dev instance (confirmed unchanged); the deployed Cloud Run
instance requires a Google-signed ID token (docs/gcp-architecture.md) - id_token_provider
supplies one when set, and is omitted entirely (no Authorization header at all) when
None, matching the real local-dev reality rather than sending an empty/fake header.
"""
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx


class AgentEvalError(Exception):
    """Base class for anything that goes wrong talking to Agent Eval."""


class AgentEvalUnavailableError(AgentEvalError):
    """Connection refused/timeout/5xx - the service itself couldn't be reached or errored."""


class AgentEvalTimeoutError(AgentEvalError):
    """The synchronous POST /runs call exceeded our own client-side wait budget -
    distinct from AgentEvalUnavailableError because a timeout doesn't mean the run
    didn't happen server-side; agent-eval may still complete it after we stop waiting.
    See docs/failure-modes.md's "an evaluation run times out"."""


class AgentEvalMalformedResponseError(AgentEvalError):
    """2xx response that doesn't match the expected schema - agent-eval changed its
    response shape, or something proxying the connection mangled it."""


@dataclass(frozen=True)
class DimensionStat:
    dimension: str
    mean_score: float | None
    n: int
    n_not_applicable: int


@dataclass(frozen=True)
class CaseRunSummary:
    case_run_id: str
    case_key: str
    status: str
    latency_ms: float


@dataclass(frozen=True)
class RunSummary:
    id: str
    agent_version_id: str
    dataset_id: str
    dataset_snapshot_hash: str
    status: str
    started_at: str | None
    completed_at: str | None
    triggered_by: str | None
    dimension_stats: list[DimensionStat]
    case_runs: list[CaseRunSummary]


@dataclass(frozen=True)
class EvaluatorVersionMismatch:
    dimension: str
    evaluator_key: str
    run_a_version: str
    run_b_version: str


@dataclass(frozen=True)
class CaseComparisonEntry:
    case_key: str
    dimension: str
    run_a_score: float | None
    run_a_passed: bool | None
    run_b_score: float | None
    run_b_passed: bool | None


@dataclass(frozen=True)
class ComparisonResult:
    run_a_id: str
    run_b_id: str
    dataset_id: str
    dataset_drift_detected: bool
    evaluator_version_mismatches: list[EvaluatorVersionMismatch]
    dimension_stats: list[DimensionStat]
    regressions: list[CaseComparisonEntry]
    improvements: list[CaseComparisonEntry]


@dataclass(frozen=True)
class Evaluator:
    id: str
    key: str
    version: str
    type: str
    dimension: str


@dataclass(frozen=True)
class DatasetCase:
    id: str
    key: str
    tags: list[str]


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    case_count: int
    cases: list[DatasetCase] | None = None  # only populated by get_dataset(), not list_datasets()


class AgentEvalClient(Protocol):
    """The interface app/services/* depends on. HttpAgentEvalClient is the real
    implementation; tests use a fake implementing the same methods - see
    tests/fakes/agent_eval.py. Keeping this a Protocol (not an ABC) means the fake
    doesn't need to inherit from anything agent-eval-specific.
    """

    async def trigger_run(
        self,
        *,
        agent_version_id: str,
        dataset_id: str,
        evaluator_ids: list[str],
        triggered_by: str | None,
        timeout_seconds: float,
    ) -> RunSummary: ...

    async def get_run(self, run_id: str, tag: str | None = None) -> RunSummary: ...

    async def compare_runs(self, run_a_id: str, run_b_id: str) -> ComparisonResult: ...

    async def list_evaluators(self) -> list[Evaluator]: ...

    async def list_datasets(self) -> list[Dataset]: ...

    async def get_dataset(self, dataset_id: str) -> Dataset: ...

    async def register_agent_version(
        self, *, external_agent_id: str, version_label: str, config: dict, description: str | None = None
    ) -> str: ...


def _parse_dimension_stats(raw: list[dict]) -> list[DimensionStat]:
    return [
        DimensionStat(
            dimension=d["dimension"], mean_score=d["mean_score"], n=d["n"], n_not_applicable=d["n_not_applicable"]
        )
        for d in raw
    ]


def _parse_run_summary(raw: dict) -> RunSummary:
    try:
        return RunSummary(
            id=raw["id"],
            agent_version_id=raw["agent_version_id"],
            dataset_id=raw["dataset_id"],
            dataset_snapshot_hash=raw["dataset_snapshot_hash"],
            status=raw["status"],
            started_at=raw.get("started_at"),
            completed_at=raw.get("completed_at"),
            triggered_by=raw.get("triggered_by"),
            dimension_stats=_parse_dimension_stats(raw["dimension_stats"]),
            case_runs=[
                CaseRunSummary(
                    case_run_id=c["case_run_id"], case_key=c["case_key"], status=c["status"],
                    latency_ms=c["latency_ms"],
                )
                for c in raw["case_runs"]
            ],
        )
    except (KeyError, TypeError) as exc:
        raise AgentEvalMalformedResponseError(f"unexpected /runs response shape: {exc}") from exc


class HttpAgentEvalClient:
    """Real implementation. id_token_provider, when set, is called fresh on every
    request (Google ID tokens for a given audience are cheap to mint from cached
    credentials and expire in ~1h - not worth caching across calls here).
    """

    def __init__(
        self,
        base_url: str,
        id_token_provider: Callable[[], str] | None = None,
        connect_timeout_seconds: float = 10.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._id_token_provider = id_token_provider
        self._connect_timeout = connect_timeout_seconds

    def _headers(self) -> dict:
        if self._id_token_provider is None:
            return {}
        return {"Authorization": f"Bearer {self._id_token_provider()}"}

    async def trigger_run(
        self,
        *,
        agent_version_id: str,
        dataset_id: str,
        evaluator_ids: list[str],
        triggered_by: str | None,
        timeout_seconds: float,
    ) -> RunSummary:
        # POST /runs is synchronous (confirmed unchanged - agent-eval's own ADR-0005)
        # so the HTTP client timeout must cover the full run duration, not just
        # connection setup. docs/evaluation-and-promotion.md's Cloud Tasks wrapper
        # exists specifically so nothing upstream of this call ever holds a user
        # request open for this long.
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(timeout_seconds, connect=self._connect_timeout)
            ) as client:
                response = await client.post(
                    "/runs",
                    json={
                        "agent_version_id": agent_version_id,
                        "dataset_id": dataset_id,
                        "evaluator_ids": evaluator_ids,
                        "triggered_by": triggered_by,
                        "timeout_seconds": timeout_seconds,
                    },
                    headers=self._headers(),
                )
        except httpx.TimeoutException as exc:
            raise AgentEvalTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AgentEvalUnavailableError(str(exc)) from exc

        if response.status_code >= 500 or response.status_code in (502, 503, 504):
            raise AgentEvalUnavailableError(f"agent-eval returned {response.status_code}: {response.text}")
        if response.status_code != 201:
            raise AgentEvalMalformedResponseError(f"unexpected status {response.status_code}: {response.text}")

        try:
            body = response.json()
        except ValueError as exc:
            raise AgentEvalMalformedResponseError(f"non-JSON response: {exc}") from exc
        return _parse_run_summary(body)

    async def get_run(self, run_id: str, tag: str | None = None) -> RunSummary:
        params = {"tag": tag} if tag else None
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(30.0, connect=self._connect_timeout)
            ) as client:
                response = await client.get(f"/runs/{run_id}", params=params, headers=self._headers())
        except httpx.HTTPError as exc:
            raise AgentEvalUnavailableError(str(exc)) from exc

        if response.status_code != 200:
            raise AgentEvalMalformedResponseError(f"unexpected status {response.status_code}: {response.text}")
        return _parse_run_summary(response.json())

    async def compare_runs(self, run_a_id: str, run_b_id: str) -> ComparisonResult:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(30.0, connect=self._connect_timeout)
            ) as client:
                response = await client.get(
                    "/runs/compare", params={"run_a_id": run_a_id, "run_b_id": run_b_id}, headers=self._headers()
                )
        except httpx.HTTPError as exc:
            raise AgentEvalUnavailableError(str(exc)) from exc

        if response.status_code != 200:
            raise AgentEvalMalformedResponseError(f"unexpected status {response.status_code}: {response.text}")
        raw = response.json()
        try:
            return ComparisonResult(
                run_a_id=raw["run_a_id"],
                run_b_id=raw["run_b_id"],
                dataset_id=raw["dataset_id"],
                dataset_drift_detected=raw["dataset_drift_detected"],
                evaluator_version_mismatches=[
                    EvaluatorVersionMismatch(**m) for m in raw["evaluator_version_mismatches"]
                ],
                dimension_stats=_parse_dimension_stats(raw["dimension_stats"]),
                regressions=[CaseComparisonEntry(**r) for r in raw["regressions"]],
                improvements=[CaseComparisonEntry(**i) for i in raw["improvements"]],
            )
        except (KeyError, TypeError) as exc:
            raise AgentEvalMalformedResponseError(f"unexpected /runs/compare response shape: {exc}") from exc

    async def list_evaluators(self) -> list[Evaluator]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(15.0, connect=self._connect_timeout)
            ) as client:
                response = await client.get("/evaluators", headers=self._headers())
        except httpx.HTTPError as exc:
            raise AgentEvalUnavailableError(str(exc)) from exc

        if response.status_code != 200:
            raise AgentEvalMalformedResponseError(f"unexpected status {response.status_code}: {response.text}")
        try:
            return [Evaluator(id=e["id"], key=e["key"], version=e["version"], type=e["type"], dimension=e["dimension"]) for e in response.json()]
        except (KeyError, TypeError) as exc:
            raise AgentEvalMalformedResponseError(f"unexpected /evaluators response shape: {exc}") from exc

    async def list_datasets(self) -> list[Dataset]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(15.0, connect=self._connect_timeout)
            ) as client:
                response = await client.get("/datasets", headers=self._headers())
        except httpx.HTTPError as exc:
            raise AgentEvalUnavailableError(str(exc)) from exc

        if response.status_code != 200:
            raise AgentEvalMalformedResponseError(f"unexpected status {response.status_code}: {response.text}")
        try:
            return [Dataset(id=d["id"], name=d["name"], case_count=d["case_count"]) for d in response.json()]
        except (KeyError, TypeError) as exc:
            raise AgentEvalMalformedResponseError(f"unexpected /datasets response shape: {exc}") from exc

    async def get_dataset(self, dataset_id: str) -> Dataset:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(15.0, connect=self._connect_timeout)
            ) as client:
                response = await client.get(f"/datasets/{dataset_id}", headers=self._headers())
        except httpx.HTTPError as exc:
            raise AgentEvalUnavailableError(str(exc)) from exc

        if response.status_code != 200:
            raise AgentEvalMalformedResponseError(f"unexpected status {response.status_code}: {response.text}")
        raw = response.json()
        try:
            return Dataset(
                id=raw["id"],
                name=raw["name"],
                case_count=raw["case_count"],
                cases=[DatasetCase(id=c["id"], key=c["key"], tags=c["tags"]) for c in raw["cases"]],
            )
        except (KeyError, TypeError) as exc:
            raise AgentEvalMalformedResponseError(f"unexpected /datasets/{{id}} response shape: {exc}") from exc

    async def register_agent_version(
        self, *, external_agent_id: str, version_label: str, config: dict, description: str | None = None
    ) -> str:
        """Phase 8 (ADR-0023, ADR-0024): the one write call this client makes -
        POST /agents/{agent_id}/versions -> 201 {id, version_label, description,
        created_at}, added to agent-eval specifically for Orion to register a
        live, callable evaluation target for each version it publishes with
        real source provenance. Idempotent by version_label on agent-eval's
        side (app/services/seed.py::ensure_agent_version there) - a retry for
        the same label returns the same id, never a duplicate.
        """
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(15.0, connect=self._connect_timeout)
            ) as client:
                response = await client.post(
                    f"/agents/{external_agent_id}/versions",
                    json={"version_label": version_label, "config": config, "description": description},
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise AgentEvalUnavailableError(str(exc)) from exc

        if response.status_code != 201:
            raise AgentEvalMalformedResponseError(f"unexpected status {response.status_code}: {response.text}")
        try:
            return response.json()["id"]
        except (KeyError, TypeError) as exc:
            raise AgentEvalMalformedResponseError(f"unexpected /agents/{{id}}/versions response shape: {exc}") from exc


def default_id_token_provider(audience: str, impersonate_service_account: str | None = None) -> Callable[[], str]:
    """Real Google-signed ID token, minted from Application Default Credentials.

    Production path (impersonate_service_account=None): on a deployed Cloud Run
    service, ADC resolves to the service's own attached service account via the
    metadata server, so google.oauth2.id_token.fetch_id_token works directly with
    zero explicit credential configuration. See docs/gcp-architecture.md.

    Local-dev-only path (impersonate_service_account set - see
    settings.agent_eval_impersonate_service_account, backend/README.md): a human's
    own gcloud ADC isn't itself a service account and cannot mint an audience-scoped
    ID token directly (fetch_id_token rejects it - "Invalid account type"). Instead,
    impersonate the real agent-dev-platform-caller service account (which has
    roles/run.invoker on the deployed agent-eval-api service - see
    docs/phase-notes/phase-3.md) using short-lived impersonated credentials -
    never a downloaded, persistent service-account key file.
    """
    import google.auth
    import google.auth.transport.requests
    import google.oauth2.id_token

    if impersonate_service_account is None:

        def _get_token() -> str:
            request = google.auth.transport.requests.Request()
            return google.oauth2.id_token.fetch_id_token(request, audience)

        return _get_token

    import google.auth.impersonated_credentials

    def _get_impersonated_token() -> str:
        source_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        target_creds = google.auth.impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=impersonate_service_account,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        id_creds = google.auth.impersonated_credentials.IDTokenCredentials(
            target_creds, target_audience=audience, include_email=True
        )
        id_creds.refresh(google.auth.transport.requests.Request())
        return id_creds.token

    return _get_impersonated_token
