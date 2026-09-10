from fastapi import FastAPI

from app.api import agents, health, me, teams

app = FastAPI(title="Orion Agent Developer Platform API", version="0.1.0")

app.include_router(health.router)
app.include_router(me.router)
app.include_router(teams.router)
app.include_router(agents.router)
