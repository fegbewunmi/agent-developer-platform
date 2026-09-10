"""Domain-level exceptions. Service functions raise these, never
HTTPException - keeps the service layer HTTP-agnostic (same reasoning as
app/services/permissions.py). API routers catch these and translate to the
appropriate status code.
"""


class DomainError(Exception):
    """Base class; never raised directly."""


class NotFoundError(DomainError):
    """Referenced entity does not exist."""


class ConflictError(DomainError):
    """A uniqueness or state constraint would be violated (duplicate version
    label, duplicate SkillVersion, duplicate active grant, etc.)."""


class ValidationError(DomainError):
    """The request is well-formed but references something invalid (an
    unknown skill/tool in a manifest, an incompatible framework, etc.)."""


class PermissionDeniedError(DomainError):
    """The authenticated user's role/team does not permit this action."""
