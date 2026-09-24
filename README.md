# Vehicle info wrapper

Small API for the Encore car-insurance onboarding assignment. The conversation flow calls this service. This service calls the insurance stub and returns one shape the flow can branch on.

## Why this exists

The stub at `insurance-webhook-.../vehicle-info` is the source of vehicle data, but its errors are not stable:

- `404` body is `{"detail": {"success": false, "error": "<Hebrew>"}}`
- `422` body is a Pydantic `detail` list, also in Hebrew
- a live success returns Hebrew make/model/color, while the assignment PDF shows English

The flow should branch on a code, not on Hebrew text or on which error shape came back.

## Contract

`POST /vehicle-info` with header `Authorization: Bearer <API_TOKEN>`

```json
{ "license_plate": "123-45-678" }
```

Spaces and dashes are removed. The plate must then be 7 or 8 digits. An invalid plate is rejected here and the stub is not called.

Success `200`:

```json
{
  "success": true,
  "data": {
    "license_plate": "12345678",
    "manufacturer": "טויוטה",
    "model": "קורולה",
    "year": 2020,
    "color": "לבן"
  }
}
```

Vehicle fields are passed through unchanged. This service does not translate them.

| Status | `error_code` | When |
| --- | --- | --- |
| 400 | `invalid_license_plate` | Not 7 or 8 digits, or the stub rejects the plate |
| 404 | `vehicle_not_found` | Stub has no vehicle for that plate |
| 401 | `unauthorized` | The bearer token is missing or wrong. The stub is not called. |
| 403 | `forbidden` | The token is valid, and this client does not have the `vehicle:read` scope. The stub is not called. |
| 502 | `upstream_unavailable` | Timeout, network error, 5xx, or a success body we cannot parse |
| 503 | `unauthorized` | `API_TOKEN` is not set on the server, so lookup is refused. |

`GET /health` returns `{"status":"ok"}` with no token and no scope. It does not call the stub, so a stub outage does not fail the deploy health check.

The insurance stub has no auth. This service is the boundary Encore calls. The bearer token answers who is calling. The route then checks the `vehicle:read` scope, which answers whether that caller may use this endpoint. `API_SCOPES` lists the scopes for that client, comma-separated. A second endpoint would declare its own scope and leave this one untouched. A wrong token is an integration failure: the customer cannot fix it by typing the plate again. A missing scope is the same kind of failure, with a different status, so an operator can tell a bad secret from a client that was not granted this action.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pytest
```

`API_TOKEN` is required for `/vehicle-info`. `API_SCOPES` must include `vehicle:read`. `API_CLIENT_NAME` defaults to `encore-flow`. `UPSTREAM_VEHICLE_URL` and `UPSTREAM_TIMEOUT_SECONDS` (default 5) override the stub location and timeout.

## Deploy

Render web service from `render.yaml`. The process binds `0.0.0.0:$PORT`. Health check path is `/health`.
