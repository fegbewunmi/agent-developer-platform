"""app/auth/cloud_tasks.py - real application-level verification of Cloud
Tasks' OIDC push token, the Phase 6 fix for the receiver-authorization gap
Phase 3's docstring assumed Cloud Run IAM would cover (see that module's
docstring for why it can't, once the same service also serves the frontend's
user-JWT-authenticated API).
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth.cloud_tasks import verify_cloud_tasks_push
from app.config import settings


def _request(headers: dict[str, str]) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {"type": "http", "headers": raw_headers}
    return Request(scope)


async def test_skips_verification_outside_cloud_tasks_mode(monkeypatch):
    monkeypatch.setattr(settings, "job_dispatch_mode", "local")
    await verify_cloud_tasks_push(_request({}))  # no error, no token needed


async def test_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(settings, "job_dispatch_mode", "cloud_tasks")
    with pytest.raises(HTTPException) as exc:
        await verify_cloud_tasks_push(_request({}))
    assert exc.value.status_code == 401


async def test_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(settings, "job_dispatch_mode", "cloud_tasks")
    with patch("app.auth.cloud_tasks.google_id_token.verify_oauth2_token", side_effect=ValueError("bad signature")):
        with pytest.raises(HTTPException) as exc:
            await verify_cloud_tasks_push(_request({"authorization": "Bearer not-a-real-token"}))
    assert exc.value.status_code == 401


async def test_rejects_wrong_service_account_identity(monkeypatch):
    monkeypatch.setattr(settings, "job_dispatch_mode", "cloud_tasks")
    monkeypatch.setattr(settings, "cloud_tasks_target_service_account_email", "expected@example.iam.gserviceaccount.com")
    with patch(
        "app.auth.cloud_tasks.google_id_token.verify_oauth2_token",
        return_value={"email": "someone-else@example.iam.gserviceaccount.com"},
    ):
        with pytest.raises(HTTPException) as exc:
            await verify_cloud_tasks_push(_request({"authorization": "Bearer real-looking-token"}))
    assert exc.value.status_code == 403


async def test_accepts_valid_token_from_expected_identity(monkeypatch):
    monkeypatch.setattr(settings, "job_dispatch_mode", "cloud_tasks")
    monkeypatch.setattr(settings, "cloud_tasks_target_service_account_email", "expected@example.iam.gserviceaccount.com")
    with patch(
        "app.auth.cloud_tasks.google_id_token.verify_oauth2_token",
        return_value={"email": "expected@example.iam.gserviceaccount.com"},
    ):
        await verify_cloud_tasks_push(_request({"authorization": "Bearer real-looking-token"}))  # no error
