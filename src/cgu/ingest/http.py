"""Cliente HTTP com limite de requisições, retentativas e cache em disco.

O cache torna a coleta retomável: uma requisição já respondida não é repetida.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = "cgu-data-analysis/0.1 (pesquisa academica; dados abertos)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class DiskSpaceError(RuntimeError):
    pass


def ensure_free_space(path: Path, min_gb: float) -> None:
    path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path).free / 1024**3
    if free < min_gb:
        raise DiskSpaceError(
            f"Só {free:.1f} GB livres em {path} (mínimo configurado: "
            f"{min_gb} GB). Libere espaço ou reduza o recorte."
        )


class RateLimiter:
    def __init__(self, per_minute: float):
        self.interval = 60.0 / per_minute
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in RETRY_STATUS


class ApiClient:
    def __init__(
        self,
        base_url: str,
        cache_dir: Path | None,
        per_minute: float,
        headers: dict[str, str] | None = None,
        timeout: float = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.limiter = RateLimiter(per_minute)
        self.http = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})},
        )

    def _cache_path(self, path: str, params: dict) -> Path | None:
        if self.cache_dir is None:
            return None
        key = json.dumps([path, sorted(params.items())], default=str)
        digest = hashlib.sha1(key.encode()).hexdigest()
        return self.cache_dir / digest[:2] / f"{digest}.json.gz"

    @retry(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=2, max=120),
        reraise=True,
    )
    def _request(self, path: str, params: dict) -> Any:
        self.limiter.wait()
        r = self.http.get(f"{self.base_url}/{path.lstrip('/')}", params=params)
        if r.status_code in (204, 404):
            return None
        r.raise_for_status()
        return r.json() if r.content else None

    def get_json(self, path: str, params: dict | None = None, cache: bool = True) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        cp = self._cache_path(path, params) if cache else None
        if cp and cp.exists():
            with gzip.open(cp, "rt", encoding="utf-8") as f:
                return json.load(f)
        data = self._request(path, params)
        if cp:
            cp.parent.mkdir(parents=True, exist_ok=True)
            tmp = cp.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            tmp.replace(cp)
        return data

    def close(self) -> None:
        self.http.close()
