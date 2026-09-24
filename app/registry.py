import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from app.models import VehicleData

logger = logging.getLogger(__name__)

# Israeli plates in this assignment are 7 or 8 digits. Customers often type dashes or spaces.
_PLATE_SEPARATORS = re.compile(r"[\s\-]")
_PLATE = re.compile(r"^\d{7,8}$")


class RegistryError(Exception):
    def __init__(self, status_code: int, error_code: str, error: str) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.error = error
        super().__init__(error)


def normalize_license_plate(raw: str) -> str:
    return _PLATE_SEPARATORS.sub("", raw.strip())


@dataclass
class VehicleRegistry:
    """Client for the insurance company's vehicle stub.

    The conversation flow depends on this shape, not on the stub's.
    The stub returns 404 as `{"detail": {"error": ...}}` and 422 as a
    Pydantic list. Both become one error object with a stable error_code.
    """

    url: str
    timeout_seconds: float
    client: Optional[httpx.AsyncClient] = None

    async def lookup(self, raw_plate: str) -> VehicleData:
        plate = normalize_license_plate(raw_plate)
        if not _PLATE.fullmatch(plate):
            raise RegistryError(
                400,
                "invalid_license_plate",
                "License plate must be 7 or 8 digits.",
            )

        try:
            response = await self._post(plate)
        except httpx.TimeoutException:
            logger.warning("vehicle registry timed out plate=%s", plate)
            raise RegistryError(
                502,
                "upstream_unavailable",
                "The vehicle registry timed out. Please try again.",
            ) from None
        except httpx.HTTPError:
            logger.warning("vehicle registry unreachable plate=%s", plate)
            raise RegistryError(
                502,
                "upstream_unavailable",
                "The vehicle registry is unreachable. Please try again.",
            ) from None

        return self._parse(plate, response)

    async def _post(self, plate: str) -> httpx.Response:
        payload = {"license_plate": plate}
        if self.client is not None:
            return await self.client.post(self.url, json=payload)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await client.post(self.url, json=payload)

    def _parse(self, plate: str, response: httpx.Response) -> VehicleData:
        if response.status_code == 200:
            return self._parse_success(response)

        if response.status_code == 404:
            logger.info("vehicle not found plate=%s", plate)
            raise RegistryError(
                404,
                "vehicle_not_found",
                "No vehicle was found for this license plate.",
            )

        if response.status_code in (400, 422):
            logger.info("upstream rejected plate=%s status=%s", plate, response.status_code)
            raise RegistryError(
                400,
                "invalid_license_plate",
                "License plate must be 7 or 8 digits.",
            )

        logger.warning("unexpected upstream status=%s plate=%s", response.status_code, plate)
        raise RegistryError(
            502,
            "upstream_unavailable",
            "The vehicle registry returned an unexpected error. Please try again.",
        )

    def _parse_success(self, response: httpx.Response) -> VehicleData:
        try:
            body = response.json()
            data = body["data"]
            if body.get("success") is not True:
                raise KeyError("success")
            return VehicleData.model_validate(data)
        except (KeyError, TypeError, ValueError):
            logger.warning("unexpected upstream success body")
            raise RegistryError(
                502,
                "upstream_unavailable",
                "The vehicle registry returned an unexpected response. Please try again.",
            ) from None
