"""Pure, testable implementation of the permission matrix in
docs/auth-and-approval-model.md. No FastAPI/HTTP dependency here on purpose -
these functions are the actual policy; API routes (Phase 2+) will call them
and translate a False/violation into a 403.

Global roles, not per-team (docs/auth-and-approval-model.md's "Why global
roles, not per-team roles"): a Builder's authority is still scoped by team
ownership via the `team_id` arguments below, even though the *role* itself
is a flat attribute on User.
"""
import uuid

from app.models.enums import MCPClassification, Role
from app.models.identity import User

_ELEVATED_ROLES = {Role.REVIEWER, Role.ADMIN}


def can_create_agent(user: User, team_id: uuid.UUID) -> bool:
    """Builder: own team only. Reviewer/Admin: any team."""
    if user.role == Role.BUILDER:
        return user.team_id == team_id
    return user.role in _ELEVATED_ROLES


def can_publish_skill_version(user: User, team_id: uuid.UUID) -> bool:
    """Same shape as can_create_agent - Skill ownership follows the same rule as Agent."""
    return can_create_agent(user, team_id)


def can_grant_mcp_tool(
    user: User, team_id: uuid.UUID, classification: MCPClassification, requires_approval: bool
) -> bool:
    """Read-capable tools: Builder (own team) or above. Write/approval-required: Reviewer/Admin only.

    docs/mcp-governance.md: "Grant authority scales with risk."
    """
    if classification == MCPClassification.WRITE or requires_approval:
        return user.role in _ELEVATED_ROLES
    if user.role == Role.BUILDER:
        return user.team_id == team_id
    return user.role in _ELEVATED_ROLES


def can_revoke_capability_grant(user: User) -> bool:
    return user.role in _ELEVATED_ROLES


def can_request_evaluation(user: User, team_id: uuid.UUID) -> bool:
    if user.role == Role.BUILDER:
        return user.team_id == team_id
    return user.role in _ELEVATED_ROLES


def can_request_promotion(user: User, team_id: uuid.UUID) -> bool:
    if user.role == Role.BUILDER:
        return user.team_id == team_id
    return user.role in _ELEVATED_ROLES


def can_decide_promotion(user: User, requested_by_user_id: uuid.UUID) -> bool:
    """Reviewer/Admin, and never the requester - docs/adrs/0009-no-self-approval.md.

    This is a defense-in-depth check: the DB trigger
    (fn_reject_self_approval, migrations/versions/0006_promotion.py) is the
    guarantee that actually can't be bypassed by application code; this
    function exists so the API can reject the attempt with a clear 403
    before ever reaching the DB.
    """
    if user.id == requested_by_user_id:
        return False
    return user.role in _ELEVATED_ROLES


def can_manage_evaluation_policy(user: User) -> bool:
    return user.role == Role.ADMIN


def can_manage_mcp_registry(user: User) -> bool:
    return user.role == Role.ADMIN


def can_manage_users_and_teams(user: User) -> bool:
    return user.role == Role.ADMIN


def can_emergency_retire(user: User) -> bool:
    return user.role in _ELEVATED_ROLES
