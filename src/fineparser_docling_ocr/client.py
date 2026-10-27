"""Minimal client for the FineParser REST API (submit, poll, download, delete)."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx


class FineParserError(RuntimeError):
    pass


class FineParserClient:
    def __init__(self, base_url: str, timeout: float = 300.0, poll_interval: float = 0.25):
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._http = httpx.Client(base_url=base_url, timeout=httpx.Timeout(60.0))

    def close(self) -> None:
        self._http.close()

    def parse_json(self, data: bytes, filename: str) -> dict[str, Any]:
        """Run one document through FineParser and return its FRE JSON result."""
        job_id = self._submit(data, filename, "json")
        try:
            file = self._wait(job_id)
            r = self._http.get(f"/jobs/{file}")
            if r.status_code != 200:
                raise FineParserError(f"download {file}: HTTP {r.status_code} {r.text[:200]}")
            return json.loads(r.content)
        finally:
            # Results are kept on the server's output volume until deleted.
            try:
                self._http.delete(f"/jobs/{job_id}")
            except httpx.HTTPError:
                pass

    def _submit(self, data: bytes, filename: str, output_type: str) -> str:
        r = self._http.post(
            "/parse",
            files={"file": (filename, data)},
            data={"outputType": output_type},
        )
        if r.status_code != 202:
            raise FineParserError(f"submit: HTTP {r.status_code} {r.text[:200]}")
        return r.json()["jobId"]

    def _wait(self, job_id: str) -> str:
        deadline = time.monotonic() + self.timeout
        while True:
            r = self._http.get(f"/jobs/{job_id}")
            if r.status_code != 200:
                raise FineParserError(f"status {job_id}: HTTP {r.status_code} {r.text[:200]}")
            st = r.json()
            status = st.get("status")
            if status == "successful":
                return st["file"]
            if status in ("failed", "cancelled"):
                raise FineParserError(f"job {job_id} {status}: {st.get('error', '')}")
            if time.monotonic() > deadline:
                raise FineParserError(f"job {job_id} still {status} after {self.timeout}s")
            time.sleep(self.poll_interval)
