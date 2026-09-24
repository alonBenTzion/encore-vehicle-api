import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_registry
from app.registry import VehicleRegistry

UPSTREAM = "https://registry.test/vehicle-info"
TOYOTA = {
    "success": True,
    "data": {
        "license_plate": "12345678",
        "manufacturer": "טויוטה",
        "model": "קורולה",
        "year": 2020,
        "color": "לבן",
    },
}


def registry_with(handler) -> VehicleRegistry:
    transport = httpx.MockTransport(handler)
    return VehicleRegistry(
        url=UPSTREAM,
        timeout_seconds=1,
        client=httpx.AsyncClient(transport=transport),
    )


API_TOKEN = "test-token"


@pytest.fixture(autouse=True)
def set_api_token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", API_TOKEN)
    monkeypatch.setenv("API_SCOPES", "vehicle:read")


@pytest.fixture
def client():
    raw = TestClient(app)

    class _Client:
        def get(self, *args, **kwargs):
            return raw.get(*args, **kwargs)

        def post(self, url, **kwargs):
            headers = {"Authorization": f"Bearer {API_TOKEN}"}
            headers.update(kwargs.pop("headers", {}))
            return raw.post(url, headers=headers, **kwargs)

    return _Client()


@pytest.fixture
def override_registry():
    originals = app.dependency_overrides.copy()

    def use(handler):
        registry = registry_with(handler)
        app.dependency_overrides[get_registry] = lambda: registry
        return registry

    yield use
    app.dependency_overrides = originals


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_success_passes_upstream_fields_through(client, override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == UPSTREAM
        assert request.content == b'{"license_plate":"12345678"}'
        return httpx.Response(200, json=TOYOTA)

    override_registry(handler)
    response = client.post("/vehicle-info", json={"license_plate": "12345678"})

    assert response.status_code == 200
    assert response.json() == TOYOTA


def test_dashes_and_spaces_are_stripped_before_lookup(client, override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.content == b'{"license_plate":"12345678"}'
        return httpx.Response(200, json=TOYOTA)

    override_registry(handler)
    response = client.post("/vehicle-info", json={"license_plate": " 123-45-678 "})

    assert response.status_code == 200
    assert response.json()["data"]["manufacturer"] == "טויוטה"


def test_invalid_plate_does_not_call_upstream(client, override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream should not be called")

    override_registry(handler)
    response = client.post("/vehicle-info", json={"license_plate": "12AB"})

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_license_plate"


def test_vehicle_not_found(client, override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"detail": {"success": False, "error": "רכב עם מספר 00000000 לא נמצא במאגר"}},
        )

    override_registry(handler)
    response = client.post("/vehicle-info", json={"license_plate": "00000000"})

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "vehicle_not_found"
    assert "רכב" not in body["error"]


def test_upstream_validation_error_is_normalized(client, override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"detail": [{"msg": "Value error, מספר רכב חייב להיות 7 או 8 ספרות"}]},
        )

    override_registry(handler)
    response = client.post("/vehicle-info", json={"license_plate": "1234567"})

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_license_plate"


def test_timeout_becomes_upstream_unavailable(client, override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    override_registry(handler)
    response = client.post("/vehicle-info", json={"license_plate": "12345678"})

    assert response.status_code == 502
    assert response.json()["error_code"] == "upstream_unavailable"


def test_upstream_500(client, override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    override_registry(handler)
    response = client.post("/vehicle-info", json={"license_plate": "12345678"})

    assert response.status_code == 502
    assert response.json()["error_code"] == "upstream_unavailable"


def test_malformed_success_body(client, override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": {"license_plate": "12345678"}})

    override_registry(handler)
    response = client.post("/vehicle-info", json={"license_plate": "12345678"})

    assert response.status_code == 502
    assert response.json()["error_code"] == "upstream_unavailable"


def test_missing_field(client):
    response = client.post("/vehicle-info", json={})
    assert response.status_code == 422


def test_missing_token_does_not_call_upstream(override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream should not be called")

    override_registry(handler)
    response = TestClient(app).post("/vehicle-info", json={"license_plate": "12345678"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"


def test_wrong_token_does_not_call_upstream(override_registry):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream should not be called")

    override_registry(handler)
    response = TestClient(app).post(
        "/vehicle-info",
        json={"license_plate": "12345678"},
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"


def test_valid_token_without_scope_is_forbidden(monkeypatch, override_registry):
    monkeypatch.setenv("API_SCOPES", "policy:write")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream should not be called")

    override_registry(handler)
    response = TestClient(app).post(
        "/vehicle-info",
        json={"license_plate": "12345678"},
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"


def test_lookup_is_refused_when_server_token_is_unset(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    response = TestClient(app).post(
        "/vehicle-info",
        json={"license_plate": "12345678"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "unauthorized"
