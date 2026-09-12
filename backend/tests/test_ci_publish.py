"""Phase 8 (ADR-0023, ADR-0024): real source provenance for CI-integrated
agents. Covers app/auth/ci_publisher.py's OIDC verification (same shape as
the already-proven app/auth/cloud_tasks.py), the manual-creation lockout for
an Agent with requires_ci_provenance=True, and idempotent publication by
commit SHA.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth.ci_publisher import verify_ci_publisher
from app.config import settings
from app.dependencies import get_agent_eval_client
from app.main import app
from app.services import agents as agents_service
from app.services.errors import PermissionDeniedError, ValidationError
from tests.fakes.agent_eval import FakeAgentEvalClient


def _request(headers: dict[str, str]) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {"type": "http", "headers": raw_headers}
    return Request(scope)


# --- auth --------------------------------------------------------------------


async def test_skips_verification_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "ci_publisher_service_account_email", None)
    await verify_ci_publisher(_request({}))  # no error, no token needed


async def test_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(settings, "ci_publisher_service_account_email", "ci@example.iam.gserviceaccount.com")
    with pytest.raises(HTTPException) as exc:
        await verify_ci_publisher(_request({}))
    assert exc.value.status_code == 401


async def test_rejects_wrong_identity(monkeypatch):
    monkeypatch.setattr(settings, "ci_publisher_service_account_email", "ci@example.iam.gserviceaccount.com")
    with patch(
        "app.auth.ci_publisher.google_id_token.verify_oauth2_token",
        return_value={"email": "someone-else@example.iam.gserviceaccount.com"},
    ):
        with pytest.raises(HTTPException) as exc:
            await verify_ci_publisher(_request({"authorization": "Bearer real-looking-token"}))
    assert exc.value.status_code == 403


async def test_accepts_valid_token_from_expected_identity(monkeypatch):
    monkeypatch.setattr(settings, "ci_publisher_service_account_email", "ci@example.iam.gserviceaccount.com")
    with patch(
        "app.auth.ci_publisher.google_id_token.verify_oauth2_token",
        return_value={"email": "ci@example.iam.gserviceaccount.com"},
    ):
        await verify_ci_publisher(_request({"authorization": "Bearer real-looking-token"}))  # no error


# --- service-layer containment/idempotency ------------------------------------

def _manifest(version: str = "1.0.0") -> dict:
    # No "name" key - resolve_manifest only checks it against the target
    # Agent's real name when present, and these tests target several
    # differently-named agents with the same manifest shape.
    return {
        "agent": {"version": version, "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [],
        "mcp": {},
        "evaluation": {"policy": "ci-agent"},
    }


_MANIFEST = _manifest()


async def test_manual_creation_rejected_for_ci_integrated_agent(db_session, org):
    agent = await agents_service.create_agent(
        db_session, actor=org["admin"], name="ci-agent", team_id=org["team_a"].id, description=None,
        requires_ci_provenance=True,
    )
    with pytest.raises(PermissionDeniedError):
        await agents_service.create_agent_version(db_session, actor=org["admin"], agent_id=agent.id, manifest=_MANIFEST)


async def test_via_ci_without_provenance_is_rejected(db_session, org):
    agent = await agents_service.create_agent(
        db_session, actor=org["admin"], name="ci-agent-2", team_id=org["team_a"].id, description=None,
        requires_ci_provenance=True,
    )
    with pytest.raises(ValidationError):
        await agents_service.create_agent_version(
            db_session, actor=org["admin"], agent_id=agent.id, manifest=_MANIFEST, via_ci=True, provenance=None
        )


async def test_via_ci_with_provenance_succeeds_and_is_stored(db_session, org):
    agent = await agents_service.create_agent(
        db_session, actor=org["admin"], name="ci-agent-3", team_id=org["team_a"].id, description=None,
        requires_ci_provenance=True,
    )
    version = await agents_service.create_agent_version(
        db_session,
        actor=org["admin"],
        agent_id=agent.id,
        manifest=_MANIFEST,
        via_ci=True,
        provenance={
            "git_repo": "org/repo",
            "git_commit_sha": "abc123",
            "git_ref": "main",
            "agent_eval_agent_version_id": "fake-agent-eval-version-1.0.0",
        },
    )
    assert version.provenance["git_repo"] == "org/repo"
    assert version.provenance["agent_eval_agent_version_id"] == "fake-agent-eval-version-1.0.0"
    assert version.provenance["git_commit_sha"] == "abc123"
    assert version.provenance["publisher"] == "ci"
    assert version.provenance["published_at"] is not None


async def test_publishing_same_commit_twice_is_idempotent(db_session, org):
    agent = await agents_service.create_agent(
        db_session, actor=org["admin"], name="ci-agent-4", team_id=org["team_a"].id, description=None,
        requires_ci_provenance=True,
    )
    provenance = {"git_repo": "org/repo", "git_commit_sha": "same-sha", "git_ref": "main"}
    first = await agents_service.create_agent_version(
        db_session, actor=org["admin"], agent_id=agent.id, manifest=_MANIFEST, via_ci=True, provenance=provenance
    )
    second_manifest = {**_MANIFEST, "agent": {**_MANIFEST["agent"], "version": "1.0.1"}}
    second = await agents_service.create_agent_version(
        db_session, actor=org["admin"], agent_id=agent.id, manifest=second_manifest, via_ci=True, provenance=provenance
    )
    assert first.id == second.id


async def test_manual_creation_still_works_for_non_ci_agent(db_session, org):
    agent = await agents_service.create_agent(
        db_session, actor=org["builder"], name="regular-agent", team_id=org["team_a"].id, description=None
    )
    version = await agents_service.create_agent_version(
        db_session, actor=org["builder"], agent_id=agent.id, manifest=_MANIFEST
    )
    assert version.provenance is None


# --- full HTTP route, including the agent-eval registration side-effect -------


async def test_publish_route_registers_a_live_agent_eval_target(monkeypatch, client, org):
    monkeypatch.setattr(settings, "ci_publish_agent_eval_agent_id", "fake-external-agent-id")
    monkeypatch.setattr(settings, "ci_publish_target_base_url", "https://real-deployment.example")
    fake = FakeAgentEvalClient()
    app.dependency_overrides[get_agent_eval_client] = lambda: fake
    try:
        resp = await client.post(
            "/internal/ci/agents/00000000-0000-0000-0000-000000000000/versions",
            json={"manifest": _manifest("2.0.0"), "provenance": {"git_repo": "org/repo", "git_commit_sha": "sha-xyz"}},
        )
        # 404 (Agent doesn't exist) is expected here - the point of this test
        # is that register_agent_version is called BEFORE that lookup fails,
        # proving the wiring, not exercising a full happy path (already
        # covered end-to-end live against the real deployed system).
        assert resp.status_code == 404
        assert fake.register_agent_version_calls == [
            {
                "external_agent_id": "fake-external-agent-id",
                "version_label": "2.0.0",
                "config": {"base_url": "https://real-deployment.example"},
            }
        ]
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)


async def test_publish_route_skips_agent_eval_registration_when_unconfigured(monkeypatch, client, org):
    monkeypatch.setattr(settings, "ci_publish_agent_eval_agent_id", None)
    fake = FakeAgentEvalClient()
    app.dependency_overrides[get_agent_eval_client] = lambda: fake
    try:
        await client.post(
            "/internal/ci/agents/00000000-0000-0000-0000-000000000000/versions",
            json={"manifest": _manifest("2.0.1"), "provenance": {"git_repo": "org/repo", "git_commit_sha": "sha-abc"}},
        )
        assert fake.register_agent_version_calls == []
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
