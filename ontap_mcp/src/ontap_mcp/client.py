"""ONTAP REST client with guardrails."""

from __future__ import annotations

import os
from typing import Any

import httpx


class OntapClient:
    """Thin wrapper around ONTAP REST API."""

    def __init__(
        self,
        host: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool | None = None,
    ) -> None:
        self.host = (host or os.environ["ONTAP_MGMT_HOST"]).rstrip("/")
        self.username = username or os.environ["ONTAP_USERNAME"]
        self.password = password or os.environ["ONTAP_PASSWORD"]
        if verify_ssl is None:
            verify_ssl = os.environ.get("ONTAP_VERIFY_SSL", "true").lower() == "true"
        self._client = httpx.Client(
            base_url=self.host,
            auth=(self.username, self.password),
            verify=verify_ssl,
            timeout=60.0,
            headers={"Accept": "application/hal+json"},
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.get(path, params=params or {})
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = self._client.post(path, json=body)
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OntapClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
