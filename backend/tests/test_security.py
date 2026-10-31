from __future__ import annotations

import socket
import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import SecurityMiddleware
from app.security import SupplierURLValidationError, validate_supplier_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/inventory",
        "http://localhost/inventory",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ],
)
def test_unsafe_supplier_urls_are_rejected(monkeypatch, url) -> None:
    if "localhost" in url:
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *args, **kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
            ],
        )
    with pytest.raises(SupplierURLValidationError):
        validate_supplier_url(url)


def test_private_resolved_supplier_hostname_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.15", 443))
        ],
    )
    with pytest.raises(SupplierURLValidationError, match="non-public"):
        validate_supplier_url("https://supplier.example/inventory")


def test_public_supplier_hostname_is_allowed_with_mocked_dns(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda hostname, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )

    validate_supplier_url("https://supplier.example/inventory")


def test_supplier_stock_fetch_works_for_public_host_with_mocked_http_and_dns(monkeypatch) -> None:
    from app import security
    from app.services.swarm import supplier_stock

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda hostname, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )

    def handle_request(request):
        assert str(request.url) == "https://supplier.example/stock"
        return httpx.Response(200, json={"items": [{"item": "seed", "qty": 12}]})

    monkeypatch.setattr(
        security.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(
            transport=httpx.MockTransport(handle_request),
            **kwargs,
        ),
    )
    stock, source = asyncio.run(
        supplier_stock(
            {"inventory_url": "https://supplier.example/stock", "stock": []}
        )
    )

    assert stock == {"seed": 12.0}
    assert source == "live inventory API"


def test_supplier_fetch_disables_redirects(monkeypatch) -> None:
    from app import security

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda hostname, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    seen = {}

    def handle_request(request):
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/"})

    def client_factory(**kwargs):
        seen.update(kwargs)
        return async_client(
            transport=httpx.MockTransport(handle_request),
            **kwargs,
        )

    monkeypatch.setattr(security.httpx, "AsyncClient", client_factory)
    with pytest.raises(SupplierURLValidationError, match="redirects"):
        asyncio.run(
            security.fetch_supplier_response(
                "GET",
                "https://supplier.example/stock",
            )
        )
    assert seen["follow_redirects"] is False


def test_supplier_fetch_rejects_oversized_response(monkeypatch) -> None:
    from app import security

    async_client = httpx.AsyncClient
    monkeypatch.setattr(security, "MAX_SUPPLIER_RESPONSE_BYTES", 4)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda hostname, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    monkeypatch.setattr(
        security.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"12345")
            ),
            **kwargs,
        ),
    )

    with pytest.raises(SupplierURLValidationError, match="1 MiB size limit"):
        asyncio.run(
            security.fetch_supplier_response(
                "GET",
                "https://supplier.example/stock",
            )
        )


def test_supplier_allow_list_is_enforced(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ALLOWED_SUPPLIER_HOSTS", ["inventory.example"])
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda hostname, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )

    validate_supplier_url("https://inventory.example/items")
    with pytest.raises(SupplierURLValidationError, match="ALLOWED_SUPPLIER_HOSTS"):
        validate_supplier_url("https://other.example/items")


def test_supplier_registration_validates_urls(monkeypatch) -> None:
    from app.routers.ops import Supplier

    with pytest.raises(ValueError, match="non-public"):
        Supplier(name="Unsafe", lat=1, lon=1, inventory_url="http://127.0.0.1/")


def _security_test_app(**middleware_options):
    app = FastAPI()
    app.add_middleware(SecurityMiddleware, **middleware_options)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/assistant/chat")
    def chat():
        return {"advisory": "ok"}

    @app.post("/grid/sites")
    def grid_site():
        return {"saved": True}

    @app.post("/relief/run")
    def relief_run():
        return {"run": True}

    @app.delete("/farms/{farm_id}")
    def delete_farm(farm_id: str):
        return {"deleted": farm_id}

    return app


def _middleware_options(**overrides):
    options = {
        "requests_per_minute": 100,
        "heavy_requests_per_minute": 20,
        "max_request_body_bytes": 1024,
        "admin_token": "",
        "trust_proxy": False,
    }
    return {**options, **overrides}


def test_heavy_route_rate_limit_returns_retry_after() -> None:
    app = _security_test_app(
        **_middleware_options(heavy_requests_per_minute=2)
    )
    client = TestClient(app)

    assert client.post("/assistant/chat").status_code == 200
    assert client.post("/assistant/chat").status_code == 200
    limited = client.post("/assistant/chat")

    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.json()["detail"].startswith("Rate limit exceeded")
    assert limited.headers["X-Content-Type-Options"] == "nosniff"


def test_admin_token_protects_mutations_only_when_configured() -> None:
    app = _security_test_app(**_middleware_options(admin_token="test-admin-token"))
    client = TestClient(app)

    assert client.post("/grid/sites", json={}).status_code == 401
    assert client.post(
        "/grid/sites",
        json={},
        headers={"X-Admin-Token": "wrong"},
    ).status_code == 401
    assert client.post(
        "/grid/sites",
        json={},
        headers={"X-Admin-Token": "test-admin-token"},
    ).status_code == 200
    assert client.get("/health").status_code == 200
    assert client.delete(
        "/farms/farm-id",
        headers={"X-Admin-Token": "test-admin-token"},
    ).status_code == 200


def test_admin_token_protects_relief_mutations_and_not_reads() -> None:
    app = _security_test_app(**_middleware_options(admin_token="admin"))
    client = TestClient(app)

    assert client.post("/relief/run").status_code == 401
    assert client.post(
        "/relief/run", headers={"X-Admin-Token": "admin"}
    ).status_code == 200
    assert client.get("/health").status_code == 200


def test_mutations_remain_available_when_admin_token_is_unset() -> None:
    app = _security_test_app(**_middleware_options(admin_token=""))
    assert TestClient(app).post("/grid/sites", json={}).status_code == 200


def test_json_request_body_limit_returns_413() -> None:
    app = _security_test_app(**_middleware_options(max_request_body_bytes=8))
    response = TestClient(app).post(
        "/assistant/chat",
        json={"message": "this exceeds eight bytes"},
    )

    assert response.status_code == 413
    assert "size limit" in response.json()["detail"]


def test_forwarded_ip_is_ignored_unless_proxy_trust_is_enabled() -> None:
    app = _security_test_app(
        **_middleware_options(requests_per_minute=1, trust_proxy=False)
    )
    client = TestClient(app)

    assert client.get("/health", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert client.get("/health", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 429


def test_forwarded_ip_is_used_when_proxy_trust_is_enabled() -> None:
    app = _security_test_app(
        **_middleware_options(requests_per_minute=1, trust_proxy=True)
    )
    client = TestClient(app)

    assert client.get("/health", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert client.get("/health", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200
    assert client.get("/health", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 429
