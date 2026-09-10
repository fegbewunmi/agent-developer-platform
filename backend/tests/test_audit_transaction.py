"""Proves docs/audit-model.md's transactional guarantee: a domain write and
its audit event share one transaction, so if anything between them fails,
neither persists. Forces the failure directly (rather than waiting for a
real one) since the two writes are otherwise both simple, reliable INSERTs
that wouldn't fail independently in practice - see app/services/audit.py.
"""
import uuid

from sqlalchemy import select

import app.services.agents as agents_service
from app.models.agent import Agent


async def test_agent_creation_rolls_back_if_audit_recording_fails(db_session, org, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(agents_service, "record_audit_event", _boom)

    agent_name = f"rollback-test-{uuid.uuid4().hex[:8]}"
    try:
        await agents_service.create_agent(
            db_session, actor=org["builder"], name=agent_name, team_id=org["team_a"].id, description=None
        )
        assert False, "expected the simulated audit failure to propagate"
    except RuntimeError:
        pass

    # The session's transaction is now aborted; roll it back before querying,
    # exactly as a real request's session teardown would.
    await db_session.rollback()

    result = await db_session.execute(select(Agent).where(Agent.name == agent_name))
    assert result.scalar_one_or_none() is None, (
        "the Agent row must not exist if its audit event failed to record - "
        "domain write and audit write share one transaction"
    )
