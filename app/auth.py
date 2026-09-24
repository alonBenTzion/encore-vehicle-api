import os
import secrets
from dataclasses import dataclass
from typing import FrozenSet, Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

# One permission. A second endpoint would declare its own scope.
VEHICLE_READ = "vehicle:read"


class AuthError(Exception):
    def __init__(self, status_code: int, error_code: str, error: str) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.error = error
        super().__init__(error)


@dataclass(frozen=True)
class Caller:
    name: str
    scopes: FrozenSet[str]


def authenticate(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Caller:
    """Who is calling.

    A missing server token fails closed. A missing or wrong bearer token is 401.
    Scopes are not checked here.
    """
    expected = os.environ.get("API_TOKEN", "").strip()
    if not expected:
        raise AuthError(503, "unauthorized", "Vehicle lookup is not configured.")

    provided = ""
    if credentials is not None and credentials.scheme.lower() == "bearer":
        provided = credentials.credentials

    if len(provided) != len(expected) or not secrets.compare_digest(provided, expected):
        raise AuthError(401, "unauthorized", "Missing or invalid API token.")

    name = os.environ.get("API_CLIENT_NAME", "encore-flow").strip() or "encore-flow"
    scopes = frozenset(
        part.strip() for part in os.environ.get("API_SCOPES", "").split(",") if part.strip()
    )
    return Caller(name, scopes)


def require_scope(scope: str):
    """Whether this caller may perform this action.

    The route names the scope. A valid token with the wrong scope is 403,
    which is a different failure from a token the server does not recognize.
    """

    def allow(caller: Caller = Depends(authenticate)) -> Caller:
        if scope not in caller.scopes:
            raise AuthError(403, "forbidden", "This client is not allowed to look up vehicles.")
        return caller

    return allow
