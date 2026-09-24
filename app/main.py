import logging
import os
from typing import Union

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from app.auth import VEHICLE_READ, AuthError, Caller, require_scope
from app.models import ErrorResponse, HealthResponse, SuccessResponse, VehicleRequest
from app.registry import RegistryError, VehicleRegistry

logging.basicConfig(level=logging.INFO)

DEFAULT_UPSTREAM_URL = (
    "https://insurance-webhook-945894769129.us-central1.run.app/vehicle-info"
)


def build_registry() -> VehicleRegistry:
    timeout = float(os.environ.get("UPSTREAM_TIMEOUT_SECONDS", "5"))
    return VehicleRegistry(
        url=os.environ.get("UPSTREAM_VEHICLE_URL", DEFAULT_UPSTREAM_URL),
        timeout_seconds=timeout,
    )


app = FastAPI(
    title="Vehicle Info Wrapper",
    version="1.0.0",
    description=(
        "Stable vehicle lookup for the car insurance onboarding flow. "
        "Wraps the insurance stub and returns one error shape the agent can branch on."
    ),
)
app.state.registry = build_registry()


def get_registry() -> VehicleRegistry:
    return app.state.registry


@app.exception_handler(AuthError)
async def auth_error(_request, exc: AuthError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error_code=exc.error_code, error=exc.error).model_dump(),
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post(
    "/vehicle-info",
    response_model=SuccessResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def vehicle_info(
    body: VehicleRequest,
    registry: VehicleRegistry = Depends(get_registry),
    _: Caller = Depends(require_scope(VEHICLE_READ)),
) -> Union[SuccessResponse, JSONResponse]:
    try:
        data = await registry.lookup(body.license_plate)
    except RegistryError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(error_code=exc.error_code, error=exc.error).model_dump(),
        )
    return SuccessResponse(data=data)
