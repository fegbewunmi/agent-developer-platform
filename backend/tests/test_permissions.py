"""Unit tests for app/services/permissions.py against the exact matrix in
docs/auth-and-approval-model.md. No DB, no HTTP - pure function tests.
"""
import uuid

import pytest

from app.models.enums import MCPClassification, Role
from app.models.identity import User
from app.services import permissions as perm

TEAM_A = uuid.uuid4()
TEAM_B = uuid.uuid4()


def _user(role: Role, team_id: uuid.UUID = TEAM_A, user_id: uuid.UUID | None = None) -> User:
    u = User(id=user_id or uuid.uuid4(), name="Test", email="t@example.com", team_id=team_id, role=role)
    return u


@pytest.mark.parametrize(
    "role,team,expected",
    [
        (Role.VIEWER, TEAM_A, False),
        (Role.BUILDER, TEAM_A, True),
        (Role.BUILDER, TEAM_B, False),  # Builder: own team only
        (Role.REVIEWER, TEAM_B, True),  # Reviewer: any team
        (Role.ADMIN, TEAM_B, True),  # Admin: any team
    ],
)
def test_can_create_agent(role, team, expected):
    user = _user(role, team_id=TEAM_A)
    assert perm.can_create_agent(user, team) is expected


@pytest.mark.parametrize(
    "role,team,classification,requires_approval,expected",
    [
        (Role.VIEWER, TEAM_A, MCPClassification.READ, False, False),
        (Role.BUILDER, TEAM_A, MCPClassification.READ, False, True),
        (Role.BUILDER, TEAM_B, MCPClassification.READ, False, False),  # own team only for read grants
        (Role.BUILDER, TEAM_A, MCPClassification.WRITE, False, False),  # write needs Reviewer/Admin
        (Role.BUILDER, TEAM_A, MCPClassification.READ, True, False),  # requires_approval needs Reviewer/Admin
        (Role.REVIEWER, TEAM_B, MCPClassification.WRITE, False, True),
        (Role.ADMIN, TEAM_B, MCPClassification.WRITE, True, True),
    ],
)
def test_can_grant_mcp_tool(role, team, classification, requires_approval, expected):
    user = _user(role, team_id=TEAM_A)
    assert perm.can_grant_mcp_tool(user, team, classification, requires_approval) is expected


def test_can_revoke_capability_grant_requires_reviewer_or_admin():
    assert perm.can_revoke_capability_grant(_user(Role.BUILDER)) is False
    assert perm.can_revoke_capability_grant(_user(Role.REVIEWER)) is True
    assert perm.can_revoke_capability_grant(_user(Role.ADMIN)) is True


def test_can_decide_promotion_rejects_self_approval_even_for_admin():
    requester_id = uuid.uuid4()
    admin_requester = _user(Role.ADMIN, user_id=requester_id)
    assert perm.can_decide_promotion(admin_requester, requester_id) is False


def test_can_decide_promotion_allows_a_different_reviewer():
    requester_id = uuid.uuid4()
    reviewer = _user(Role.REVIEWER, user_id=uuid.uuid4())
    assert perm.can_decide_promotion(reviewer, requester_id) is True


def test_can_decide_promotion_rejects_builder_even_if_not_requester():
    requester_id = uuid.uuid4()
    builder = _user(Role.BUILDER, user_id=uuid.uuid4())
    assert perm.can_decide_promotion(builder, requester_id) is False


@pytest.mark.parametrize(
    "checker,role,expected",
    [
        (perm.can_manage_evaluation_policy, Role.ADMIN, True),
        (perm.can_manage_evaluation_policy, Role.REVIEWER, False),
        (perm.can_manage_mcp_registry, Role.ADMIN, True),
        (perm.can_manage_mcp_registry, Role.BUILDER, False),
        (perm.can_manage_users_and_teams, Role.ADMIN, True),
        (perm.can_manage_users_and_teams, Role.REVIEWER, False),
        (perm.can_emergency_retire, Role.REVIEWER, True),
        (perm.can_emergency_retire, Role.BUILDER, False),
    ],
)
def test_admin_only_and_elevated_only_checks(checker, role, expected):
    assert checker(_user(role)) is expected
