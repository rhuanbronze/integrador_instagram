"""Read-only HTTP checks inside the built container (stdlib; no Instagram calls)."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def run():
    base = "http://127.0.0.1:8000"
    with urlopen(base + "/health", timeout=10) as response:
        assert json.load(response) == {"status": "ok", "database": "ok"}
    with urlopen(base + "/api/status", timeout=10) as response:
        status = json.load(response)
        assert status["accounts_count"] == status["media_count"] == 0
    with urlopen(base + "/openapi.json", timeout=10) as response:
        routes = json.load(response)["paths"]
        assert set(routes) == {
            "/health",
            "/api/status",
            "/api/jobs/account",
            "/api/jobs/media",
            "/api/jobs/all",
        }
    for job_type in ("account", "media", "all"):
        try:
            urlopen(Request(base + "/api/jobs/" + job_type, method="POST"), timeout=10)
        except HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Unauthenticated job accepted")
    print("Container smoke test OK: health, status, OpenAPI, POST authentication")


if __name__ == "__main__":
    run()
