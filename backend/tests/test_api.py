import uuid

from app.models.agent import Agent
from app.models.enums import Role


async def _authed_headers(seed_team_and_user, sign_token, role=Role.VIEWER):
    team, user = await seed_team_and_user(role=role, email="viewer@orioncommerce.example")
    token = sign_token(email="viewer@orioncommerce.example")
    return team, user, {"Authorization": f"Bearer {token}"}


async def test_list_teams_requires_auth(client):
    resp = await client.get("/v1/teams")
    assert resp.status_code == 401


async def test_list_teams_returns_seeded_team(client, seed_team_and_user, sign_token):
    team, _, headers = await _authed_headers(seed_team_and_user, sign_token)
    resp = await client.get("/v1/teams", headers=headers)
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert team.name in names


async def test_list_agents_labels_representative_data(client, seed_team_and_user, sign_token, db_session):
    team, _, headers = await _authed_headers(seed_team_and_user, sign_token)

    real_agent = Agent(id=uuid.uuid4(), name="incident-investigator", team_id=team.id, is_representative_data=False)
    seeded_agent = Agent(
        id=uuid.uuid4(), name="customer-support-agent", team_id=team.id, is_representative_data=True
    )
    db_session.add_all([real_agent, seeded_agent])
    await db_session.commit()

    resp = await client.get("/v1/agents", headers=headers)
    assert resp.status_code == 200
    by_name = {a["name"]: a for a in resp.json()}
    assert by_name["incident-investigator"]["is_representative_data"] is False
    assert by_name["customer-support-agent"]["is_representative_data"] is True
