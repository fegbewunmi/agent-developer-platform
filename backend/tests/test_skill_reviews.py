"""Phase 9 (ADR-0025): SkillVersionLifecycle + SkillReviewRequest/Decision -
a SkillVersion's own "recommended" concept, deliberately not built on
PromotionRequest/PromotionDecision. Covers the same guarantees the Agent
side already has: no self-approval (DB trigger), one RECOMMENDED version per
Skill (partial unique index + advisory lock), and immutable decisions.
"""
import pytest

from app.services import skill_reviews as skill_reviews_service
from app.services import skills as skills_service
from app.services.errors import ConflictError, PermissionDeniedError


async def _publish(db_session, org, version="1.0", owner_team=None):
    skill = await skills_service.create_skill(
        db_session, actor=org["builder"], name=f"skill-{version}-{id(version)}", owner_team_id=owner_team or org["team_a"].id,
        description=None,
    )
    sv = await skills_service.create_skill_version(
        db_session, actor=org["builder"], skill_id=skill.id, version=version, purpose="test",
        input_contract=None, output_contract=None, implementation_ref=None, compatible_frameworks=["langgraph"],
    )
    return skill, sv


async def test_new_skill_version_starts_published_not_recommended(db_session, org):
    _skill, sv = await _publish(db_session, org)
    lifecycle = await skills_service.get_skill_version_lifecycle(db_session, sv.id)
    assert lifecycle.stage.value == "published"


async def test_review_request_then_approve_makes_it_recommended(db_session, org):
    _skill, sv = await _publish(db_session, org)
    request = await skill_reviews_service.request_skill_review(db_session, actor=org["builder"], skill_version_id=sv.id)
    assert request.status.value == "pending"

    decision = await skill_reviews_service.approve_skill_review(
        db_session, actor=org["reviewer"], skill_review_request_id=request.id
    )
    assert decision.decision.value == "approve"
    lifecycle = await skills_service.get_skill_version_lifecycle(db_session, sv.id)
    assert lifecycle.stage.value == "recommended"


async def test_reviewer_cannot_approve_own_request(db_session, org):
    _skill, sv = await _publish(db_session, org)
    request = await skill_reviews_service.request_skill_review(db_session, actor=org["reviewer"], skill_version_id=sv.id)
    with pytest.raises(PermissionDeniedError):
        await skill_reviews_service.approve_skill_review(
            db_session, actor=org["reviewer"], skill_review_request_id=request.id
        )


async def test_self_approval_blocked_at_db_level_even_if_app_check_were_bypassed(db_session, org):
    """Defense-in-depth proof, mirroring tests/test_promotions.py's
    equivalent - the trigger, not just can_decide_skill_review, is what
    actually can't be bypassed."""
    from app.models.skill_review import SkillReviewDecision

    _skill, sv = await _publish(db_session, org)
    request = await skill_reviews_service.request_skill_review(db_session, actor=org["reviewer"], skill_version_id=sv.id)
    import uuid

    from app.models.enums import SkillReviewDecisionType

    db_session.add(
        SkillReviewDecision(
            id=uuid.uuid4(),
            skill_review_request_id=request.id,
            decision=SkillReviewDecisionType.APPROVE,
            decided_by=org["reviewer"].id,
        )
    )
    with pytest.raises(Exception, match="self-approval"):
        await db_session.flush()


async def test_only_one_recommended_version_per_skill(db_session, org):
    skill = await skills_service.create_skill(
        db_session, actor=org["builder"], name="rec-supersede", owner_team_id=org["team_a"].id, description=None
    )
    v1 = await skills_service.create_skill_version(
        db_session, actor=org["builder"], skill_id=skill.id, version="1.0", purpose="p",
        input_contract=None, output_contract=None, implementation_ref=None, compatible_frameworks=[],
    )
    v2 = await skills_service.create_skill_version(
        db_session, actor=org["builder"], skill_id=skill.id, version="2.0", purpose="p",
        input_contract=None, output_contract=None, implementation_ref=None, compatible_frameworks=[],
    )

    r1 = await skill_reviews_service.request_skill_review(db_session, actor=org["builder"], skill_version_id=v1.id)
    await skill_reviews_service.approve_skill_review(db_session, actor=org["reviewer"], skill_review_request_id=r1.id)

    r2 = await skill_reviews_service.request_skill_review(db_session, actor=org["builder"], skill_version_id=v2.id)
    await skill_reviews_service.approve_skill_review(db_session, actor=org["reviewer"], skill_review_request_id=r2.id)

    lifecycle_v1 = await skills_service.get_skill_version_lifecycle(db_session, v1.id)
    lifecycle_v2 = await skills_service.get_skill_version_lifecycle(db_session, v2.id)
    assert lifecycle_v1.stage.value == "deprecated"
    assert lifecycle_v2.stage.value == "recommended"


async def test_duplicate_pending_review_request_is_conflict(db_session, org):
    _skill, sv = await _publish(db_session, org)
    await skill_reviews_service.request_skill_review(db_session, actor=org["builder"], skill_version_id=sv.id)
    with pytest.raises(ConflictError):
        await skill_reviews_service.request_skill_review(db_session, actor=org["builder"], skill_version_id=sv.id)


async def test_reject_leaves_version_published_and_reviewable_again(db_session, org):
    _skill, sv = await _publish(db_session, org)
    request = await skill_reviews_service.request_skill_review(db_session, actor=org["builder"], skill_version_id=sv.id)
    decision = await skill_reviews_service.reject_skill_review(
        db_session, actor=org["reviewer"], skill_review_request_id=request.id
    )
    assert decision.decision.value == "reject"
    lifecycle = await skills_service.get_skill_version_lifecycle(db_session, sv.id)
    assert lifecycle.stage.value == "published"

    # No longer pending, so a fresh request is allowed.
    second_request = await skill_reviews_service.request_skill_review(
        db_session, actor=org["builder"], skill_version_id=sv.id
    )
    assert second_request.status.value == "pending"


# --- dependency/impact analysis ------------------------------------------


async def test_skill_impact_current_vs_historical(db_session, org):
    """The core Phase 9 story: two agents on the old SkillVersion, a newer
    one exists with no consumers yet, current_impact shows exactly the
    agents still on the old version (their most recent, non-deprecated
    AgentVersion), historical_consumers is the unfiltered record."""
    from app.services import agents as agents_service

    skill = await skills_service.create_skill(
        db_session, actor=org["builder"], name="deployment-analysis-test", owner_team_id=org["team_a"].id, description=None
    )
    sv_old = await skills_service.create_skill_version(
        db_session, actor=org["builder"], skill_id=skill.id, version="1.3", purpose="p",
        input_contract=None, output_contract=None, implementation_ref=None, compatible_frameworks=["langgraph"],
    )
    sv_new = await skills_service.create_skill_version(
        db_session, actor=org["builder"], skill_id=skill.id, version="1.4", purpose="p",
        input_contract=None, output_contract=None, implementation_ref=None, compatible_frameworks=["langgraph"],
    )

    manifest = {
        "agent": {"name": "consumer-a", "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": ["deployment-analysis-test@1.3"],
        "mcp": {},
        "evaluation": {"policy": "irrelevant"},
    }
    agent_a = await agents_service.create_agent(
        db_session, actor=org["builder"], name="consumer-a", team_id=org["team_a"].id, description=None
    )
    av_a = await agents_service.create_agent_version(db_session, actor=org["builder"], agent_id=agent_a.id, manifest=manifest)

    agent_b = await agents_service.create_agent(
        db_session, actor=org["builder"], name="consumer-b", team_id=org["team_a"].id, description=None
    )
    manifest_b = {**manifest, "agent": {**manifest["agent"], "name": "consumer-b"}}
    av_b = await agents_service.create_agent_version(db_session, actor=org["builder"], agent_id=agent_b.id, manifest=manifest_b)

    impact = await skills_service.get_skill_impact(db_session, skill.id)
    assert impact["latest_version"]["version"] == "1.4"
    current_agent_ids = {c["agent_id"] for c in impact["current_impact"]}
    assert current_agent_ids == {str(agent_a.id), str(agent_b.id)}
    assert len(impact["historical_consumers"]) == 2
