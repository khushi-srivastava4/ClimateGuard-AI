"""Validation helpers for user-configured supplier HTTP endpoints."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from urllib.parse import urlsplit

import httpx

from app.config import settings

MAX_SUPPLIER_RESPONSE_BYTES = 1024 * 1024


class SupplierURLValidationError(ValueError):
    """A supplier endpoint is unsafe or cannot be safely reached."""


_BLOCKED_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "metadata.google",
    "instance-data",
}


def validate_supplier_url(url: str) -> None:
    try:
        parsed = urlsplit(url.strip())
        hostname = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError as exc:
        raise SupplierURLValidationError("Supplier URL is invalid.") from exc

    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise SupplierURLValidationError("Supplier URL must use HTTP or HTTPS and include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise SupplierURLValidationError("Supplier URL must not include embedded credentials.")
    if hostname in _BLOCKED_HOSTS:
        raise SupplierURLValidationError("Supplier URL targets a blocked metadata host.")
    if settings.ALLOWED_SUPPLIER_HOSTS and hostname not in settings.ALLOWED_SUPPLIER_HOSTS:
        raise SupplierURLValidationError("Supplier hostname is not in ALLOWED_SUPPLIER_HOSTS.")

    try:
        literal_address = ipaddress.ip_address(hostname)
        addresses = [literal_address]
    except ValueError:
        try:
            resolved = socket.getaddrinfo(
                hostname,
                port or (443 if parsed.scheme.lower() == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except (OSError, UnicodeError) as exc:
            raise SupplierURLValidationError("Supplier hostname could not be resolved.") from exc
        addresses = []
        for result in resolved:
            try:
                addresses.append(ipaddress.ip_address(result[4][0]))
            except (IndexError, ValueError):
                raise SupplierURLValidationError("Supplier hostname resolved to an invalid address.") from None

    if not addresses:
        raise SupplierURLValidationError("Supplier hostname did not resolve to an address.")
    for address in addresses:
        if (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise SupplierURLValidationError("Supplier URL resolves to a non-public IP address.")


async def fetch_supplier_response(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    json_body: dict | None = None,
) -> tuple[int, bytes]:
    await asyncio.to_thread(validate_supplier_url, url)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15, connect=6),
        follow_redirects=False,
    ) as client:
        async with client.stream(method, url, headers=headers, json=json_body) as response:
            if 300 <= response.status_code < 400:
                raise SupplierURLValidationError("Supplier URL redirects are not allowed.")
            content_length = response.headers.get("content-length")
            if content_length and content_length.isdigit() and int(content_length) > MAX_SUPPLIER_RESPONSE_BYTES:
                raise SupplierURLValidationError("Supplier response exceeds the 1 MiB size limit.")
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_SUPPLIER_RESPONSE_BYTES:
                    raise SupplierURLValidationError("Supplier response exceeds the 1 MiB size limit.")
                body.extend(chunk)
            return response.status_code, bytes(body)


def parse_supplier_json(response_body: bytes):
    try:
        return json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Supplier returned invalid JSON.") from exc
