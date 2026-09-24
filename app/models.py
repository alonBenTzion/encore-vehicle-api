from typing import Literal

from pydantic import BaseModel, Field


class VehicleRequest(BaseModel):
    license_plate: str = Field(
        description="License plate as the customer typed it. Spaces and dashes are removed before lookup."
    )


class VehicleData(BaseModel):
    license_plate: str
    manufacturer: str
    model: str
    year: int
    color: str


class SuccessResponse(BaseModel):
    success: Literal[True] = True
    data: VehicleData


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error_code: Literal[
        "invalid_license_plate",
        "vehicle_not_found",
        "upstream_unavailable",
        "unauthorized",
        "forbidden",
    ]
    error: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
