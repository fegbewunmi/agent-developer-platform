"""Phase 8: real application-level verification of a CI publisher's OIDC
token - the machine identity that publishes a real AgentVersion with source
provenance on behalf of an integrated agent's repository (starting with
`ai-operations`/incident-investigator). Same verification mechanism as
app/auth/cloud_tasks.py (a real Google-signed ID token, checked against
Google's own certs, audience, and expected service-account identity) -
deliberately not refactored to share code with that module, to avoid any
risk to the already-proven Cloud Tasks/Scheduler push path; this is a
distinct, smaller, independently-scoped machine identity - see
docs/adrs/0024-ci-publishing-machine-identity.md.

Kept structurally separate from human RBAC throughout: a CI caller is never
a `User` row, never holds a `Role`, and can only ever reach the one
CI-publish endpoint this protects - see app/api/ci_publish.py.
"""
from fastapi import Depends, HTTPException, Request, status
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token

from app.config import settings

_google_request = google_auth_requests.Request()


async def verify_ci_publisher(request: Request) -> None:
    if not settings.ci_publisher_service_account_email:
        # Not configured in this environment (local dev/test) - the
        # CI-publish endpoint is real but has no legitimate caller to expect
        # yet, matching app/auth/cloud_tasks.py's same-shaped dev/test
        # bypass. Deployed environments always set this.
        return

    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = auth_header[len("bearer "):]

    try:
        claims = google_id_token.verify_oauth2_token(
            token, _google_request, audience=settings.ci_publisher_audience or settings.cloud_tasks_target_base_url
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid publisher token: {exc}") from None

    if claims.get("email") != settings.ci_publisher_service_account_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"publisher token identity {claims.get('email')!r} is not the expected CI publisher",
        )


CIPublisherAuth = Depends(verify_ci_publisher)
