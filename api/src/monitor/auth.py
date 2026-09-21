import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from monitor.settings import settings


def api_access_denied() -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


def api_request_authorized(request: Request) -> bool:
    token = settings.api_access_token
    if not token:
        return False
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        return False
    return secrets.compare_digest(supplied.encode(), token.encode())
