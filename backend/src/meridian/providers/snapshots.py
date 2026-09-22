"""Recorded real API responses used for demo/offline mode. Always surfaced as snapshot data, never as live."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel

from meridian.core.ids import utcnow

SECRET_PARAMS = frozenset({"apikey", "api_key", "token", "key", "apiKey"})


class Snapshot(BaseModel):
    provider: str
    url: str
    fetched_at: datetime
    content_type: str  # "json" | "text"
    body: Any

    @property
    def snapshot_date(self) -> date:
        return self.fetched_at.date()


def request_key(url: str, params: dict[str, Any] | None = None) -> str:
    public = {k: v for k, v in sorted((params or {}).items()) if k not in SECRET_PARAMS}
    canonical = url + ("?" + urlencode(public) if public else "")
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, provider: str, key: str) -> Path:
        return self.root / provider / f"{key}.json.gz"

    def load(self, provider: str, url: str, params: dict[str, Any] | None = None) -> Snapshot | None:
        path = self._path(provider, request_key(url, params))
        if not path.is_file():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return Snapshot.model_validate_json(fh.read())

    def save(self, provider: str, url: str, params: dict[str, Any] | None, body: Any, content_type: str) -> Path:
        path = self._path(provider, request_key(url, params))
        path.parent.mkdir(parents=True, exist_ok=True)
        snap = Snapshot(provider=provider, url=url, fetched_at=utcnow(), content_type=content_type, body=body)
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as fh:
            fh.write(snap.model_dump_json())
        return path

    def exists(self, provider: str, url: str, params: dict[str, Any] | None = None) -> bool:
        return self._path(provider, request_key(url, params)).is_file()


def dumps(body: Any) -> bytes:
    return json.dumps(body, separators=(",", ":")).encode()
