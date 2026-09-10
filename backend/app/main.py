from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import agents, capability_grants, evaluation_policies, evaluations, health, mcp, me, skills, tasks, teams
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError

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
app.include_router(tasks.router)
