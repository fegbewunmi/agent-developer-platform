from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import (
    agents,
    audit,
    capability_grants,
    dashboard,
    demo,
    evaluation_policies,
    evaluations,
    health,
    mcp,
    me,
    promotions,
    skills,
    tasks,
    teams,
)
from app.config import settings
from app.observability import configure_logging
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError

configure_logging(structured=settings.environment != "development")

app = FastAPI(title="Orion Agent Developer Platform API", version="0.1.0")


@app.exception_handler(NotFoundError)
async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def _conflict(_: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def _validation(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(PermissionDeniedError)
async def _permission_denied(_: Request, exc: PermissionDeniedError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


app.include_router(health.router)
app.include_router(me.router)
app.include_router(teams.router)
app.include_router(agents.router)
app.include_router(agents.versions_router)
app.include_router(skills.router)
app.include_router(skills.versions_router)
app.include_router(mcp.router)
app.include_router(mcp.tools_router)
app.include_router(capability_grants.router)
app.include_router(capability_grants.revoke_router)
app.include_router(evaluation_policies.router)
app.include_router(evaluations.router)
app.include_router(promotions.router)
app.include_router(audit.router)
app.include_router(dashboard.router)
app.include_router(tasks.router)
app.include_router(demo.router)

if settings.auth_jwks_file:
    # Dev-only browser login - see app/api/dev_auth.py's module docstring.
    # Never registered when the app is configured for real Identity
    # Platform auth (no auth_jwks_file set), i.e. never in production.
    from app.api import dev_auth

    app.include_router(dev_auth.router)
