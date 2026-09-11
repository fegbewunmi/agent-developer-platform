"""Phase 6: real application-level verification of Cloud Tasks' OIDC push
token, closing a gap the Phase 3 docstring assumed away.

Original assumption (app/api/tasks.py, Phase 3): "Cloud Run's own IAM
authenticates the push request's OIDC token before it ever reaches this
handler." That's only true if the whole Cloud Run service is deployed
`--no-allow-unauthenticated` - but this service also serves the main API to
the frontend's Server Components, which authenticate with the platform's own
user JWTs in the same `Authorization` header Cloud Run's ingress IAM check
would consume. Cloud Run IAM is service-wide, not per-path, so it cannot
protect only `/internal/tasks/*` while leaving the rest of the service
reachable - the two auth schemes collide on one header if IAM is enabled.

The resolution (documented for real in docs/gcp-architecture.md and
docs/adrs/0021-cloud-run-ingress-and-tasks-receiver-auth.md): the service is
deployed publicly reachable, and this one path verifies the OIDC token
itself, application-side, using the same real Google-signed-JWT machinery
google-auth provides for exactly this purpose - genuinely checking the
token's signature (against Google's real certs), audience, and the caller's
service-account identity, not merely trusting the header is present.
"""
import uuid

from fastapi import Depends, HTTPException, Request, status
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token

from app.config import settings

_google_request = google_auth_requests.Request()


async def verify_cloud_tasks_push(request: Request) -> None:
    if settings.job_dispatch_mode != "cloud_tasks":
        # Local/test dev mode - LocalSyncDispatcher never calls this endpoint
        # over HTTP at all, so this path is only reachable when Cloud Tasks
        # is the real configured dispatcher. Skipping verification outside
        # that mode keeps `uvicorn --reload` dev usable without a real OIDC
        # token, without weakening anything the deployed path relies on.
        return

    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = auth_header[len("bearer "):]

    try:
        claims = google_id_token.verify_oauth2_token(
            token, _google_request, audience=settings.cloud_tasks_target_base_url
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid push token: {exc}") from None

    expected_email = settings.cloud_tasks_target_service_account_email
    if expected_email and claims.get("email") != expected_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"push token identity {claims.get('email')!r} is not the expected Cloud Tasks invoker",
        )


CloudTasksAuth = Depends(verify_cloud_tasks_push)
